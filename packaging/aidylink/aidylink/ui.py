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
from .branding import apply_aidychat_branding
from .paths import control_socket_path


CHAT_CSS = b"""
window.aidychat-lan {
  background: #efeae2;
}
.wa-sidebar {
  background: #ffffff;
  border-right: 1px solid #d1d7db;
}
.wa-header {
  background: #075e54;
  padding: 12px 14px;
}
.wa-header label, .wa-header-title, .wa-header-sub {
  color: #ffffff;
}
.wa-header-title {
  font-weight: bold;
  font-size: 17px;
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
.wa-search {
  background: #f0f2f5;
  padding: 8px 12px;
}
.wa-search entry {
  background: #ffffff;
  border-radius: 8px;
  border: none;
  padding: 8px 10px;
  color: #111b21;
  box-shadow: none;
}
.wa-contact {
  padding: 10px 14px;
  border-bottom: 1px solid #f0f2f5;
  background: #ffffff;
}
.wa-contact:hover {
  background: #f5f6f6;
}
row:selected .wa-contact {
  background: #f0f2f5;
}
.wa-contact-name {
  font-weight: 600;
  color: #111b21;
  font-size: 14px;
}
.wa-contact-preview {
  color: #667781;
  font-size: 12px;
}
.wa-contact-meta {
  color: #667781;
  font-size: 11px;
}
.wa-badge {
  background: #25d366;
  color: #ffffff;
  border-radius: 10px;
  padding: 1px 7px;
  font-size: 11px;
  font-weight: bold;
}
.wa-chat-head {
  background: #f0f2f5;
  padding: 10px 14px;
  border-bottom: 1px solid #d1d7db;
}
.wa-chat-head-title {
  font-weight: bold;
  color: #111b21;
  font-size: 15px;
}
.wa-chat-head-sub {
  color: #667781;
  font-size: 12px;
}
.lan-message-area, viewport.lan-message-area, scrolledwindow.lan-message-area {
  background: #efeae2;
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
  padding: 10px 14px;
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
  min-width: 44px;
  min-height: 44px;
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
  font-size: 14px;
}
.wa-empty-pane {
  background: #f0f2f5;
}
.wa-connect {
  background: #25d366;
  color: #ffffff;
  border-radius: 18px;
  padding: 6px 14px;
  border: none;
}
.emoji-grid button {
  background: transparent;
  border: none;
  box-shadow: none;
  font-size: 18px;
  min-width: 36px;
  min-height: 36px;
  padding: 2px;
}
.emoji-grid button:hover {
  background: #f0f2f5;
  border-radius: 8px;
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


EMOJI_SET = (
    "😀 😂 🥹 😍 🥰 😎 🤔 🙌 👍 👎 👏 🔥 ✨ ✅ ❌ ❤️ 💙 💚 💛 💜 "
    "😅 😭 😴 🤯 🤝 🙏 💪 🎉 🎂 ☕ 🍕 🏠 💻 📱 📷 📎 📷 ⭐ 🌟 🚀"
).split()


class AidylinkWindow(Gtk.Window):
    def __init__(self, *, standalone: bool = True) -> None:
        super().__init__(title="AidyChat")
        self.set_default_size(1120, 740)
        self.set_border_width(0)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.get_style_context().add_class("aidychat-lan")
        apply_aidychat_branding(self)
        _install_chat_style()

        self._peers: list[dict[str, Any]] = []
        self._selected_peer_data: dict[str, Any] | None = None
        self._selected_mismatch: dict[str, Any] | None = None
        self._seen_ids: set[str] = set()
        self._status_ok = False
        self._standalone = standalone
        self._mismatches: list[dict[str, Any]] = []
        self._messages: list[dict[str, Any]] = []
        self._connecting = False
        self._pending_ask_dialog: Gtk.Dialog | None = None
        self._seen_ask_ids: set[str] = set()
        self._previews: dict[str, str] = {}
        self._emoji_popover: Gtk.Popover | None = None
        self._rebuild_contacts = True

        split = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        split.set_position(340)
        self.add(split)

        # ---- Sidebar (lista estilo WhatsApp / aidyc-web) ----
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.sidebar.set_size_request(300, -1)
        self.sidebar.get_style_context().add_class("wa-sidebar")
        split.pack1(self.sidebar, False, False)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.get_style_context().add_class("wa-header")
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
        self.refresh_btn.connect("clicked", lambda *_: self._manual_refresh())
        header.pack_start(self.refresh_btn, False, False, 0)
        self.pair_btn = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        self.pair_btn.set_tooltip_text("Emparejar / nuevo contacto")
        self.pair_btn.connect("clicked", lambda *_: self.open_pair_dialog())
        header.pack_start(self.pair_btn, False, False, 0)
        self.settings_btn = Gtk.Button.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON)
        self.settings_btn.set_tooltip_text("Ajustes")
        self.settings_btn.connect("clicked", lambda *_: self.open_settings_menu())
        header.pack_start(self.settings_btn, False, False, 0)
        self.sidebar.pack_start(header, False, False, 0)

        search_wrap = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        search_wrap.get_style_context().add_class("wa-search")
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Buscar chat o equipo")
        self.search.connect("search-changed", self._filter_contacts)
        search_wrap.pack_start(self.search, True, True, 0)
        self.sidebar.pack_start(search_wrap, False, False, 0)

        self.chat_list = Gtk.ListBox()
        self.chat_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.chat_list.connect("row-selected", self._on_contact_selected)
        chat_scroll = Gtk.ScrolledWindow()
        chat_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        chat_scroll.set_vexpand(True)
        chat_scroll.add(self.chat_list)
        self.sidebar.pack_start(chat_scroll, True, True, 0)

        self.peer_empty = Gtk.Label(
            label="Buscando equipos en la red…",
            xalign=0,
        )
        self.peer_empty.set_margin_start(14)
        self.peer_empty.set_margin_end(14)
        self.peer_empty.set_margin_top(8)
        self.peer_empty.set_margin_bottom(10)
        self.peer_empty.set_line_wrap(True)
        self.peer_empty.get_style_context().add_class("lan-empty")
        self.sidebar.pack_start(self.peer_empty, False, False, 0)

        # Compat aliases used by older helpers
        self.peer_cards = self.chat_list
        self.peer_cards_scroll = chat_scroll
        self.google_btn = self.settings_btn
        self.group_btn = self.settings_btn

        # ---- Conversation pane ----
        self.conversation = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        split.pack2(self.conversation, True, False)

        chat_head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        chat_head.get_style_context().add_class("wa-chat-head")
        head_titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        head_titles.set_hexpand(True)
        self.chat_peer_label = Gtk.Label(label="AidyChat", xalign=0)
        self.chat_peer_label.get_style_context().add_class("wa-chat-head-title")
        head_titles.pack_start(self.chat_peer_label, False, False, 0)
        self.chat_peer_sub = Gtk.Label(
            label="Selecciona un chat a la izquierda para empezar",
            xalign=0,
        )
        self.chat_peer_sub.get_style_context().add_class("wa-chat-head-sub")
        head_titles.pack_start(self.chat_peer_sub, False, False, 0)
        chat_head.pack_start(head_titles, True, True, 0)
        self.connect_peer_btn = Gtk.Button(label="Conectar")
        self.connect_peer_btn.get_style_context().add_class("wa-connect")
        self.connect_peer_btn.set_tooltip_text("Pedir conexión a este PC")
        self.connect_peer_btn.connect("clicked", lambda *_: self._connect_selected_mismatch())
        self.connect_peer_btn.set_no_show_all(True)
        self.connect_peer_btn.hide()
        chat_head.pack_start(self.connect_peer_btn, False, False, 0)
        self.conversation.pack_start(chat_head, False, False, 0)

        self.message_scroll = Gtk.ScrolledWindow()
        self.message_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.message_scroll.set_vexpand(True)
        self.message_scroll.set_shadow_type(Gtk.ShadowType.NONE)
        self.message_scroll.get_style_context().add_class("lan-message-area")
        self.message_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.message_box.set_border_width(12)
        self.message_box.set_valign(Gtk.Align.END)
        self.message_box.get_style_context().add_class("lan-message-area")
        viewport = Gtk.Viewport()
        viewport.set_shadow_type(Gtk.ShadowType.NONE)
        viewport.get_style_context().add_class("lan-message-area")
        viewport.add(self.message_box)
        self.message_scroll.add(viewport)
        self.conversation.pack_start(self.message_scroll, True, True, 0)

        send_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        send_row.get_style_context().add_class("lan-composer")
        self.conversation.pack_start(send_row, False, False, 0)
        attach_btn = Gtk.Button.new_from_icon_name("mail-attachment-symbolic", Gtk.IconSize.BUTTON)
        attach_btn.set_tooltip_text("Adjuntar archivo o imagen (máx. 15 MB)")
        attach_btn.connect("clicked", lambda *_: self.choose_attachment())
        send_row.pack_start(attach_btn, False, False, 0)
        theme = Gtk.IconTheme.get_default()
        emoji_icon = "face-smile-symbolic"
        if theme is None or not theme.has_icon(emoji_icon):
            emoji_icon = "face-smile"
        if theme is not None and theme.has_icon(emoji_icon):
            emoji_btn = Gtk.Button.new_from_icon_name(emoji_icon, Gtk.IconSize.BUTTON)
        else:
            emoji_btn = Gtk.Button(label="😊")
        emoji_btn.set_tooltip_text("Emojis")
        emoji_btn.connect("clicked", self._toggle_emoji_picker)
        send_row.pack_start(emoji_btn, False, False, 0)
        self._emoji_btn = emoji_btn
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
        self._poll_pending_asks()
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

    def _manual_refresh(self) -> None:
        try:
            control_request({"cmd": "rescan"}, timeout=1.5)
        except Exception:
            pass
        self._rebuild_contacts = True
        self.refresh_peers()
        self.refresh_status()

    def refresh_peers(self, silent: bool = False) -> None:
        selected_id = str((self._selected_peer_data or {}).get("node_id") or "")
        selected_host = str((self._selected_mismatch or {}).get("host") or "")
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
        self._set_peer_cards(
            self._peers,
            selected_id=selected_id,
            selected_host=selected_host,
        )

    def _contact_fingerprint(self) -> str:
        bits = [
            f"p:{p.get('node_id')}:{p.get('display_name')}:{p.get('host')}"
            for p in self._peers
            if isinstance(p, dict)
        ]
        bits.extend(
            f"m:{h.get('host')}:{h.get('display_name')}"
            for h in self._mismatches
            if isinstance(h, dict)
        )
        bits.append(f"q:{(self.search.get_text() or '').strip().casefold()}")
        return "|".join(bits)

    def _set_peer_cards(
        self,
        peers: list[dict[str, Any]],
        *,
        selected_id: str = "",
        selected_host: str = "",
    ) -> None:
        fingerprint = self._contact_fingerprint()
        if (
            not self._rebuild_contacts
            and getattr(self, "_contacts_fp", None) == fingerprint
            and self.chat_list.get_children()
        ):
            # Soft-update selected peer payload if it is still online.
            if selected_id:
                for peer in peers:
                    if str(peer.get("node_id") or "") == selected_id:
                        self._selected_peer_data = peer
                        break
            return
        self._rebuild_contacts = False
        self._contacts_fp = fingerprint
        previous = self._selected_peer_data
        previous_mismatch = self._selected_mismatch
        for child in list(self.chat_list.get_children()):
            self.chat_list.remove(child)

        has_rows = bool(peers or self._mismatches)
        self.peer_empty.set_visible(not has_rows)
        if peers:
            empty_text = ""
        elif self._mismatches:
            empty_text = "Equipos cerca sin emparejar. Ábrelos y pulsa Conectar."
        else:
            empty_text = "Sin chats aún. Empareja (+) o espera a que aparezcan."
        self.peer_empty.set_text(empty_text)

        query = (self.search.get_text() or "").strip().casefold()
        selected_row: Gtk.ListBoxRow | None = None

        for peer in peers:
            name = str(peer.get("display_name") or "PC")
            if query and query not in name.casefold() and query not in str(peer.get("host") or "").casefold():
                continue
            node_id = str(peer.get("node_id") or "")
            preview = self._previews.get(node_id) or str(peer.get("host") or "en línea")
            row = self._make_contact_row(
                name=name,
                preview=preview,
                meta="en línea",
                peer=peer,
                mismatch=None,
            )
            self.chat_list.add(row)
            if selected_id and node_id == selected_id:
                selected_row = row
                self._selected_peer_data = peer
                self._selected_mismatch = None

        for hint in self._mismatches:
            name = str(hint.get("display_name") or hint.get("host") or "PC")
            host = str(hint.get("host") or "")
            if query and query not in name.casefold() and query not in host.casefold():
                continue
            row = self._make_contact_row(
                name=name,
                preview="Sin emparejar · toca Conectar",
                meta="disponible",
                peer=None,
                mismatch=hint,
                badge="!",
            )
            self.chat_list.add(row)
            if selected_host and host == selected_host:
                selected_row = row
                self._selected_mismatch = hint
                self._selected_peer_data = None

        if selected_row is None and previous is not None:
            self._selected_peer_data = previous
        if selected_row is None and previous_mismatch is not None and self._selected_peer_data is None:
            self._selected_mismatch = previous_mismatch

        self.chat_list.show_all()
        if selected_row is not None:
            self.chat_list.select_row(selected_row)

    def _make_contact_row(
        self,
        *,
        name: str,
        preview: str,
        meta: str,
        peer: dict[str, Any] | None,
        mismatch: dict[str, Any] | None,
        badge: str = "",
    ) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.peer_data = peer
        row.mismatch_data = mismatch
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        box.get_style_context().add_class("wa-contact")
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name_l = Gtk.Label(label=name, xalign=0)
        name_l.set_ellipsize(Pango.EllipsizeMode.END)
        name_l.set_hexpand(True)
        name_l.get_style_context().add_class("wa-contact-name")
        top.pack_start(name_l, True, True, 0)
        meta_l = Gtk.Label(label=meta, xalign=1)
        meta_l.get_style_context().add_class("wa-contact-meta")
        top.pack_start(meta_l, False, False, 0)
        if badge:
            badge_l = Gtk.Label(label=badge)
            badge_l.get_style_context().add_class("wa-badge")
            top.pack_start(badge_l, False, False, 0)
        box.pack_start(top, False, False, 0)
        prev = preview if len(preview) <= 56 else preview[:53] + "…"
        preview_l = Gtk.Label(label=prev, xalign=0)
        preview_l.set_ellipsize(Pango.EllipsizeMode.END)
        preview_l.get_style_context().add_class("wa-contact-preview")
        box.pack_start(preview_l, False, False, 0)
        row.add(box)
        return row

    def _filter_contacts(self, *_args: object) -> None:
        self._rebuild_contacts = True
        self._set_peer_cards(
            self._peers,
            selected_id=str((self._selected_peer_data or {}).get("node_id") or ""),
            selected_host=str((self._selected_mismatch or {}).get("host") or ""),
        )

    def _on_contact_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        peer = getattr(row, "peer_data", None)
        mismatch = getattr(row, "mismatch_data", None)
        if isinstance(peer, dict):
            self._selected_peer_data = peer
            self._selected_mismatch = None
            self.connect_peer_btn.hide()
            name = str(peer.get("display_name") or "Computador")
            host = str(peer.get("host") or "")
            self.chat_peer_label.set_text(name)
            self.chat_peer_sub.set_text(f"en línea · {host}" if host else "en línea en la red local")
            self.refresh_inbox(initial=True)
            return
        if isinstance(mismatch, dict):
            self._selected_mismatch = mismatch
            self._selected_peer_data = None
            name = str(mismatch.get("display_name") or mismatch.get("host") or "PC")
            host = str(mismatch.get("host") or "")
            self.chat_peer_label.set_text(name)
            self.chat_peer_sub.set_text(
                f"Sin emparejar · {host}" if host else "Sin emparejar en esta Wi‑Fi"
            )
            self.connect_peer_btn.show()
            for child in list(self.message_box.get_children()):
                self.message_box.remove(child)
            self._seen_ids.clear()
            self._messages = []
            self._append_notice(
                f"{name} está en la red pero aún no comparte tu grupo. "
                "Pulsa Conectar; en el otro PC saldrá Aprobar."
            )

    def _connect_selected_mismatch(self) -> None:
        if self._selected_mismatch:
            self._ask_connect(self._selected_mismatch)

    def open_settings_menu(self) -> None:
        menu = Gtk.Menu()
        items = (
            ("Emparejar / código de grupo", self.open_pair_dialog),
            ("Ajustes de grupo local", self.open_group_dialog),
            ("Cuenta AidyC / AidyChat nube", self.open_cloud_dialog),
            ("Actualizar equipos", self._manual_refresh),
        )
        for label, handler in items:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i, h=handler: h())
            menu.append(item)
        menu.show_all()
        menu.popup_at_widget(self.settings_btn, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def _toggle_emoji_picker(self, button: Gtk.Button) -> None:
        if self._emoji_popover is None:
            pop = Gtk.Popover.new(button)
            pop.set_position(Gtk.PositionType.TOP)
            grid = Gtk.FlowBox()
            grid.set_max_children_per_line(8)
            grid.set_selection_mode(Gtk.SelectionMode.NONE)
            grid.get_style_context().add_class("emoji-grid")
            grid.set_border_width(8)
            for emoji in EMOJI_SET:
                btn = Gtk.Button(label=emoji)
                btn.connect("clicked", lambda _b, e=emoji: self._insert_emoji(e))
                grid.add(btn)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_min_content_height(180)
            scroll.set_max_content_height(220)
            scroll.set_min_content_width(280)
            scroll.add(grid)
            pop.add(scroll)
            pop.show_all()
            self._emoji_popover = pop
        assert self._emoji_popover is not None
        if self._emoji_popover.get_visible():
            self._emoji_popover.popdown()
        else:
            self._emoji_popover.set_relative_to(button)
            self._emoji_popover.popup()

    def _insert_emoji(self, emoji: str) -> None:
        text = self.msg_entry.get_text() or ""
        pos = self.msg_entry.get_position()
        new = text[:pos] + emoji + text[pos:]
        self.msg_entry.set_text(new)
        self.msg_entry.set_position(pos + len(emoji))
        self.msg_entry.grab_focus_without_selecting()
        if self._emoji_popover is not None:
            self._emoji_popover.popdown()

    def refresh_inbox(self, initial: bool = False) -> None:
        try:
            resp = control_request({"cmd": "inbox", "limit": 300}, timeout=1.5)
        except Exception:
            return
        messages = resp.get("messages") or []
        if not isinstance(messages, list):
            return
        cfg = load_config()
        my_id = cfg.node_id if cfg else ""
        previews: dict[str, str] = {}
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            from_id = str(msg.get("from_id") or "")
            to_id = str(msg.get("to_id") or "")
            peer_id = to_id if from_id == my_id else from_id
            if not peer_id or peer_id in ("*", my_id):
                continue
            text = str(msg.get("text") or "").strip()
            if not text:
                filename = str(msg.get("filename") or "")
                text = f"📎 {filename}" if filename else "📎 Archivo"
            previews[peer_id] = text
        if previews != self._previews:
            self._previews = previews
            self._rebuild_contacts = True

        selected_id = str((self._selected_peer_data or {}).get("node_id") or "")
        if self._selected_mismatch is not None and not selected_id:
            return
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
            "host": peer.get("host") or "",
            "port": peer.get("message_port") or "",
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

    def _ask_connect(self, hint: dict[str, Any]) -> None:
        """One-tap: ask the other PC to Approve joining its group."""
        host = str(hint.get("host") or "").strip()
        name = str(hint.get("display_name") or host or "PC").strip() or "PC"
        if not host:
            self._append_line("⚠ No se conoce la IP de ese equipo.")
            return
        if self._connecting:
            self._append_line("Ya hay una solicitud de conexión en curso…")
            return
        self._connecting = True
        self.pair_btn.set_sensitive(False)
        self._append_line(f"Esperando que {name} apruebe la conexión…")

        def work() -> None:
            try:
                resp = control_request(
                    {"cmd": "pair_ask", "host": host},
                    timeout=100.0,
                )
                error = None
            except Exception as exc:
                resp, error = None, exc
            GLib.idle_add(finish, resp, error)

        def finish(resp: dict[str, Any] | None, error: Exception | None) -> bool:
            self._connecting = False
            self.pair_btn.set_sensitive(True)
            if error:
                self._append_line(f"⚠ Conexión falló: {error}")
                return GLib.SOURCE_REMOVE
            if not resp or not resp.get("ok"):
                detail = ((resp or {}).get("error") if resp else None) or "No se pudo conectar"
                self._append_line(f"⚠ {detail}")
                return GLib.SOURCE_REMOVE
            host_name = str(resp.get("host_name") or name)
            self._append_line(f"✓ Conectado con {host_name}. Ya pueden chatear.")
            self.refresh_status()
            self.refresh_peers()
            return GLib.SOURCE_REMOVE

        import threading

        threading.Thread(target=work, daemon=True, name="aidychat-pair-ask").start()

    def _poll_pending_asks(self) -> None:
        if self._pending_ask_dialog is not None:
            return
        try:
            resp = control_request({"cmd": "pair_pending"}, timeout=1.0)
        except Exception:
            return
        if not resp.get("ok"):
            return
        asks = resp.get("asks") or []
        if not isinstance(asks, list):
            return
        active_ids = {
            str(item.get("ask_id") or "")
            for item in asks
            if isinstance(item, dict) and item.get("ask_id")
        }
        self._seen_ask_ids &= active_ids
        for item in asks:
            if not isinstance(item, dict):
                continue
            ask_id = str(item.get("ask_id") or "")
            if not ask_id or ask_id in self._seen_ask_ids:
                continue
            self._seen_ask_ids.add(ask_id)
            self._show_approve_dialog(item)
            break

    def _show_approve_dialog(self, ask: dict[str, Any]) -> None:
        ask_id = str(ask.get("ask_id") or "")
        name = str(ask.get("from_name") or ask.get("from_host") or "PC")
        host = str(ask.get("from_host") or "")
        dialog = Gtk.Dialog(title="Solicitud de conexión", transient_for=self, flags=0)
        dialog.add_buttons(
            "Rechazar", Gtk.ResponseType.REJECT,
            "Aprobar", Gtk.ResponseType.ACCEPT,
        )
        dialog.set_default_size(420, 160)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(16)
        where = f" ({host})" if host else ""
        box.pack_start(
            Gtk.Label(
                label=f"{name}{where} quiere conectarse a tu grupo AidyChat.",
                xalign=0,
                wrap=True,
            ),
            False,
            False,
            0,
        )
        box.pack_start(
            Gtk.Label(
                label="Si apruebas, compartirán el mismo chat local.",
                xalign=0,
                wrap=True,
            ),
            False,
            False,
            0,
        )
        self._pending_ask_dialog = dialog
        decided = {"done": False}

        def decide(approve: bool) -> None:
            if decided["done"]:
                return
            decided["done"] = True
            try:
                control_request(
                    {"cmd": "pair_decide", "ask_id": ask_id, "approve": approve},
                    timeout=3.0,
                )
            except Exception as exc:
                self._append_line(f"⚠ No se pudo responder: {exc}")
            if approve:
                self._append_line(f"✓ Aprobaste a {name}.")
            else:
                self._append_line(f"Rechazaste a {name}.")
            self._pending_ask_dialog = None
            self.refresh_status()
            self.refresh_peers()

        def on_response(_dlg: Gtk.Dialog, response: int) -> None:
            approve = response == Gtk.ResponseType.ACCEPT
            decide(approve)
            dialog.destroy()

        def on_delete(*_args: Any) -> bool:
            decide(False)
            return False

        dialog.connect("response", on_response)
        dialog.connect("delete-event", on_delete)
        dialog.show_all()

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
                    "Código de grupo (no caduca). Lo habitual: si ves el otro PC, "
                    "pulsa Conectar y en el otro Aprueba. El código sirve si no aparecen."
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
        dialog = Gtk.Dialog(title="Cuenta AidyChat", transient_for=self, flags=0)
        dialog.add_buttons(
            "Google", Gtk.ResponseType.APPLY,
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Entrar", Gtk.ResponseType.OK,
        )
        dialog.set_default_size(420, 260)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.pack_start(
            Gtk.Label(
                label="Entra con el mismo usuario y contraseña de AidyC.",
                xalign=0,
                wrap=True,
            ),
            False,
            False,
            0,
        )
        user_e = Gtk.Entry()
        user_e.set_placeholder_text("Usuario AidyC")
        user_e.set_activates_default(True)
        pass_e = Gtk.Entry()
        pass_e.set_placeholder_text("Contraseña")
        pass_e.set_visibility(False)
        pass_e.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        pass_e.set_activates_default(True)
        box.pack_start(Gtk.Label(label="Usuario", xalign=0), False, False, 0)
        box.pack_start(user_e, False, False, 0)
        box.pack_start(Gtk.Label(label="Contraseña", xalign=0), False, False, 0)
        box.pack_start(pass_e, False, False, 0)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        response = dialog.run()
        username = (user_e.get_text() or "").strip()
        password = pass_e.get_text() or ""
        dialog.destroy()
        if response == Gtk.ResponseType.APPLY:
            self._start_google_login(cfg)
            return
        if response != Gtk.ResponseType.OK:
            return
        if not username or not password:
            self._append_line("⚠ Escribe usuario y contraseña de AidyC.")
            return
        self._append_line("Validando cuenta AidyC…")
        self.google_btn.set_sensitive(False)

        def work() -> None:
            try:
                from .cloud import AidyChatBridge

                if not cfg.cloud.base_url:
                    cfg.cloud.base_url = "https://www.aidycsolutions.com"
                bridge = AidyChatBridge(cfg)
                data = bridge.login_aidyc(username, password)
                save_config(cfg)
                user = data.get("user") if isinstance(data.get("user"), dict) else {}
                result = str(user.get("username") or username)
                error = None
            except Exception as exc:
                result, error = None, exc
            GLib.idle_add(finish, result, error)

        def finish(name: str | None, error: Exception | None) -> bool:
            self.google_btn.set_sensitive(True)
            if error:
                self._append_line(f"⚠ No se pudo iniciar sesión: {error}")
                return GLib.SOURCE_REMOVE
            self._append_line(f"✓ Sesión iniciada como {name or 'AidyChat'}.")
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

        import threading

        threading.Thread(target=work, daemon=True, name="aidychat-aidyc-login").start()

    def _start_google_login(self, cfg: Any) -> None:
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
            self._append_notice("⚠ Selecciona un chat a la izquierda primero.")
            return
        payload: dict[str, Any] = {
            "cmd": "send",
            "to": peer.get("node_id") or peer.get("display_name") or "",
            "text": text,
            "host": peer.get("host") or "",
            "port": peer.get("message_port") or "",
        }

        try:
            resp = control_request(payload, timeout=5.0)
        except Exception as exc:
            self._append_notice(f"⚠ Error: {exc}")
            return

        if resp.get("ok"):
            self.msg_entry.set_text("")
            self.refresh_inbox()
            self._rebuild_contacts = True
            self.refresh_peers(silent=True)
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

    apply_aidychat_branding()
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
