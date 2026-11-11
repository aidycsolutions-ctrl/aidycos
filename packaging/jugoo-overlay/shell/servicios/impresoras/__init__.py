"""CUPS printer helpers for the Jugoo settings page."""

from .service import (
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

__all__ = [
    "PrinterInfo",
    "PrintersError",
    "PrintersSnapshot",
    "cancel_jobs",
    "launch_cups_web",
    "launch_printer_manager",
    "list_printers",
    "set_default_printer",
    "set_printer_enabled",
]
