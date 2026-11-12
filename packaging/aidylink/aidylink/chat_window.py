"""Native GTK desktop chat backed by the AidyChat account APIs."""

from __future__ import annotations

import mimetypes
import hashlib
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from .cloud import AidyChatBridge
try:
    from .calls import NativeCall
except (ImportError, ValueError):  # GStreamer WebRTC is an optional desktop add-on.
    NativeCall = None  # type: ignore[assignment,misc]
from .config import LinkConfig, load_config, save_config
from .native_auth import start_google_login
from .branding import apply_aidychat_branding
from .paths import data_dir


GREEN = "#075e54"
PALE_GREEN = "#d9fdd3"
BACKGROUND = "#efeae2"


def _install_style() -> None:
    css = Gtk.CssProvider()
    css.load_from_data(f"""
        window.aidylink {{ background: {BACKGROUND}; }}
        .link-sidebar {{ background: #f0f2f5; }}
        .link-brand {{ background: {GREEN}; color: white; padding: 12px; font-size: 16px; font-weight: bold; }}
        .link-contact {{ padding: 12px; border-bottom: 1px solid #e7e8ea; }}
        .link-contact:selected {{ background: #d9fdd3; }}
        .link-chat-header {{ background: #f0f2f5; padding: 10px; }}
        .link-message-area {{ background: {BACKGROUND}; }}
        .link-message-in {{ background: white; border-radius: 10px; padding: 8px 11px; }}
        .link-message-out {{ background: {PALE_GREEN}; border-radius: 10px; padding: 8px 11px; }}
        .link-muted {{ color: #667781; font-size: 10px; }}
        .link-composer {{ background: #f0f2f5; padding: 10px; }}
        .link-send {{ background: {GREEN}; color: white; }}
        .link-status {{ color: #667781; padding: 8px; }}
    """.encode())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


