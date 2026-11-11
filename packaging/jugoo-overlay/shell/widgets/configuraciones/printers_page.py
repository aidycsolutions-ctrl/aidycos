"""Printer manager page for Configuraciones → Impresoras."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk, Pango

from ...servicios.impresoras import (
    PrinterInfo,
    PrintersError,
    PrintersSnapshot,
    cancel_jobs,
    launch_cups_web,
    launch_printer_manager,
    list_printers,
    set_default_printer,
    set_printer_enabled,
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
        label="Gestiona impresoras locales, la predeterminada y abre el gestor completo.",
        xalign=0,
    )
    sub.get_style_context().add_class("settings-page-subtitle")
    sub.set_line_wrap(True)
    page.pack_start(sub, False, False, 0)

    toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    toolbar.get_style_context().add_class("settings-printers-toolbar")

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

    status = Gtk.Label(xalign=0)
    status.get_style_context().add_class("settings-page-note")
    status.set_line_wrap(True)
    page.pack_start(status, False, False, 0)

    list_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    list_host.get_style_context().add_class("settings-printers-list")
    page.pack_start(list_host, True, True, 0)

    def set_status(message: str) -> None:
        status.set_text(message)

    def reload(*_args) -> None:
        snapshot = list_printers()
        _rebuild_list(list_host, snapshot, set_status, reload)
        if snapshot.error:
            set_status(snapshot.error)
        elif not snapshot.printers:
            set_status("No hay impresoras configuradas. Usa «Abrir gestor» para añadir una.")
        else:
            default = snapshot.default_name or "ninguna"
            set_status(
                f"{len(snapshot.printers)} impresora(s). Predeterminada: {default}."
            )

    def on_manage(_btn: Gtk.Button) -> None:
        try:
            launch_printer_manager()
            set_status("Se abrió el gestor de impresoras del sistema.")
        except PrintersError as error:
            set_status(str(error))

    def on_cups(_btn: Gtk.Button) -> None:
        try:
            launch_cups_web()
            set_status("Se abrió la interfaz web de CUPS.")
        except PrintersError as error:
            set_status(str(error))

    refresh_btn.connect("clicked", reload)
    manage_btn.connect("clicked", on_manage)
    cups_btn.connect("clicked", on_cups)
    reload()
    return page


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
    if printer.device_uri:
        parts.append(printer.device_uri)
    return " · ".join(part for part in parts if part)


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
