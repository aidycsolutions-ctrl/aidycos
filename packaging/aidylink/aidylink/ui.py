"""Ventana GTK de AidyLink — habla con el daemon por el socket de control."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from .cloud import apply_cloud_settings, test_cloud_connection
from .config import init_config, load_config, save_config
from .daemon import control_request
from .netutil import is_qemu_slirp_ip
from .paths import control_socket_path


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

    dialog = Gtk.Dialog(title="Configurar AidyLink", flags=0)
    dialog.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        "Crear y abrir", Gtk.ResponseType.OK,
    )
    dialog.set_default_size(420, 200)
    box = dialog.get_content_area()
    box.set_spacing(8)
    box.set_border_width(12)
    box.pack_start(
        Gtk.Label(
            label="Primera vez: elige un nombre y el equipo (mismo secreto en todas las PCs).",
            xalign=0,
        ),
        False,
        False,
        0,
    )
    name_e = Gtk.Entry()
    name_e.set_placeholder_text("Nombre (ej. Caja-1 o Host)")
    team_e = Gtk.Entry()
    team_e.set_placeholder_text("Equipo compartido")
    secret_e = Gtk.Entry()
    secret_e.set_text("")
    secret_e.set_visibility(False)
    for label, entry in (
        ("Nombre visible", name_e),
        ("Equipo / team", team_e),
        ("Secreto compartido", secret_e),
    ):
        box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
        box.pack_start(entry, False, False, 0)
    dialog.show_all()
    response = dialog.run()
    if response != Gtk.ResponseType.OK:
        dialog.destroy()
        return False
    name = (name_e.get_text() or "").strip() or "AidyC-OS"
    team = (team_e.get_text() or "").strip() or "default"
    secret = (secret_e.get_text() or "").strip() or None
    dialog.destroy()
    init_config(display_name=name, team_id=team, team_secret=secret)
    return True


class AidylinkWindow(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="AidyLink")
        self.set_default_size(520, 560)
        self.set_border_width(10)

        self._peers: list[dict[str, Any]] = []
        self._seen_ids: set[str] = set()
        self._status_ok = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(root)

        self.status = Gtk.Label(xalign=0)
        self.status.set_line_wrap(True)
        root.pack_start(self.status, False, False, 0)

        dest_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        root.pack_start(dest_row, False, False, 0)

        dest_row.pack_start(Gtk.Label(label="Para:"), False, False, 0)
        self.peer_combo = Gtk.ComboBoxText()
        self.peer_combo.set_hexpand(True)
        dest_row.pack_start(self.peer_combo, True, True, 0)

        self.refresh_btn = Gtk.Button(label="Actualizar")
        self.refresh_btn.connect("clicked", lambda *_: self.refresh_peers())
        dest_row.pack_start(self.refresh_btn, False, False, 0)
        cloud_btn = Gtk.Button(label="Servidor…")
        cloud_btn.connect("clicked", lambda *_: self.open_cloud_dialog())
        dest_row.pack_start(cloud_btn, False, False, 0)

        host_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        root.pack_start(host_row, False, False, 0)
        host_row.pack_start(Gtk.Label(label="IP directa:"), False, False, 0)
        self.host_entry = Gtk.Entry()
        self.host_entry.set_placeholder_text("ej. 10.0.2.2 (VM→host) o vacío si hay peer")
        host_row.pack_start(self.host_entry, True, True, 0)
        host_row.pack_start(Gtk.Label(label="puerto"), False, False, 0)
        self.port_entry = Gtk.Entry()
        self.port_entry.set_width_chars(6)
        self.port_entry.set_text("47833")
        host_row.pack_start(self.port_entry, False, False, 0)

        tip = Gtk.Label(
            label=(
                "QEMU: elige el peer «Qemu» (el host reescribe solo a 127.0.0.1:47834). "
                "Desde la VM: IP 10.0.2.2 puerto 47833."
            ),
            xalign=0,
        )
        tip.set_line_wrap(True)
        tip.get_style_context().add_class("dim-label")
        root.pack_start(tip, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        root.pack_start(scroll, True, True, 0)

        self.chat_view = Gtk.TextView()
        self.chat_view.set_editable(False)
        self.chat_view.set_cursor_visible(False)
        self.chat_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.chat_buf = self.chat_view.get_buffer()
        mono = Pango.FontDescription("Monospace 10")
        self.chat_view.override_font(mono)
        scroll.add(self.chat_view)

        send_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        root.pack_start(send_row, False, False, 0)
        self.msg_entry = Gtk.Entry()
        self.msg_entry.set_placeholder_text("Escribe un mensaje…")
        self.msg_entry.connect("activate", lambda *_: self.send_message())
        send_row.pack_start(self.msg_entry, True, True, 0)
        send_btn = Gtk.Button(label="Enviar")
        send_btn.connect("clicked", lambda *_: self.send_message())
        send_row.pack_start(send_btn, False, False, 0)

        self.connect("destroy", Gtk.main_quit)
        self.refresh_status()
        self._apply_qemu_defaults()
        self.refresh_peers()
        self.refresh_inbox(initial=True)
        GLib.timeout_add_seconds(2, self._tick)

    def _apply_qemu_defaults(self) -> None:
        """Si estamos dentro de QEMU NAT, prellenar destino al host."""
        try:
            resp = control_request({"cmd": "status"}, timeout=1.0)
        except Exception:
            return
        lan = str(resp.get("lan_ip") or "")
        if is_qemu_slirp_ip(lan) and not (self.host_entry.get_text() or "").strip():
            self.host_entry.set_text("10.0.2.2")
            self.port_entry.set_text("47833")

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
        except Exception as exc:
            self._set_status(f"Daemon apagado — {exc}", ok=False)
            return
        if not resp.get("ok"):
            self._set_status(resp.get("error") or "daemon error", ok=False)
            return
        self._set_status(
            f"{resp.get('display_name')} · equipo {resp.get('team_id')} · "
            f"LAN {resp.get('lan_ip')} · peers {resp.get('peers')}"
        )

    def refresh_peers(self, silent: bool = False) -> None:
        active = self.peer_combo.get_active_text()
        try:
            resp = control_request({"cmd": "peers"}, timeout=1.5)
        except Exception:
            if not silent:
                self.peer_combo.remove_all()
                self.peer_combo.append_text("(sin daemon)")
                self.peer_combo.set_active(0)
            return
        peers = resp.get("peers") or []
        self._peers = peers if isinstance(peers, list) else []
        self.peer_combo.remove_all()
        self.peer_combo.append_text("— elegir peer / o usa IP directa —")
        labels: list[str] = []
        for peer in self._peers:
            label = f"{peer.get('display_name')} ({peer.get('host')})"
            labels.append(label)
            self.peer_combo.append_text(label)
        if active and active in labels:
            self.peer_combo.set_active(labels.index(active) + 1)
        else:
            self.peer_combo.set_active(0)

    def refresh_inbox(self, initial: bool = False) -> None:
        try:
            resp = control_request({"cmd": "inbox", "limit": 200}, timeout=1.5)
        except Exception:
            return
        messages = resp.get("messages") or []
        if not isinstance(messages, list):
            return
        cfg = load_config()
        my_id = cfg.node_id if cfg else ""
        new_lines: list[str] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            mid = str(msg.get("msg_id") or "")
            if mid and mid in self._seen_ids:
                continue
            if mid:
                self._seen_ids.add(mid)
            if initial and mid:
                # En la carga inicial solo marcamos vistos y pintamos al final
                continue
            new_lines.append(self._format_msg(msg, my_id))
        if initial:
            self.chat_buf.set_text("")
            for msg in messages:
                if isinstance(msg, dict):
                    mid = str(msg.get("msg_id") or "")
                    if mid:
                        self._seen_ids.add(mid)
                    self._append_line(self._format_msg(msg, my_id))
            return
        for line in new_lines:
            self._append_line(line)

    def _format_msg(self, msg: dict[str, Any], my_id: str) -> str:
        ts = msg.get("ts")
        try:
            stamp = datetime.fromtimestamp(float(ts)).strftime("%H:%M:%S")
        except (TypeError, ValueError, OSError):
            stamp = "--:--:--"
        from_id = str(msg.get("from_id") or "")
        name = str(msg.get("from_name") or from_id[:8] or "?")
        text = str(msg.get("text") or "")
        via = str(msg.get("via") or "")
        mine = from_id == my_id
        who = "Tú" if mine else name
        suffix = f" [{via}]" if via else ""
        return f"[{stamp}] {who}{suffix}: {text}"

    def _append_line(self, line: str) -> None:
        end = self.chat_buf.get_end_iter()
        self.chat_buf.insert(end, line + "\n")
        # auto-scroll
        mark = self.chat_buf.create_mark(None, self.chat_buf.get_end_iter(), False)
        self.chat_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

    def _selected_peer(self) -> dict[str, Any] | None:
        idx = self.peer_combo.get_active()
        if idx <= 0 or idx - 1 >= len(self._peers):
            return None
        return self._peers[idx - 1]

    def open_cloud_dialog(self) -> None:
        cfg = load_config()
        if cfg is None:
            self._append_line("⚠ Sin configuración local.")
            return
        dialog = Gtk.Dialog(title="Servidor AidyChat", transient_for=self, flags=0)
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "Probar y guardar", Gtk.ResponseType.OK,
        )
        dialog.set_default_size(480, 220)
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.pack_start(
            Gtk.Label(
                label=(
                    "URL del servidor + token Bearer de AidyChat.\n"
                    "En el navegador: entra a /aidychat, inicia sesión, "
                    "DevTools → Application → Cookies → aidychat_auth "
                    "(o usa el campo token del JSON de login tras desplegar)."
                ),
                xalign=0,
            ),
            False,
            False,
            0,
        )
        url_e = Gtk.Entry()
        url_e.set_text(cfg.cloud.base_url or "https://www.aidycsolutions.com")
        tok_e = Gtk.Entry()
        tok_e.set_text(cfg.cloud.bearer_token or "")
        tok_e.set_visibility(False)
        map_name = Gtk.Entry()
        map_name.set_placeholder_text("Nombre peer local (ej. Qemu)")
        map_id = Gtk.Entry()
        map_id.set_placeholder_text("user_id AidyChat del peer (número)")
        for label, entry in (
            ("Base URL", url_e),
            ("Token Bearer", tok_e),
            ("Mapear peer → user_id (opcional)", map_name),
            ("user_id del peer", map_id),
        ):
            box.pack_start(Gtk.Label(label=label, xalign=0), False, False, 0)
            box.pack_start(entry, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        if response != Gtk.ResponseType.OK:
            dialog.destroy()
            return
        apply_cloud_settings(
            cfg,
            base_url=url_e.get_text().strip(),
            token=tok_e.get_text().strip(),
        )
        peer_name = (map_name.get_text() or "").strip()
        peer_uid = (map_id.get_text() or "").strip()
        if peer_name and peer_uid.isdigit():
            cfg.cloud.peer_user_ids[peer_name] = int(peer_uid)
        dialog.destroy()
        try:
            result = test_cloud_connection(cfg)
        except Exception as exc:
            self._append_line(f"⚠ Servidor: {exc}")
            return
        if not result.get("ok"):
            self._append_line(f"⚠ Servidor: {result.get('error')}")
            return
        save_config(cfg)
        self._append_line(
            f"✓ Cloud OK como {result.get('username')} "
            f"(id {result.get('user_id')}). Reinicia el daemon o cierra/abre AidyLink."
        )
        # Intentar reiniciar el servicio user sin molestar
        try:
            subprocess.run(
                ["systemctl", "--user", "restart", "aidylink.service"],
                check=False,
                timeout=5,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            ensure_daemon_running()
            self.refresh_status()
        except Exception:
            pass

    def send_message(self) -> None:
        text = (self.msg_entry.get_text() or "").strip()
        if not text:
            return
        if not self._status_ok:
            self._append_line("⚠ Arranca el daemon primero (aidylink daemon o systemd).")
            return

        host = (self.host_entry.get_text() or "").strip()
        port_txt = (self.port_entry.get_text() or "").strip()
        peer = self._selected_peer()
        payload: dict[str, Any] = {"cmd": "send", "text": text}

        if host:
            payload["host"] = host
            try:
                payload["port"] = int(port_txt or "47833")
            except ValueError:
                self._append_line("⚠ Puerto inválido")
                return
        elif peer:
            payload["to"] = peer.get("display_name") or peer.get("node_id")
            # Prefer direct LAN to that peer host (más fiable que solo el nombre)
            payload["host"] = peer.get("host")
            payload["port"] = int(peer.get("message_port") or 47833)
            payload["to"] = peer.get("node_id") or "*"
        else:
            self._append_line("⚠ Elige un peer o escribe una IP directa.")
            return

        try:
            resp = control_request(payload, timeout=5.0)
        except Exception as exc:
            self._append_line(f"⚠ Error: {exc}")
            return

        if resp.get("ok"):
            self.msg_entry.set_text("")
            # El daemon ya persistió; refrescar inbox
            self.refresh_inbox()
        else:
            self._append_line(
                f"⚠ No enviado: {resp.get('detail') or resp.get('error') or 'error'}"
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
    return 0
