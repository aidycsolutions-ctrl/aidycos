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
window.aidychat-lan {
  background: #e5ddd5;
}
.wa-header {
  background: #075e54;
  padding: 10px 14px;
}
.wa-header label, .wa-header-title, .wa-header-sub {
  color: #ffffff;
}
.wa-header-title {
  font-weight: bold;
  font-size: 15px;
}
.wa-header-sub {
  font-size: 11px;
  opacity: 0.9;
}
.wa-header button {
  background: transparent;
  border: none;
  color: #ffffff;
  box-shadow: none;
  outline: none;
  padding: 4px;
}
.wa-header button:hover {
  background: rgba(255,255,255,0.12);
  border-radius: 18px;
}
.wa-peers {
  background: #f0f2f5;
  padding: 8px 10px;
  border-bottom: 1px solid #d1d7db;
}
.wa-peer {
  background: #ffffff;
  border-radius: 18px;
  padding: 6px 12px;
  border: 1px solid #e9edef;
  box-shadow: none;
}
.wa-peer:hover {
  background: #f5f6f6;
}
.wa-peer-selected {
  background: #d9fdd3;
  border-color: #25d366;
}
.wa-peer-mismatch {
  background: #fff7ed;
  border-color: #fdba74;
  color: #9a3412;
}
.wa-chat-head {
  background: #f0f2f5;
  padding: 8px 14px;
  border-bottom: 1px solid #d1d7db;
}
.wa-chat-head-title {
  font-weight: bold;
  color: #111b21;
}
.wa-chat-head-sub {
  color: #667781;
  font-size: 11px;
}
.lan-message-area, viewport.lan-message-area, scrolledwindow.lan-message-area {
  background: #e5ddd5;
  border: none;
  box-shadow: none;
}
.lan-bubble-in, .lan-bubble-out {
  border-radius: 8px;
  padding: 6px 8px 4px 8px;
  box-shadow: 0 1px 0.5px rgba(0,0,0,0.13);
}
.lan-bubble-in {
  background: #ffffff;
  border-top-left-radius: 0;
}
.lan-bubble-out {
  background: #d9fdd3;
  border-top-right-radius: 0;
}
.lan-sender {
  color: #53bdeb;
  font-size: 12px;
  font-weight: bold;
}
.lan-body {
  color: #111b21;
  font-size: 14px;
}
.lan-meta {
  color: #667781;
  font-size: 10px;
  padding-left: 8px;
}
.lan-composer {
  background: #f0f2f5;
  padding: 8px 10px;
}
.lan-composer entry {
  background: #ffffff;
  border-radius: 24px;
  border: none;
  padding: 8px 14px;
  color: #111b21;
  box-shadow: none;
}
.lan-composer button {
  border-radius: 20px;
  border: none;
  background: transparent;
  box-shadow: none;
  padding: 6px;
}
.lan-send {
  background: #25d366;
  color: #ffffff;
  border-radius: 22px;
  min-width: 42px;
  min-height: 42px;
  padding: 0;
}
.lan-send:hover {
  background: #1da851;
}
.lan-notice {
  color: #54656f;
  background: #fff5c4;
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 12px;
}
.lan-empty {
  color: #667781;
  font-size: 13px;
}
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


