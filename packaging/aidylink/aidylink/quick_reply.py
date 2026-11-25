"""Small reply prompt launched by a notification action."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .cloud import AidyChatBridge
from .config import load_config


def run_quick_reply(chat_id: int, sender: str, preview: str) -> int:
    cfg = load_config()
    if not cfg or not cfg.cloud.enabled:
        return 1

    dialog = Gtk.Dialog(title=f"Responder a {sender or 'AidyChat'}")
    dialog.set_wmclass("aidychat-reply", "AidyChatReply")
    dialog.set_default_size(390, 190)
    dialog.set_border_width(12)
    dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
    send_button = dialog.add_button("Enviar", Gtk.ResponseType.OK)
    send_button.set_can_default(True)
    dialog.set_default_response(Gtk.ResponseType.OK)

    box = dialog.get_content_area()
    box.set_spacing(8)
    if preview:
        label = Gtk.Label(label=preview, xalign=0)
        label.set_line_wrap(True)
        label.set_max_width_chars(56)
        box.pack_start(label, False, False, 0)
    entry = Gtk.Entry()
    entry.set_placeholder_text("Escribe una respuesta")
    entry.set_activates_default(True)
    box.pack_start(entry, False, False, 0)
    status = Gtk.Label(xalign=0)
    box.pack_start(status, False, False, 0)
    dialog.show_all()

    result = 1
    while True:
        response = dialog.run()
        text = entry.get_text().strip()
        if response != Gtk.ResponseType.OK:
            break
        if not text:
            status.set_text("Escribe un mensaje antes de enviarlo.")
            continue
        try:
            AidyChatBridge(cfg).send_chat_message(int(chat_id), text)
        except Exception as exc:
            status.set_text(f"No se pudo enviar: {exc}")
            continue
        result = 0
        break

    dialog.destroy()
    return result
