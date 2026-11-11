"""Ventana GTK de AidyChat (LAN) — habla con el daemon por el socket de control."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from .config import default_team_secret, init_config, load_config, save_config
from .daemon import control_request
from .messages import MAX_ATTACHMENT_BYTES
from .native_auth import start_google_login
from .paths import control_socket_path


CHAT_CSS = b"""
window.aidychat-lan { background: #efeae2; }
.lan-status { color: #667781; }
.lan-message-area { background: #efeae2; }
.lan-bubble-in {
  background: #ffffff;
  border-radius: 10px;
  padding: 8px 11px;
}
.lan-bubble-out {
  background: #d9fdd3;
  border-radius: 10px;
  padding: 8px 11px;
}
.lan-meta { color: #667781; font-size: 10px; }
.lan-composer { background: #f0f2f5; padding: 8px; }
.lan-notice { color: #667781; font-style: italic; padding: 4px 12px; }
"""


def _install_chat_style() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_data(CHAT_CSS)
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def _daemon_alive() -> bool:
    try:
        resp = control_request({"cmd": "ping"}, timeout=0.8)
        return bool(resp.get("ok"))
    except Exception:
        return False


def ensure_daemon_running() -> bool:
    """Start aidylink daemon in background if the control socket is down."""
    if _daemon_alive():
        return True
    sock = control_socket_path()
    if sock.exists():
        try:
            sock.unlink()
        except OSError:
            pass
    # Prefer the installed wrapper; fall back to the same interpreter/module.
    cmd: list[str]
    wrapper = Path("/usr/local/bin/aidylink")
    if wrapper.is_file() and os.access(wrapper, os.X_OK):
        cmd = [str(wrapper), "daemon"]
    else:
        cmd = [sys.executable, "-m", "aidylink", "daemon"]
    log_path = Path.home() / ".local" / "share" / "aidylink" / "daemon.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        subprocess.Popen(
            cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=os.environ.copy(),
        )
    import time

    for _ in range(25):
        if _daemon_alive():
            return True
        time.sleep(0.2)
    return _daemon_alive()


def _first_run_setup() -> bool:
    """Simple dialog to create identity if missing. Returns True if config exists."""
    if load_config() is not None:
        return True

    dialog = Gtk.Dialog(title="Bienvenido a AidyChat", flags=0)
    dialog.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        "Continuar", Gtk.ResponseType.OK,
    )
    dialog.set_default_size(460, 280)
    box = dialog.get_content_area()
    box.set_spacing(8)
    box.set_border_width(12)
    box.pack_start(
        Gtk.Label(
            label=(
                "¿Cómo llamamos a este computador?\n\n"
                "Cada PC tiene su propia IP: eso es normal. Para verse entre sí "
                "usa Emparejar con un código de 6 dígitos (no hace falta copiar IPs)."
            ),
            xalign=0,
            wrap=True,
        ),
        False,
        False,
        0,
    )
    name_e = Gtk.Entry()
    name_e.set_placeholder_text("Por ejemplo: Caja, Recepción o Oficina")
    name_e.set_activates_default(True)
    dialog.set_default_response(Gtk.ResponseType.OK)
    team_e = Gtk.Entry()
    team_e.set_text("AidyCOS")
    team_e.set_placeholder_text("Nombre de la red local")
    secret_e = Gtk.Entry()
    secret_e.set_placeholder_text("Dejar vacío (recomendado)")
    secret_e.set_visibility(False)
    box.pack_start(Gtk.Label(label="Nombre de este computador", xalign=0), False, False, 0)
    box.pack_start(name_e, False, False, 0)
    advanced = Gtk.Expander(label="Configuración avanzada (opcional)")
    advanced_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    advanced_box.pack_start(
        Gtk.Label(
            label="Solo si quieres forzar un grupo/código a mano. Lo habitual es Emparejar.",
            xalign=0,
            wrap=True,
        ),
        False,
        False,
        0,
    )
    advanced_box.pack_start(Gtk.Label(label="Nombre del grupo", xalign=0), False, False, 0)
    advanced_box.pack_start(team_e, False, False, 0)
    advanced_box.pack_start(Gtk.Label(label="Código compartido del grupo", xalign=0), False, False, 0)
    advanced_box.pack_start(secret_e, False, False, 0)
    advanced.add(advanced_box)
    advanced.set_expanded(False)
    box.pack_start(advanced, False, False, 0)
    dialog.show_all()
    response = dialog.run()
    if response != Gtk.ResponseType.OK:
        dialog.destroy()
        return False
    name = (name_e.get_text() or "").strip() or "AidyC-OS"
    team = (team_e.get_text() or "").strip() or "AidyCOS"
    secret = (secret_e.get_text() or "").strip() or None
    dialog.destroy()
    init_config(display_name=name, team_id=team, team_secret=secret)
    return True


class AidylinkWindow(Gtk.Window):
    def __init__(self, *, standalone: bool = True) -> None:
        super().__init__(title="AidyChat · Red local")
        self.set_default_size(820, 720)
        self.set_border_width(10)
        self.get_style_context().add_class("aidychat-lan")
        _install_chat_style()

        self._peers: list[dict[str, Any]] = []
        self._selected_peer_data: dict[str, Any] | None = None
        self._seen_ids: set[str] = set()
        self._status_ok = False
        self._standalone = standalone
        self._mismatches: list[dict[str, Any]] = []
        self._messages: list[dict[str, Any]] = []

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(root)

        self.status = Gtk.Label(label="Listo para conectar", xalign=0)
        self.status.set_line_wrap(True)
        self.status.get_style_context().add_class("lan-status")
        root.pack_start(self.status, False, False, 0)

        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root.pack_start(title_row, False, False, 0)
        title_row.pack_start(Gtk.Label(label="Computadores disponibles", xalign=0), True, True, 0)
        self.refresh_btn = Gtk.Button(label="Actualizar")
        self.refresh_btn.connect("clicked", lambda *_: self.refresh_peers())
        title_row.pack_start(self.refresh_btn, False, False, 0)
        self.pair_btn = Gtk.Button(label="Emparejar")
        self.pair_btn.connect("clicked", lambda *_: self.open_pair_dialog())
        title_row.pack_start(self.pair_btn, False, False, 0)
        self.group_btn = Gtk.Button(label="Grupo local")
        self.group_btn.connect("clicked", lambda *_: self.open_group_dialog())
        title_row.pack_start(self.group_btn, False, False, 0)
        cfg = load_config()
        self.google_btn = Gtk.Button(label="Cuenta conectada" if cfg and cfg.cloud.enabled else "Iniciar sesión con Google")
        self.google_btn.connect("clicked", lambda *_: self.open_cloud_dialog())
        self.google_btn.set_sensitive(not bool(cfg and cfg.cloud.enabled))
        title_row.pack_start(self.google_btn, False, False, 0)

        self.peer_cards = Gtk.FlowBox()
        self.peer_cards.set_selection_mode(Gtk.SelectionMode.NONE)
        self.peer_cards.set_max_children_per_line(3)
        self.peer_cards.set_row_spacing(8)
        self.peer_cards.set_column_spacing(8)
        self.peer_cards.set_homogeneous(True)
        self.peer_cards_scroll = Gtk.ScrolledWindow()
        self.peer_cards_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.peer_cards_scroll.set_min_content_height(100)
        self.peer_cards_scroll.add(self.peer_cards)
        root.pack_start(self.peer_cards_scroll, False, True, 0)
        self.peer_empty = Gtk.Label(label="Buscando computadores de AidyChat en esta red…", xalign=0)
        self.peer_empty.get_style_context().add_class("dim-label")
        root.pack_start(self.peer_empty, False, False, 0)

        self.chat_peer_label = Gtk.Label(label="Selecciona un computador para chatear", xalign=0)
        self.chat_peer_label.get_style_context().add_class("lan-status")
        root.pack_start(self.chat_peer_label, False, False, 0)

        self.message_scroll = Gtk.ScrolledWindow()
        self.message_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.message_scroll.set_vexpand(True)
        self.message_scroll.get_style_context().add_class("lan-message-area")
        self.message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.message_box.set_border_width(12)
        self.message_box.get_style_context().add_class("lan-message-area")
        self.message_scroll.add_with_viewport(self.message_box)
        root.pack_start(self.message_scroll, True, True, 0)

        send_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        send_row.get_style_context().add_class("lan-composer")
        root.pack_start(send_row, False, False, 0)
        attach_btn = Gtk.Button.new_from_icon_name("mail-attachment-symbolic", Gtk.IconSize.BUTTON)
        attach_btn.set_tooltip_text("Adjuntar archivo o imagen (máx. 15 MB)")
        attach_btn.connect("clicked", lambda *_: self.choose_attachment())
        send_row.pack_start(attach_btn, False, False, 0)
        self.msg_entry = Gtk.Entry()
        self.msg_entry.set_placeholder_text("Escribe un mensaje… (Ctrl+V pega imagen)")
        self.msg_entry.connect("activate", lambda *_: self.send_message())
        self.msg_entry.connect("key-press-event", self._on_entry_key)
        send_row.pack_start(self.msg_entry, True, True, 0)
        send_btn = Gtk.Button(label="Enviar")
        send_btn.connect("clicked", lambda *_: self.send_message())
        send_row.pack_start(send_btn, False, False, 0)

        self.connect("key-press-event", self._on_window_key)
        if self._standalone:
            self.connect("destroy", Gtk.main_quit)
        self.refresh_status()
        self._apply_qemu_defaults()
        self.refresh_peers()
        self.refresh_inbox(initial=True)
        GLib.timeout_add_seconds(2, self._tick)

    def _apply_qemu_defaults(self) -> None:
        """Keep QEMU routing out of the user-facing interface."""
        return

    def _tick(self) -> bool:
        self.refresh_status()
        self.refresh_peers(silent=True)
        self.refresh_inbox()
        return True

    def _set_status(self, text: str, ok: bool = True) -> None:
        self._status_ok = ok
        prefix = "● " if ok else "○ "
        self.status.set_markup(f"{prefix}{GLib.markup_escape_text(text)}")

    def refresh_status(self) -> None:
        try:
            resp = control_request({"cmd": "status"}, timeout=1.5)
        except Exception:
            self._set_status("No se pudo conectar con AidyLink", ok=False)
            return
        if not resp.get("ok"):
            self._set_status(resp.get("error") or "daemon error", ok=False)
            return
        team = str(resp.get("team_id") or "")
        peers = int(resp.get("peers") or 0)
        mismatches = int(resp.get("mismatches") or 0)
        if peers:
            self._set_status(f"Conectado · {peers} equipo(s) · grupo {team}")
        elif mismatches:
            self._set_status(
                f"Conectado · hay AidyLink cerca pero el grupo/código no coincide · grupo {team}"
            )
        else:
            self._set_status(f"Conectado · buscando equipos cercanos · grupo {team}")

    def refresh_peers(self, silent: bool = False) -> None:
        selected_id = str((self._selected_peer_data or {}).get("node_id") or "")
        try:
            resp = control_request({"cmd": "peers"}, timeout=1.5)
        except Exception:
            if not silent:
                self._set_peer_cards([])
                self.peer_empty.set_text("No se pudo encontrar AidyLink en esta red.")
            return
        peers = resp.get("peers") or []
        mismatches = resp.get("mismatches") or []
        self._peers = peers if isinstance(peers, list) else []
        self._mismatches = mismatches if isinstance(mismatches, list) else []
        self._set_peer_cards(self._peers, selected_id=selected_id)

    def _set_peer_cards(self, peers: list[dict[str, Any]], *, selected_id: str = "") -> None:
        for child in self.peer_cards.get_children():
            self.peer_cards.remove(child)
        self._selected_peer_data = None
        self.peer_empty.set_visible(not peers)
        if peers:
            empty_text = ""
        elif self._mismatches:
            labels = []
            for item in self._mismatches[:3]:
                name = str(item.get("display_name") or "").strip()
                host = str(item.get("host") or "?")
                labels.append(f"{name} ({host})" if name else host)
            empty_text = (
                f"Hay AidyChat cerca ({', '.join(labels)}) pero aún no están emparejados. "
                "Pulsa Emparejar: un PC muestra el código y el otro lo escribe."
            )
        else:
            empty_text = (
                "Aún no hay computadores disponibles. Ambos deben estar en la misma Wi‑Fi/LAN "
                "con AidyChat abierto. IPs distintas son normales; usa Emparejar con el código."
            )
        self.peer_empty.set_text(empty_text)
        for peer in peers:
            card = Gtk.Button()
            card.set_relief(Gtk.ReliefStyle.NONE)
            card.peer_data = peer
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            content.set_border_width(12)
            avatar = Gtk.Label(label="💻")
            avatar.set_halign(Gtk.Align.START)
            name = Gtk.Label(label=str(peer.get("display_name") or "Computador"), xalign=0)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            hint = Gtk.Label(label="En esta red · Seleccionar", xalign=0)
            hint.get_style_context().add_class("dim-label")
            content.pack_start(avatar, False, False, 0)
            content.pack_start(name, False, False, 0)
            content.pack_start(hint, False, False, 0)
            card.add(content)
            card.connect("clicked", self._select_peer_card)
            self.peer_cards.add(card)
            if selected_id and str(peer.get("node_id") or "") == selected_id:
                self._selected_peer_data = peer
                hint.set_text("Seleccionado · listo para escribir")
        self.peer_cards.show_all()

    def _select_peer_card(self, card: Gtk.Button) -> None:
        self._selected_peer_data = getattr(card, "peer_data", None)
        if self._selected_peer_data:
            name = str(self._selected_peer_data.get("display_name") or "Computador")
            self.peer_empty.set_text(f"Chat con {name}.")
            self.peer_empty.show()
            self.chat_peer_label.set_text(f"Conversación con {name}")
            self.refresh_inbox(initial=True)

    def refresh_inbox(self, initial: bool = False) -> None:
        try:
            resp = control_request({"cmd": "inbox", "limit": 300}, timeout=1.5)
        except Exception:
            return
        messages = resp.get("messages") or []
        if not isinstance(messages, list):
            return
        selected_id = str((self._selected_peer_data or {}).get("node_id") or "")
        filtered: list[dict[str, Any]] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if selected_id and selected_id not in (
                str(msg.get("from_id") or ""),
                str(msg.get("to_id") or ""),
            ):
                continue
            filtered.append(msg)

        if initial:
            self._seen_ids.clear()
            self._messages = []
            for child in list(self.message_box.get_children()):
                self.message_box.remove(child)
            for msg in filtered:
                mid = str(msg.get("msg_id") or "")
                if mid:
                    self._seen_ids.add(mid)
                self._append_bubble(msg)
            GLib.idle_add(self._scroll_chat_end)
            return

        for msg in filtered:
            mid = str(msg.get("msg_id") or "")
            if mid and mid in self._seen_ids:
                continue
            if mid:
                self._seen_ids.add(mid)
            self._append_bubble(msg)
        if filtered:
            GLib.idle_add(self._scroll_chat_end)

    def _scroll_chat_end(self) -> bool:
        adj = self.message_scroll.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return GLib.SOURCE_REMOVE

    def _append_notice(self, text: str) -> None:
        label = Gtk.Label(label=text, xalign=0.5)
        label.set_line_wrap(True)
        label.get_style_context().add_class("lan-notice")
        self.message_box.pack_start(label, False, False, 0)
        self.message_box.show_all()
        GLib.idle_add(self._scroll_chat_end)

    def _append_line(self, line: str) -> None:
        # Compat: system / pairing notices still use this helper.
        self._append_notice(line)

    def _append_bubble(self, msg: dict[str, Any]) -> None:
        cfg = load_config()
        my_id = cfg.node_id if cfg else ""
        from_id = str(msg.get("from_id") or "")
        mine = from_id == my_id
        self._messages.append(msg)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        row.set_halign(Gtk.Align.END if mine else Gtk.Align.START)
        bubble = Gtk.EventBox()
        bubble_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        bubble_box.set_margin_start(8)
        bubble_box.set_margin_end(8)
        bubble_box.get_style_context().add_class("lan-bubble-out" if mine else "lan-bubble-in")
        bubble.add(bubble_box)
        bubble.msg_data = msg

        if not mine:
            name = Gtk.Label(
                label=str(msg.get("from_name") or "Contacto"),
                xalign=0,
            )
            name.get_style_context().add_class("lan-meta")
            bubble_box.pack_start(name, False, False, 0)

        kind = str(msg.get("kind") or "text")
        text = str(msg.get("text") or "")
        media_path = str(msg.get("media_path") or "")
        filename = str(msg.get("filename") or "")
        if not kind or kind == "text":
            mime = str(msg.get("mime") or "")
            if mime.startswith("image/") or (media_path and filename.lower().endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
            )):
                kind = "image"
            elif media_path or filename:
                kind = "file"

        if kind == "image" and media_path and Path(media_path).is_file():
            try:
                from gi.repository import GdkPixbuf

                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(media_path, 280, 280, True)
                image = Gtk.Image.new_from_pixbuf(pb)
                bubble_box.pack_start(image, False, False, 0)
            except Exception:
                btn = Gtk.Button(label=f"🖼 {filename or 'Imagen'}")
                btn.connect("clicked", lambda *_a, p=media_path: self._open_path(p))
                bubble_box.pack_start(btn, False, False, 0)
        elif kind in ("image", "file") and (media_path or filename):
            label = filename or ("Imagen" if kind == "image" else "Archivo")
            btn = Gtk.Button(label=f"📎 {label}")
            btn.set_halign(Gtk.Align.START)
            if media_path and Path(media_path).is_file():
                btn.connect("clicked", lambda *_a, p=media_path: self._open_path(p))
            bubble_box.pack_start(btn, False, False, 0)

        if text:
            body = Gtk.Label(label=text, xalign=0)
            body.set_line_wrap(True)
            body.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            body.set_max_width_chars(42)
            body.set_selectable(True)
            bubble_box.pack_start(body, False, False, 0)

        try:
            stamp = datetime.fromtimestamp(float(msg.get("ts") or 0)).strftime("%H:%M")
        except (TypeError, ValueError, OSError):
            stamp = "--:--"
        meta = Gtk.Label(label=stamp, xalign=1.0 if mine else 0.0)
        meta.get_style_context().add_class("lan-meta")
        bubble_box.pack_start(meta, False, False, 0)

        bubble.connect("button-press-event", self._on_bubble_press)
        row.pack_start(bubble, False, False, 0)
        self.message_box.pack_start(row, False, False, 0)
        self.message_box.show_all()

    def _open_path(self, path: str) -> None:
        try:
            subprocess.Popen(
                ["xdg-open", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            self._append_notice(f"⚠ No se pudo abrir: {exc}")

    def _on_bubble_press(self, widget: Gtk.EventBox, event: Gdk.EventButton) -> bool:
        if event.type != Gdk.EventType.BUTTON_PRESS or event.button != 3:
            return False
        msg = getattr(widget, "msg_data", None)
        if not isinstance(msg, dict):
            return False
        menu = Gtk.Menu()
        copy_item = Gtk.MenuItem(label="Copiar")
        copy_item.connect("activate", lambda *_: self.copy_message(msg))
        menu.append(copy_item)
        forward_item = Gtk.MenuItem(label="Reenviar…")
        forward_item.connect("activate", lambda *_: self.forward_message(msg))
        menu.append(forward_item)
        media_path = str(msg.get("media_path") or "")
        if media_path and Path(media_path).is_file():
            open_item = Gtk.MenuItem(label="Abrir archivo")
            open_item.connect("activate", lambda *_: self._open_path(media_path))
            menu.append(open_item)
            save_item = Gtk.MenuItem(label="Guardar como…")
            save_item.connect("activate", lambda *_: self.save_attachment(msg))
            menu.append(save_item)
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def copy_message(self, msg: dict[str, Any]) -> None:
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        text = str(msg.get("text") or "").strip()
        media_path = str(msg.get("media_path") or "")
        filename = str(msg.get("filename") or "")
        if text:
            clip.set_text(text, -1)
            self._append_notice("Mensaje copiado.")
            return
        if media_path and Path(media_path).is_file():
            # Prefer file URI so paste into other apps works.
            uri = Path(media_path).resolve().as_uri()
            clip.set_text(uri, -1)
            self._append_notice(f"Ruta copiada: {filename or media_path}")
            return
        clip.set_text(filename or "(vacío)", -1)
        self._append_notice("Copiado.")

    def forward_message(self, msg: dict[str, Any]) -> None:
        peers = [p for p in self._peers if isinstance(p, dict)]
        if not peers:
            self._append_notice("⚠ No hay otros computadores para reenviar.")
            return
        dialog = Gtk.Dialog(title="Reenviar mensaje", transient_for=self, flags=0)
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Reenviar", Gtk.ResponseType.OK,
        )
        dialog.set_default_size(360, 160)
        box = dialog.get_content_area()
        box.set_border_width(12)
        box.set_spacing(8)
        box.pack_start(Gtk.Label(label="Enviar a:", xalign=0), False, False, 0)
        combo = Gtk.ComboBoxText()
        for peer in peers:
            combo.append(
                str(peer.get("node_id") or ""),
                str(peer.get("display_name") or peer.get("node_id") or "?"),
            )
        combo.set_active(0)
        box.pack_start(combo, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        target = combo.get_active_id() or ""
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not target:
            return
        text = str(msg.get("text") or "")
        media_path = str(msg.get("media_path") or "")
        payload: dict[str, Any] = {"cmd": "send", "to": target, "text": text}
        timeout = 5.0
        if media_path and Path(media_path).is_file():
            payload["file"] = media_path
            timeout = 90.0
        elif not text:
            self._append_notice("⚠ Ese mensaje no se puede reenviar.")
            return
        try:
            resp = control_request(payload, timeout=timeout)
        except Exception as exc:
            self._append_notice(f"⚠ Reenvío falló: {exc}")
            return
        if resp.get("ok"):
            self._append_notice("Mensaje reenviado.")
            self.refresh_inbox()
        else:
            self._append_notice(f"⚠ No se pudo reenviar: {resp.get('detail') or 'error'}")

    def save_attachment(self, msg: dict[str, Any]) -> None:
        media_path = str(msg.get("media_path") or "")
        if not media_path or not Path(media_path).is_file():
            return
        dialog = Gtk.FileChooserDialog(
            title="Guardar archivo",
            parent=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Guardar", Gtk.ResponseType.OK,
        )
        dialog.set_current_name(str(msg.get("filename") or Path(media_path).name))
        response = dialog.run()
        dest = dialog.get_filename() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if not dest:
            return
        try:
            shutil.copy2(media_path, dest)
            self._append_notice(f"Guardado en {dest}")
        except OSError as exc:
            self._append_notice(f"⚠ No se pudo guardar: {exc}")

    def _on_entry_key(self, _entry: Gtk.Entry, event: Gdk.EventKey) -> bool:
        if event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval in (
            Gdk.KEY_v,
            Gdk.KEY_V,
        ):
            if self._paste_clipboard_media():
                return True
        return False

    def _on_window_key(self, _window: Gtk.Window, event: Gdk.EventKey) -> bool:
        if event.state & Gdk.ModifierType.CONTROL_MASK and event.keyval in (
            Gdk.KEY_v,
            Gdk.KEY_V,
        ):
            # Only intercept when focus isn't a text field that wants plain paste,
            # except our composer which already handles images.
            return False
        return False

    def _paste_clipboard_media(self) -> bool:
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        # File URIs first (Nautilus copy).
        uris = clip.wait_for_uris()
        if uris:
            for uri in uris:
                if uri.startswith("file://"):
                    path = Path(GLib.filename_from_uri(uri)[0])
                    if path.is_file():
                        self.send_attachment(path)
                        return True
        image = clip.wait_for_image()
        if image is not None:
            fd, tmp_name = tempfile.mkstemp(prefix="aidychat-paste-", suffix=".png")
            os.close(fd)
            tmp_path = Path(tmp_name)
            try:
                image.savev(str(tmp_path), "png", [], [])
            except Exception as exc:
                tmp_path.unlink(missing_ok=True)
                self._append_notice(f"⚠ No se pudo pegar la imagen: {exc}")
                return True
            self.send_attachment(tmp_path, cleanup=True)
            return True
        return False

    def choose_attachment(self) -> None:
        dialog = Gtk.FileChooserDialog(
            title="Adjuntar archivo",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Adjuntar", Gtk.ResponseType.OK,
        )
        filt_all = Gtk.FileFilter()
        filt_all.set_name("Todos los archivos")
        filt_all.add_pattern("*")
        dialog.add_filter(filt_all)
        filt_img = Gtk.FileFilter()
        filt_img.set_name("Imágenes")
        filt_img.add_mime_type("image/*")
        dialog.add_filter(filt_img)
        response = dialog.run()
        path = dialog.get_filename() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if path:
            self.send_attachment(Path(path))

    def send_attachment(self, path: Path, *, cleanup: bool = False) -> None:
        path = Path(path)
        if not path.is_file():
            self._append_notice("⚠ Archivo no encontrado.")
            return
        size = path.stat().st_size
        if size <= 0 or size > MAX_ATTACHMENT_BYTES:
            self._append_notice("⚠ El archivo debe pesar entre 1 byte y 15 MB.")
            if cleanup:
                path.unlink(missing_ok=True)
            return
        peer = self._selected_peer()
        if not peer:
            self._append_notice("⚠ Selecciona un computador disponible primero.")
            if cleanup:
                path.unlink(missing_ok=True)
            return
        if not self._status_ok:
            self._append_notice("⚠ El daemon de AidyChat no está disponible.")
            if cleanup:
                path.unlink(missing_ok=True)
            return
        caption = (self.msg_entry.get_text() or "").strip()
        payload = {
            "cmd": "send",
            "to": peer.get("node_id") or peer.get("display_name") or "",
            "text": caption,
            "file": str(path.resolve()),
        }
        self._append_notice(f"Enviando {path.name}…")
        try:
            resp = control_request(payload, timeout=90.0)
        except Exception as exc:
            self._append_notice(f"⚠ Error al enviar archivo: {exc}")
            if cleanup:
                path.unlink(missing_ok=True)
            return
        if cleanup:
            path.unlink(missing_ok=True)
        if resp.get("ok"):
            self.msg_entry.set_text("")
            self.refresh_inbox()
        else:
            self._append_notice(
                f"⚠ No se pudo enviar el archivo: {resp.get('detail') or 'revisa la conexión'}"
            )

    def _selected_peer(self) -> dict[str, Any] | None:
        return self._selected_peer_data

    def open_pair_dialog(self) -> None:
        cfg = load_config()
        if cfg is None:
            self._append_line("⚠ No se encontró la configuración de AidyChat.")
            return
        chooser = Gtk.Dialog(title="Emparejar computadores", transient_for=self, flags=0)
        chooser.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Ingresar código", Gtk.ResponseType.REJECT,
            "Mostrar código", Gtk.ResponseType.OK,
        )
        chooser.set_default_size(460, 180)
        box = chooser.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.pack_start(
            Gtk.Label(
                label=(
                    "No necesitas copiar IPs. En un PC pulsa «Mostrar código» y en el otro "
                    "«Ingresar código» con esos 6 dígitos. Así ambos quedan en el mismo grupo."
                ),
                xalign=0,
                wrap=True,
            ),
            False,
            False,
            0,
        )
        chooser.show_all()
        response = chooser.run()
        chooser.destroy()
        if response == Gtk.ResponseType.OK:
            self._pair_show_code()
        elif response == Gtk.ResponseType.REJECT:
            self._pair_enter_code()

    def _pair_show_code(self) -> None:
        try:
            resp = control_request({"cmd": "pair_host"}, timeout=3.0)
        except Exception as exc:
            self._append_line(f"⚠ No se pudo crear el código: {exc}")
            return
        if not resp.get("ok"):
            self._append_line(f"⚠ {resp.get('error') or 'No se pudo crear el código'}")
            return
        pin = str(resp.get("pin") or "")
        paired = {"done": False}
        dialog = Gtk.Dialog(title="Código de emparejado", transient_for=self, flags=0)
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL)
        dialog.set_default_size(420, 220)
        box = dialog.get_content_area()
        box.set_spacing(10)
        box.set_border_width(16)
        box.pack_start(
            Gtk.Label(
                label="En el otro computador abre Emparejar → Ingresar código y escribe:",
                xalign=0,
                wrap=True,
            ),
            False,
            False,
            0,
        )
        pin_label = Gtk.Label()
        pin_label.set_markup(f"<span size='xx-large' weight='bold'>{GLib.markup_escape_text(pin)}</span>")
        pin_label.set_selectable(True)
        box.pack_start(pin_label, False, False, 8)
        hint = Gtk.Label(
            label="Esperando al otro PC… el código caduca en unos 3 minutos.",
            xalign=0,
            wrap=True,
        )
        box.pack_start(hint, False, False, 0)
        dialog.show_all()

        def poll_pair() -> bool:
            if not dialog.get_visible():
                return False
            try:
                status = control_request({"cmd": "pair_status"}, timeout=1.5)
            except Exception:
                return True
            if status.get("active"):
                left = int(status.get("expires_in") or 0)
                hint.set_text(f"Esperando al otro PC… quedan ~{left}s.")
                return True
            if status.get("paired"):
                paired["done"] = True
                hint.set_text("¡Emparejado! Ya pueden chatear en la red local.")
                GLib.timeout_add(600, dialog.response, Gtk.ResponseType.OK)
                return False
            hint.set_text("El código expiró. Cierra e inténtalo de nuevo.")
            return False

        GLib.timeout_add_seconds(1, poll_pair)
        dialog.run()
        dialog.destroy()
        if not paired["done"]:
            try:
                control_request({"cmd": "pair_stop"}, timeout=2.0)
            except Exception:
                pass
        else:
            self._append_line("✓ Otro computador se emparejó con este PC.")
        self.refresh_status()
        self.refresh_peers()

    def _pair_enter_code(self) -> None:
        dialog = Gtk.Dialog(title="Ingresar código", transient_for=self, flags=0)
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Emparejar", Gtk.ResponseType.OK,
        )
        dialog.set_default_size(400, 160)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.pack_start(
            Gtk.Label(label="Código de 6 dígitos del otro PC", xalign=0),
            False,
            False,
            0,
        )
        pin_e = Gtk.Entry()
        pin_e.set_max_length(6)
        pin_e.set_placeholder_text("123456")
        pin_e.set_input_purpose(Gtk.InputPurpose.DIGITS)
        pin_e.set_activates_default(True)
        dialog.set_default_response(Gtk.ResponseType.OK)
        box.pack_start(pin_e, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        pin = (pin_e.get_text() or "").strip()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not pin:
            return
        self._append_line("Buscando el otro computador en la red…")
        self.pair_btn.set_sensitive(False)

        def work() -> None:
            try:
                resp = control_request({"cmd": "pair_join", "pin": pin}, timeout=45.0)
                error = None
            except Exception as exc:
                resp, error = None, exc
            GLib.idle_add(finish, resp, error)

        def finish(resp: dict[str, Any] | None, error: Exception | None) -> bool:
            self.pair_btn.set_sensitive(True)
            if error:
                self._append_line(f"⚠ Emparejado falló: {error}")
                return GLib.SOURCE_REMOVE
            if not resp or not resp.get("ok"):
                self._append_line(f"⚠ {((resp or {}).get('error') if resp else None) or 'No se pudo emparejar'}")
                return GLib.SOURCE_REMOVE
            host_name = str(resp.get("host_name") or "otro PC")
            self._append_line(f"✓ Emparejado con {host_name}. Ya pueden verse en la red local.")
            self.refresh_status()
            self.refresh_peers()
            return GLib.SOURCE_REMOVE

        import threading

        threading.Thread(target=work, daemon=True, name="aidychat-pair-join").start()

    def open_group_dialog(self) -> None:
        cfg = load_config()
        if cfg is None:
            self._append_line("⚠ No se encontró la configuración de AidyChat.")
            return
        dialog = Gtk.Dialog(title="Grupo local de AidyChat", transient_for=self, flags=0)
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Guardar y reiniciar", Gtk.ResponseType.OK,
        )
        dialog.set_default_size(480, 280)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.pack_start(
            Gtk.Label(
                label="Todos los PCs del mismo local deben compartir el mismo grupo y código. "
                "Si otro AidyLink aparece en la red pero no en la lista, casi siempre es por esto.",
                xalign=0,
                wrap=True,
            ),
            False,
            False,
            0,
        )
        name_e = Gtk.Entry()
        name_e.set_text(cfg.display_name)
        team_e = Gtk.Entry()
        team_e.set_text(cfg.team_id)
        secret_e = Gtk.Entry()
        secret_e.set_text(cfg.team_secret)
        secret_e.set_visibility(True)
        for label, entry in (
            ("Nombre de este computador", name_e),
            ("Nombre del grupo", team_e),
            ("Código compartido", secret_e),
        ):
            box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
            box.pack_start(entry, False, False, 0)
        if self._mismatches:
            hosts = ", ".join(str(item.get("host") or "?") for item in self._mismatches[:3])
            box.pack_start(
                Gtk.Label(
                    label=f"Detectado en la red sin coincidir: {hosts}",
                    xalign=0,
                    wrap=True,
                ),
                False,
                False,
                0,
            )
        hint = Gtk.Label(
            label=(
                "En el otro PC ejecuta:\n"
                f"aidylink init --name SU_NOMBRE --team {cfg.team_id} --team-secret {cfg.team_secret}\n"
                "systemctl --user restart aidylink"
            ),
            xalign=0,
            selectable=True,
        )
        hint.set_line_wrap(True)
        box.pack_start(hint, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        if response != Gtk.ResponseType.OK:
            dialog.destroy()
            return
        name = (name_e.get_text() or "").strip() or cfg.display_name
        team = (team_e.get_text() or "").strip() or "AidyCOS"
        secret = (secret_e.get_text() or "").strip() or default_team_secret(team)
        dialog.destroy()
        cfg.display_name = name
        cfg.team_id = team
        cfg.team_secret = secret
        save_config(cfg)
        self._append_line(f"✓ Grupo local guardado: {team}. Reiniciando AidyLink…")
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
        GLib.timeout_add_seconds(1, lambda: (self.refresh_status() or self.refresh_peers() or False) or False)

    def open_cloud_dialog(self) -> None:
        cfg = load_config()
        if cfg is None:
            self._append_line("⚠ No se encontró la configuración de AidyChat.")
            return
        self.google_btn.set_sensitive(False)
        self._append_line("Preparando inicio de sesión con Google…")

        def done(username: str | None, error: Exception | None) -> None:
            GLib.idle_add(finish, username, error)

        def ready(url: str, opened: bool) -> None:
            GLib.idle_add(show_ready, url, opened)

        def show_ready(url: str, opened: bool) -> bool:
            if opened:
                self._append_line(
                    "Se intentó abrir el navegador. Si no aparece, usa el enlace del diálogo."
                )
            else:
                self._append_line("No se abrió el navegador solo. Usa el enlace del diálogo.")
            dialog = Gtk.Dialog(title="Iniciar sesión con Google", transient_for=self, flags=0)
            dialog.add_buttons(
                "Reabrir navegador", Gtk.ResponseType.APPLY,
                "Cerrar", Gtk.ResponseType.CLOSE,
            )
            dialog.set_default_size(560, 220)
            box = dialog.get_content_area()
            box.set_spacing(8)
            box.set_border_width(12)
            box.pack_start(
                Gtk.Label(
                    label=(
                        "Completa Google en el navegador. Si no se abrió una ventana, "
                        "copia este enlace o pulsa «Reabrir navegador»:"
                    ),
                    xalign=0,
                    wrap=True,
                ),
                False,
                False,
                0,
            )
            link = Gtk.Entry()
            link.set_text(url)
            link.set_editable(False)
            link.set_visibility(True)
            box.pack_start(link, False, False, 0)
            dialog.show_all()
            link.select_region(0, -1)

            def on_response(dlg: Gtk.Dialog, response: int) -> None:
                if response == Gtk.ResponseType.APPLY:
                    from .native_auth import open_login_url

                    open_login_url(url)
                    return
                dlg.destroy()

            dialog.connect("response", on_response)
            return GLib.SOURCE_REMOVE

        def finish(username: str | None, error: Exception | None) -> bool:
            self.google_btn.set_sensitive(True)
            if error:
                self._append_line(f"⚠ No se pudo iniciar sesión: {error}")
                return GLib.SOURCE_REMOVE
            self._append_line(f"✓ Sesión iniciada como {username or 'AidyChat'}.")
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
            self.destroy()
            return GLib.SOURCE_REMOVE

        start_google_login(cfg, done, on_ready=ready)

    def send_message(self) -> None:
        text = (self.msg_entry.get_text() or "").strip()
        if not text:
            return
        if not self._status_ok:
            self._append_notice("⚠ Arranca el daemon primero (aidylink daemon o systemd).")
            return

        peer = self._selected_peer()
        if not peer:
            self._append_notice("⚠ Selecciona un computador disponible primero.")
            return
        payload: dict[str, Any] = {
            "cmd": "send",
            "to": peer.get("node_id") or peer.get("display_name") or "",
            "text": text,
        }

        try:
            resp = control_request(payload, timeout=5.0)
        except Exception as exc:
            self._append_notice(f"⚠ Error: {exc}")
            return

        if resp.get("ok"):
            self.msg_entry.set_text("")
            self.refresh_inbox()
        else:
            self._append_notice(
                "⚠ No se pudo enviar. Revisa que el otro computador siga conectado."
            )


def run_ui() -> int:
    if not _first_run_setup():
        return 1

    if not ensure_daemon_running():
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="No se pudo arrancar el daemon de AidyLink",
        )
        dialog.format_secondary_text(
            "Revisa ~/.local/share/aidylink/daemon.log\n"
            "o ejecuta en una terminal: aidylink daemon"
        )
        dialog.run()
        dialog.destroy()
        return 1

    cfg = load_config()
    if cfg is not None and cfg.cloud.enabled:
        # Keep the local LAN window available for accounts without AidyChat;
        # a linked account opens the richer native conversation interface.
        from .chat_window import run_cloud_chat

        return run_cloud_chat()

    win = AidylinkWindow()
    win.show_all()
    Gtk.main()
    cfg = load_config()
    if cfg is not None and cfg.cloud.enabled:
        from .chat_window import run_cloud_chat

        return run_cloud_chat()
    return 0
