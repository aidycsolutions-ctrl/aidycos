from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "packaging"
    / "jugoo-overlay"
    / "shell"
    / "user_icon_paths.py"
)
SPEC = importlib.util.spec_from_file_location("aidycos_user_icon_paths", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeIconTheme:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def get_search_path(self) -> list[str]:
        return list(self.paths)

    def append_search_path(self, path: str) -> None:
        self.paths.append(path)


class UserIconSearchPathTests(unittest.TestCase):
    def test_adds_existing_user_icon_paths_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            data_home = home / "data"
            (data_home / "icons").mkdir(parents=True)
            (home / ".icons").mkdir()
            theme = FakeIconTheme()

            added = MODULE.append_user_icon_search_paths(theme, data_home=data_home, home=home)

            self.assertEqual(set(added), {data_home / "icons", home / ".icons"})
            self.assertEqual(len(theme.paths), 2)
            self.assertEqual(MODULE.append_user_icon_search_paths(theme, data_home=data_home, home=home), ())


if __name__ == "__main__":
    unittest.main()
