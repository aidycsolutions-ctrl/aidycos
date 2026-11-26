"""GTK file manager window."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from .branding import apply_branding, load_logo_pixbuf
from .fs import (
    DirEntry,
    copy_entry,
    delete_path,
    delete_trash_item,
    format_mtime,
    human_size,
    icon_name_for,
    list_directory,
    list_trash,
    make_directory,
    move_entry,
    move_to_trash,
    parse_location,
    rename_entry,
    resolve_start,
    restore_trash,
    user_places,
)

BG = "#0E1418"
PANEL = "#102028"
INK = "#E8F4F8"
MUTED = "#8AA0A8"
CYAN = "#19D3F5"


def _install_style() -> None:
    css = Gtk.CssProvider()
    css.load_from_data(
        f"""
        window.aidycexplorer, window.aidycexplorer * {{ color: {INK}; }}
        window.aidycexplorer {{ background: {BG}; }}
        .explorer-toolbar, .explorer-sidebar {{ background: {PANEL}; }}
        .explorer-toolbar {{ padding: 8px; }}
        entry {{ background: #0c1216; color: {INK}; }}
        button.explorer-btn {{
            background: #16303a;
            color: {INK};
            border-radius: 6px;
            padding: 4px 8px;
        }}
        button.explorer-btn:disabled {{ color: {MUTED}; }}
        .explorer-sidebar row {{ padding: 6px 10px; }}
        .explorer-sidebar row:selected {{ background: #0e6f86; }}
        treeview {{ background: {BG}; color: {INK}; }}
        treeview:selected, treeview:selected:focus {{ background: #0e6f86; color: {INK}; }}
        .explorer-status {{ color: {MUTED}; padding: 4px 10px; }}
        """.encode()
    )
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(
            screen,
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_USER,
        )


class ExplorerWindow(Gtk.Window):
    def __init__(self, start: Path, *, mode: str = "path", select: str | None = None) -> None:
        super().__init__(title="AidyCExplorer")
        self.set_default_size(980, 640)
        self.get_style_context().add_class("aidycexplorer")
        apply_branding(self)

        self.mode = "path"
        self.current = start
        self.show_hidden = False
        self.history: list[tuple[str, Path]] = []
        self.history_index = -1
        self.clipboard: list[Path] = []
        self.clipboard_mode: str | None = None
        self._pending_select = select
        self._sort = "name"
        self._sort_desc = False

        self.store = Gtk.ListStore(str, str, str, str, str, bool, str, str)
        self.view = Gtk.TreeView(model=self.store)
        self.view.set_headers_clickable(True)
        self.view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.view.connect("row-activated", self._on_activated)
        self.view.connect("button-press-event", self._on_button_press)
        self.view.get_selection().connect("changed", lambda *_args: self._update_status())

        for title, column_id, sort_key, expand in (
            ("Nombre", 1, "name", True),
            ("Tamaño", 2, "size", False),
            ("Modificado", 3, "mtime", False),
        ):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=column_id)
            if column_id == 1:
                icon = Gtk.CellRendererPixbuf()
                column.pack_start(icon, False)
                column.add_attribute(icon, "icon_name", 0)
                column.reorder(icon, 0)
            column.set_resizable(True)
            column.set_expand(expand)
            column.set_clickable(True)
            column.connect("clicked", self._on_sort, sort_key)
            self.view.append_column(column)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.view)

        self.places = Gtk.ListBox()
        self.places.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.places.set_activate_on_single_click(True)
        self.places.connect("row-activated", self._on_place)
        side_scroll = Gtk.ScrolledWindow()
        side_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        side_scroll.add(self.places)
        side_scroll.set_size_request(200, -1)
        side_scroll.get_style_context().add_class("explorer-sidebar")

        pane = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        pane.pack1(side_scroll, False, False)
        pane.pack2(scroll, True, False)

        self.status = Gtk.Label(label="")
        self.status.set_xalign(0)
        self.status.get_style_context().add_class("explorer-status")

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.pack_start(self._build_toolbar(), False, False, 0)
        root.pack_start(pane, True, True, 0)
        root.pack_start(self.status, False, False, 0)
        self.add(root)

        self.connect("key-press-event", self._on_key)
        self._refresh_places()
        self._navigate(mode, start, select=select)

    def _build_toolbar(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.get_style_context().add_class("explorer-toolbar")
        logo = load_logo_pixbuf(28)
        if logo is not None:
            bar.pack_start(Gtk.Image.new_from_pixbuf(logo), False, False, 0)

        self.back_button = self._tool("go-previous-symbolic", "Atrás", self._back)
        self.forward_button = self._tool("go-next-symbolic", "Adelante", self._forward)
        self.up_button = self._tool("go-up-symbolic", "Subir", self._up)
        bar.pack_start(self.back_button, False, False, 0)
        bar.pack_start(self.forward_button, False, False, 0)
        bar.pack_start(self.up_button, False, False, 0)
        bar.pack_start(self._tool("go-home-symbolic", "Inicio", self._home), False, False, 0)
        bar.pack_start(self._tool("view-refresh-symbolic", "Actualizar", lambda *_a: self._reload()), False, False, 0)

        self.path_entry = Gtk.Entry()
        self.path_entry.set_hexpand(True)
        self.path_entry.connect("activate", self._on_path)
        bar.pack_start(self.path_entry, True, True, 0)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Buscar")
        self.search.set_width_chars(16)
        self.search.connect("search-changed", lambda *_a: self._reload())
        bar.pack_start(self.search, False, False, 0)

        self.hidden_button = Gtk.ToggleButton(label="Ocultos")
        self.hidden_button.get_style_context().add_class("explorer-btn")
        self.hidden_button.connect("toggled", self._toggle_hidden)
        bar.pack_start(self.hidden_button, False, False, 0)
        bar.pack_start(self._tool("folder-new-symbolic", "Nueva carpeta", lambda *_a: self._new_folder()), False, False, 0)
        return bar

    def _tool(self, icon: str, tooltip: str, handler) -> Gtk.Button:
        button = Gtk.Button()
        button.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
        button.set_tooltip_text(tooltip)
        button.get_style_context().add_class("explorer-btn")
        button.connect("clicked", handler)
        return button

    def _navigate(self, mode: str, path: Path, *, record: bool = True, select: str | None = None) -> None:
        path = Path(path)
        if record:
            self.history = self.history[: self.history_index + 1]
            item = (mode, path)
            if not self.history or self.history[-1] != item:
                self.history.append(item)
            self.history_index = len(self.history) - 1
        self.mode = mode
        self.current = path
        self._pending_select = select
        self._reload()
        self._update_nav_buttons()

    def _reload(self) -> None:
        self.store.clear()
        if self.mode == "trash":
            self.path_entry.set_text("trash://")
            self.set_title("AidyCExplorer — Papelera")
        else:
            self.path_entry.set_text(str(self.current))
            self.set_title(f"AidyCExplorer — {self.current.name or self.current}")
        try:
            if self.mode == "trash":
                entries = list_trash()
            else:
                entries = list_directory(self.current, show_hidden=self.show_hidden)
        except OSError as exc:
            self._error(f"No se puede abrir:\n{exc}")
            self._update_status()
            return
        query = self.search.get_text().strip().casefold()
        if query:
            entries = [entry for entry in entries if query in entry.name.casefold()]
        entries = self._sorted(entries)
        for entry in entries:
            self.store.append(
                [
                    icon_name_for(entry),
                    entry.name,
                    "Carpeta" if entry.is_dir else human_size(entry.size),
                    format_mtime(entry.mtime),
                    str(entry.path),
                    entry.is_dir,
                    entry.trash_name,
                    entry.origin,
                ]
            )
        if self._pending_select:
            self._select_named(self._pending_select)
            self._pending_select = None
        self._update_status()
        self._mark_place()

    def _sorted(self, entries: list[DirEntry]) -> list[DirEntry]:
        def key(entry: DirEntry):
            if self._sort == "size":
                return entry.size or 0
            if self._sort == "mtime":
                return entry.mtime
            return entry.name.casefold()

        folders = sorted((entry for entry in entries if entry.is_dir), key=key, reverse=self._sort_desc)
        files = sorted((entry for entry in entries if not entry.is_dir), key=key, reverse=self._sort_desc)
        return folders + files

    def _on_sort(self, _column: Gtk.TreeViewColumn, key: str) -> None:
        if self._sort == key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort = key
            self._sort_desc = False
        self._reload()

    def _selected_rows(self) -> list[dict[str, object]]:
        _model, paths = self.view.get_selection().get_selected_rows()
        rows: list[dict[str, object]] = []
        for tree_path in paths:
            iterator = self.store.get_iter(tree_path)
            rows.append(
                {
                    "name": self.store.get_value(iterator, 1),
                    "path": Path(self.store.get_value(iterator, 4)),
                    "is_dir": bool(self.store.get_value(iterator, 5)),
                    "trash_name": self.store.get_value(iterator, 6) or "",
                    "origin": self.store.get_value(iterator, 7) or "",
                }
            )
        return rows

    def _select_named(self, name: str) -> None:
        iterator = self.store.get_iter_first()
        while iterator is not None:
            if self.store.get_value(iterator, 1) == name:
                tree_path = self.store.get_path(iterator)
                self.view.get_selection().select_path(tree_path)
                self.view.scroll_to_cell(tree_path, None, True, 0.3, 0)
                return
            iterator = self.store.iter_next(iterator)

    def _update_status(self) -> None:
        selected = self._selected_rows()
        total = len(self.store)
        if len(selected) == 1 and selected[0]["origin"]:
            self.status.set_text(f"1 seleccionado · {selected[0]['origin']}")
            return
        if selected:
            self.status.set_text(f"{len(selected)} seleccionados · {total} elementos")
            return
        self.status.set_text(f"{total} elementos")

    def _update_nav_buttons(self) -> None:
        self.back_button.set_sensitive(self.history_index > 0)
        self.forward_button.set_sensitive(self.history_index < len(self.history) - 1)
        parent = self.current.parent
        self.up_button.set_sensitive(self.mode == "trash" or parent != self.current)

    def _back(self, *_args) -> None:
        if self.history_index <= 0:
            return
        self.history_index -= 1
        mode, path = self.history[self.history_index]
        self._navigate(mode, path, record=False)

    def _forward(self, *_args) -> None:
        if self.history_index >= len(self.history) - 1:
            return
        self.history_index += 1
        mode, path = self.history[self.history_index]
        self._navigate(mode, path, record=False)

    def _up(self, *_args) -> None:
        if self.mode == "trash":
            self._home()
            return
        parent = self.current.parent
        if parent != self.current:
            self._navigate("path", parent)

    def _home(self, *_args) -> None:
        self._navigate("path", Path.home())

    def _toggle_hidden(self, button: Gtk.ToggleButton) -> None:
        self.show_hidden = button.get_active()
        self._reload()

    def _on_path(self, entry: Gtk.Entry) -> None:
        try:
            mode, path = parse_location(entry.get_text(), home=Path.home(), cwd=self.current)
        except ValueError as exc:
            self._error(str(exc))
            return
        if mode == "path" and path.is_file():
            self._navigate("path", path.parent, select=path.name)
            return
        self._navigate(mode, path)

    def _on_activated(self, _view, tree_path, _column) -> None:
        iterator = self.store.get_iter(tree_path)
        path = Path(self.store.get_value(iterator, 4))
        is_dir = bool(self.store.get_value(iterator, 5))
        if is_dir:
            self._navigate("path", path)
            return
        self._open_file(path)

    def _open_file(self, path: Path) -> None:
        try:
            launched = Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)
        except GLib.Error as exc:
            self._error(str(exc))
            return
        if not launched:
            self._error(f"No hay una aplicación para abrir {path.name}")

    def _on_place(self, _box, row: Gtk.ListBoxRow) -> None:
        kind = str(getattr(row, "place_kind", ""))
        if kind == "trash":
            self._navigate("trash", Path.home() / ".local" / "share" / "Trash" / "files")
            return
        if kind.startswith("path:"):
            self._navigate("path", Path(kind.removeprefix("path:")))

    def _refresh_places(self) -> None:
        for child in list(self.places.get_children()):
            self.places.remove(child)
        for label, path in user_places():
            self._add_place(label, f"path:{path}", "folder")
        for label, path in _mounted_places():
            self._add_place(label, f"path:{path}", "drive-harddisk")
        self._add_place("Papelera", "trash", "user-trash")
        self.places.show_all()
        self._mark_place()

    def _add_place(self, label: str, kind: str, icon: str) -> None:
        row = Gtk.ListBoxRow()
        row.place_kind = kind  # type: ignore[attr-defined]
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
        text = Gtk.Label(label=label)
        text.set_xalign(0)
        box.pack_start(text, True, True, 0)
        row.add(box)
        self.places.add(row)

    def _mark_place(self) -> None:
        target = "trash" if self.mode == "trash" else f"path:{self.current}"
        for row in self.places.get_children():
            if getattr(row, "place_kind", "") == target:
                self.places.select_row(row)
                return
        self.places.unselect_all()

    def _on_button_press(self, widget: Gtk.TreeView, event: Gdk.EventButton) -> bool:
        if event.button != 3:
            return False
        found = widget.get_path_at_pos(int(event.x), int(event.y))
        if found is not None:
            tree_path = found[0]
            selection = widget.get_selection()
            if not selection.path_is_selected(tree_path):
                selection.unselect_all()
                selection.select_path(tree_path)
        self._popup(event)
        return True

    def _popup(self, event: Gdk.EventButton) -> None:
        menu = Gtk.Menu()
        rows = self._selected_rows()
        actions = [("Abrir", self._open_selected)]
        if self.mode == "trash":
            actions.append(("Restaurar", self._restore_selected))
        else:
            actions.extend(
                [
                    ("Copiar", self._copy),
                    ("Cortar", self._cut),
                    ("Pegar", self._paste),
                    ("Renombrar", self._rename),
                    ("Nueva carpeta", self._new_folder),
                    ("Mover a la papelera", self._trash_selected),
                ]
            )
        actions.append(("Eliminar", self._delete_selected))
        if len(rows) == 1:
            actions.append(("Propiedades", self._properties))
        for label, handler in actions:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _item, callback=handler: callback())
            menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(event)

    def _open_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        path = Path(str(rows[0]["path"]))
        if rows[0]["is_dir"]:
            self._navigate("path", path)
            return
        self._open_file(path)

    def _copy(self) -> None:
        rows = self._selected_rows()
        if rows:
            self.clipboard = [Path(str(row["path"])) for row in rows]
            self.clipboard_mode = "copy"

    def _cut(self) -> None:
        rows = self._selected_rows()
        if rows:
            self.clipboard = [Path(str(row["path"])) for row in rows]
            self.clipboard_mode = "cut"

    def _paste(self) -> None:
        if self.mode == "trash":
            self._error("No se puede pegar en la papelera")
            return
        if not self.clipboard or not self.clipboard_mode:
            return
        errors: list[str] = []
        for src in list(self.clipboard):
            try:
                if self.clipboard_mode == "cut":
                    move_entry(src, self.current)
                else:
                    copy_entry(src, self.current)
            except (OSError, ValueError) as exc:
                errors.append(f"{src.name}: {exc}")
        if self.clipboard_mode == "cut":
            self.clipboard = []
            self.clipboard_mode = None
        self._reload()
        if errors:
            self._error("\n".join(errors))

    def _rename(self) -> None:
        rows = self._selected_rows()
        if len(rows) != 1 or self.mode == "trash":
            return
        current = str(rows[0]["name"])
        name = self._prompt("Renombrar", "Nombre nuevo", current)
        if name is None or name == current:
            return
        try:
            renamed = rename_entry(Path(str(rows[0]["path"])), name)
        except (OSError, ValueError) as exc:
            self._error(str(exc))
            return
        self._pending_select = renamed.name
        self._reload()

    def _new_folder(self) -> None:
        if self.mode == "trash":
            self._error("No se pueden crear carpetas en la papelera")
            return
        name = self._prompt("Nueva carpeta", "Nombre de la carpeta", "Carpeta nueva")
        if name is None:
            return
        try:
            created = make_directory(self.current, name)
        except (OSError, ValueError) as exc:
            self._error(str(exc))
            return
        self._pending_select = created.name
        self._reload()

    def _trash_selected(self) -> None:
        rows = self._selected_rows()
        if not rows or self.mode == "trash":
            return
        errors: list[str] = []
        for row in rows:
            try:
                move_to_trash(Path(str(row["path"])))
            except (OSError, ValueError) as exc:
                errors.append(f"{row['name']}: {exc}")
        self._reload()
        if errors:
            self._error("\n".join(errors))

    def _restore_selected(self) -> None:
        rows = self._selected_rows()
        errors: list[str] = []
        for row in rows:
            trash_name = str(row["trash_name"])
            if not trash_name:
                continue
            try:
                restore_trash(trash_name)
            except (OSError, ValueError) as exc:
                errors.append(f"{row['name']}: {exc}")
        self._reload()
        if errors:
            self._error("\n".join(errors))

    def _delete_selected(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        names = ", ".join(str(row["name"]) for row in rows[:6])
        if len(rows) > 6:
            names += "…"
        if not self._confirm(f"Eliminar de forma permanente:\n{names}"):
            return
        errors: list[str] = []
        for row in rows:
            try:
                if self.mode == "trash" and row["trash_name"]:
                    delete_trash_item(str(row["trash_name"]))
                else:
                    delete_path(Path(str(row["path"])))
            except (OSError, ValueError) as exc:
                errors.append(f"{row['name']}: {exc}")
        self._reload()
        if errors:
            self._error("\n".join(errors))

    def _properties(self) -> None:
        rows = self._selected_rows()
        if len(rows) != 1:
            return
        row = rows[0]
        path = Path(str(row["path"]))
        kind = "Carpeta" if row["is_dir"] else (path.suffix or "Archivo")
        origin = f"\nOrigen: {row['origin']}" if row["origin"] else ""
        size = "—" if row["is_dir"] else human_size(path.stat().st_size if path.exists() else None)
        self._info(f"{row['name']}\nTipo: {kind}\nTamaño: {size}\nRuta: {path}{origin}")

    def _on_key(self, _widget, event: Gdk.EventKey) -> bool:
        key = Gdk.keyval_name(event.keyval) or ""
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(event.state & Gdk.ModifierType.MOD1_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        focus = self.get_focus()
        editing = focus in {self.path_entry, self.search}
        if editing:
            if key == "Escape":
                self.view.grab_focus()
                return True
            return False
        if alt and key == "Left":
            self._back()
            return True
        if alt and key == "Right":
            self._forward()
            return True
        if alt and key == "Up":
            self._up()
            return True
        if key in {"BackSpace", "Back"}:
            self._up()
            return True
        if ctrl and key in {"l", "L"}:
            self.path_entry.grab_focus()
            return True
        if ctrl and key in {"f", "F"}:
            self.search.grab_focus()
            return True
        if ctrl and key in {"h", "H"}:
            self.hidden_button.set_active(not self.hidden_button.get_active())
            return True
        if ctrl and key in {"c", "C"}:
            self._copy()
            return True
        if ctrl and key in {"x", "X"}:
            self._cut()
            return True
        if ctrl and key in {"v", "V"}:
            self._paste()
            return True
        if key == "F2":
            self._rename()
            return True
        if key == "F5":
            self._refresh_places()
            self._reload()
            return True
        if key in {"Return", "KP_Enter"}:
            self._open_selected()
            return True
        if key in {"Delete", "KP_Delete"} and shift:
            self._delete_selected()
            return True
        if key in {"Delete", "KP_Delete"}:
            if self.mode == "trash":
                self._delete_selected()
            else:
                self._trash_selected()
            return True
        return False

    def _prompt(self, title: str, label: str, text: str) -> str | None:
        dialog = Gtk.Dialog(title=title, transient_for=self, flags=0)
        dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        dialog.add_button("Aceptar", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.set_border_width(12)
        box.set_spacing(8)
        box.add(Gtk.Label(label=label))
        entry = Gtk.Entry()
        entry.set_text(text)
        entry.set_activates_default(True)
        box.add(entry)
        dialog.set_default_size(360, 120)
        dialog.show_all()
        response = dialog.run()
        value = entry.get_text()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return None
        return value

    def _confirm(self, text: str) -> bool:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=text,
        )
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def _error(self, text: str) -> None:
        self._message(text, Gtk.MessageType.ERROR)

    def _info(self, text: str) -> None:
        self._message(text, Gtk.MessageType.INFO)

    def _message(self, text: str, kind: Gtk.MessageType) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=kind,
            buttons=Gtk.ButtonsType.CLOSE,
            text=text,
        )
        dialog.run()
        dialog.destroy()


def _mounted_places() -> list[tuple[str, Path]]:
    places: list[tuple[str, Path]] = []
    try:
        monitor = Gio.VolumeMonitor.get()
        mounts = monitor.get_mounts()
    except Exception:
        return places
    home = str(Path.home())
    for mount in mounts:
        root = mount.get_root()
        if root is None:
            continue
        location = root.get_path()
        if not location or location in {"/", home, "/home"}:
            continue
        name = mount.get_name() or location
        places.append((name, Path(location)))
    return places


def run(locations: list[str] | None = None) -> int:
    _install_style()
    mode, path, select = resolve_start(locations)
    if mode == "path" and not path.is_dir():
        path = Path.home()
        select = None
    window = ExplorerWindow(path, mode=mode, select=select)
    window.connect("destroy", Gtk.main_quit)
    window.show_all()
    Gtk.main()
    return 0
