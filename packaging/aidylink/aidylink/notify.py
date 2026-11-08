"""Desktop notifications via FreeDesktop Notifications (Jugoo host)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading

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
        # Keep the notification action alive asynchronously. Clicking it opens
        # the native chat window while the background daemon continues polling.
        proc = subprocess.Popen(
            [binary, "-a", "AidyChat", "-u", urgency, "-A", "open=Abrir AidyChat", title, body],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        threading.Thread(target=_open_on_action, args=(proc,), daemon=True).start()
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _open_on_action(proc: subprocess.Popen[bytes]) -> None:
    try:
        if proc.communicate()[0] == b"open\n":
            subprocess.Popen(
                ["/usr/local/bin/aidylink", "ui"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=os.environ.copy(),
            )
    except OSError:
        LOGGER.debug("could not open AidyChat from notification", exc_info=True)


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
