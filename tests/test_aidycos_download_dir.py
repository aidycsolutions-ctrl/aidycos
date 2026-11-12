from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "aidycos_download_dir",
    ROOT / "packaging" / "thunar" / "aidycos-download-dir.py",
)
assert SPEC and SPEC.loader
ddl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ddl)


class DownloadDirTests(unittest.TestCase):
    def test_spanish_locale_prefers_descargas(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            with mock.patch.dict(os.environ, {"LANG": "es_DO.UTF-8"}, clear=False):
                self.assertEqual(ddl.preferred_download_name(home), "Descargas")

    def test_ensure_renames_downloads_to_descargas_when_empty_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            downloads = home / "Downloads"
            downloads.mkdir()
            (downloads / "report.pdf").write_text("ok", encoding="utf-8")
            config = home / ".config"
            with mock.patch.dict(
                os.environ,
                {
                    "HOME": str(home),
                    "LANG": "es_ES.UTF-8",
                    "XDG_CONFIG_HOME": str(config),
                },
                clear=False,
            ):
                with mock.patch.object(ddl, "shutil_which", return_value=None):
                    path = ddl.ensure_download_dir(home)
            self.assertEqual(path, home / "Descargas")
            self.assertTrue((home / "Descargas" / "report.pdf").is_file())
            self.assertTrue((home / "Downloads").is_symlink())
            self.assertEqual((home / "Downloads").resolve(), (home / "Descargas").resolve())
            dirs_file = config / "user-dirs.dirs"
            self.assertIn("XDG_DOWNLOAD_DIR", dirs_file.read_text(encoding="utf-8"))
            bookmarks = config / "gtk-3.0" / "bookmarks"
            text = bookmarks.read_text(encoding="utf-8")
            self.assertIn("Descargas", text)
            self.assertIn((home / "Descargas").resolve().as_uri(), text)

    def test_ensure_leaves_populated_sibling_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            descargas = home / "Descargas"
            downloads = home / "Downloads"
            descargas.mkdir()
            downloads.mkdir()
            (descargas / "a.pdf").write_text("a", encoding="utf-8")
            (downloads / "b.pdf").write_text("b", encoding="utf-8")
            config = home / ".config"
            with mock.patch.dict(
                os.environ,
                {
                    "HOME": str(home),
                    "LANG": "es_ES.UTF-8",
                    "XDG_CONFIG_HOME": str(config),
                },
                clear=False,
            ):
                with mock.patch.object(ddl, "shutil_which", return_value=None):
                    path = ddl.ensure_download_dir(home)
            self.assertEqual(path, descargas)
            self.assertTrue(downloads.is_dir())
            self.assertFalse(downloads.is_symlink())
            self.assertTrue((downloads / "b.pdf").is_file())

    def test_partial_name_detection(self) -> None:
        self.assertTrue(ddl._is_partial_name("file.pdf.crdownload"))
        self.assertTrue(ddl._is_partial_name("file.pdf.part"))
        self.assertFalse(ddl._is_partial_name("file.pdf"))


if __name__ == "__main__":
    unittest.main()
