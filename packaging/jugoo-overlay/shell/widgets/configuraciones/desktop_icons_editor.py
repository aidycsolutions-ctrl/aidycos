def _desktop_icons_editor(manager: SettingsManager) -> Gtk.Widget:
    """Minimal create/list/delete UI for desktop shortcuts (does not delete targets)."""
    from ...actions import known_action_names
    from ...servicios.escritorio.desktop_icons.model import CREATABLE_TYPES

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.get_style_context().add_class("settings-desktop-icons")

    title = Gtk.Label(label="Iconos del escritorio", xalign=0)
    title.get_style_context().add_class("settings-row-title")
    box.pack_start(title, False, False, 0)

    hint = Gtk.Label(
        label=(
            "Crear accesos (aplicación / archivo / carpeta / acción Jugoo). "
            "Eliminar un icono no borra la app ni el archivo original. "
            "Doble clic abre; arrastrar mueve; la posición se guarda al soltar."
        ),
        xalign=0,
    )
    hint.get_style_context().add_class("settings-row-desc")
    hint.set_line_wrap(True)
    box.pack_start(hint, False, False, 0)

    status = Gtk.Label(xalign=0)
    status.get_style_context().add_class("settings-page-note")
    status.set_line_wrap(True)
    box.pack_start(status, False, False, 0)

    form = Gtk.Grid()
    form.set_column_spacing(8)
    form.set_row_spacing(6)
    form.get_style_context().add_class("settings-desktop-icons-form")

    name_entry = Gtk.Entry()
    name_entry.set_placeholder_text("Nombre")
    type_combo = Gtk.ComboBoxText()
    type_labels = {
        "application": "Aplicación (.desktop id)",
        "file": "Archivo (ruta absoluta)",
        "directory": "Carpeta (ruta absoluta)",
        "action": "Acción Jugoo",
    }
    for kind in CREATABLE_TYPES:
        type_combo.append(kind, type_labels.get(kind, kind))
    type_combo.set_active_id("application")
    target_entry = Gtk.Entry()
    target_entry.set_placeholder_text("firefox /ruta /jugoo-action")
    icon_entry = Gtk.Entry()
    icon_entry.set_placeholder_text("Icono (opcional)")

    form.attach(Gtk.Label(label="Nombre", xalign=0), 0, 0, 1, 1)
    form.attach(name_entry, 1, 0, 1, 1)
    form.attach(Gtk.Label(label="Tipo", xalign=0), 0, 1, 1, 1)
    form.attach(type_combo, 1, 1, 1, 1)
    form.attach(Gtk.Label(label="Destino", xalign=0), 0, 2, 1, 1)
    form.attach(target_entry, 1, 2, 1, 1)
    form.attach(Gtk.Label(label="Icono", xalign=0), 0, 3, 1, 1)
    form.attach(icon_entry, 1, 3, 1, 1)
    box.pack_start(form, False, False, 0)

    actions_hint = Gtk.Label(
        label="Acciones Jugoo: " + ", ".join(known_action_names()[:8]) + "…",
        xalign=0,
    )
    actions_hint.get_style_context().add_class("settings-row-desc")
    actions_hint.set_line_wrap(True)
    box.pack_start(actions_hint, False, False, 0)

    add_button = Gtk.Button(label="Crear acceso directo")
    add_button.get_style_context().add_class("settings-browse-button")
    add_button.set_halign(Gtk.Align.START)
    box.pack_start(add_button, False, False, 0)

    list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    list_box.get_style_context().add_class("settings-desktop-icons-list")
    box.pack_start(list_box, False, False, 0)

    def _service():
        return getattr(manager, "desktop_icons", None)

    def _set_status(message: str) -> None:
        status.set_text(message)

    def _rebuild_list() -> None:
        for child in list(list_box.get_children()):
            list_box.remove(child)
        service = _service()
        if service is None:
            empty = Gtk.Label(
                label="El servicio de iconos no está disponible (¿Jugoo reiniciado?).",
                xalign=0,
            )
            empty.get_style_context().add_class("settings-row-desc")
            list_box.pack_start(empty, False, False, 0)
            list_box.show_all()
            return
        shortcuts = service.shortcuts
        if not shortcuts:
            empty = Gtk.Label(label="Sin iconos todavía.", xalign=0)
            empty.get_style_context().add_class("settings-row-desc")
            list_box.pack_start(empty, False, False, 0)
        for shortcut in shortcuts:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            label = Gtk.Label(
                label=f"{shortcut.name} · {shortcut.type} · {shortcut.target}",
                xalign=0,
            )
            try:
                from gi.repository import Pango

                label.set_ellipsize(Pango.EllipsizeMode.END)
            except Exception:
                pass
            label.set_hexpand(True)
            row.pack_start(label, True, True, 0)
            remove = Gtk.Button(label="Eliminar")
            remove.get_style_context().add_class("settings-browse-button")

            def _remove(_btn, shortcut_id=shortcut.id) -> None:
                svc = _service()
                if svc is not None and svc.remove(shortcut_id):
                    _set_status("Icono eliminado (el destino original no se tocó).")
                    _rebuild_list()

            remove.connect("clicked", _remove)
            row.pack_start(remove, False, False, 0)
            list_box.pack_start(row, False, False, 0)
        list_box.show_all()

    def _add(_btn) -> None:
        service = _service()
        if service is None:
            _set_status("Servicio de iconos no disponible.")
            return
        kind = type_combo.get_active_id() or "application"
        try:
            service.create(
                name=name_entry.get_text(),
                type=kind,  # type: ignore[arg-type]
                target=target_entry.get_text(),
                icon=icon_entry.get_text(),
            )
        except ValueError as error:
            _set_status(str(error))
            return
        name_entry.set_text("")
        target_entry.set_text("")
        icon_entry.set_text("")
        _set_status("Acceso creado en el escritorio.")
        _rebuild_list()

    add_button.connect("clicked", _add)
    _rebuild_list()
    return box
