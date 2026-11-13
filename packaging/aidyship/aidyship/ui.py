"""GTK window for AidyShip: GitHub login + fast commit/push."""

from __future__ import annotations

import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from .branding import apply_aidyship_branding, load_logo_pixbuf
from .config import ShipConfig, add_favorite, load_config, remove_favorite, save_config
from .gitops import (
    ChangedFile,
    RepoStatus,
    commit,
    find_git_root,
    pull,
    push,
    repo_status,
    short_diff,
    stage_paths,
)
from .github_auth import (
    GitHubSession,
    auth_status,
    logout,
    setup_git_credentials,
    start_login_flow,
)
from .publish import DeployProfile, deploy_only, detect_deploy_profile, publish_repo

TEAL = "#0B3D4A"
MINT = "#3DDC97"
BG = "#F4F7F8"
SIDE = "#E8EEF0"


def _install_style() -> None:
    css = Gtk.CssProvider()
    css.load_from_data(
        f"""
        window.aidyship {{ background: {BG}; }}
        .ship-header {{ background: {TEAL}; color: white; padding: 12px 14px; }}
        .ship-header label {{ color: white; }}
        .ship-side {{ background: {SIDE}; }}
        .ship-card {{ padding: 10px; }}
        .ship-muted {{ color: #5b6b73; font-size: 11px; }}
        .ship-status-ok {{ color: {TEAL}; font-weight: bold; }}
        .ship-status-bad {{ color: #a33; font-weight: bold; }}
        .ship-primary {{ background: {TEAL}; color: white; padding: 8px 12px; border-radius: 4px; }}
        .ship-accent {{ background: {MINT}; color: {TEAL}; padding: 8px 12px; border-radius: 4px; }}
        .ship-deploy {{ background: #c45c26; color: white; padding: 8px 12px; border-radius: 4px; }}
        .ship-diff {{ font-family: monospace; font-size: 11px; }}
        """.encode("utf-8")
    )
    screen = Gtk.Window().get_screen()
    Gtk.StyleContext.add_provider_for_screen(
        screen,
        css,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


class ShipWindow(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="AidyShip")
        self.set_default_size(920, 620)
        self.set_border_width(0)
        self.get_style_context().add_class("aidyship")
        apply_aidyship_branding(self)

        self.cfg: ShipConfig = load_config()
        self.session = GitHubSession(logged_in=False)
        self.repo: Path | None = None
        self.deploy_profile: DeployProfile | None = None
        self.status = RepoStatus(root=Path("."))
        self._file_checks: dict[str, Gtk.CheckButton] = {}
        self._busy = False
        self._auth_poll_id = 0

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.get_style_context().add_class("ship-header")
        root.pack_start(header, False, False, 0)

        brand_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        logo_pixbuf = load_logo_pixbuf(32)
        if logo_pixbuf is not None:
            logo = Gtk.Image.new_from_pixbuf(logo_pixbuf)
            brand_box.pack_start(logo, False, False, 0)
        brand = Gtk.Label(label="AidyShip")
        brand.set_xalign(0)
        brand.set_markup("<span size='large'><b>AidyShip</b></span>")
        brand_box.pack_start(brand, False, False, 0)
        header.pack_start(brand_box, True, True, 0)

        self.auth_label = Gtk.Label(label="Comprobando GitHub…")
        self.auth_label.set_xalign(1)
        header.pack_start(self.auth_label, False, False, 0)

        self.btn_login = Gtk.Button(label="Conectar GitHub")
        self.btn_login.connect("clicked", self._on_login)
        header.pack_start(self.btn_login, False, False, 0)

        self.btn_logout = Gtk.Button(label="Cerrar sesión")
        self.btn_logout.connect("clicked", self._on_logout)
        header.pack_start(self.btn_logout, False, False, 0)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.pack_start(body, True, True, 0)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        side.set_size_request(240, -1)
        side.set_margin_top(10)
        side.set_margin_bottom(10)
        side.set_margin_start(10)
        side.set_margin_end(6)
        side.get_style_context().add_class("ship-side")
        body.pack_start(side, False, False, 0)

        side_title = Gtk.Label(label="Repositorios")
        side_title.set_xalign(0)
        side_title.set_markup("<b>Repositorios</b>")
        side.pack_start(side_title, False, False, 0)

        scroll_fav = Gtk.ScrolledWindow()
        scroll_fav.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        side.pack_start(scroll_fav, True, True, 0)
        self.fav_list = Gtk.ListBox()
        self.fav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.fav_list.connect("row-activated", self._on_favorite_activated)
        scroll_fav.add(self.fav_list)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        side.pack_start(btn_row, False, False, 0)
        self.btn_add = Gtk.Button(label="Añadir…")
        self.btn_add.connect("clicked", self._on_add_repo)
        btn_row.pack_start(self.btn_add, True, True, 0)
        self.btn_remove = Gtk.Button(label="Quitar")
        self.btn_remove.connect("clicked", self._on_remove_repo)
        btn_row.pack_start(self.btn_remove, True, True, 0)

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        main.set_margin_top(10)
        main.set_margin_bottom(10)
        main.set_margin_start(6)
        main.set_margin_end(10)
        body.pack_start(main, True, True, 0)

        self.repo_meta = Gtk.Label(label="Elige o añade un repositorio")
        self.repo_meta.set_xalign(0)
        self.repo_meta.set_line_wrap(True)
        main.pack_start(self.repo_meta, False, False, 0)

        tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        main.pack_start(tools, False, False, 0)
        self.btn_refresh = Gtk.Button(label="Actualizar")
        self.btn_refresh.connect("clicked", lambda *_: self.refresh_repo())
        tools.pack_start(self.btn_refresh, False, False, 0)
        self.btn_pull = Gtk.Button(label="Pull")
        self.btn_pull.connect("clicked", self._on_pull)
        tools.pack_start(self.btn_pull, False, False, 0)
        self.btn_select_all = Gtk.Button(label="Marcar todo")
        self.btn_select_all.connect("clicked", lambda *_: self._set_all_checks(True))
        tools.pack_start(self.btn_select_all, False, False, 0)
        self.btn_select_none = Gtk.Button(label="Desmarcar")
        self.btn_select_none.connect("clicked", lambda *_: self._set_all_checks(False))
        tools.pack_start(self.btn_select_none, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        main.pack_start(paned, True, True, 0)

        files_scroll = Gtk.ScrolledWindow()
        files_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        paned.pack1(files_scroll, resize=True, shrink=False)
        self.files_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.files_box.set_margin_top(4)
        self.files_box.set_margin_bottom(4)
        files_scroll.add(self.files_box)

        diff_scroll = Gtk.ScrolledWindow()
        diff_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        paned.pack2(diff_scroll, resize=True, shrink=True)
        self.diff_view = Gtk.TextView()
        self.diff_view.set_editable(False)
        self.diff_view.set_cursor_visible(False)
        self.diff_view.set_wrap_mode(Gtk.WrapMode.NONE)
        self.diff_view.get_style_context().add_class("ship-diff")
        self.diff_buffer = self.diff_view.get_buffer()
        diff_scroll.add(self.diff_view)
        paned.set_position(280)

        msg_label = Gtk.Label(label="Mensaje de commit")
        msg_label.set_xalign(0)
        main.pack_start(msg_label, False, False, 0)
        self.message = Gtk.Entry()
        self.message.set_placeholder_text("Describe el cambio…")
        main.pack_start(self.message, False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        main.pack_start(actions, False, False, 0)
        self.btn_commit = Gtk.Button(label="Commit")
        self.btn_commit.get_style_context().add_class("ship-primary")
        self.btn_commit.connect("clicked", lambda *_: self._run_commit(push_after=False))
        actions.pack_start(self.btn_commit, False, False, 0)
        self.btn_commit_push = Gtk.Button(label="Commit + Push")
        self.btn_commit_push.get_style_context().add_class("ship-accent")
        self.btn_commit_push.connect("clicked", lambda *_: self._run_commit(push_after=True))
        actions.pack_start(self.btn_commit_push, False, False, 0)

        self.btn_publish = Gtk.Button(label="Publicar")
        self.btn_publish.set_tooltip_text("Commit (si hay cambios) + push a GitHub, como en AidyCAI")
        self.btn_publish.connect("clicked", lambda *_: self._run_publish(deploy=False))
        actions.pack_start(self.btn_publish, False, False, 0)
        self.btn_publish_deploy = Gtk.Button(label="Publicar + Deploy")
        self.btn_publish_deploy.get_style_context().add_class("ship-deploy")
        self.btn_publish_deploy.set_tooltip_text("Publicar y desplegar en PythonAnywhere (AidyC-web)")
        self.btn_publish_deploy.connect("clicked", lambda *_: self._run_publish(deploy=True))
        actions.pack_start(self.btn_publish_deploy, False, False, 0)
        self.btn_deploy = Gtk.Button(label="Deploy")
        self.btn_deploy.set_tooltip_text("Solo deploy remoto (sin commit nuevo)")
        self.btn_deploy.connect("clicked", self._on_deploy_only)
        actions.pack_start(self.btn_deploy, False, False, 0)
        self._set_deploy_buttons_visible(False)

        self.notice = Gtk.Label(label="")
        self.notice.set_xalign(0)
        self.notice.set_line_wrap(True)
        self.notice.get_style_context().add_class("ship-muted")
        main.pack_start(self.notice, False, False, 0)

        self.connect("destroy", Gtk.main_quit)
        self._rebuild_favorites()
        self._set_notice("Listo.")
        self.refresh_auth()
        if self.cfg.last_repo:
            self.open_repo(self.cfg.last_repo)
        elif self.cfg.favorites:
            self.open_repo(self.cfg.favorites[0])

    def _set_notice(self, text: str, *, ok: bool | None = None) -> None:
        self.notice.set_text(text)
        ctx = self.notice.get_style_context()
        ctx.remove_class("ship-status-ok")
        ctx.remove_class("ship-status-bad")
        if ok is True:
            ctx.add_class("ship-status-ok")
        elif ok is False:
            ctx.add_class("ship-status-bad")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (
            self.btn_login,
            self.btn_logout,
            self.btn_add,
            self.btn_remove,
            self.btn_refresh,
            self.btn_pull,
            self.btn_commit,
            self.btn_commit_push,
            self.btn_publish,
            self.btn_publish_deploy,
            self.btn_deploy,
            self.btn_select_all,
            self.btn_select_none,
        ):
            widget.set_sensitive(not busy)

    def _set_deploy_buttons_visible(self, visible: bool) -> None:
        for widget in (self.btn_publish, self.btn_publish_deploy, self.btn_deploy):
            if visible:
                widget.show()
            else:
                widget.hide()

    def refresh_auth(self) -> None:
        def work() -> None:
            try:
                session = auth_status()
            except Exception as exc:  # noqa: BLE001 — show any auth probe failure in UI
                session = GitHubSession(logged_in=False, detail=str(exc))
            GLib.idle_add(self._apply_auth, session)

        threading.Thread(target=work, daemon=True).start()
        # Don't leave "Comprobando…" forever if gh hangs.
        GLib.timeout_add_seconds(8, self._auth_timeout)

    def _auth_timeout(self) -> bool:
        if self.auth_label.get_text() == "Comprobando GitHub…":
            self.auth_label.set_text("Sin respuesta de gh")
            self.btn_login.show()
            self.btn_logout.hide()
        return False

    def _apply_auth(self, session: GitHubSession) -> bool:
        self.session = session
        if session.logged_in:
            label = f"@{session.login}" if session.login else "GitHub conectado"
            self.auth_label.set_text(label)
            self.btn_login.hide()
            self.btn_logout.show()
            threading.Thread(target=setup_git_credentials, daemon=True).start()
        else:
            self.auth_label.set_text("Sin sesión de GitHub")
            self.btn_login.show()
            self.btn_logout.hide()
        return False

    def _on_login(self, *_args) -> None:
        ok, detail = start_login_flow()
        self._set_notice(detail, ok=ok)
        if not ok:
            return
        if self._auth_poll_id:
            GLib.source_remove(self._auth_poll_id)
        self._auth_poll_id = GLib.timeout_add_seconds(2, self._poll_auth)

    def _poll_auth(self) -> bool:
        session = auth_status()
        self._apply_auth(session)
        if session.logged_in:
            self._set_notice(f"Conectado como @{session.login}", ok=True)
            self._auth_poll_id = 0
            return False
        return True

    def _on_logout(self, *_args) -> None:
        ok, detail = logout()
        self._set_notice(detail, ok=ok)
        self.refresh_auth()

    def _rebuild_favorites(self) -> None:
        for child in list(self.fav_list.get_children()):
            self.fav_list.remove(child)
        for path in self.cfg.favorites:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            box.set_margin_top(6)
            box.set_margin_bottom(6)
            box.set_margin_start(8)
            box.set_margin_end(8)
            name = Path(path).name or path
            title = Gtk.Label(label=name)
            title.set_xalign(0)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            title.set_markup(f"<b>{GLib.markup_escape_text(name)}</b>")
            sub = Gtk.Label(label=path)
            sub.set_xalign(0)
            sub.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            sub.get_style_context().add_class("ship-muted")
            box.pack_start(title, False, False, 0)
            box.pack_start(sub, False, False, 0)
            row.add(box)
            row._aidyship_path = path  # type: ignore[attr-defined]
            self.fav_list.add(row)
        self.fav_list.show_all()

    def _on_favorite_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        path = getattr(row, "_aidyship_path", None)
        if path:
            self.open_repo(path)

    def _on_add_repo(self, *_args) -> None:
        dialog = Gtk.FileChooserDialog(
            title="Elegir repositorio git",
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN,
            Gtk.ResponseType.OK,
        )
        if self.cfg.last_repo:
            dialog.set_current_folder(self.cfg.last_repo)
        response = dialog.run()
        chosen = dialog.get_filename() if response == Gtk.ResponseType.OK else None
        dialog.destroy()
        if not chosen:
            return
        root = find_git_root(chosen)
        if root is None:
            self._set_notice("Esa carpeta no es un repositorio git.", ok=False)
            return
        self.cfg = add_favorite(self.cfg, root)
        self._rebuild_favorites()
        self.open_repo(root)

    def _on_remove_repo(self, *_args) -> None:
        row = self.fav_list.get_selected_row()
        if row is None:
            self._set_notice("Selecciona un favorito para quitar.")
            return
        path = getattr(row, "_aidyship_path", None)
        if not path:
            return
        self.cfg = remove_favorite(self.cfg, path)
        self._rebuild_favorites()
        if self.repo and str(self.repo) == path:
            self.repo = None
            self.deploy_profile = None
            self._set_deploy_buttons_visible(False)
            self.repo_meta.set_text("Elige o añade un repositorio")
            self._clear_files()
        self._set_notice("Favorito eliminado.")

    def open_repo(self, path: Path | str) -> None:
        root = find_git_root(path)
        if root is None:
            self._set_notice(f"No es un repo git: {path}", ok=False)
            return
        self.repo = root
        self.deploy_profile = detect_deploy_profile(root)
        self._set_deploy_buttons_visible(bool(self.deploy_profile and self.deploy_profile.can_deploy))
        self.cfg.last_repo = str(root)
        if str(root) not in self.cfg.favorites:
            self.cfg = add_favorite(self.cfg, root)
            self._rebuild_favorites()
        else:
            save_config(self.cfg)
        self.refresh_repo()

    def refresh_repo(self) -> None:
        if self.repo is None:
            return
        repo = self.repo

        def work() -> None:
            status = repo_status(repo)
            GLib.idle_add(self._apply_status, status)

        self._set_notice("Consultando git…")
        threading.Thread(target=work, daemon=True).start()

    def _apply_status(self, status: RepoStatus) -> bool:
        self.status = status
        if not status.ok:
            self.repo_meta.set_text(status.error)
            self._clear_files()
            self._set_notice(status.error, ok=False)
            return False
        bits = [str(status.root), status.branch or "sin rama"]
        if status.upstream:
            bits.append(f"↑{status.ahead} ↓{status.behind} · {status.upstream}")
        bits.append(f"{len(status.files)} cambio(s)")
        if self.deploy_profile and self.deploy_profile.can_deploy:
            bits.append(f"deploy {self.deploy_profile.deploy_host}")
        self.repo_meta.set_text("  ·  ".join(bits))
        self._render_files(status.files)
        self._set_notice("Estado actualizado.", ok=True)
        return False

    def _clear_files(self) -> None:
        for child in list(self.files_box.get_children()):
            self.files_box.remove(child)
        self._file_checks.clear()
        self.diff_buffer.set_text("")

    def _render_files(self, files: list[ChangedFile]) -> None:
        self._clear_files()
        if not files:
            empty = Gtk.Label(label="Sin cambios locales")
            empty.set_xalign(0)
            empty.get_style_context().add_class("ship-muted")
            self.files_box.pack_start(empty, False, False, 0)
            self.files_box.show_all()
            return
        for item in files:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            check = Gtk.CheckButton()
            check.set_active(True)
            self._file_checks[item.path] = check
            label = Gtk.Label(label=f"{item.status}  {item.path}")
            label.set_xalign(0)
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            btn = Gtk.Button(label="Diff")
            btn.connect("clicked", self._on_diff, item.path)
            row.pack_start(check, False, False, 0)
            row.pack_start(label, True, True, 0)
            row.pack_start(btn, False, False, 0)
            self.files_box.pack_start(row, False, False, 0)
        self.files_box.show_all()

    def _set_all_checks(self, active: bool) -> None:
        for check in self._file_checks.values():
            check.set_active(active)

    def _selected_paths(self) -> list[str]:
        return [path for path, check in self._file_checks.items() if check.get_active()]

    def _on_diff(self, _btn: Gtk.Button, path: str) -> None:
        if self.repo is None:
            return
        repo = self.repo

        def work() -> None:
            text = short_diff(repo, path)
            GLib.idle_add(self.diff_buffer.set_text, text)

        self.diff_buffer.set_text(f"Cargando diff de {path}…")
        threading.Thread(target=work, daemon=True).start()

    def _run_commit(self, *, push_after: bool) -> None:
        if self._busy:
            return
        if self.repo is None:
            self._set_notice("Abre un repositorio primero.", ok=False)
            return
        if push_after and not self.session.logged_in:
            self._set_notice("Conecta GitHub antes de hacer push.", ok=False)
            return
        paths = self._selected_paths()
        message = self.message.get_text()
        repo = self.repo
        self._set_busy(True)
        self._set_notice("Preparando commit…")

        def work() -> None:
            ok, detail = stage_paths(repo, paths)
            if not ok:
                GLib.idle_add(self._finish_op, False, detail)
                return
            ok, detail = commit(repo, message)
            if not ok:
                GLib.idle_add(self._finish_op, False, detail)
                return
            if push_after:
                ok, detail = push(repo)
                GLib.idle_add(self._finish_op, ok, detail, True)
                return
            GLib.idle_add(self._finish_op, True, detail, True)

        threading.Thread(target=work, daemon=True).start()

    def _on_pull(self, *_args) -> None:
        if self._busy or self.repo is None:
            return
        if not self.session.logged_in:
            self._set_notice("Conecta GitHub antes de hacer pull.", ok=False)
            return
        repo = self.repo
        self._set_busy(True)
        self._set_notice("Haciendo pull…")

        def work() -> None:
            ok, detail = pull(repo)
            GLib.idle_add(self._finish_op, ok, detail, False)

        threading.Thread(target=work, daemon=True).start()

    def _run_publish(self, *, deploy: bool) -> None:
        if self._busy or self.repo is None:
            return
        if not self.session.logged_in:
            self._set_notice("Conecta GitHub antes de publicar.", ok=False)
            return
        if deploy and not (self.deploy_profile and self.deploy_profile.can_deploy):
            self._set_notice("Este repo no tiene deploy (AidyC-web).", ok=False)
            return
        message = self.message.get_text()
        paths = self._selected_paths()
        repo = self.repo
        profile = self.deploy_profile
        self._set_busy(True)
        self._set_notice("Publicando + deploy…" if deploy else "Publicando…")

        def work() -> None:
            result = publish_repo(
                repo,
                message,
                paths=paths,
                deploy=deploy,
                profile=profile,
            )
            ok = result.pushed and (result.deployed if deploy else True)
            GLib.idle_add(self._finish_op, ok, result.detail, result.committed)

        threading.Thread(target=work, daemon=True).start()

    def _on_deploy_only(self, *_args) -> None:
        if self._busy or self.repo is None:
            return
        if not (self.deploy_profile and self.deploy_profile.can_deploy):
            self._set_notice("Este repo no tiene deploy (AidyC-web).", ok=False)
            return
        repo = self.repo
        profile = self.deploy_profile
        self._set_busy(True)
        self._set_notice("Desplegando en PythonAnywhere…")

        def work() -> None:
            ok, detail = deploy_only(repo, profile=profile)
            GLib.idle_add(self._finish_op, ok, detail, False)

        threading.Thread(target=work, daemon=True).start()

    def _finish_op(self, ok: bool, detail: str, clear_message: bool = False) -> bool:
        self._set_busy(False)
        self._set_notice(detail, ok=ok)
        if ok and clear_message:
            self.message.set_text("")
        if ok:
            self.refresh_repo()
            self._notify(detail)
        return False

    def _notify(self, body: str) -> None:
        try:
            import subprocess

            subprocess.Popen(
                [
                    "notify-send",
                    "--app-name=AidyShip",
                    "--icon=aidyship",
                    "AidyShip",
                    body[:180] or "Listo",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass


def run_ui() -> int:
    _install_style()
    apply_aidyship_branding()
    win = ShipWindow()
    win.show_all()
    # Hide logout until we know auth state.
    if not win.session.logged_in:
        win.btn_logout.hide()
    win._set_deploy_buttons_visible(bool(win.deploy_profile and win.deploy_profile.can_deploy))
    Gtk.main()
    return 0
