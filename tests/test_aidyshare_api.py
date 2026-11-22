"""Unit tests for AidyShare helpers (no network)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging" / "aidyshare"))

from aidyshare.api import ApiError, ShareClient  # noqa: E402
from aidyshare.config import ShareConfig, ShareSession, load_session, save_session  # noqa: E402


class AidyshareApiTest(unittest.TestCase):
    def test_session_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import os

            os.environ["XDG_CONFIG_HOME"] = tmp
            session = ShareSession(
                token="abc",
                session_id="s1",
                usuario="demo",
                padre="negocio1",
                nombre="Demo",
            )
            save_session(session)
            again = load_session()
            self.assertTrue(again.ok)
            self.assertEqual(again.usuario, "demo")
            self.assertEqual(again.padre, "negocio1")

    def test_login_parses_token(self) -> None:
        client = ShareClient(ShareConfig())
        payload = {
            "success": True,
            "session_id": "sid-9",
            "data": {
                "usuario": "caja1",
                "nombre": "Caja",
                "padre": "acme",
                "tipo": "cajero",
                "token": "jwt-token",
                "expires": "2099-01-01T00:00:00",
            },
        }

        def fake_request(method, path, **kwargs):
            self.assertEqual(method, "POST")
            self.assertEqual(path, "/loginU2")
            return 200, payload

        with mock.patch.object(client, "_request", side_effect=fake_request):
            session = client.login("caja1", "secret")
        self.assertEqual(session.token, "jwt-token")
        self.assertEqual(session.padre, "acme")

    def test_upload_requires_file(self) -> None:
        client = ShareClient(ShareConfig(), ShareSession(token="t", usuario="u", padre="p"))
        with self.assertRaises(ApiError):
            client.upload_file(Path("/no/existe.pdf"), "AidyCOS-Backup")


if __name__ == "__main__":
    unittest.main()
