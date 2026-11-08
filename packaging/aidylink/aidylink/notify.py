"""Desktop notifications via FreeDesktop Notifications (Jugoo host)."""

from __future__ import annotations

import logging
import shutil
import subprocess

LOGGER = logging.getLogger(__name__)


def notify(title: str, body: str, *, urgency: str = "normal") -> None:
    title = (title or "AidyLink")[:80]
    body = (body or "")[:240]
    if _notify_send(title, body, urgency=urgency):
        return
    if _gdbus(title, body):
        return
    LOGGER.info("notify: %s — %s", title, body)


def _notify_send(title: str, body: str, *, urgency: str) -> bool:
    binary = shutil.which("notify-send")
    if not binary:
        return False
    try:
        subprocess.run(
            [binary, "-a", "AidyLink", "-u", urgency, title, body],
            check=False,
            timeout=3,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _gdbus(title: str, body: str) -> bool:
    binary = shutil.which("gdbus")
    if not binary:
        return False
    # org.freedesktop.Notifications.Notify
    try:
        subprocess.run(
            [
                binary,
                "call",
                "--session",
                "--dest",
                "org.freedesktop.Notifications",
                "--object-path",
                "/org/freedesktop/Notifications",
                "--method",
                "org.freedesktop.Notifications.Notify",
                "AidyLink",
                "0",
                "dialog-information",
                title,
                body,
                "[]",
                "{}",
                "5000",
            ],
            check=False,
            timeout=3,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False
