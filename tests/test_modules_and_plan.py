import tempfile
import unittest
from pathlib import Path

from aidycos.distro import Distribution
from aidycos.modules import Module, ModuleError, load_modules, resolve_modules
from aidycos.plan import build_plan


class ModuleTests(unittest.TestCase):
    def test_desktop_module_plan_deduplicates_packages(self):
        modules = load_modules()
        modules["extra"] = Module("extra", "", {"apt": ("wtype", "curl")}, ("desktop-runtime",))
        plan = build_plan(["extra"], modules, Distribution("debian", "13"), "apt")
        self.assertEqual(plan.packages.count("wtype"), 1)
        self.assertEqual(plan.modules[0].name, "desktop-runtime")

    def test_desktop_module_includes_usb_mount_stack(self):
        # --no-install-recommends would otherwise skip Thunar's USB Recommends.
        modules = load_modules()
        plan = build_plan(["aidyc-desktop"], modules, Distribution("debian", "13"), "apt")
        for pkg in ("udisks2", "gvfs", "thunar-volman", "usbutils"):
            self.assertIn(pkg, plan.packages)

    def test_unknown_module_fails(self):
        with self.assertRaisesRegex(ModuleError, "desconocido"):
            resolve_modules(["missing"], {})

    def test_manifest_rejects_shell_metacharacters_in_package_names(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "module.toml"
            manifest.write_text('name="safe"\n[packages.apt]\npackages=["x; touch /tmp/pwned"]\n')
            with self.assertRaises(ModuleError):
                from aidycos.modules import load_module
                load_module(manifest)


if __name__ == "__main__":
    unittest.main()
