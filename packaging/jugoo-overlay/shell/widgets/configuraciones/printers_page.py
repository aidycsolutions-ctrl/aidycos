"""Printer manager page for Configuraciones → Impresoras."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk, Pango

from ...servicios.impresoras import (
    PrinterInfo,
    PrintersError,
    PrintersSnapshot,
    cancel_jobs,
    default_catalog_path,
    enable_lan_sharing,
    export_share_catalog,
    import_share_catalog,
    is_directly_shareable_uri,
    is_local_uri,
    launch_cups_web,
    launch_printer_manager,
    list_printers,
    set_default_printer,
    set_printer_enabled,
    shareable_entries,
)


def build_printers_page() -> Gtk.Widget:
    """Build the Impresoras manager. Reloads CUPS state on demand."""
    page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    page.get_style_context().add_class("settings-page")
    page.get_style_context().add_class("settings-printers-page")

    heading = Gtk.Label(label="Impresoras", xalign=0)
    heading.get_style_context().add_class("settings-page-title")
    page.pack_start(heading, False, False, 0)

    sub = Gtk.Label(
        label=(
            "Gestiona impresoras locales, exporta un catálogo AidyCOS para otros PCs "
            "e importa el mismo archivo en cada equipo."
        ),
        xalign=0,
    )
    sub.get_style_context().add_class("settings-page-subtitle")
    sub.set_line_wrap(True)
    page.pack_start(sub, False, False, 0)

    toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    toolbar.get_style_context().add_class("settings-printers-toolbar")
    toolbar.set_homogeneous(False)

    refresh_btn = Gtk.Button(label="Actualizar")
    refresh_btn.get_style_context().add_class("settings-browse-button")
    refresh_btn.set_tooltip_text("Volver a leer el estado de CUPS")
    toolbar.pack_start(refresh_btn, False, False, 0)

    manage_btn = Gtk.Button(label="Abrir gestor")
    manage_btn.get_style_context().add_class("settings-browse-button")
    manage_btn.set_tooltip_text("Abrir system-config-printer para añadir o configurar")
    toolbar.pack_start(manage_btn, False, False, 0)

    cups_btn = Gtk.Button(label="CUPS web")
    cups_btn.get_style_context().add_class("settings-browse-button")
    cups_btn.set_tooltip_text("Abrir la interfaz web de CUPS (localhost:631)")
    toolbar.pack_start(cups_btn, False, False, 0)

    page.pack_start(toolbar, False, False, 0)

    share_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    share_bar.get_style_context().add_class("settings-printers-toolbar")

    export_btn = Gtk.Button(label="Exportar catálogo…")
    export_btn.get_style_context().add_class("settings-browse-button")
    export_btn.set_tooltip_text(
        "Guardar las impresoras de red en un JSON para otros PCs AidyCOS"
    )
    share_bar.pack_start(export_btn, False, False, 0)

    import_btn = Gtk.Button(label="Importar catálogo…")
    import_btn.get_style_context().add_class("settings-browse-button")
    import_btn.set_tooltip_text(
        "Leer un catálogo AidyCOS y añadir esas impresoras en este equipo"
    )
    share_bar.pack_start(import_btn, False, False, 0)

    share_local_btn = Gtk.Button(label="Compartir locales en LAN")
    share_local_btn.get_style_context().add_class("settings-browse-button")
    share_local_btn.set_tooltip_text(
        "Activa CUPS sharing para impresoras USB/locales y las incluye al exportar"
    )
    share_bar.pack_start(share_local_btn, False, False, 0)

    page.pack_start(share_bar, False, False, 0)

    include_local = Gtk.CheckButton(label="Al exportar, incluir locales vía este PC")
    include_local.set_tooltip_text(
        "Convierte colas USB/locales en ipp://este-pc/printers/NOMBRE (requiere "
        "«Compartir locales en LAN»)."
    )
    page.pack_start(include_local, False, False, 0)

    status = Gtk.Label(xalign=0)
    status.get_style_context().add_class("settings-page-note")
    status.set_line_wrap(True)
    page.pack_start(status, False, False, 0)

    list_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    list_host.get_style_context().add_class("settings-printers-list")
    page.pack_start(list_host, True, True, 0)

    def set_status(message: str) -> None:
        status.set_text(message)

    def parent_window() -> Gtk.Window | None:
        top = page.get_toplevel()
        return top if isinstance(top, Gtk.Window) else None

    def reload(*_args) -> None:
        snapshot = list_printers()
        _rebuild_list(list_host, snapshot, set_status, reload)
        if snapshot.error:
            set_status(snapshot.error)
        elif not snapshot.printers:
            set_status("No hay impresoras configuradas. Usa «Abrir gestor» para añadir una.")
        else:
            default = snapshot.default_name or "ninguna"
            network = sum(
                1 for item in snapshot.printers if is_directly_shareable_uri(item.device_uri)
            )
            set_status(
                f"{len(snapshot.printers)} impresora(s) ({network} de red). "
                f"Predeterminada: {default}."
            )

    def notify(message: str, *, error: bool = False, popup: bool = False) -> None:
        set_status(message)
        # Popups only when asked (import result / errors). Avoid stacking them
        # on top of the file chooser during export success.
        if error or popup:
            _show_message(parent_window(), message, error=error)

    def on_manage(_btn: Gtk.Button) -> None:
        try:
            launch_printer_manager()
            set_status("Se abrió el gestor de impresoras del sistema.")
        except PrintersError as error:
            notify(str(error), error=True)

    def on_cups(_btn: Gtk.Button) -> None:
        try:
            launch_cups_web()
            set_status("Se abrió la interfaz web de CUPS.")
        except PrintersError as error:
            notify(str(error), error=True)

    def on_export(_btn: Gtk.Button) -> None:
        try:
            entries = shareable_entries(
                include_local_via_cups=include_local.get_active()
            )
        except PrintersError as error:
            notify(str(error), error=True)
            return
        if not entries:
            notify(
                "No hay impresoras compartibles. La Wi‑Fi de red se exporta sola; "
                "USB/localhost necesitan «Compartir locales en LAN».",
                error=True,
            )
            return
        chosen = _choose_catalog_path(
            parent_window(),
            title="Exportar catálogo de impresoras AidyCOS",
            action=Gtk.FileChooserAction.SAVE,
            suggest=str(default_catalog_path()),
        )
        if not chosen:
            return
        try:
            path = export_share_catalog(
                chosen,
                include_local_via_cups=include_local.get_active(),
            )
            # Keep a local copy under ~/.local/share/aidycos for convenience.
            try:
                export_share_catalog(
                    default_catalog_path(),
                    include_local_via_cups=include_local.get_active(),
                )
            except PrintersError:
                pass
            names = ", ".join(item.name for item in entries)
            notify(
                f"Catálogo exportado ({len(entries)}): {names}\nGuardado en:\n{path}"
            )
        except PrintersError as error:
            notify(str(error), error=True)

    def on_import(_btn: Gtk.Button) -> None:
        default = default_catalog_path()
        suggest = str(default if default.is_file() else Path.home())
        chosen = _choose_catalog_path(
            parent_window(),
            title="Importar catálogo de impresoras AidyCOS",
            action=Gtk.FileChooserAction.OPEN,
            suggest=suggest,
        )
        if not chosen:
            notify(
                "No se eligió ningún catálogo JSON. Vuelve a Importar y pulsa Abrir.",
                error=True,
            )
            return
        try:
            result = import_share_catalog(chosen)
            parts = [f"Archivo: {chosen}"]
            if result.added:
                parts.append(f"Añadidas: {', '.join(result.added)}")
            if result.updated:
                parts.append(f"Actualizadas: {', '.join(result.updated)}")
            if result.skipped:
                parts.append(
                    "Ya estaban en este PC (no hace falta reimportarlas): "
                    + ", ".join(result.skipped)
                )
            if result.default_set:
                parts.append(f"Predeterminada: {result.default_set}")
            if not (result.added or result.updated or result.skipped):
                parts.append("El JSON no trajo impresoras nuevas.")
            notify("\n".join(parts), popup=True)
            reload()
        except PrintersError as error:
            notify(f"Al leer {chosen}:\n{error}", error=True)

    def on_share_local(_btn: Gtk.Button) -> None:
        try:
            enable_lan_sharing()
            include_local.set_active(True)
            notify(
                "Compartido CUPS activado para impresoras locales. "
                "Vuelve a exportar el catálogo para incluir USB/localhost."
            )
        except PrintersError as error:
            notify(str(error), error=True)

    refresh_btn.connect("clicked", reload)
    manage_btn.connect("clicked", on_manage)
    cups_btn.connect("clicked", on_cups)
    export_btn.connect("clicked", on_export)
    import_btn.connect("clicked", on_import)
    share_local_btn.connect("clicked", on_share_local)
    reload()
    return page


def _flush_gtk() -> None:
    """Let Wayland/Hyprland finish unmapping dialogs before the next one."""
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def _show_message(parent: Gtk.Window | None, message: str, *, error: bool = False) -> None:
    # Avoid transient_for layer-shell parents: those dialogs often stick on Hyprland.
    dialog = Gtk.MessageDialog(
        transient_for=None,
        flags=0,
        message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO,
        buttons=Gtk.ButtonsType.OK,
        text="Impresoras" if not error else "No se pudo completar",
    )
    dialog.set_modal(True)
    if parent is not None:
        try:
            dialog.set_transient_for(None)
        except Exception:
            pass
    dialog.format_secondary_text(message)
    dialog.connect("response", lambda d, _r: d.hide())
    dialog.run()
    dialog.hide()
    dialog.destroy()
    _flush_gtk()


def _native_dialog_path(dialog: Gtk.FileChooserNative) -> str | None:
    """Resolve the chosen path from a native/portal file chooser."""
    filename = dialog.get_filename()
    if filename:
        return filename
    gio_file = dialog.get_file()
    if gio_file is not None:
        path = gio_file.get_path()
        if path:
            return path
        uri = gio_file.get_uri()
        if uri and uri.startswith("file://"):
            from urllib.parse import unquote, urlparse

            return unquote(urlparse(uri).path)
    return None


def _choose_catalog_path(
    parent: Gtk.Window | None,
    *,
    title: str,
    action: Gtk.FileChooserAction,
    suggest: str,
) -> Path | None:
    # Native chooser closes cleanly on Wayland; FileChooserDialog often sticks
    # when the parent is a Jugoo layer-shell settings window.
    accept_label = "Guardar" if action == Gtk.FileChooserAction.SAVE else "Abrir"
    dialog = Gtk.FileChooserNative.new(
        title,
        None,
        action,
        accept_label,
        "Cancelar",
    )
    dialog.set_modal(True)
    filt = Gtk.FileFilter()
    filt.set_name("Catálogo AidyCOS (*.json)")
    filt.add_pattern("*.json")
    dialog.add_filter(filt)
    all_filt = Gtk.FileFilter()
    all_filt.set_name("Todos los archivos")
    all_filt.add_pattern("*")
    dialog.add_filter(all_filt)
    suggest_path = Path(suggest).expanduser()
    if action == Gtk.FileChooserAction.SAVE:
        dialog.set_do_overwrite_confirmation(True)
        if suggest_path.parent.is_dir():
            dialog.set_current_folder(str(suggest_path.parent))
        dialog.set_current_name(suggest_path.name or "shared-printers.json")
    else:
        if suggest_path.is_file():
            dialog.set_filename(str(suggest_path))
            folder = suggest_path.parent
            if folder.is_dir():
                dialog.set_current_folder(str(folder))
        elif suggest_path.is_dir():
            dialog.set_current_folder(str(suggest_path))

    response = dialog.run()
    chosen = (
        _native_dialog_path(dialog)
        if response in (Gtk.ResponseType.OK, Gtk.ResponseType.ACCEPT)
        else None
    )
    dialog.destroy()
    _flush_gtk()
    if not chosen:
        return None
    path = Path(chosen)
    if action == Gtk.FileChooserAction.SAVE and path.suffix.casefold() != ".json":
        path = path.with_suffix(".json")
    return path


def _rebuild_list(
    host: Gtk.Box,
    snapshot: PrintersSnapshot,
    set_status,
    reload,
) -> None:
    for child in list(host.get_children()):
        host.remove(child)

    if not snapshot.printers:
        empty = Gtk.Label(label="Sin impresoras detectadas.", xalign=0)
        empty.get_style_context().add_class("settings-page-note")
        host.pack_start(empty, False, False, 0)
        host.show_all()
        return

    for printer in snapshot.printers:
        host.pack_start(_printer_row(printer, set_status, reload), False, False, 0)
    host.show_all()


def _printer_row(printer: PrinterInfo, set_status, reload) -> Gtk.Widget:
    row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    row.get_style_context().add_class("settings-printer-row")

    top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    title = Gtk.Label(xalign=0)
    title.set_markup(_title_markup(printer))
    title.set_hexpand(True)
    title.set_ellipsize(Pango.EllipsizeMode.END)
    top.pack_start(title, True, True, 0)

    if printer.is_default:
        badge = Gtk.Label(label="Predeterminada")
        badge.get_style_context().add_class("settings-page-note")
        top.pack_end(badge, False, False, 0)
    row.pack_start(top, False, False, 0)

    detail = Gtk.Label(xalign=0)
    detail.set_text(_detail_text(printer))
    detail.get_style_context().add_class("settings-page-note")
    detail.set_line_wrap(True)
    row.pack_start(detail, False, False, 0)

    actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    actions.set_halign(Gtk.Align.START)

    if not printer.is_default:
        default_btn = Gtk.Button(label="Usar por defecto")
        default_btn.get_style_context().add_class("settings-browse-button")
        default_btn.connect(
            "clicked",
            lambda _b, name=printer.name: _safe_action(
                lambda: set_default_printer(name),
                set_status,
                reload,
                ok_message=f"«{name}» es ahora la predeterminada.",
            ),
        )
        actions.pack_start(default_btn, False, False, 0)

    toggle_label = "Desactivar" if printer.enabled else "Activar"
    toggle_btn = Gtk.Button(label=toggle_label)
    toggle_btn.get_style_context().add_class("settings-browse-button")
    toggle_btn.connect(
        "clicked",
        lambda _b, name=printer.name, enabled=not printer.enabled: _safe_action(
            lambda: set_printer_enabled(name, enabled),
            set_status,
            reload,
            ok_message=(
                f"Impresora «{name}» activada."
                if enabled
                else f"Impresora «{name}» desactivada."
            ),
        ),
    )
    actions.pack_start(toggle_btn, False, False, 0)

    clear_btn = Gtk.Button(label="Vaciar cola")
    clear_btn.get_style_context().add_class("settings-browse-button")
    clear_btn.set_tooltip_text("Cancelar todos los trabajos de esta impresora")
    clear_btn.connect(
        "clicked",
        lambda _b, name=printer.name: _safe_action(
            lambda: cancel_jobs(name),
            set_status,
            reload,
            ok_message=f"Cola de «{name}» vaciada.",
        ),
    )
    actions.pack_start(clear_btn, False, False, 0)

    row.pack_start(actions, False, False, 0)
    return row


def _safe_action(action, set_status, reload, *, ok_message: str) -> None:
    try:
        action()
        set_status(ok_message)
        reload()
    except PrintersError as error:
        set_status(str(error))


def _title_markup(printer: PrinterInfo) -> str:
    name = _escape(printer.name)
    if printer.enabled:
        return f"<b>{name}</b>"
    return f"<b>{name}</b> <i>(desactivada)</i>"


def _detail_text(printer: PrinterInfo) -> str:
    parts = [printer.state_text]
    if not printer.accepting:
        parts.append("No acepta trabajos")
    if is_directly_shareable_uri(printer.device_uri):
        parts.append("Red (exportable)")
    elif is_local_uri(printer.device_uri) or printer.device_uri:
        parts.append("Local (comparte en LAN para exportar)")
    if printer.device_uri:
        parts.append(printer.device_uri)
    return " · ".join(part for part in parts if part)


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
