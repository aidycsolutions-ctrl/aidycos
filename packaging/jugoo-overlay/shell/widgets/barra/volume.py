"""Compact system-volume control for the top bar."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, GLib, Gtk

from ... import config as shell_config
from ...eventbus import EventBus
from ...models import AudioSnapshot, SystemVolumeState
from ...servicios.audio.audio import AUDIO_CHANGED, AudioService
from ...ui import ShellModule
from ..audio.volume_slider import VolumeSlider


def _volume_icon_name(state: SystemVolumeState | None) -> str:
    # Unknown state must not look muted: on some test PCs pactl is down while
    # wpctl still changes volume, so system_volume stays None and the old
    # fallback drew a permanent mute "x" even though audio worked.
    if state is None:
        return "audio-volume-medium-symbolic"
    if state.is_muted or state.volume <= 0.001:
        return "audio-volume-muted-symbolic"
    if state.volume < 0.34:
        return "audio-volume-low-symbolic"
    if state.volume < 0.67:
        return "audio-volume-medium-symbolic"
    return "audio-volume-high-symbolic"


def _volume_tooltip(state: SystemVolumeState | None) -> str:
    if state is None:
        return "Volumen del sistema"
    sink = state.sink_description or state.sink_name or "Salida"
    if state.is_muted:
        return f"{sink}\nSilenciado"
    return f"{sink}\nVolumen: {state.percent}%"


class VolumeWidget(ShellModule):
    """Icon + slider for the default sink; click icon to mute."""

    def __init__(
        self,
        event_bus: EventBus,
        audio_service: AudioService,
    ) -> None:
        super().__init__("volume-widget", spacing=4)

        self._event_bus = event_bus
        self._service = audio_service
        self._state = audio_service.snapshot.system_volume
        self._scroll_step = float(getattr(shell_config, "VOLUME_BAR_SCROLL_STEP", 0.05))

        self._mute = Gtk.Button()
        self._mute.set_relief(Gtk.ReliefStyle.NONE)
        self._mute.get_style_context().add_class("volume-mute-button")
        self._mute.set_can_focus(False)
        self._icon = Gtk.Image.new_from_icon_name(
            _volume_icon_name(self._state),
            Gtk.IconSize.MENU,
        )
        self._icon.set_pixel_size(int(getattr(shell_config, "VOLUME_BAR_ICON_SIZE", 16)))
        self._mute.add(self._icon)
        self._mute.connect("clicked", self._on_mute_clicked)

        initial = 0.0 if self._state is None else self._state.volume
        self._slider = VolumeSlider(initial_volume=initial, on_change=self._on_slider_changed)
        self._slider.set_size_request(
            int(getattr(shell_config, "VOLUME_BAR_SLIDER_WIDTH", 72)),
            -1,
        )

        self.pack_start(self._mute, False, False, 0)
        self.pack_start(self._slider, False, False, 0)
        self.set_tooltip_text(_volume_tooltip(self._state))
        self.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.connect("scroll-event", self._on_scroll)
        self._event_bus.subscribe(AUDIO_CHANGED, self._on_audio_changed)
        self.connect("destroy", self._on_destroy)
        GLib.idle_add(self._apply_state, self._state)

    def _on_destroy(self, *_args) -> None:
        self._event_bus.unsubscribe(AUDIO_CHANGED, self._on_audio_changed)

    def _on_audio_changed(self, snapshot: object) -> None:
        if isinstance(snapshot, AudioSnapshot):
            GLib.idle_add(self._apply_state, snapshot.system_volume)

    def _apply_state(self, state: SystemVolumeState | None) -> bool:
        self._state = state
        self._icon.set_from_icon_name(_volume_icon_name(state), Gtk.IconSize.MENU)
        self._icon.set_pixel_size(int(getattr(shell_config, "VOLUME_BAR_ICON_SIZE", 16)))
        if state is not None and not self._slider.is_dragging:
            self._slider.set_volume(0.0 if state.is_muted else state.volume)
        self.set_tooltip_text(_volume_tooltip(state))
        style = self.get_style_context()
        if state is not None and state.is_muted:
            style.add_class("volume-muted")
        else:
            style.remove_class("volume-muted")
        return False

    def _on_mute_clicked(self, *_args) -> None:
        self._service.toggle_system_mute()

    def _on_slider_changed(self, volume: float) -> None:
        self._service.set_system_volume(volume)

    def _on_scroll(self, _widget: Gtk.Widget, event: Gdk.EventScroll) -> bool:
        delta = 0.0
        if event.direction == Gdk.ScrollDirection.UP:
            delta = self._scroll_step
        elif event.direction == Gdk.ScrollDirection.DOWN:
            delta = -self._scroll_step
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            _dx, dy = event.get_scroll_deltas()
            if dy:
                delta = -dy * self._scroll_step
        if not delta:
            return False
        current = 0.0 if self._state is None else self._state.volume
        if self._state is not None and self._state.is_muted and delta > 0:
            self._service.toggle_system_mute()
        self._service.set_system_volume(max(0.0, min(1.0, current + delta)))
        return True