class AidyChatWindow(Gtk.Window):
    """WhatsApp-like native shell for messages and shared media."""

    def __init__(self, cfg: LinkConfig) -> None:
        super().__init__(title="AidyChat")
        self.cfg = cfg
        self.bridge = AidyChatBridge(cfg)
        self.set_default_size(1120, 740)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.get_style_context().add_class("aidylink")
        apply_aidychat_branding(self)
        _install_style()
        self._chats: list[dict[str, Any]] = []
        self._active_chat: dict[str, Any] | None = None
        self._last_id: dict[int, int] = {}
        self._inflight = 0
        self._load_gen = 0
        self._local_devices_window: Gtk.Window | None = None
        self._recorder: subprocess.Popen[bytes] | None = None
        self._record_path: Path | None = None
        self.call_engine = (
            NativeCall(
                self.bridge,
                on_status=self._call_status,
                on_incoming=self._confirm_incoming,
                on_finished=self._call_finished,
            )
            if NativeCall is not None
            else None
        )

        split = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        split.set_position(340)
        self.add(split)
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.sidebar.set_size_request(280, -1)
        self.sidebar.get_style_context().add_class("link-sidebar")
        split.pack1(self.sidebar, False, False)
        self.conversation = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        split.pack2(self.conversation, True, False)

        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        brand.get_style_context().add_class("link-brand")
        title = Gtk.Label(label="AidyChat", xalign=0)
        title.set_hexpand(True)
        brand.pack_start(title, True, True, 0)
        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        refresh.set_tooltip_text("Actualizar conversaciones")
        refresh.connect("clicked", lambda *_: self.refresh_chats())
        brand.pack_start(refresh, False, False, 0)
        local_devices = Gtk.Button.new_from_icon_name("network-workgroup-symbolic", Gtk.IconSize.BUTTON)
        local_devices.set_tooltip_text("Computadores en esta red")
        local_devices.connect("clicked", lambda *_: self.open_local_devices())
        brand.pack_start(local_devices, False, False, 0)
        new_chat = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        new_chat.set_tooltip_text("Nueva conversación")
        new_chat.connect("clicked", lambda *_: self.open_new_chat())
        brand.pack_start(new_chat, False, False, 0)
        settings = Gtk.Button.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON)
        settings.set_tooltip_text("Cuenta AidyChat")
        settings.connect("clicked", lambda *_: self.open_account_dialog())
        brand.pack_start(settings, False, False, 0)
        self.sidebar.pack_start(brand, False, False, 0)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Buscar en tus chats")
        self.search.connect("search-changed", self._filter_chats)
        self.search.set_tooltip_text("Filtra la lista. Para hallar gente nueva usa +")
        search_box = Gtk.Box()
        search_box.set_border_width(10)
        search_box.pack_start(self.search, True, True, 0)
        self.sidebar.pack_start(search_box, False, False, 0)

        self.chat_list = Gtk.ListBox()
        self.chat_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.chat_list.connect("row-selected", self._on_chat_selected)
        chat_scroll = Gtk.ScrolledWindow()
        chat_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        chat_scroll.add(self.chat_list)
        self.sidebar.pack_start(chat_scroll, True, True, 0)
        self.sidebar_status = Gtk.Label(label="Conectando…", xalign=0)
        self.sidebar_status.get_style_context().add_class("link-status")
        self.sidebar.pack_start(self.sidebar_status, False, False, 0)

        self._show_empty_conversation()
        self.connect("destroy", self._on_destroy)
        self.refresh_chats()
        GLib.timeout_add_seconds(2, self._tick)

    def _show_empty_conversation(self) -> None:
        for child in self.conversation.get_children():
            self.conversation.remove(child)
        empty = Gtk.Label(label="Selecciona una conversación para empezar a chatear")
        empty.get_style_context().add_class("link-status")
        self.conversation.pack_start(empty, True, True, 0)
        self.conversation.show_all()

    def open_local_devices(self) -> None:
        if self._local_devices_window is not None:
            self._local_devices_window.present()
            return
        from .ui import AidylinkWindow

        window = AidylinkWindow(standalone=False)
        self._local_devices_window = window
        window.connect("destroy", lambda *_: setattr(self, "_local_devices_window", None))
        window.show_all()

    def _call(self, action: Callable[[], Any], done: Callable[[Any, Exception | None], None]) -> None:
        """Run network work without blocking other actions.

        The old global ``_busy`` flag silently dropped loads/sends while any
        other request was in flight — that felt like a broken WhatsApp.
        """
        self._inflight += 1

        def work() -> None:
            try:
                result = action()
                error = None
            except Exception as exc:  # network errors are displayed in the UI
                result, error = None, exc
            GLib.idle_add(finish, result, error)

        def finish(result: Any, error: Exception | None) -> bool:
            self._inflight = max(0, self._inflight - 1)
            done(result, error)
            return GLib.SOURCE_REMOVE

        threading.Thread(target=work, daemon=True, name="aidylink-cloud-ui").start()

    def refresh_chats(self) -> None:
        def fetch() -> list[dict[str, Any]]:
            # Don't hit check-session + disk on every sidebar refresh.
            return self.bridge.list_chats()

        self._call(fetch, self._chats_loaded)

    def _chats_loaded(self, chats: Any, error: Exception | None) -> None:
        if error:
            self.sidebar_status.set_text(f"Sin conexión: {error}")
            return
        active_id = (
            int(self._active_chat.get("chat_id") or 0) if self._active_chat else 0
        )
        normalized: list[dict[str, Any]] = []
        for chat in chats or []:
            if not isinstance(chat, dict):
                continue
            item = dict(chat)
            cid = int(item.get("chat_id") or item.get("id") or 0)
            if not cid:
                continue
            item["chat_id"] = cid
            normalized.append(item)
        self._chats = normalized
        self.sidebar_status.set_text(f"{len(self._chats)} conversaciones · AidyChat")
        # Preserve selection without destroying the open conversation pane.
        previous = self.chat_list.get_selected_row()
        previous_id = 0
        if previous is not None:
            prev_chat = getattr(previous, "chat_data", {}) or {}
            previous_id = int(prev_chat.get("chat_id") or 0)
        for child in list(self.chat_list.get_children()):
            self.chat_list.remove(child)
        selected = None
        for chat in self._chats:
            name = str(chat.get("username") or chat.get("contact_name") or "Contacto")
            preview = str(chat.get("last_message") or "Empieza una conversación")
            if len(preview) > 58:
                preview = preview[:55] + "…"
            row = Gtk.ListBoxRow()
            row.chat_data = chat
            row.get_style_context().add_class("link-contact")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            name_label = Gtk.Label(label=name, xalign=0)
            name_label.set_ellipsize(Pango.EllipsizeMode.END)
            name_label.set_hexpand(True)
            top.pack_start(name_label, True, True, 0)
            unread = int(chat.get("unread_count") or 0)
            if unread:
                badge = Gtk.Label(label=str(unread))
                badge.set_markup(f"<span foreground='white' background='{GREEN}'>{unread}</span>")
                top.pack_start(badge, False, False, 0)
            box.pack_start(top, False, False, 0)
            snippet = Gtk.Label(label=preview, xalign=0)
            snippet.get_style_context().add_class("link-muted")
            snippet.set_ellipsize(Pango.EllipsizeMode.END)
            box.pack_start(snippet, False, False, 0)
            row.add(box)
            self.chat_list.add(row)
            if chat["chat_id"] == active_id or chat["chat_id"] == previous_id:
                selected = row
        self.chat_list.show_all()
        if selected:
            # Block signal re-entry that would rebuild the conversation.
            self.chat_list.handler_block_by_func(self._on_chat_selected)
            try:
                self.chat_list.select_row(selected)
                self._active_chat = getattr(selected, "chat_data", self._active_chat)
            finally:
                self.chat_list.handler_unblock_by_func(self._on_chat_selected)
        elif self._chats and self._active_chat is None:
            self.chat_list.select_row(self.chat_list.get_row_at_index(0))

    def _filter_chats(self, *_args: object) -> None:
        query = (self.search.get_text() or "").strip().casefold()
        for row in self.chat_list.get_children():
            chat = getattr(row, "chat_data", {})
            name = str(chat.get("username") or "").casefold()
            row.set_visible(not query or query in name)

    def _on_chat_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        chat = getattr(row, "chat_data", None)
        if not isinstance(chat, dict):
            return
        chat_id = int(chat.get("chat_id") or chat.get("id") or 0)
        if not chat_id:
            self.sidebar_status.set_text("Ese chat no tiene id válido")
            return
        # Avoid rebuilding the whole pane if the same chat is re-selected
        # (ListBox fires again after refresh_chats).
        if (
            self._active_chat
            and int(self._active_chat.get("chat_id") or 0) == chat_id
            and hasattr(self, "message_box")
        ):
            self._active_chat = chat
            return
        chat = dict(chat)
        chat["chat_id"] = chat_id
        self._active_chat = chat
        self._last_id[chat_id] = 0
        self._build_conversation(chat)
        self.sidebar_status.set_text(f"Cargando chat con {chat.get('username') or 'contacto'}…")
        self._load_messages(initial=True)

    def _build_conversation(self, chat: dict[str, Any]) -> None:
        for child in self.conversation.get_children():
            self.conversation.remove(child)
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.get_style_context().add_class("link-chat-header")
        name = Gtk.Label(label=str(chat.get("username") or "Contacto"), xalign=0)
        name.set_hexpand(True)
        header.pack_start(name, True, True, 0)
        self.call_audio = Gtk.Button.new_from_icon_name("call-start-symbolic", Gtk.IconSize.BUTTON)
        self.call_audio.set_tooltip_text("Llamada de voz")
        self.call_audio.connect("clicked", lambda *_: self._start_call("audio"))
        header.pack_start(self.call_audio, False, False, 0)
        self.call_video = Gtk.Button.new_from_icon_name("camera-video-symbolic", Gtk.IconSize.BUTTON)
        self.call_video.set_tooltip_text("Videollamada")
        self.call_video.connect("clicked", lambda *_: self._start_call("video"))
        header.pack_start(self.call_video, False, False, 0)
        self.ptt_button = Gtk.Button(label="Intercomunicador")
        self.ptt_button.set_tooltip_text("Mantén pulsado para hablar")
        self.ptt_button.connect("pressed", self._ptt_pressed)
        self.ptt_button.connect("released", self._ptt_released)
        header.pack_start(self.ptt_button, False, False, 0)
        self.hangup_button = Gtk.Button.new_from_icon_name("call-stop-symbolic", Gtk.IconSize.BUTTON)
        self.hangup_button.set_tooltip_text("Colgar")
        self.hangup_button.connect("clicked", lambda *_: self.call_engine and self.call_engine.hangup())
        self.hangup_button.set_sensitive(False)
        header.pack_start(self.hangup_button, False, False, 0)
        self.conversation.pack_start(header, False, False, 0)

        self.message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.message_box.set_border_width(16)
        self.message_scroll = Gtk.ScrolledWindow()
        self.message_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.message_scroll.set_vexpand(True)
        self.message_scroll.add_with_viewport(self.message_box)
        self.message_scroll.get_style_context().add_class("link-message-area")
        self.message_box.get_style_context().add_class("link-message-area")
        self.conversation.pack_start(self.message_scroll, True, True, 0)

        composer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        composer.get_style_context().add_class("link-composer")
        attach = Gtk.Button.new_from_icon_name("mail-attachment-symbolic", Gtk.IconSize.BUTTON)
        attach.set_tooltip_text("Adjuntar archivo, imagen o audio")
        attach.connect("clicked", lambda *_: self._choose_attachment())
        composer.pack_start(attach, False, False, 0)
        self.record_button = Gtk.Button.new_from_icon_name("audio-input-microphone-symbolic", Gtk.IconSize.BUTTON)
        self.record_button.set_tooltip_text("Grabar audio: pulsa para iniciar y otra vez para enviar")
        self.record_button.connect("clicked", lambda *_: self._toggle_recording())
        composer.pack_start(self.record_button, False, False, 0)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Escribe un mensaje")
        self.entry.connect("activate", lambda *_: self._send_text())
        composer.pack_start(self.entry, True, True, 0)
        send = Gtk.Button(label="Enviar")
        send.get_style_context().add_class("link-send")
        send.connect("clicked", lambda *_: self._send_text())
        composer.pack_start(send, False, False, 0)
        self.conversation.pack_start(composer, False, False, 0)
        self.conversation.show_all()

    def _load_messages(self, *, initial: bool = False) -> None:
        chat = self._active_chat
        if not chat:
            return
        chat_id = int(chat.get("chat_id") or chat.get("id") or 0)
        if not chat_id:
            return
        since_id = 0 if initial else self._last_id.get(chat_id, 0)
        self._load_gen += 1
        gen = self._load_gen
        self._call(
            lambda: self.bridge.get_messages(chat_id, since_id=since_id),
            lambda data, error: self._messages_loaded(chat_id, data, error, initial, gen),
        )

    def _messages_loaded(
        self,
        chat_id: int,
        data: Any,
        error: Exception | None,
        initial: bool,
        gen: int,
    ) -> None:
        if gen != self._load_gen:
            return
        if error:
            self.sidebar_status.set_text(f"No se pudieron cargar mensajes: {error}")
            return
        if not self._active_chat or int(self._active_chat.get("chat_id") or 0) != chat_id:
            return
        if not hasattr(self, "message_box"):
            return
        messages = data.get("messages") if isinstance(data, dict) else []
        if not isinstance(messages, list):
            messages = []
        if initial:
            for child in list(self.message_box.get_children()):
                self.message_box.remove(child)
            self._last_id[chat_id] = 0
        my_id = int(self.cfg.cloud.peer_user_ids.get("self") or 0)
        if not my_id:
            # Resolve once in background without blocking the bubble render.
            self._call(self.bridge.refresh_self_id, lambda *_: None)
            my_id = int(self.cfg.cloud.peer_user_ids.get("self") or 0)
        added = 0
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            mid = int(msg.get("id") or 0)
            if mid <= self._last_id.get(chat_id, 0) and not initial:
                continue
            if mid:
                self._last_id[chat_id] = max(mid, self._last_id.get(chat_id, 0))
            self._append_message(msg, my_id)
            added += 1
        name = str(self._active_chat.get("username") or "chat")
        if initial:
            self.sidebar_status.set_text(
                f"{name} · {len(messages)} mensaje(s)" if messages else f"{name} · sin mensajes aún"
            )
        elif added:
            self.sidebar_status.set_text(f"{name} · {added} nuevo(s)")
        GLib.idle_add(self._scroll_to_end)

    def _append_message(self, msg: dict[str, Any], my_id: int) -> None:
        mine = int(msg.get("sender_id") or -1) == my_id
        align = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        align.set_halign(Gtk.Align.END if mine else Gtk.Align.START)
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        bubble.set_margin_start(20)
        bubble.set_margin_end(20)
        bubble.set_margin_top(2)
        bubble.set_margin_bottom(2)
        bubble.get_style_context().add_class("link-message-out" if mine else "link-message-in")
        kind = str(msg.get("message_type") or "text")
        content = str(msg.get("content") or "")
        media_url = str(msg.get("media_url") or "")
        if kind == "text" or content:
            label = Gtk.Label(label=content, xalign=0)
            label.set_line_wrap(True)
            label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            label.set_max_width_chars(48)
            bubble.pack_start(label, False, False, 0)
        if media_url:
            if kind == "image":
                preview = Gtk.Label(label="Cargando imagen…", xalign=0)
                bubble.pack_start(preview, False, False, 0)
                self._load_image(media_url, preview, bubble)
            else:
                label = {"video": "▶ Video", "audio": "▶ Reproducir audio", "document": "📎 Abrir archivo"}.get(kind, "📎 Archivo")
                button = Gtk.Button(label=label) if kind == "audio" else Gtk.LinkButton(uri=self.bridge._url(media_url), label=label)
                if kind == "audio":
                    button.connect("clicked", lambda *_args, url=media_url: self._play_audio(url))
                button.set_halign(Gtk.Align.START)
                bubble.pack_start(button, False, False, 0)
        created = str(msg.get("created_at") or "")
        stamp = created[11:16] if len(created) >= 16 else ""
        if stamp:
            meta = Gtk.Label(label=stamp, xalign=1)
            meta.get_style_context().add_class("link-muted")
            bubble.pack_start(meta, False, False, 0)
        align.pack_start(bubble, False, False, 0)
        self.message_box.pack_start(align, False, False, 0)
        align.show_all()

    def _load_image(self, media_url: str, label: Gtk.Label, bubble: Gtk.Box) -> None:
        suffix = Path(media_url.split("?", 1)[0]).suffix[:12] or ".img"
        cache = data_dir() / "media" / f"{hashlib.sha256(media_url.encode()).hexdigest()}{suffix}"

        def work() -> None:
            try:
                local = cache if cache.is_file() else self.bridge.download_media(media_url, cache)
                GLib.idle_add(self._show_image, local, label, bubble)
            except Exception as exc:
                GLib.idle_add(label.set_text, f"No se pudo cargar la imagen: {exc}")

        threading.Thread(target=work, daemon=True, name="aidylink-image-download").start()

    def _show_image(self, path: Path, label: Gtk.Label, bubble: Gtk.Box) -> bool:
        try:
            from gi.repository import GdkPixbuf

            image = GdkPixbuf.Pixbuf.new_from_file(str(path))
            width, height = image.get_width(), image.get_height()
            ratio = min(1.0, 360 / max(width, 1), 260 / max(height, 1))
            if ratio < 1.0:
                image = image.scale_simple(max(1, int(width * ratio)), max(1, int(height * ratio)), GdkPixbuf.InterpType.BILINEAR)
            widget = Gtk.Image.new_from_pixbuf(image)
            widget.set_tooltip_text("Doble clic para abrir en tamaño completo")
            widget.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            widget.connect(
                "button-press-event",
                lambda _widget, event: self._open_local(path)
                if event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS
                else False,
            )
            bubble.remove(label)
            bubble.pack_start(widget, False, False, 0)
            widget.show()
        except Exception as exc:
            label.set_text(f"No se pudo mostrar la imagen: {exc}")
        return GLib.SOURCE_REMOVE

    def _play_audio(self, media_url: str) -> None:
        suffix = Path(media_url.split("?", 1)[0]).suffix[:12] or ".audio"
        cache = data_dir() / "media" / f"{hashlib.sha256(media_url.encode()).hexdigest()}{suffix}"

        def work() -> None:
            try:
                local = cache if cache.is_file() else self.bridge.download_media(media_url, cache)
                GLib.idle_add(self._open_local, local)
            except Exception as exc:
                GLib.idle_add(self.sidebar_status.set_text, f"No se pudo descargar el audio: {exc}")

        threading.Thread(target=work, daemon=True, name="aidylink-audio-download").start()

    @staticmethod
    def _open_local(path: Path) -> bool:
        opener = shutil_which("xdg-open")
        if opener:
            subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return GLib.SOURCE_REMOVE

    def _scroll_to_end(self) -> bool:
        adjustment = self.message_scroll.get_vadjustment()
        adjustment.set_value(adjustment.get_upper())
        return GLib.SOURCE_REMOVE

    def _send_text(self) -> None:
        if not self._active_chat:
            return
        text = (self.entry.get_text() or "").strip()
        if not text:
            return
        chat_id = int(self._active_chat.get("chat_id") or 0)
        my_id = int(self.cfg.cloud.peer_user_ids.get("self") or 0)
        # Optimistic bubble — WhatsApp-feel while the POST is in flight.
        self.entry.set_text("")
        if hasattr(self, "message_box"):
            self._append_message(
                {
                    "id": 0,
                    "sender_id": my_id,
                    "content": text,
                    "message_type": "text",
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                my_id,
            )
            GLib.idle_add(self._scroll_to_end)
        self._call(
            lambda: self.bridge.send_chat_message(chat_id, text),
            lambda _data, error: self._message_sent(error, clear=False),
        )

    def _message_sent(self, error: Exception | None, *, clear: bool) -> None:
        if hasattr(self, "entry"):
            self.entry.set_sensitive(True)
            if clear and not error:
                self.entry.set_text("")
        if error:
            self.sidebar_status.set_text(f"No se pudo enviar: {error}")
            return
        # Pull server ids in background; don't also refresh the whole sidebar.
        self._load_messages()

    def _choose_attachment(self) -> None:
        if not self._active_chat:
            return
        dialog = Gtk.FileChooserDialog(
            title="Adjuntar a AidyLink",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Enviar", Gtk.ResponseType.OK)
        response = dialog.run()
        path = Path(dialog.get_filename()) if response == Gtk.ResponseType.OK and dialog.get_filename() else None
        dialog.destroy()
        if path:
            self._upload_and_send(path)

    def _upload_and_send(self, path: Path) -> None:
        mime = mimetypes.guess_type(path.name)[0] or ""
        kind = "image" if mime.startswith("image/") else "video" if mime.startswith("video/") else "audio" if mime.startswith("audio/") else "document"
        chat_id = int(self._active_chat.get("chat_id") or 0)
        self.sidebar_status.set_text(f"Subiendo {path.name}…")

        def work() -> None:
            try:
                media = self.bridge.upload_media(path, file_type=kind)
                result = self.bridge.send_chat_message(chat_id, path.name, message_type=kind, media_url=media["url"])
                error = None
            except Exception as exc:
                result, error = None, exc
            GLib.idle_add(self._media_sent, result, error, path.name)

        threading.Thread(target=work, daemon=True, name="aidylink-media-upload").start()

    def _media_sent(self, _result: Any, error: Exception | None, filename: str) -> bool:
        if error:
            self.sidebar_status.set_text(f"No se pudo enviar {filename}: {error}")
        else:
            self.sidebar_status.set_text(f"Archivo enviado: {filename}")
            self._load_messages()
        return GLib.SOURCE_REMOVE

    def _toggle_recording(self) -> None:
        if self._recorder:
            self._recorder.terminate()
            self._recorder.wait(timeout=3)
            self._recorder = None
            self.record_button.set_label("Enviando audio…")
            path, self._record_path = self._record_path, None
            if path and path.exists() and path.stat().st_size:
                self._upload_and_send(path)
            self.record_button.set_label("")
            self.record_button.set_image(Gtk.Image.new_from_icon_name("audio-input-microphone-symbolic", Gtk.IconSize.BUTTON))
            return
        recorder = shutil_which("pw-record")
        if not recorder:
            self.sidebar_status.set_text("No se encontró pw-record para grabar audio")
            return
        target = data_dir() / f"audio-{int(time.time())}.wav"
        try:
            self._recorder = subprocess.Popen(
                [recorder, "--format", "s16", "--rate", "24000", "--channels", "1", str(target)]
            )
            self._record_path = target
            self.record_button.set_label("Detener y enviar")
            self.sidebar_status.set_text("Grabando… pulsa de nuevo para finalizar")
        except OSError as exc:
            self.sidebar_status.set_text(f"No se pudo grabar: {exc}")

    def _start_call(self, kind: str) -> None:
        if not self._active_chat:
            return
        if self.call_engine is None or not self.call_engine.available(video=kind == "video"):
            self.sidebar_status.set_text("Instala los componentes GStreamer WebRTC para llamar")
            return
        chat_id = int(self._active_chat.get("chat_id") or 0)
        self.call_engine.start(chat_id, kind)
        self.hangup_button.set_sensitive(True)

    def _ptt_pressed(self, *_args: object) -> bool:
        label = "Intercomunicador"
        if self.call_engine is None:
            self.sidebar_status.set_text("Las llamadas requieren GStreamer WebRTC")
        elif self.call_engine.call is None:
            if self._active_chat and self.call_engine.available():
                chat_id = int(self._active_chat.get("chat_id") or 0)
                self.call_engine.start(chat_id, "audio", push_to_talk=True)
                self.hangup_button.set_sensitive(True)
                label = "Conectando…"
        else:
            self.call_engine.set_muted(False)
            label = "Transmitiendo…"
        if hasattr(self, "ptt_button"):
            self.ptt_button.set_label(label)
        return True

    def _ptt_released(self, *_args: object) -> bool:
        if self.call_engine is not None and self.call_engine.call is not None:
            self.call_engine.set_muted(True)
        if hasattr(self, "ptt_button"):
            self.ptt_button.set_label("Intercomunicador")
        return True

    def _call_status(self, text: str) -> None:
        self.sidebar_status.set_text(text)

    def _confirm_incoming(self, call: dict[str, Any]) -> bool:
        name = call.get("caller_name") or "Contacto"
        kind = "videollamada" if call.get("call_type") == "video" else "llamada de voz"
        chat_id = int(call.get("chat_id") or 0)
        chat = next(
            (item for item in self._chats if int(item.get("chat_id") or 0) == chat_id),
            {"chat_id": chat_id, "username": name},
        )
        self._active_chat = chat
        self._build_conversation(chat)
        self._load_messages(initial=True)
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"{name} te está llamando",
        )
        dialog.format_secondary_text(f"¿Aceptar la {kind}?")
        response = dialog.run()
        dialog.destroy()
        if hasattr(self, "hangup_button"):
            self.hangup_button.set_sensitive(response == Gtk.ResponseType.YES)
        return response == Gtk.ResponseType.YES

    def _call_finished(self) -> bool:
        if hasattr(self, "hangup_button"):
            self.hangup_button.set_sensitive(False)
        return GLib.SOURCE_REMOVE

    def open_account_dialog(self) -> None:
        dialog = Gtk.Dialog(title="Cuenta AidyChat", transient_for=self, flags=0)
        dialog.add_buttons(
            "Google", Gtk.ResponseType.APPLY,
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Entrar con AidyC", Gtk.ResponseType.OK,
        )
        dialog.set_default_size(460, 320)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.pack_start(
            Gtk.Label(
                label="Entra con el mismo usuario y contraseña de AidyC, o cambia a Google.",
                xalign=0,
                wrap=True,
            ),
            False,
            False,
            0,
        )
        user_e = Gtk.Entry()
        user_e.set_placeholder_text("Usuario AidyC")
        pass_e = Gtk.Entry()
        pass_e.set_placeholder_text("Contraseña")
        pass_e.set_visibility(False)
        pass_e.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        box.pack_start(Gtk.Label(label="Usuario AidyC", xalign=0), False, False, 0)
        box.pack_start(user_e, False, False, 0)
        box.pack_start(Gtk.Label(label="Contraseña", xalign=0), False, False, 0)
        box.pack_start(pass_e, False, False, 0)
        advanced = Gtk.Expander(label="Opciones avanzadas de llamadas")
        advanced_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        turn = Gtk.Entry()
        turn.set_text(self.cfg.cloud.turn_server)
        turn.set_placeholder_text("turns://usuario:clave@servidor:5349 (opcional)")
        advanced_box.pack_start(Gtk.Label(label="Relay TURN (opcional)", xalign=0), False, False, 0)
        advanced_box.pack_start(turn, False, False, 0)
        advanced.add(advanced_box)
        box.pack_start(advanced, False, False, 0)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        response = dialog.run()
        username = (user_e.get_text() or "").strip()
        password = pass_e.get_text() or ""
        if (turn.get_text() or "").strip() != self.cfg.cloud.turn_server:
            self.cfg.cloud.turn_server = (turn.get_text() or "").strip()
            save_config(self.cfg)
        dialog.destroy()
        if response == Gtk.ResponseType.APPLY:
            self._start_google_relogin()
            return
        if response != Gtk.ResponseType.OK:
            return
        if not username or not password:
            self.sidebar_status.set_text("Escribe usuario y contraseña de AidyC")
            return
        self.sidebar_status.set_text("Validando cuenta AidyC…")

        def work() -> None:
            try:
                data = self.bridge.login_aidyc(username, password)
                save_config(self.cfg)
                user = data.get("user") if isinstance(data.get("user"), dict) else {}
                result = str(user.get("username") or username)
                error = None
            except Exception as exc:
                result, error = None, exc
            GLib.idle_add(finish, result, error)

        def finish(name: str | None, error: Exception | None) -> bool:
            if error:
                self.sidebar_status.set_text(f"No se pudo iniciar sesión: {error}")
                return GLib.SOURCE_REMOVE
            self.bridge = AidyChatBridge(self.cfg)
            if self.call_engine is not None:
                self.call_engine.bridge = self.bridge
            self.sidebar_status.set_text(f"Conectado como {name or 'AidyChat'}")
            self.refresh_chats()
            try:
                subprocess.run(
                    ["systemctl", "--user", "restart", "aidylink.service"],
                    check=False,
                    timeout=8,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
            return GLib.SOURCE_REMOVE

        threading.Thread(target=work, daemon=True, name="aidychat-aidyc-login").start()

    def _start_google_relogin(self) -> None:
        self.sidebar_status.set_text("Preparando inicio de sesión con Google…")

        def done(username: str | None, error: Exception | None) -> None:
            GLib.idle_add(finish, username, error)

        def ready(url: str, opened: bool) -> None:
            GLib.idle_add(show_ready, url, opened)

        def show_ready(url: str, opened: bool) -> bool:
            if opened:
                self.sidebar_status.set_text(
                    "Navegador abierto. Completa Google allí y vuelve a AidyChat."
                )
            else:
                self.sidebar_status.set_text(
                    "No se abrió el navegador. Copia el enlace del diálogo."
                )
                link = Gtk.MessageDialog(
                    transient_for=self,
                    flags=0,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.OK,
                    text="Abre este enlace en el navegador",
                )
                link.format_secondary_text(url)
                link.run()
                link.destroy()
            return GLib.SOURCE_REMOVE

        def finish(username: str | None, error: Exception | None) -> bool:
            if error:
                self.sidebar_status.set_text(f"No se pudo iniciar sesión: {error}")
                return GLib.SOURCE_REMOVE
            self.bridge = AidyChatBridge(self.cfg)
            if self.call_engine is not None:
                self.call_engine.bridge = self.bridge
            self.sidebar_status.set_text(f"Conectado como {username or 'AidyChat'}")
            self.refresh_chats()
            try:
                subprocess.run(
                    ["systemctl", "--user", "restart", "aidylink.service"],
                    check=False,
                    timeout=8,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
            return GLib.SOURCE_REMOVE

        start_google_login(self.cfg, done, on_ready=ready)

    def open_new_chat(self) -> None:
        dialog = Gtk.Dialog(title="Buscar usuario", transient_for=self, flags=0)
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Abrir chat", Gtk.ResponseType.OK,
        )
        dialog.set_default_size(460, 360)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.pack_start(
            Gtk.Label(
                label="Busca por nombre de chat, usuario AidyC o teléfono",
                xalign=0,
                wrap=True,
            ),
            False,
            False,
            0,
        )
        query = Gtk.SearchEntry()
        query.set_placeholder_text("Ej. María, admin, 3001234567")
        box.pack_start(query, False, False, 0)
        status = Gtk.Label(label="Escribe al menos 2 letras y pulsa Enter", xalign=0)
        status.get_style_context().add_class("link-muted")
        box.pack_start(status, False, False, 0)
        results = Gtk.ListBox()
        results.set_selection_mode(Gtk.SelectionMode.SINGLE)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(180)
        scroll.add(results)
        box.pack_start(scroll, True, True, 0)
        found_users: list[dict[str, Any]] = []

        def clear_rows() -> None:
            for child in list(results.get_children()):
                results.remove(child)

        def fill_rows(users: list[dict[str, Any]]) -> None:
            clear_rows()
            found_users.clear()
            found_users.extend(users)
            for item in users:
                row = Gtk.ListBoxRow()
                row.user_data = item
                name = str(item.get("username") or "?")
                aidyc = str(item.get("aidyc_username") or "").strip()
                phone = str(item.get("phone") or "").strip()
                bits = [name]
                if aidyc and aidyc.lower() != name.lower():
                    bits.append(f"AidyC: {aidyc}")
                if phone:
                    bits.append(phone)
                label = Gtk.Label(label=" · ".join(bits), xalign=0)
                label.set_margin_top(8)
                label.set_margin_bottom(8)
                label.set_margin_start(8)
                label.set_margin_end(8)
                row.add(label)
                results.add(row)
            results.show_all()
            if users:
                results.select_row(results.get_row_at_index(0))
                status.set_text(f"{len(users)} resultado(s)")
            else:
                status.set_text("Sin resultados")

        def run_search(*_args: object) -> None:
            text = (query.get_text() or "").strip()
            if len(text) < 2:
                status.set_text("Escribe al menos 2 letras")
                clear_rows()
                found_users.clear()
                return
            status.set_text("Buscando…")

            def work() -> None:
                try:
                    result = self.bridge.search_user(text)
                    error = None
                except Exception as exc:
                    result, error = None, exc
                GLib.idle_add(done_search, result, error)

            def done_search(result: Any, error: Exception | None) -> bool:
                if error:
                    status.set_text(f"Error: {error}")
                    clear_rows()
                    found_users.clear()
                    return GLib.SOURCE_REMOVE
                users = result.get("users") if isinstance(result, dict) else None
                if not isinstance(users, list):
                    user = result.get("user") if isinstance(result, dict) else None
                    users = [user] if isinstance(user, dict) else []
                fill_rows([u for u in users if isinstance(u, dict)])
                return GLib.SOURCE_REMOVE

            threading.Thread(target=work, daemon=True, name="aidychat-user-search").start()

        query.connect("activate", run_search)
        query.connect("search-changed", lambda *_: None)
        search_btn = Gtk.Button(label="Buscar")
        search_btn.connect("clicked", run_search)
        box.pack_start(search_btn, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        row = results.get_selected_row()
        user = getattr(row, "user_data", None) if row is not None else None
        if user is None and len(found_users) == 1:
            user = found_users[0]
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not isinstance(user, dict):
            return
        try:
            chat_id = self.bridge.create_chat(int(user["id"]))
            self.refresh_chats()
            self._active_chat = {
                "chat_id": chat_id,
                "username": user.get("username") or "Contacto",
            }
            self._last_id[chat_id] = 0
            self._build_conversation(self._active_chat)
            self._load_messages(initial=True)
        except Exception as exc:
            self.sidebar_status.set_text(f"No se pudo abrir conversación: {exc}")

    def _tick(self) -> bool:
        # Poll lightly; never block sends/loads with a global busy gate.
        if self._active_chat and self._inflight < 3:
            self._load_messages()
        if self.call_engine is not None:
            self.call_engine.check_incoming()
        return True

    def _on_destroy(self, *_args: object) -> None:
        if self._recorder:
            self._recorder.terminate()
        if self.call_engine is not None and self.call_engine.call is not None:
            self.call_engine.hangup()


def shutil_which(program: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        path = Path(directory) / program
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def run_cloud_chat() -> int:
    cfg = load_config()
    if not cfg or not cfg.cloud.enabled:
        return 2
    apply_aidychat_branding()
    win = AidyChatWindow(cfg)
    win.show_all()
    Gtk.main()
    return 0
