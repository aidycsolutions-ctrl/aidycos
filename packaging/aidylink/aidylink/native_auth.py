"""Browser based Google sign-in handoff for the native AidyChat client."""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .cloud import AidyChatBridge
from .config import LinkConfig, save_config

DEFAULT_BASE_URL = "https://www.aidycsolutions.com"
LOGIN_URL = DEFAULT_BASE_URL + "/aidychat/loginchat"


def open_login_url(url: str) -> bool:
    """Open a URL with the desktop handler. Prefer xdg-open over webbrowser.

    ``webbrowser.open`` often returns True without showing a window when called
    from a background thread under Wayland; ``xdg-open`` is what the DE expects.
    """
    env = os.environ.copy()
    # Ensure portals/compositor can see the session even if a parent stripped it.
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
        if key not in env and key in os.environ:
            env[key] = os.environ[key]

    candidates: list[list[str]] = []
    if shutil.which("xdg-open"):
        candidates.append(["xdg-open", url])
    if shutil.which("gio"):
        candidates.append(["gio", "open", url])
    for browser in ("firefox", "google-chrome", "chromium", "chromium-browser"):
        path = shutil.which(browser)
        if path:
            candidates.append([path, url])

    for cmd in candidates:
        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
            return True
        except OSError:
            continue
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


def start_google_login(
    cfg: LinkConfig,
    on_done: Callable[[str | None, Exception | None], None],
    *,
    on_ready: Callable[[str, bool], None] | None = None,
) -> None:
    """Open AidyChat's Google login in the default browser and accept its token.

    The short-lived localhost listener accepts one GET or POST with a random
    state value. It never binds to the LAN interface. GET is preferred because
    browsers often block HTTPS→HTTP form posts to loopback as private-network
    access, while a top-level redirect to 127.0.0.1 still works.

    ``on_ready(url, opened)`` is called once the login URL is known (ideally on
    the GTK main loop via the caller's GLib.idle_add wrapper).
    """
    state = secrets.token_urlsafe(32)
    completed = threading.Event()
    result: dict[str, str | Exception] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def _take_fields(self, fields: dict[str, list[str]]) -> None:
            if completed.is_set():
                self.send_error(404)
                return
            try:
                received_state = (fields.get("state") or [""])[0]
                # URLSearchParams / some browsers may turn '+' into spaces.
                token = (fields.get("token") or [""])[0].strip().replace(" ", "+")
                if not token:
                    self.send_error(400, "Falta el token de AidyChat")
                    return
                if (
                    not received_state
                    or len(received_state) != len(state)
                    or not secrets.compare_digest(received_state, state)
                ):
                    self.send_error(400, "Estado de inicio de sesión inválido")
                    return
                cfg.cloud.base_url = DEFAULT_BASE_URL
                cfg.cloud.bearer_token = token
                cfg.cloud.enabled = True
                bridge = AidyChatBridge(cfg)
                session = bridge.check_session()
                user = session.get("user") if isinstance(session.get("user"), dict) else {}
                user_id = user.get("id")
                if not session.get("authenticated") or user_id is None:
                    raise RuntimeError(
                        "El servidor no aceptó el token "
                        f"(authenticated={session.get('authenticated')!r}). "
                        "Vuelve a intentar el inicio de sesión."
                    )
                cfg.cloud.peer_user_ids["self"] = int(user_id)
                save_config(cfg)
                result["username"] = str(user.get("username") or "AidyChat")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(
                    "<!doctype html><meta charset='utf-8'><title>AidyChat</title>"
                    "<h2>Sesión iniciada</h2>"
                    "<p>Ya puedes volver a AidyChat. Esta pestaña se puede cerrar.</p>"
                    "<script>setTimeout(() => window.close(), 800);</script>".encode()
                )
                completed.set()
            except Exception as exc:
                result["error"] = exc
                detail = str(exc).strip() or exc.__class__.__name__
                # Keep message short enough for BaseHTTPRequestHandler status line.
                msg = f"No se pudo validar la sesión: {detail}"[:200]
                try:
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(
                        (
                            "<!doctype html><meta charset='utf-8'><title>AidyChat</title>"
                            "<h2>No se pudo validar la sesión</h2>"
                            f"<p>{detail}</p>"
                            "<p>Vuelve a AidyChat e inténtalo de nuevo.</p>"
                        ).encode("utf-8", errors="replace")
                    )
                except Exception:
                    try:
                        self.send_error(400, msg)
                    except Exception:
                        pass
                completed.set()

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/aidylink-auth" or completed.is_set():
                self.send_error(404)
                return
            fields = urllib.parse.parse_qs(parsed.query)
            self._take_fields(fields)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path != "/aidylink-auth" or completed.is_set():
                self.send_error(404)
                return
            length = min(int(self.headers.get("Content-Length", "0")), 8192)
            fields = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
            self._take_fields(fields)

        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CallbackHandler)
    server.daemon_threads = True
    server.timeout = 0.5
    callback = f"http://127.0.0.1:{server.server_port}/aidylink-auth"
    query = urllib.parse.urlencode({"native_callback": callback, "native_state": state})
    login_url = f"{LOGIN_URL}?{query}"

    def wait_for_login() -> None:
        opened = False
        try:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            time.sleep(0.05)

            # Prefer opening from the GTK main loop when available.
            open_done = threading.Event()

            def do_open() -> bool:
                nonlocal opened
                opened = open_login_url(login_url)
                if on_ready is not None:
                    on_ready(login_url, opened)
                open_done.set()
                return False

            try:
                from gi.repository import GLib  # type: ignore

                GLib.idle_add(do_open)
                open_done.wait(timeout=5.0)
                if not open_done.is_set():
                    do_open()
            except Exception:
                do_open()

            # Even if the auto-open failed, keep listening: the user can paste the URL.
            completed.wait(timeout=300)
            if not completed.is_set():
                result["error"] = TimeoutError(
                    "El inicio de sesión expiró. Si el navegador no abrió, usa el enlace mostrado."
                    if not opened
                    else "El inicio de sesión expiró"
                )
            error = result.get("error")
            on_done(
                None if isinstance(error, Exception) else str(result.get("username") or "AidyChat"),
                error if isinstance(error, Exception) else None,
            )
        finally:
            server.shutdown()
            server.server_close()

    threading.Thread(target=wait_for_login, daemon=True, name="aidychat-google-login").start()
