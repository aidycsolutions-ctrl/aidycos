"""Clipboard targets that should paste as a chat image."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging" / "aidylink"))

from aidylink.clipboard_image import image_file_from_uris, target_includes_image  # noqa: E402


class ClipboardImageTests(unittest.TestCase):
    def test_screenshot_mime_is_an_image(self) -> None:
        self.assertTrue(target_includes_image(["image/png", "text/plain"]))
        self.assertTrue(target_includes_image(["image/jpeg;charset=utf-8"]))
        self.assertTrue(target_includes_image(["application/x-qt-image"]))

    def test_plain_text_is_not_an_image(self) -> None:
        self.assertFalse(target_includes_image(["text/plain", "text/html", "UTF8_STRING"]))
        self.assertFalse(target_includes_image([]))

    def test_file_uri_picks_the_image(self) -> None:
        found = image_file_from_uris(
            [
                "file:///home/a/notas.txt",
                "file:///home/a/Captura%20de%20pantalla.png",
            ]
        )
        self.assertEqual(found, "/home/a/Captura de pantalla.png")

    def test_non_image_file_is_ignored(self) -> None:
        self.assertIsNone(image_file_from_uris(["file:///tmp/informe.pdf", "https://example.com/a.png"]))


if __name__ == "__main__":
    unittest.main()
