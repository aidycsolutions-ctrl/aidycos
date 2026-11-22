"""Discreet PC identity on the left of the Jugoo bar (hostname + user tooltip)."""

from __future__ import annotations

import getpass
import os
import socket

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")

from gi.repository import Gtk, Pango

from ...ui.module import ShellModule


def _hostname() -> str:
    for getter in (
        lambda: socket.gethostname(),
        lambda: os.uname().nodename,
    ):
        try:
            name = (getter() or "").strip()
            if name and name != "localhost":
                return name.split(".")[0]
        except OSError:
            continue
    return "pc"


def _username() -> str:
    try:
        name = (getpass.getuser() or "").strip()
        if name:
            return name
    except Exception:
        pass
    return (os.environ.get("USER") or os.environ.get("LOGNAME") or "").strip() or "user"


class HostIdentityWidget(ShellModule):
    """Small hostname label so techs can tell which machine they are on."""

    def __init__(self) -> None:
        super().__init__("host-identity-widget", spacing=0)
        host = _hostname()
        user = _username()

        self._label = Gtk.Label(label=host)
        self._label.set_xalign(0.0)
        # Short hostnames must stay fully readable (no "AidyC…").
        self._label.set_ellipsize(Pango.EllipsizeMode.NONE)
        self._label.set_width_chars(len(host))
        self._label.get_style_context().add_class("host-identity-label")

        self.set_tooltip_text(f"{user}@{host}")
        self.set_hexpand(False)
        self.set_vexpand(False)
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.CENTER)
        self.pack_start(self._label, False, False, 0)
        self.show_all()
