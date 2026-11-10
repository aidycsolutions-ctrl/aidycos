"""Browser based Google sign-in handoff for the native AidyChat client."""

from __future__ import annotations

import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .cloud import AidyChatBridge
from .config import LinkConfig, save_config

DEFAULT_BASE_URL = "https://www.aidycsolutions.com"
LOGIN_URL = DEFAULT_BASE_URL + "/aidychat/loginchat"


def start_google_login(
    cfg: LinkConfig,
    on_done: Callable[[str | None, Exception | None], None],
) -> None:
    """Open AidyChat's Google login in the default browser and accept its token.

    The short-lived localhost listener accepts one GET or POST with a random
    state value. It never binds to the LAN interface. GET is preferred because
    browsers often block HTTPS→HTTP form posts to loopback as private-network
    access, while a top-level redirect to 127.0.0.1 still works.
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
                token = (fields.get("token") or [""])[0].strip()
                if not secrets.compare_digest(received_state, state) or not token:
                    self.send_error(400, "Inicio de sesión inválido")
                    return
                cfg.cloud.base_url = DEFAULT_BASE_URL
                cfg.cloud.bearer_token = token
                cfg.cloud.enabled = True
                bridge = AidyChatBridge(cfg)
                session = bridge.check_session()
                user = session.get("user") if isinstance(session.get("user"), dict) else {}
                user_id = user.get("id") if session.get("authenticated") else None
                if user_id is None:
                    raise RuntimeError("AidyChat no devolvió la cuenta autenticada")
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
                self.send_error(400, "No se pudo validar la sesión de AidyChat")
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
        try:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            threading.Event().wait(0.05)
            if not webbrowser.open(login_url):
                result["error"] = RuntimeError("No se pudo abrir el navegador predeterminado")
            else:
                completed.wait(timeout=300)
                if not completed.is_set():
                    result["error"] = TimeoutError("El inicio de sesión expiró")
            error = result.get("error")
            on_done(
                None if isinstance(error, Exception) else str(result.get("username") or "AidyChat"),
                error if isinstance(error, Exception) else None,
            )
        finally:
            server.shutdown()
            server.server_close()

    threading.Thread(target=wait_for_login, daemon=True, name="aidychat-google-login").start()
