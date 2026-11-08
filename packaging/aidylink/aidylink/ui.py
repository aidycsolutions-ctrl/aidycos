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

from .config import init_config, load_config
from .daemon import control_request
from .native_auth import start_google_login
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

    dialog = Gtk.Dialog(title="Bienvenido a AidyLink", flags=0)
    dialog.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        "Continuar", Gtk.ResponseType.OK,
    )
    dialog.set_default_size(460, 340)
    box = dialog.get_content_area()
    box.set_spacing(8)
    box.set_border_width(12)
    box.pack_start(
        Gtk.Label(
            label="¿Cómo llamamos a este computador? Después podrás iniciar sesión o elegir otro equipo de la red.",
            xalign=0,
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
    secret_e.set_placeholder_text("Código compartido entre computadores (opcional)")
    secret_e.set_visibility(False)
    box.pack_start(Gtk.Label(label="Nombre de este computador", xalign=0), False, False, 0)
    box.pack_start(name_e, False, False, 0)
    advanced = Gtk.Expander(label="Configuración avanzada de red local")
    advanced_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    advanced_box.pack_start(
        Gtk.Label(
            label="Para que dos computadores se encuentren en la red local, ambos usan el mismo grupo y código.",
            xalign=0,
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
        super().__init__(title="AidyLink · Mensajería")
        self.set_default_size(760, 680)
        self.set_border_width(10)

        self._peers: list[dict[str, Any]] = []
        self._selected_peer_data: dict[str, Any] | None = None
        self._seen_ids: set[str] = set()
        self._status_ok = False
        self._standalone = standalone

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(root)

        self.status = Gtk.Label(label="Listo para conectar", xalign=0)
        self.status.set_line_wrap(True)
        root.pack_start(self.status, False, False, 0)

        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root.pack_start(title_row, False, False, 0)
        title_row.pack_start(Gtk.Label(label="Computadores disponibles", xalign=0), True, True, 0)
        self.refresh_btn = Gtk.Button(label="Actualizar")
        self.refresh_btn.connect("clicked", lambda *_: self.refresh_peers())
        title_row.pack_start(self.refresh_btn, False, False, 0)
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
        self.peer_empty = Gtk.Label(label="Buscando computadores de AidyLink en esta red…", xalign=0)
        self.peer_empty.get_style_context().add_class("dim-label")
        root.pack_start(self.peer_empty, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        root.pack_start(scroll, True, True, 0)

        self.chat_view = Gtk.TextView()
        self.chat_view.set_editable(False)
        self.chat_view.set_cursor_visible(False)
        self.chat_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.chat_view.set_left_margin(12)
        self.chat_view.set_right_margin(12)
        self.chat_buf = self.chat_view.get_buffer()
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
        self._set_status("Conectado · buscando equipos cercanos")

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
        self._peers = peers if isinstance(peers, list) else []
        self._set_peer_cards(self._peers, selected_id=selected_id)

    def _set_peer_cards(self, peers: list[dict[str, Any]], *, selected_id: str = "") -> None:
        for child in self.peer_cards.get_children():
            self.peer_cards.remove(child)
        self._selected_peer_data = None
        self.peer_empty.set_visible(not peers)
        self.peer_empty.set_text(
            "Aún no hay computadores disponibles. Revisa que ambos estén en la misma red, tengan AidyLink abierto y usen el mismo código local."
            if not peers else ""
        )
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
            self.peer_empty.set_text(
                f"Listo para escribirle a {self._selected_peer_data.get('display_name')}."
            )
            self.peer_empty.show()
            self.refresh_inbox(initial=True)

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
        selected_id = str((self._selected_peer_data or {}).get("node_id") or "")
        new_lines: list[str] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            if selected_id and selected_id not in (
                str(msg.get("from_id") or ""),
                str(msg.get("to_id") or ""),
            ):
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
                    if selected_id and selected_id not in (
                        str(msg.get("from_id") or ""),
                        str(msg.get("to_id") or ""),
                    ):
                        continue
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
            stamp = datetime.fromtimestamp(float(ts)).strftime("%H:%M")
        except (TypeError, ValueError, OSError):
            stamp = "--:--:--"
        from_id = str(msg.get("from_id") or "")
        name = str(msg.get("from_name") or from_id[:8] or "?")
        text = str(msg.get("text") or "")
        mine = from_id == my_id
        who = "Tú" if mine else name
        return f"{stamp} · {who}: {text}"

    def _append_line(self, line: str) -> None:
        end = self.chat_buf.get_end_iter()
        self.chat_buf.insert(end, line + "\n")
        # auto-scroll
        mark = self.chat_buf.create_mark(None, self.chat_buf.get_end_iter(), False)
        self.chat_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

    def _selected_peer(self) -> dict[str, Any] | None:
        return self._selected_peer_data

    def open_cloud_dialog(self) -> None:
        cfg = load_config()
        if cfg is None:
            self._append_line("⚠ No se encontró la configuración de AidyLink.")
            return
        self.google_btn.set_sensitive(False)
        self._append_line("Se abrió AidyChat en tu navegador. Inicia sesión con Google para continuar.")

        def done(username: str | None, error: Exception | None) -> None:
            GLib.idle_add(finish, username, error)

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

        start_google_login(cfg, done)

    def send_message(self) -> None:
        text = (self.msg_entry.get_text() or "").strip()
        if not text:
            return
        if not self._status_ok:
            self._append_line("⚠ Arranca el daemon primero (aidylink daemon o systemd).")
            return

        peer = self._selected_peer()
        if not peer:
            self._append_line("⚠ Selecciona un computador disponible primero.")
            return
        payload: dict[str, Any] = {
            "cmd": "send",
            "to": peer.get("node_id") or peer.get("display_name") or "",
            "text": text,
        }

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
            self._append_line("⚠ No se pudo enviar. Revisa que el otro computador siga conectado.")


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
