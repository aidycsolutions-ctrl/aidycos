"""GTK window for AidyShare: login AidyC + respaldo a AidyCShare del negocio."""

from __future__ import annotations

import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from .api import ActiveSessionConflict, ApiError, ShareClient
from .branding import apply_aidyshare_branding, load_logo_pixbuf
from .config import (
    ShareConfig,
    ShareSession,
    clear_session,
    load_config,
    load_session,
    save_config,
    save_session,
)

TEAL = "#0B3D4A"
ACCENT = "#2F80ED"
BG = "#F5F7FA"
SIDE = "#E8EEF4"


def _install_style() -> None:
    css = Gtk.CssProvider()
    css.load_from_data(
        f"""
        window.aidyshare {{ background: {BG}; }}
        .share-header {{ background: {TEAL}; color: white; padding: 12px 14px; }}
        .share-header label {{ color: white; }}
        .share-muted {{ color: #5b6b73; font-size: 11px; }}
        .share-ok {{ color: {TEAL}; font-weight: bold; }}
        .share-bad {{ color: #a33; font-weight: bold; }}
        .share-primary {{ background: {TEAL}; color: white; padding: 8px 12px; border-radius: 4px; }}
        .share-accent {{ background: {ACCENT}; color: white; padding: 8px 12px; border-radius: 4px; }}
        """.encode("utf-8")
    )
    screen = Gtk.Window().get_screen()
    Gtk.StyleContext.add_provider_for_screen(screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


class ShareWindow(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="AidyShare")
        self.set_default_size(860, 580)
        self.set_border_width(0)
        self.get_style_context().add_class("aidyshare")
        apply_aidyshare_branding(self)

        self.cfg: ShareConfig = load_config()
        self.session: ShareSession = load_session()
        self.client = ShareClient(self.cfg, self.session)
        self.remote_path = self.cfg.remote_folder.strip("/")
        self._busy = False
        self._selected_remote: str | None = None

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.add(self.stack)

        self.stack.add_named(self._build_login(), "login")
        self.stack.add_named(self._build_main(), "main")
        self.connect("destroy", Gtk.main_quit)

        if self.session.ok:
            self.stack.set_visible_child_name("main")
            self._refresh_all()
        else:
            self.stack.set_visible_child_name("login")

    def _build_login(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(40)
        box.set_margin_bottom(40)
        box.set_margin_start(80)
        box.set_margin_end(80)

        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        brand.set_halign(Gtk.Align.CENTER)
        pix = load_logo_pixbuf(48)
        if pix is not None:
            brand.pack_start(Gtk.Image.new_from_pixbuf(pix), False, False, 0)
        title = Gtk.Label()
        title.set_markup("<span size='xx-large'><b>AidyShare</b></span>")
        brand.pack_start(title, False, False, 0)
        box.pack_start(brand, False, False, 0)

        hint = Gtk.Label(
            label="Respaldo sencillo en AidyCShare del negocio.\nUsa tu usuario y contraseña de AidyC."
        )
        hint.set_justify(Gtk.Justification.CENTER)
        hint.get_style_context().add_class("share-muted")
        box.pack_start(hint, False, False, 0)

        self.login_user = Gtk.Entry()
        self.login_user.set_placeholder_text("Usuario AidyC")
        self.login_user.set_text(self.cfg.username)
        box.pack_start(self.login_user, False, False, 0)

        self.login_pass = Gtk.Entry()
        self.login_pass.set_placeholder_text("Contraseña")
        self.login_pass.set_visibility(False)
        self.login_pass.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.login_pass.connect("activate", lambda *_: self._on_login())
        box.pack_start(self.login_pass, False, False, 0)

        self.btn_login = Gtk.Button(label="Entrar")
        self.btn_login.get_style_context().add_class("share-primary")
        self.btn_login.connect("clicked", lambda *_: self._on_login())
        box.pack_start(self.btn_login, False, False, 0)

        self.login_notice = Gtk.Label(label="")
        self.login_notice.set_line_wrap(True)
        box.pack_start(self.login_notice, False, False, 0)
        return box

    def _build_main(self) -> Gtk.Widget:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.get_style_context().add_class("share-header")
        root.pack_start(header, False, False, 0)

        brand_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        pix = load_logo_pixbuf(28)
        if pix is not None:
            brand_box.pack_start(Gtk.Image.new_from_pixbuf(pix), False, False, 0)
        brand = Gtk.Label()
        brand.set_markup("<b>AidyShare</b>")
        brand_box.pack_start(brand, False, False, 0)
        header.pack_start(brand_box, True, True, 0)

        self.user_label = Gtk.Label(label="")
        header.pack_start(self.user_label, False, False, 0)
        btn_out = Gtk.Button(label="Salir")
        btn_out.connect("clicked", self._on_logout)
        header.pack_start(btn_out, False, False, 0)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.set_margin_top(10)
        body.set_margin_bottom(10)
        body.set_margin_start(12)
        body.set_margin_end(12)
        root.pack_start(body, True, True, 0)

        self.quota_label = Gtk.Label(label="Cuota…")
        self.quota_label.set_xalign(0)
        body.pack_start(self.quota_label, False, False, 0)
        self.quota_bar = Gtk.ProgressBar()
        body.pack_start(self.quota_bar, False, False, 0)

        path_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        body.pack_start(path_row, False, False, 0)
        self.path_entry = Gtk.Entry()
        self.path_entry.set_text(self.remote_path)
        self.path_entry.set_placeholder_text("Carpeta remota (ej. AidyCOS-Backup)")
        path_row.pack_start(self.path_entry, True, True, 0)
        btn_go = Gtk.Button(label="Abrir")
        btn_go.connect("clicked", lambda *_: self._goto_path())
        path_row.pack_start(btn_go, False, False, 0)
        btn_up = Gtk.Button(label="↑")
        btn_up.set_tooltip_text("Carpeta padre")
        btn_up.connect("clicked", lambda *_: self._goto_parent())
        path_row.pack_start(btn_up, False, False, 0)

        tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        body.pack_start(tools, False, False, 0)
        self.btn_refresh = Gtk.Button(label="Actualizar")
        self.btn_refresh.connect("clicked", lambda *_: self._refresh_all())
        tools.pack_start(self.btn_refresh, False, False, 0)
        self.btn_backup = Gtk.Button(label="Respaldar archivos…")
        self.btn_backup.get_style_context().add_class("share-accent")
        self.btn_backup.set_tooltip_text("Elige archivos locales y súbelos a la carpeta del negocio")
        self.btn_backup.connect("clicked", self._on_backup)
        tools.pack_start(self.btn_backup, False, False, 0)
        self.btn_mkdir = Gtk.Button(label="Nueva carpeta")
        self.btn_mkdir.connect("clicked", self._on_mkdir)
        tools.pack_start(self.btn_mkdir, False, False, 0)
        self.btn_download = Gtk.Button(label="Descargar")
        self.btn_download.connect("clicked", self._on_download)
        tools.pack_start(self.btn_download, False, False, 0)
        self.btn_delete = Gtk.Button(label="Borrar")
        self.btn_delete.connect("clicked", self._on_delete)
        tools.pack_start(self.btn_delete, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        body.pack_start(scroll, True, True, 0)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-activated", self._on_row_activated)
        self.listbox.connect("row-selected", self._on_row_selected)
        scroll.add(self.listbox)

        self.notice = Gtk.Label(label="")
        self.notice.set_xalign(0)
        self.notice.set_line_wrap(True)
        body.pack_start(self.notice, False, False, 0)
        return root

    def _set_notice(self, text: str, *, ok: bool | None = None) -> None:
        self.notice.set_text(text)
        ctx = self.notice.get_style_context()
        ctx.remove_class("share-ok")
        ctx.remove_class("share-bad")
        if ok is True:
            ctx.add_class("share-ok")
        elif ok is False:
            ctx.add_class("share-bad")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (
            self.btn_login,
            self.btn_refresh,
            self.btn_backup,
            self.btn_mkdir,
            self.btn_download,
            self.btn_delete,
        ):
            widget.set_sensitive(not busy)

    def _on_login(self, *, force: bool = False, kick: str | None = None) -> None:
        if self._busy:
            return
        user = self.login_user.get_text().strip()
        password = self.login_pass.get_text()
        if not user or not password:
            self.login_notice.set_text("Escribe usuario y contraseña.")
            return
        self._set_busy(True)
        self.login_notice.set_text("Conectando…")

        def work() -> None:
            try:
                session = self.client.login(user, password, force_login=force, session_id_to_kick=kick)
                GLib.idle_add(self._login_ok, session)
            except ActiveSessionConflict as exc:
                GLib.idle_add(self._login_conflict, exc)
            except ApiError as exc:
                GLib.idle_add(self._login_fail, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _login_ok(self, session: ShareSession) -> bool:
        self._set_busy(False)
        self.session = session
        self.client.session = session
        self.cfg.username = session.usuario
        save_config(self.cfg)
        save_session(session)
        self.login_pass.set_text("")
        self.stack.set_visible_child_name("main")
        self._refresh_all()
        return False

    def _login_fail(self, message: str) -> bool:
        self._set_busy(False)
        self.login_notice.set_text(message)
        return False

    def _login_conflict(self, exc: ActiveSessionConflict) -> bool:
        self._set_busy(False)
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text="Sesión activa en otro dispositivo",
        )
        dialog.format_secondary_text(
            f"{exc.message}\n¿Entrar aquí y cerrar la otra sesión?"
        )
        dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        dialog.add_button("Entrar aquí", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            info = exc.session_info or {}
            self._on_login(force=True, kick=str(info.get("session_id") or "") or None)
        else:
            self.login_notice.set_text("Login cancelado (sesión activa en otro sitio).")
        return False

    def _on_logout(self, *_args) -> None:
        clear_session()
        self.session = ShareSession()
        self.client.session = self.session
        self.stack.set_visible_child_name("login")
        self.login_notice.set_text("Sesión cerrada en este PC.")

    def _refresh_all(self) -> None:
        if self._busy:
            return
        self.remote_path = self.path_entry.get_text().strip().strip("/")
        self.cfg.remote_folder = self.remote_path or self.cfg.remote_folder
        save_config(self.cfg)
        self._set_busy(True)
        self._set_notice("Actualizando…")
        path = self.remote_path
        client = self.client

        def work() -> None:
            try:
                client.ensure_folder(path)
                quota = client.quota()
                listing = client.list_dir(path)
                GLib.idle_add(self._apply_refresh, quota, listing, None)
            except ApiError as exc:
                GLib.idle_add(self._apply_refresh, None, None, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _apply_refresh(self, quota, listing, error: str | None) -> bool:
        self._set_busy(False)
        self.user_label.set_text(
            f"@{self.session.usuario} · {self.session.padre}"
            + (f" · {self.session.nombre}" if self.session.nombre else "")
        )
        if error:
            self._set_notice(error, ok=False)
            return False
        if isinstance(quota, dict):
            usado = float(quota.get("usado_mb") or 0)
            limite = float(quota.get("limite_mb") or 500)
            pct = float(quota.get("porcentaje") or 0) / 100.0
            self.quota_label.set_text(
                f"Negocio {self.session.padre}: {usado:.1f} / {limite:.0f} MB usados"
            )
            self.quota_bar.set_fraction(min(1.0, max(0.0, pct)))
        for child in list(self.listbox.get_children()):
            self.listbox.remove(child)
        items = (listing or {}).get("items") or []
        if not items:
            row = Gtk.ListBoxRow()
            lab = Gtk.Label(label="(vacío — usa Respaldar archivos…)")
            lab.set_xalign(0)
            lab.get_style_context().add_class("share-muted")
            lab.set_margin_top(8)
            lab.set_margin_bottom(8)
            lab.set_margin_start(10)
            row.add(lab)
            self.listbox.add(row)
        else:
            for item in items:
                row = Gtk.ListBoxRow()
                box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                box.set_margin_top(6)
                box.set_margin_bottom(6)
                box.set_margin_start(8)
                box.set_margin_end(8)
                kind = "📁" if item.get("type") == "dir" else "📄"
                name = Gtk.Label(label=f"{kind}  {item.get('name')}")
                name.set_xalign(0)
                name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
                meta = Gtk.Label(label=_fmt_size(item.get("size") if item.get("type") != "dir" else None))
                meta.get_style_context().add_class("share-muted")
                box.pack_start(name, True, True, 0)
                box.pack_start(meta, False, False, 0)
                row.add(box)
                row._aidyshare_item = item  # type: ignore[attr-defined]
                self.listbox.add(row)
        self.listbox.show_all()
        self._set_notice("Listo.", ok=True)
        return False

    def _goto_path(self) -> None:
        self._refresh_all()

    def _goto_parent(self) -> None:
        parts = [p for p in self.path_entry.get_text().strip("/").split("/") if p]
        self.path_entry.set_text("/".join(parts[:-1]))
        self._refresh_all()

    def _on_row_selected(self, _box: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        item = getattr(row, "_aidyshare_item", None) if row else None
        self._selected_remote = str(item.get("path")) if isinstance(item, dict) else None

    def _on_row_activated(self, _box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        item = getattr(row, "_aidyshare_item", None)
        if not isinstance(item, dict):
            return
        if item.get("type") == "dir":
            self.path_entry.set_text(str(item.get("path") or ""))
            self._refresh_all()

    def _on_backup(self, *_args) -> None:
        if self._busy:
            return
        dialog = Gtk.FileChooserDialog(
            title="Elegir archivos para respaldar",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.set_select_multiple(True)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Subir", Gtk.ResponseType.OK)
        response = dialog.run()
        files = dialog.get_filenames() if response == Gtk.ResponseType.OK else []
        dialog.destroy()
        if not files:
            return
        remote = self.path_entry.get_text().strip().strip("/") or self.cfg.remote_folder
        self._set_busy(True)
        self._set_notice(f"Subiendo {len(files)} archivo(s)…")

        def work() -> None:
            try:
                self.client.ensure_folder(remote)
                uploaded = 0
                for raw in files:
                    self.client.upload_file(Path(raw), remote)
                    uploaded += 1
                GLib.idle_add(self._backup_done, True, f"Subidos {uploaded} archivo(s) a {remote}")
            except ApiError as exc:
                GLib.idle_add(self._backup_done, False, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _backup_done(self, ok: bool, detail: str) -> bool:
        self._set_busy(False)
        self._set_notice(detail, ok=ok)
        if ok:
            self._notify(detail)
            self._refresh_all()
        return False

    def _on_mkdir(self, *_args) -> None:
        dialog = Gtk.Dialog(title="Nueva carpeta", transient_for=self, modal=True)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Crear", Gtk.ResponseType.OK)
        entry = Gtk.Entry()
        entry.set_placeholder_text("Nombre")
        box = dialog.get_content_area()
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.add(entry)
        dialog.show_all()
        response = dialog.run()
        name = entry.get_text().strip()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not name:
            return
        remote = self.path_entry.get_text().strip().strip("/")
        self._set_busy(True)

        def work() -> None:
            try:
                self.client.mkdir(remote, name)
                GLib.idle_add(self._backup_done, True, f"Carpeta creada: {name}")
            except ApiError as exc:
                GLib.idle_add(self._backup_done, False, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _on_download(self, *_args) -> None:
        if not self._selected_remote:
            self._set_notice("Selecciona un archivo.", ok=False)
            return
        remote = self._selected_remote
        dialog = Gtk.FileChooserDialog(
            title="Guardar como",
            parent=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.set_current_name(Path(remote).name)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Guardar", Gtk.ResponseType.OK)
        response = dialog.run()
        dest = dialog.get_filename() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if not dest:
            return
        self._set_busy(True)
        self._set_notice("Descargando…")

        def work() -> None:
            try:
                self.client.download_file(remote, Path(dest))
                GLib.idle_add(self._backup_done, True, f"Descargado: {dest}")
            except ApiError as exc:
                GLib.idle_add(self._backup_done, False, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _on_delete(self, *_args) -> None:
        if not self._selected_remote:
            self._set_notice("Selecciona un elemento.", ok=False)
            return
        remote = self._selected_remote
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=f"¿Borrar «{remote}» del negocio?",
        )
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        self._set_busy(True)

        def work() -> None:
            try:
                self.client.delete_paths([remote])
                GLib.idle_add(self._backup_done, True, f"Borrado: {remote}")
            except ApiError as exc:
                GLib.idle_add(self._backup_done, False, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _notify(self, body: str) -> None:
        try:
            import subprocess

            subprocess.Popen(
                [
                    "notify-send",
                    "--app-name=AidyShare",
                    "--icon=aidyshare",
                    "AidyShare",
                    body[:180] or "Listo",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass


def _fmt_size(size) -> str:
    try:
        n = int(size or 0)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n/1024:.1f} KB"
    return f"{n/(1024*1024):.1f} MB"


def run_ui() -> int:
    _install_style()
    apply_aidyshare_branding()
    win = ShareWindow()
    win.show_all()
    Gtk.main()
    return 0
