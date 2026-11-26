"""AidyCExplorer file operations and profile wiring."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging" / "aidycexplorer"))

from aidycexplorer.fs import (  # noqa: E402
    copy_entry,
    human_size,
    list_directory,
    list_trash,
    make_directory,
    move_to_trash,
    parse_location,
    rename_entry,
    resolve_start,
    restore_trash,
    user_places,
    validate_name,
)
from aidycexplorer.mime import clear_directory_handler, set_directory_handler  # noqa: E402


class ExplorerFsTests(unittest.TestCase):
    def test_lists_folders_first_and_hides_dotfiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "b.txt").write_text("hola", encoding="utf-8")
            (root / "A").mkdir()
            (root / ".secret").write_text("x", encoding="utf-8")
            visible = [entry.name for entry in list_directory(root)]
            self.assertEqual(visible, ["A", "b.txt"])
            hidden = [entry.name for entry in list_directory(root, show_hidden=True)]
            self.assertIn(".secret", hidden)
            self.assertEqual(human_size(1536), "1.5 KB")

    def test_copy_rename_and_refuse_invalid_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "nota.txt"
            source.write_text("abc", encoding="utf-8")
            other = root / "otra"
            other.mkdir()
            copied = copy_entry(source, other)
            self.assertEqual(copied.read_text(encoding="utf-8"), "abc")
            again = copy_entry(source, root)
            self.assertEqual(again.name, "nota (copia).txt")
            renamed = rename_entry(copied, "final.txt")
            self.assertTrue(renamed.is_file())
            with self.assertRaises(ValueError):
                validate_name("../etc")
            with self.assertRaises(ValueError):
                make_directory(root, "")

    def test_trash_roundtrip_restores_original_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trash = root / "Trash"
            folder = root / "docs"
            folder.mkdir()
            original = folder / "informe.txt"
            original.write_text("datos", encoding="utf-8")
            move_to_trash(original, trash)
            self.assertFalse(original.exists())
            items = list_trash(trash)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].name, "informe.txt")
            self.assertEqual(items[0].origin, str(original))
            restored = restore_trash(items[0].trash_name, trash)
            self.assertEqual(restored, original)
            self.assertEqual(restored.read_text(encoding="utf-8"), "datos")

    def test_locations_and_places(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / "Escritorio").mkdir()
            (home / ".config").mkdir()
            (home / ".config" / "user-dirs.dirs").write_text(
                'XDG_DESKTOP_DIR="$HOME/Escritorio"\n',
                encoding="utf-8",
            )
            labels = [label for label, _path in user_places(home)]
            self.assertEqual(labels[0], "Inicio")
            self.assertIn("Escritorio", labels)
            mode, path = parse_location(f"file://{home}/Escritorio", home=home)
            self.assertEqual(mode, "path")
            self.assertEqual(path, home / "Escritorio")
            self.assertEqual(parse_location("papelera", home=home)[0], "trash")
            note = home / "nota.txt"
            note.write_text("x", encoding="utf-8")
            start_mode, start, selected = resolve_start([str(note)], home=home)
            self.assertEqual(start_mode, "path")
            self.assertEqual(start, home)
            self.assertEqual(selected, "nota.txt")

    def test_mime_handler_replaces_previous_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mimeapps.list"
            path.write_text(
                "[Default Applications]\ninode/directory=thunar.desktop\ntext/plain=foot.desktop\n",
                encoding="utf-8",
            )
            self.assertTrue(set_directory_handler(path))
            text = path.read_text(encoding="utf-8")
            self.assertIn("inode/directory=aidycexplorer.desktop", text)
            self.assertNotIn("thunar.desktop", text)
            self.assertIn("text/plain=foot.desktop", text)
            self.assertFalse(set_directory_handler(path))
            self.assertTrue(clear_directory_handler(path))
            cleared = path.read_text(encoding="utf-8")
            self.assertNotIn("aidycexplorer.desktop", cleared)
            self.assertIn("text/plain=foot.desktop", cleared)

    def test_profile_ships_explorer_to_every_machine(self) -> None:
        installer = (ROOT / "scripts" / "install-debian-profile.sh").read_text(encoding="utf-8")
        uninstaller = (ROOT / "scripts" / "uninstall-debian-profile.sh").read_text(encoding="utf-8")
        updater = (ROOT / "scripts" / "aidycos-update").read_text(encoding="utf-8")
        icon = ROOT / "packaging" / "aidycexplorer" / "aidycexplorer.png"
        self.assertIn("install_aidycexplorer", installer)
        self.assertIn("bind = SUPER, E, exec, aidycexplorer", installer)
        self.assertIn("set_directory_handler", installer)
        self.assertIn("/usr/local/bin/aidycexplorer", uninstaller)
        self.assertIn("aidycexplorer.desktop", uninstaller)
        self.assertIn("clear_explorer_mime", uninstaller)
        self.assertIn('if [[ ! -f "\\${installer}" ]]; then', updater)
        self.assertNotIn('if [[ ! -x "\\${installer}" ]]; then', updater)
        self.assertEqual(icon.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
