from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "deploy_jugoo", ROOT / "scripts" / "deploy-jugoo.py"
)
assert SPEC and SPEC.loader
deploy_jugoo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy_jugoo)


def make_source(path: Path, value: str) -> Path:
    shell = path / "shell"
    shell.mkdir(parents=True)
    (shell / "__main__.py").write_text(value, encoding="utf-8")
    return path


class JugooDeploymentTests(unittest.TestCase):
    def test_new_install_preserves_existing_user_checkout_and_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_source(root / "official", "official v1")
            destination = root / "opt" / "aidyc" / "jugoo"
            user_checkout = root / ".config" / "jugoo"
            user_checkout.mkdir(parents=True)
            (user_checkout / "local-change.py").write_text("keep me", encoding="utf-8")

            deploy_jugoo.deploy(source, destination)

            self.assertEqual((destination / "shell" / "__main__.py").read_text(), "official v1")
            self.assertTrue((destination / deploy_jugoo.MARKER).is_file())
            self.assertEqual((user_checkout / "local-change.py").read_text(), "keep me")
            self.assertFalse(destination.with_name("jugoo.aidycos-preserved").exists())

    def test_existing_iso_install_is_preserved_and_managed_install_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            destination = root / "opt" / "aidyc" / "jugoo"
            destination.mkdir(parents=True)
            (destination / "iso-version.txt").write_text("ISO copy", encoding="utf-8")
            source_v1 = make_source(root / "source-v1", "official v1")

            deploy_jugoo.deploy(source_v1, destination)

            preserved = destination.with_name("jugoo.aidycos-preserved")
            self.assertEqual((preserved / "iso-version.txt").read_text(), "ISO copy")
            self.assertEqual((destination / "shell" / "__main__.py").read_text(), "official v1")

            source_v2 = make_source(root / "source-v2", "official v2")
            deploy_jugoo.deploy(source_v2, destination)

            self.assertEqual((destination / "shell" / "__main__.py").read_text(), "official v2")
            self.assertEqual((preserved / "iso-version.txt").read_text(), "ISO copy")

    def test_launcher_and_user_service_override_share_system_entry_point(self) -> None:
        launcher = (ROOT / "packaging" / "jugoo-launcher").read_text(encoding="utf-8")
        service = (
            ROOT
            / "packaging"
            / "systemd"
            / "jugoo-task-watcher.service.d"
            / "aidycos.conf"
        ).read_text(encoding="utf-8")
        installer = (ROOT / "scripts" / "install-debian-profile.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("JUGOO_DIR=/opt/aidyc/jugoo", launcher)
        self.assertIn("python3 -m shell \"$@\"", launcher)
        self.assertIn("ExecStart=/usr/local/bin/jugoo --task-watcher", service)
        self.assertIn("exec-once = /usr/local/bin/jugoo", installer)
