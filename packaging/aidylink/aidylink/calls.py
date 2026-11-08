"""Native audio/video calls over AidyChat signaling and GStreamer WebRTC."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstSdp", "1.0")
gi.require_version("GstWebRTC", "1.0")
from gi.repository import GLib, Gst, GstSdp, GstWebRTC  # noqa: E402

from .cloud import AidyChatBridge

LOGGER = logging.getLogger(__name__)


class NativeCall:
    """One-to-one voice/video call; signaling is polled through AidyChat."""

    def __init__(
        self,
        bridge: AidyChatBridge,
        *,
        on_status: Callable[[str], None],
        on_incoming: Callable[[dict[str, Any]], bool],
        on_finished: Callable[[], None],
    ) -> None:
        Gst.init(None)
        self.bridge = bridge
        self.on_status = on_status
        self.on_incoming = on_incoming
        self.on_finished = on_finished
        self.call: dict[str, Any] | None = None
        self.pipeline: Gst.Pipeline | None = None
        self.pc: Gst.Element | None = None
        self.mic_volume: Gst.Element | None = None
        self._stop = threading.Event()
        self._last_signal_id = 0
        self._pending_ice: list[tuple[int, str]] = []
        self._remote_description_ready = False
        self._offerer = False
        self._video = False
        self._push_to_talk = False
        self._active = False
        self._muted = False
        self._incoming_pending = False

    @staticmethod
    def available(video: bool = False) -> bool:
        Gst.init(None)
        audio_ready = bool(
            Gst.ElementFactory.find("webrtcbin")
            and Gst.ElementFactory.find("opusenc")
        )
        return audio_ready and (not video or bool(Gst.ElementFactory.find("vp8enc")))

    def start(self, chat_id: int, call_type: str = "audio", *, push_to_talk: bool = False) -> None:
        if self.call:
            raise RuntimeError("Ya hay una llamada en curso")
        self._stop.clear()
        self._last_signal_id = 0
        self._pending_ice.clear()
        self._remote_description_ready = False
        self._video = call_type == "video"
        self._push_to_talk = push_to_talk

        def run() -> None:
            try:
                result = self.bridge.start_call(chat_id, call_type)
                self.call = result.get("call")
                if not self.call:
                    raise RuntimeError(result.get("error") or "No se inició la llamada")
                self._offerer = True
                self._status(f"Llamando a {self.call.get('callee_name') or 'contacto'}…")
                started = time.monotonic()
                while not self._stop.wait(1.0):
                    state = self.bridge.call_status(int(self.call["id"])).get("call") or {}
                    status = state.get("status")
                    if status == "accepted":
                        self.call = state
                        GLib.idle_add(self._connect)
                        return
                    if status != "ringing" or time.monotonic() - started > 50:
                        if status == "ringing":
                            self.bridge.hangup_call(int(self.call["id"]), "missed")
                        self._status("Sin respuesta")
                        self._finish()
                        return
            except Exception as exc:
                self._status(f"No se pudo llamar: {exc}")
                self._finish()

        threading.Thread(target=run, daemon=True, name="aidylink-call-start").start()

    def check_incoming(self) -> None:
        if self.call or self._incoming_pending:
            return
        self._incoming_pending = True

        def run() -> None:
            try:
                data = self.bridge.incoming_call()
                call = data.get("call")
                if not isinstance(call, dict) or self.call:
                    self._incoming_pending = False
                    return
                GLib.idle_add(self._ask_incoming, call)
            except Exception as exc:
                self._incoming_pending = False
                LOGGER.debug("incoming call check: %s", exc)

        threading.Thread(target=run, daemon=True, name="aidylink-call-incoming").start()

    def _ask_incoming(self, call: dict[str, Any]) -> bool:
        self._incoming_pending = False
        if self.call:
            return GLib.SOURCE_REMOVE
        self._stop.clear()
        self.call = call
        self._video = call.get("call_type") == "video"
        self._last_signal_id = 0
        self._pending_ice.clear()
        self._remote_description_ready = False
        result = self.on_incoming(call)
        if result:
            self._offerer = False
            self._status(f"Conectando con {call.get('caller_name') or 'contacto'}…")
            threading.Thread(target=self._accept, daemon=True, name="aidylink-call-accept").start()
        else:
            threading.Thread(
                target=lambda: self.bridge.hangup_call(int(call["id"]), "declined"),
                daemon=True,
            ).start()
            self._finish()
        return GLib.SOURCE_REMOVE

    def _accept(self) -> None:
        try:
            self.bridge.accept_call(int(self.call["id"]))
            GLib.idle_add(self._connect)
        except Exception as exc:
            self._status(f"No se pudo aceptar: {exc}")
            self._finish()

    def _connect(self) -> bool:
        if not self.call:
            return GLib.SOURCE_REMOVE
        try:
            if not self.available():
                raise RuntimeError("Faltan los componentes GStreamer WebRTC en AidyC-OS")
            self._create_pipeline()
            self.pipeline.set_state(Gst.State.PLAYING)
            self._active = True
            if self._push_to_talk:
                self.set_muted(True)
            self._status("En llamada" if not self._video else "En videollamada")
            if self._offerer:
                self._create_offer()
            threading.Thread(target=self._signal_loop, daemon=True, name="aidylink-call-signal").start()
        except Exception as exc:
            self._status(f"No se pudo conectar audio/vídeo: {exc}")
            self.hangup()
        return GLib.SOURCE_REMOVE

    def _create_pipeline(self) -> None:
        video_src = (
            "autovideosrc ! videoconvert ! queue ! vp8enc deadline=1 keyframe-max-dist=30 "
            "! rtpvp8pay pt=97 ! "
            "application/x-rtp,media=video,encoding-name=VP8,payload=97 ! queue ! pc. "
            if self._video
            else ""
        )
        description = (
            "webrtcbin name=pc bundle-policy=max-bundle "
            "stun-server=stun://stun.l.google.com:19302 "
            "autoaudiosrc ! audioconvert ! audioresample ! volume name=micvol "
            "! opusenc ! rtpopuspay pt=96 ! "
            "application/x-rtp,media=audio,encoding-name=OPUS,payload=96 ! queue ! pc. "
            + video_src
        )
        self.pipeline = Gst.parse_launch(description)
        self.pc = self.pipeline.get_by_name("pc")
        self.mic_volume = self.pipeline.get_by_name("micvol")
        if not self.pc:
            raise RuntimeError("No se pudo crear webrtcbin")
        if self.bridge.cfg.cloud.turn_server:
            self.pc.set_property("turn-server", self.bridge.cfg.cloud.turn_server)
        self.pc.connect("on-ice-candidate", self._on_ice)
        self.pc.connect("pad-added", self._on_remote_pad)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_gst_error)

    def _on_ice(self, _pc: Gst.Element, mline: int, candidate: str) -> None:
        self._send_signal("ice", {"candidate": candidate, "sdpMLineIndex": mline})

    def _on_remote_pad(self, _pc: Gst.Element, pad: Gst.Pad) -> None:
        if not self.pipeline:
            return
        caps = pad.get_current_caps() or pad.query_caps(None)
        structure = caps.get_structure(0) if caps and caps.get_size() else None
        name = structure.get_name() if structure else ""
        media = structure.get_string("media") if structure and structure.has_field("media") else ""
        is_video = media == "video" or name.startswith("video/")
        desc = (
            "queue ! decodebin ! videoconvert ! autovideosink sync=false"
            if is_video
            else "queue ! decodebin ! audioconvert ! audioresample ! autoaudiosink sync=false"
        )
        sink_bin = Gst.parse_bin_from_description(desc, True)
        self.pipeline.add(sink_bin)
        sink_bin.sync_state_with_parent()
        sink_pad = sink_bin.get_static_pad("sink")
        if sink_pad and not sink_pad.is_linked():
            pad.link(sink_pad)

    def _on_gst_error(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        error, debug = message.parse_error()
        LOGGER.warning("GStreamer call error: %s (%s)", error, debug)
        self._status(f"Error multimedia: {error}")
        self.hangup()

    def _create_offer(self) -> None:
        if not self.pc:
            return
        promise = Gst.Promise.new_with_change_func(self._offer_created, None, None)
        self.pc.emit("create-offer", None, promise)

    def _offer_created(self, promise: Gst.Promise, *_args: object) -> None:
        try:
            offer = promise.get_reply().get_value("offer")
            self.pc.emit("set-local-description", offer, Gst.Promise.new())
            self._send_signal("offer", {"type": "offer", "sdp": offer.sdp.as_text()})
        except Exception as exc:
            LOGGER.exception("create offer: %s", exc)
            self._status(f"Falló la oferta de llamada: {exc}")

    def _signal_loop(self) -> None:
        while not self._stop.wait(0.8):
            call = self.call
            if not call:
                return
            try:
                data = self.bridge.get_call_signals(int(call["id"]), since_id=self._last_signal_id)
                self._last_signal_id = int(data.get("last_id") or self._last_signal_id)
                if data.get("status") not in (None, "ringing", "accepted"):
                    GLib.idle_add(self._finish)
                    return
                for signal in data.get("signals") or []:
                    GLib.idle_add(self._apply_signal, signal)
            except Exception as exc:
                LOGGER.debug("call signal poll: %s", exc)

    def _send_signal(self, kind: str, payload: Any) -> None:
        call = self.call
        if not call:
            return

        def run() -> None:
            try:
                self.bridge.send_call_signal(int(call["id"]), kind, payload)
            except Exception as exc:
                LOGGER.warning("send call signal %s: %s", kind, exc)

        threading.Thread(target=run, daemon=True, name="aidylink-call-ice").start()

    def _apply_signal(self, signal: dict[str, Any]) -> bool:
        if not self.pc:
            return GLib.SOURCE_REMOVE
        kind = signal.get("type")
        payload = signal.get("payload") or {}
        try:
            if kind in ("offer", "answer"):
                parsed, sdp_message = GstSdp.SDPMessage.new_from_text(str(payload.get("sdp") or ""))
                if parsed != GstSdp.SDPResult.OK:
                    raise RuntimeError("SDP recibido no válido")
                sdp_type = GstWebRTC.WebRTCSDPType.OFFER if kind == "offer" else GstWebRTC.WebRTCSDPType.ANSWER
                description = GstWebRTC.WebRTCSessionDescription.new(sdp_type, sdp_message)
                promise = Gst.Promise.new_with_change_func(self._remote_description_set, kind, None)
                self.pc.emit("set-remote-description", description, promise)
            elif kind == "ice":
                item = (int(payload.get("sdpMLineIndex") or 0), str(payload.get("candidate") or ""))
                if self._remote_description_ready:
                    self.pc.emit("add-ice-candidate", *item)
                else:
                    self._pending_ice.append(item)
            elif kind == "hangup":
                self._finish()
        except Exception as exc:
            LOGGER.warning("apply call signal %s: %s", kind, exc)
            self._status(f"Error de señalización: {exc}")
        return GLib.SOURCE_REMOVE

    def _remote_description_set(self, promise: Gst.Promise, kind: str, *_args: object) -> None:
        try:
            reply = promise.get_reply()
            if reply and reply.has_field("error"):
                raise RuntimeError(str(reply.get_value("error")))
            self._remote_description_ready = True
            pending, self._pending_ice = self._pending_ice, []
            for mline, candidate in pending:
                self.pc.emit("add-ice-candidate", mline, candidate)
            if kind == "offer":
                answer = Gst.Promise.new_with_change_func(self._answer_created, None, None)
                self.pc.emit("create-answer", None, answer)
        except Exception as exc:
            self._status(f"No se pudo aplicar la descripción remota: {exc}")

    def _answer_created(self, promise: Gst.Promise, *_args: object) -> None:
        try:
            answer = promise.get_reply().get_value("answer")
            self.pc.emit("set-local-description", answer, Gst.Promise.new())
            self._send_signal("answer", {"type": "answer", "sdp": answer.sdp.as_text()})
        except Exception as exc:
            LOGGER.exception("create answer: %s", exc)
            self._status(f"Falló la respuesta: {exc}")

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        if self.mic_volume:
            self.mic_volume.set_property("volume", 0.0 if muted else 1.0)

    def hangup(self) -> None:
        call = self.call
        self._stop.set()
        self._active = False
        self.call = None
        if call:
            threading.Thread(
                target=lambda: self.bridge.hangup_call(int(call["id"])),
                daemon=True,
                name="aidylink-call-hangup",
            ).start()
        if self.pipeline:
            try:
                self.pipeline.set_state(Gst.State.NULL)
            except Exception:
                pass
        self.pipeline = None
        self.pc = None
        self.mic_volume = None
        self._status("Llamada finalizada")
        self._finish()

    def _finish(self) -> None:
        self._stop.set()
        self.call = None
        self._active = False
        if self.pipeline:
            try:
                self.pipeline.set_state(Gst.State.NULL)
            except Exception:
                pass
        self.pipeline = None
        self.pc = None
        self.mic_volume = None
        GLib.idle_add(self.on_finished)

    def _status(self, text: str) -> None:
        GLib.idle_add(self.on_status, text)