def _pids_on_aidylink_ports() -> set[int]:
    """PIDs listening on AidyChat LAN/mobile ports (orphans without a socket)."""
    try:
        out = subprocess.check_output(
            ["ss", "-ltnup"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        out_udp = subprocess.check_output(
            ["ss", "-lnup"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        out = out + "\n" + out_udp
    except (OSError, subprocess.CalledProcessError):
        return set()
    pids: set[int] = set()
    for line in out.splitlines():
        if ":47833" not in line and ":47835" not in line and ":47832" not in line:
            continue
        for part in line.replace(",", " ").split():
            if part.startswith("pid="):
                try:
                    pids.add(int(part.split("=", 1)[1]))
                except ValueError:
                    pass
    return pids


def _stop_orphan_daemon() -> None:
    """Kill a daemon that still holds ports after its control socket vanished."""
    from .paths import runtime_dir

    pid_path = runtime_dir() / "aidylink.pid"
    pids = set(_pids_on_aidylink_ports())
    if pid_path.is_file():
        try:
            pids.add(int(pid_path.read_text(encoding="utf-8").strip().splitlines()[0]))
        except (OSError, ValueError):
            pass
    me = os.getpid()
    for pid in sorted(pids):
        if pid <= 1 or pid == me:
            continue
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    import time

    time.sleep(0.4)
    for pid in sorted(_pids_on_aidylink_ports()):
        if pid <= 1 or pid == me:
            continue
        try:
            os.kill(pid, 9)
        except OSError:
            pass
    sock = control_socket_path()
    if sock.exists():
        try:
            sock.unlink()
        except OSError:
            pass
    if pid_path.exists():
        try:
            pid_path.unlink()
        except OSError:
            pass


def ensure_daemon_running() -> bool:
    """Start aidylink daemon in background if the control socket is down."""
    if _daemon_alive():
        return True
    # Common failure mode: ports still held but sock was deleted → UI sees no PCs.
    if _pids_on_aidylink_ports() or control_socket_path().exists():
        _stop_orphan_daemon()
    # Prefer the installed wrapper; fall back to the same interpreter/module.
    cmd: list[str]
    local_wrapper = Path.home() / ".local" / "bin" / "aidylink"
    system_wrapper = Path("/usr/local/bin/aidylink")
    if local_wrapper.is_file() and os.access(local_wrapper, os.X_OK):
        cmd = [str(local_wrapper), "daemon"]
    elif system_wrapper.is_file() and os.access(system_wrapper, os.X_OK):
        cmd = [str(system_wrapper), "daemon"]
    else:
        cmd = [sys.executable, "-m", "aidylink", "daemon"]
        env_pythonpath = os.environ.get("PYTHONPATH", "")
        user_pkg = str(Path.home() / ".local" / "share" / "aidycos" / "aidylink")
        if user_pkg not in env_pythonpath.split(":"):
            os.environ["PYTHONPATH"] = (
                user_pkg + (":" + env_pythonpath if env_pythonpath else "")
            )
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

    for _ in range(40):
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
        super().__init__(title="AidyChat")
        self.set_default_size(920, 700)
        self.set_border_width(0)
        self.get_style_context().add_class("aidychat-lan")
        _install_chat_style()

        self._peers: list[dict[str, Any]] = []
        self._selected_peer_data: dict[str, Any] | None = None
        self._seen_ids: set[str] = set()
        self._status_ok = False
        self._standalone = standalone
        self._mismatches: list[dict[str, Any]] = []
        self._messages: list[dict[str, Any]] = []

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        # WhatsApp-style green header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.get_style_context().add_class("wa-header")
        root.pack_start(header, False, False, 0)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        titles.set_hexpand(True)
        brand = Gtk.Label(label="AidyChat", xalign=0)
        brand.get_style_context().add_class("wa-header-title")
        titles.pack_start(brand, False, False, 0)
        self.status = Gtk.Label(label="Conectando…", xalign=0)
        self.status.set_line_wrap(True)
        self.status.get_style_context().add_class("wa-header-sub")
        titles.pack_start(self.status, False, False, 0)
        header.pack_start(titles, True, True, 0)

        self.refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic", Gtk.IconSize.BUTTON)
        self.refresh_btn.set_tooltip_text("Actualizar equipos")
        self.refresh_btn.connect("clicked", lambda *_: self.refresh_peers())
        header.pack_start(self.refresh_btn, False, False, 0)
        self.pair_btn = Gtk.Button.new_from_icon_name("network-workgroup-symbolic", Gtk.IconSize.BUTTON)
        self.pair_btn.set_tooltip_text("Emparejar")
        self.pair_btn.connect("clicked", lambda *_: self.open_pair_dialog())
        header.pack_start(self.pair_btn, False, False, 0)
        self.group_btn = Gtk.Button.new_from_icon_name("preferences-system-symbolic", Gtk.IconSize.BUTTON)
        self.group_btn.set_tooltip_text("Grupo local")
        self.group_btn.connect("clicked", lambda *_: self.open_group_dialog())
        header.pack_start(self.group_btn, False, False, 0)
        cfg = load_config()
        self.google_btn = Gtk.Button.new_from_icon_name(
            "avatar-default-symbolic" if cfg and cfg.cloud.enabled else "web-browser-symbolic",
            Gtk.IconSize.BUTTON,
        )
        self.google_btn.set_tooltip_text(
            "Cuenta conectada" if cfg and cfg.cloud.enabled else "Iniciar sesión con Google"
        )
        self.google_btn.connect("clicked", lambda *_: self.open_cloud_dialog())
        self.google_btn.set_sensitive(not bool(cfg and cfg.cloud.enabled))
        header.pack_start(self.google_btn, False, False, 0)

        # Compact peer chips (like chats strip)
        peers_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        peers_wrap.get_style_context().add_class("wa-peers")
        root.pack_start(peers_wrap, False, False, 0)
        self.peer_cards = Gtk.FlowBox()
        self.peer_cards.set_selection_mode(Gtk.SelectionMode.NONE)
        self.peer_cards.set_max_children_per_line(8)
        self.peer_cards.set_row_spacing(6)
        self.peer_cards.set_column_spacing(6)
        self.peer_cards.set_homogeneous(False)
        self.peer_cards.set_valign(Gtk.Align.START)
        peers_wrap.pack_start(self.peer_cards, False, False, 0)
        self.peer_empty = Gtk.Label(
            label="Buscando equipos en la red… Usa Emparejar si no aparecen.",
            xalign=0,
        )
        self.peer_empty.get_style_context().add_class("lan-empty")
        peers_wrap.pack_start(self.peer_empty, False, False, 0)
        # Keep a scroll handle unused (compat with older refresh helpers).
        self.peer_cards_scroll = peers_wrap

        chat_head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        chat_head.get_style_context().add_class("wa-chat-head")
        root.pack_start(chat_head, False, False, 0)
        self.chat_peer_label = Gtk.Label(label="Selecciona un computador", xalign=0)
        self.chat_peer_label.get_style_context().add_class("wa-chat-head-title")
        chat_head.pack_start(self.chat_peer_label, False, False, 0)
        self.chat_peer_sub = Gtk.Label(label="Los mensajes de esa conversación aparecen abajo", xalign=0)
        self.chat_peer_sub.get_style_context().add_class("wa-chat-head-sub")
        chat_head.pack_start(self.chat_peer_sub, False, False, 0)

        self.message_scroll = Gtk.ScrolledWindow()
        self.message_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.message_scroll.set_vexpand(True)
        self.message_scroll.set_shadow_type(Gtk.ShadowType.NONE)
        self.message_scroll.get_style_context().add_class("lan-message-area")
        self.message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.message_box.set_border_width(10)
        self.message_box.set_valign(Gtk.Align.END)
        self.message_box.get_style_context().add_class("lan-message-area")
        viewport = Gtk.Viewport()
        viewport.set_shadow_type(Gtk.ShadowType.NONE)
        viewport.get_style_context().add_class("lan-message-area")
        viewport.add(self.message_box)
        self.message_scroll.add(viewport)
        root.pack_start(self.message_scroll, True, True, 0)

        send_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        send_row.get_style_context().add_class("lan-composer")
        root.pack_start(send_row, False, False, 0)
        attach_btn = Gtk.Button.new_from_icon_name("mail-attachment-symbolic", Gtk.IconSize.BUTTON)
        attach_btn.set_tooltip_text("Adjuntar archivo o imagen (máx. 15 MB)")
        attach_btn.connect("clicked", lambda *_: self.choose_attachment())
        send_row.pack_start(attach_btn, False, False, 0)
        self.msg_entry = Gtk.Entry()
        self.msg_entry.set_placeholder_text("Escribe un mensaje")
        self.msg_entry.connect("activate", lambda *_: self.send_message())
        self.msg_entry.connect("key-press-event", self._on_entry_key)
        send_row.pack_start(self.msg_entry, True, True, 0)
        send_btn = Gtk.Button.new_from_icon_name("document-send-symbolic", Gtk.IconSize.BUTTON)
        send_btn.set_tooltip_text("Enviar")
        send_btn.get_style_context().add_class("lan-send")
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
        self.status.set_text(text)

    def refresh_status(self) -> None:
        try:
            resp = control_request({"cmd": "status"}, timeout=1.5)
        except Exception:
            self._set_status("Sin conexión con el servicio local", ok=False)
            return
        if not resp.get("ok"):
            self._set_status(resp.get("error") or "daemon error", ok=False)
            return
        team = str(resp.get("team_id") or "")
        peers = int(resp.get("peers") or 0)
        mismatches = int(resp.get("mismatches") or 0)
        if peers:
            self._set_status(f"en línea · {peers} equipo(s) · {team}")
        elif mismatches:
            self._set_status(f"en línea · hay equipos sin emparejar · {team}")
        else:
            self._set_status(f"en línea · buscando equipos · {team}")

    def refresh_peers(self, silent: bool = False) -> None:
        selected_id = str((self._selected_peer_data or {}).get("node_id") or "")
        try:
            resp = control_request({"cmd": "peers"}, timeout=1.5)
        except Exception:
            if not silent:
                self._set_peer_cards([])
                self.peer_empty.set_text("No se pudo buscar equipos en la red.")
            return
        peers = resp.get("peers") or []
        mismatches = resp.get("mismatches") or []
        self._peers = peers if isinstance(peers, list) else []
        self._mismatches = mismatches if isinstance(mismatches, list) else []
        self._set_peer_cards(self._peers, selected_id=selected_id)

    def _set_peer_cards(self, peers: list[dict[str, Any]], *, selected_id: str = "") -> None:
        previous = self._selected_peer_data
        for child in self.peer_cards.get_children():
            self.peer_cards.remove(child)
        self._selected_peer_data = None
        has_rows = bool(peers or self._mismatches)
        self.peer_empty.set_visible(not has_rows)
        if peers:
            empty_text = ""
        elif self._mismatches:
            empty_text = "Equipos cerca sin el mismo código. Pulsa uno o Emparejar."
        else:
            empty_text = "Buscando equipos… Empareja con el código si no aparecen."
        self.peer_empty.set_text(empty_text)
        for peer in peers:
            card = Gtk.Button(label=str(peer.get("display_name") or "PC"))
            card.set_relief(Gtk.ReliefStyle.NONE)
            card.get_style_context().add_class("wa-peer")
            card.peer_data = peer
            card.connect("clicked", self._select_peer_card)
            self.peer_cards.add(card)
            if selected_id and str(peer.get("node_id") or "") == selected_id:
                self._selected_peer_data = peer
                card.get_style_context().add_class("wa-peer-selected")
        for hint in self._mismatches:
            name = str(hint.get("display_name") or hint.get("host") or "PC")
            card = Gtk.Button(label=f"{name} · sin emparejar")
            card.set_relief(Gtk.ReliefStyle.NONE)
            card.get_style_context().add_class("wa-peer")
            card.get_style_context().add_class("wa-peer-mismatch")
            card.peer_data = None
            card.mismatch_data = hint
            card.set_tooltip_text(
                "Mismo Wi‑Fi, pero otro código de grupo. Pulsa Emparejar para unirlos."
            )
            card.connect("clicked", lambda *_: self.open_pair_dialog())
            self.peer_cards.add(card)
        if self._selected_peer_data is None and previous is not None:
            # Keep selection object if peer briefly disappeared from discovery.
            self._selected_peer_data = previous
        self.peer_cards.show_all()

    def _select_peer_card(self, card: Gtk.Button) -> None:
        self._selected_peer_data = getattr(card, "peer_data", None)
        for child in self.peer_cards.get_children():
            btn = child.get_child() if hasattr(child, "get_child") else None
            # FlowBoxChild wraps the button.
            target = btn if isinstance(btn, Gtk.Button) else child
            if isinstance(target, Gtk.FlowBoxChild):
                target = target.get_child()
            if isinstance(target, Gtk.Button):
                ctx = target.get_style_context()
                ctx.remove_class("wa-peer-selected")
                if target is card:
                    ctx.add_class("wa-peer-selected")
        if self._selected_peer_data:
            name = str(self._selected_peer_data.get("display_name") or "Computador")
            self.peer_empty.set_visible(False)
            self.chat_peer_label.set_text(name)
            self.chat_peer_sub.set_text("en línea en la red local")
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

        # Outer row: left/right alignment like WhatsApp
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        row.set_halign(Gtk.Align.END if mine else Gtk.Align.START)
        row.set_margin_top(1)
        row.set_margin_bottom(1)
        row.set_margin_start(8 if mine else 4)
        row.set_margin_end(4 if mine else 8)

        bubble = Gtk.EventBox()
        bubble.set_halign(Gtk.Align.END if mine else Gtk.Align.START)
        bubble.set_hexpand(False)
        bubble_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        bubble_box.set_halign(Gtk.Align.FILL)
        bubble_box.set_hexpand(False)
        bubble_box.get_style_context().add_class("lan-bubble-out" if mine else "lan-bubble-in")
        bubble.add(bubble_box)
        bubble.msg_data = msg

        if not mine:
            name = Gtk.Label(
                label=str(msg.get("from_name") or "Contacto"),
                xalign=0,
            )
            name.get_style_context().add_class("lan-sender")
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

                original = GdkPixbuf.Pixbuf.new_from_file(media_path)
                # Tiny test / corrupt thumbnails look like pink blocks when
                # stretched; show a file chip instead.
                if original.get_width() < 8 or original.get_height() < 8:
                    raise ValueError("thumbnail too small")
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(media_path, 240, 240, True)
                image = Gtk.Image.new_from_pixbuf(pb)
                image.set_halign(Gtk.Align.START)
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

        try:
            stamp = datetime.fromtimestamp(float(msg.get("ts") or 0)).strftime("%H:%M")
        except (TypeError, ValueError, OSError):
            stamp = "--:--"

        # WhatsApp-like: text + timestamp on the same visual block
        content_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        content_row.set_halign(Gtk.Align.START)
        if text:
            body = Gtk.Label(label=text, xalign=0)
            body.set_line_wrap(True)
            body.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            body.set_max_width_chars(36)
            body.set_selectable(True)
            body.get_style_context().add_class("lan-body")
            content_row.pack_start(body, False, False, 0)
        meta = Gtk.Label(label=stamp, xalign=1.0)
        meta.set_valign(Gtk.Align.END)
        meta.get_style_context().add_class("lan-meta")
        content_row.pack_end(meta, False, False, 0)
        bubble_box.pack_start(content_row, False, False, 0)

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
        try:
            info = control_request({"cmd": "pair_info"}, timeout=3.0)
        except Exception:
            info = {}
        if not info.get("ok"):
            try:
                info = control_request({"cmd": "pair_host"}, timeout=3.0)
            except Exception as exc:
                self._append_line(f"⚠ No se pudo abrir Emparejar: {exc}")
                return
        code = str(info.get("group_code") or "")
        mobile_url = str(info.get("mobile_url") or "")
        dialog = Gtk.Dialog(title="Emparejar", transient_for=self, flags=0)
        dialog.add_buttons(
            "Cerrar", Gtk.ResponseType.CANCEL,
            "Ingresar código de otro PC", Gtk.ResponseType.REJECT,
        )
        dialog.set_default_size(460, 520)
        box = dialog.get_content_area()
        box.set_spacing(10)
        box.set_border_width(16)
        box.pack_start(
            Gtk.Label(
                label=(
                    "Este es tu código de grupo (no caduca). Compártelo una vez. "
                    "Si cambian de Wi‑Fi, al estar otra vez en la misma red se ven solos."
                ),
                xalign=0,
                wrap=True,
            ),
            False,
            False,
            0,
        )
        pin_label = Gtk.Label()
        pin_label.set_markup(
            f"<span size='xx-large' weight='bold'>{GLib.markup_escape_text(code or '------')}</span>"
        )
        pin_label.set_selectable(True)
        box.pack_start(pin_label, False, False, 4)
        if mobile_url:
            qr = self._qr_image(mobile_url)
            if qr is not None:
                box.pack_start(qr, False, False, 4)
            url_label = Gtk.Label(label=mobile_url, xalign=0.5, selectable=True)
            url_label.set_line_wrap(True)
            box.pack_start(url_label, False, False, 0)
        box.pack_start(
            Gtk.Label(
                label="Móvil: escanea el QR. Otro PC: «Ingresar código» con estos 6 dígitos.",
                xalign=0,
                wrap=True,
            ),
            False,
            False,
            0,
        )
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.REJECT:
            self._pair_enter_code()
        self.refresh_status()
        self.refresh_peers()

    def _qr_image(self, url: str, size: int = 220) -> Gtk.Widget | None:
        try:
            import io

            import qrcode
            from gi.repository import GdkPixbuf
        except Exception:
            return None
        try:
            qr = qrcode.QRCode(border=2, box_size=6)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            loader = GdkPixbuf.PixbufLoader.new_with_type("png")
            loader.write(buf.getvalue())
            loader.close()
            pixbuf = loader.get_pixbuf()
            if pixbuf is None:
                return None
            scaled = pixbuf.scale_simple(size, size, GdkPixbuf.InterpType.NEAREST)
            return Gtk.Image.new_from_pixbuf(scaled)
        except Exception:
            return None

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
        mobile_url = str(resp.get("mobile_url") or "")
        # Track PC pairing separately from mobile QR joins. Closing after a
        # phone connects used to kill the PIN before the other PC could join.
        state = {"pc_paired": False, "mobile_joined": False}
        dialog = Gtk.Dialog(title="Código de emparejado", transient_for=self, flags=0)
        dialog.add_buttons("Cerrar", Gtk.ResponseType.CANCEL)
        dialog.set_default_size(440, 520)
        box = dialog.get_content_area()
        box.set_spacing(10)
        box.set_border_width(16)

        box.pack_start(
            Gtk.Label(
                label=(
                    "Deja esta ventana abierta. En el otro PC: Emparejar → Ingresar código. "
                    "El móvil puede escanear el QR sin gastar el código del PC."
                ),
                xalign=0,
                wrap=True,
            ),
            False,
            False,
            0,
        )
        pin_label = Gtk.Label()
        pin_label.set_markup(
            f"<span size='xx-large' weight='bold'>{GLib.markup_escape_text(pin)}</span>"
        )
        pin_label.set_selectable(True)
        box.pack_start(pin_label, False, False, 4)

        if mobile_url:
            qr = self._qr_image(mobile_url)
            if qr is not None:
                box.pack_start(qr, False, False, 4)
            url_label = Gtk.Label(label=mobile_url, xalign=0.5, selectable=True)
            url_label.set_line_wrap(True)
            url_label.get_style_context().add_class("wa-chat-head-sub")
            box.pack_start(url_label, False, False, 0)

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
            mobiles = int(status.get("mobiles") or 0)
            if mobiles:
                state["mobile_joined"] = True
            if status.get("active"):
                left = int(status.get("expires_in") or 0)
                bits = [f"Esperando al otro PC… quedan ~{left}s"]
                if mobiles:
                    bits.append(f"{mobiles} móvil(es) ya conectado(s)")
                hint.set_text(" · ".join(bits))
                return True
            if status.get("paired"):
                state["pc_paired"] = True
                hint.set_text("¡PC emparejado! Ya pueden chatear en la red local.")
                GLib.timeout_add(700, dialog.response, Gtk.ResponseType.OK)
                return False
            if state["mobile_joined"]:
                hint.set_text(
                    "El código expiró para PCs. El móvil que ya entró sigue conectado."
                )
                return False
            hint.set_text("El código expiró. Cierra e inténtalo de nuevo.")
            return False

        GLib.timeout_add_seconds(1, poll_pair)
        dialog.run()
        dialog.destroy()
        # Only cancel an unused PIN. A successful PC pair already consumed it.
        if not state["pc_paired"]:
            try:
                control_request({"cmd": "pair_stop"}, timeout=2.0)
            except Exception:
                pass
        if state["pc_paired"]:
            self._append_line("✓ Otro computador se emparejó con este PC.")
        elif state["mobile_joined"]:
            self._append_line("✓ Móvil conectado. Si falta un PC, vuelve a Emparejar.")
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
