"""Hyprbars setup for Debian 13 / Hyprland 0.55.2 backports."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "packaging" / "hyprland" / "setup-hyprbars.sh"
SRC = ROOT / "packaging" / "hyprland" / "hyprbars-src"
COMPAT = ROOT / "packaging" / "hyprland" / "compat-headers"
CONF_IN = ROOT / "packaging" / "hyprland" / "jugoo_hyprbars.conf.in"
INSTALLER = ROOT / "scripts" / "install-debian-profile.sh"
REPAIR = ROOT / "scripts" / "repair-desktop-chrome.sh"


def _bash(script: str, *, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        check=check,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
    )


class HyprbarsTreeTests(unittest.TestCase):
    def test_setup_script_is_executable(self) -> None:
        self.assertTrue(SETUP.is_file())
        self.assertTrue(SETUP.stat().st_mode & stat.S_IXUSR)

    def test_vendored_sources_present(self) -> None:
        for name in (
            "main.cpp",
            "barDeco.cpp",
            "barDeco.hpp",
            "BarPassElement.cpp",
            "BarPassElement.hpp",
            "globals.hpp",
        ):
            self.assertTrue((SRC / name).is_file(), name)

    def test_compat_hyprutils_0131_is_non_explicit_bool(self) -> None:
        header = COMPAT / "hyprutils-0.13.1" / "hyprutils" / "memory" / "SharedPtr.hpp"
        self.assertTrue(header.is_file())
        text = header.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^\s*operator bool\(\) const")
        self.assertNotRegex(text, r"(?m)^\s*explicit\s+operator bool\(\) const")
        self.assertEqual((COMPAT / "hyprutils-0.13.1" / "VERSION").read_text(encoding="utf-8").strip(), "0.13.1")

    def test_setup_detects_hyprutils_mismatch_and_uses_compat(self) -> None:
        text = SETUP.read_text(encoding="utf-8")
        self.assertIn("compat-headers", text)
        self.assertIn("HYPRUTILS_VERSION", text)
        self.assertIn("explicit", text)
        self.assertIn("HYPRBARS_FORCE", text)
        # Compiler invocation must not pass the clang-only narrowing flag.
        compile_lines = [ln for ln in text.splitlines() if "g++ -shared" in ln or ln.strip().startswith("g++")]
        joined = "\n".join(compile_lines)
        self.assertNotIn("-Wno-c++11-narrowing", joined)
        self.assertIn("aidycos-backup-", text)

    def test_installer_fails_when_hyprbars_missing(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("packaging/hyprland/setup-hyprbars.sh", text)
        self.assertIn("no se pudieron instalar los botones de título (hyprbars)", text)
        self.assertIn("hyprctl plugin list", text)
        self.assertIn("HYPRBARS_FORCE=1", text)

    def test_repair_script_force_rebuilds(self) -> None:
        text = REPAIR.read_text(encoding="utf-8")
        self.assertIn("HYPRBARS_FORCE=1", text)
        self.assertIn("setup-hyprbars.sh", text)

    def test_conf_template_keeps_window_buttons(self) -> None:
        text = CONF_IN.read_text(encoding="utf-8")
        self.assertIn("@VENTANAS@ close", text)
        self.assertIn("@VENTANAS@ max", text)
        self.assertIn("@VENTANAS@ minimize", text)
        self.assertIn("plugin = @PLUGIN@", text)

    def test_button_exec_appends_window_address(self) -> None:
        text = (SRC / "barDeco.cpp").read_text(encoding="utf-8")
        self.assertIn('std::format("{} 0x{:x}", b.cmd, (uintptr_t)window.get())', text)
        self.assertIn('std::format("{} 0x{:x}", ON_DOUBLE_CLICK, (uintptr_t)PWINDOW.get())', text)

    def test_csd_minimize_packaging_wired(self) -> None:
        csd_src = ROOT / "packaging" / "hyprland" / "csd-minimize-src" / "main.cpp"
        setup = ROOT / "packaging" / "hyprland" / "setup-csd-minimize.sh"
        conf_in = ROOT / "packaging" / "hyprland" / "jugoo_csd_minimize.conf.in"
        self.assertTrue(csd_src.is_file())
        self.assertTrue(setup.is_file())
        self.assertTrue(setup.stat().st_mode & stat.S_IXUSR)
        self.assertTrue(conf_in.is_file())
        text = csd_src.read_text(encoding="utf-8")
        self.assertIn("PLUGIN_INIT", text)
        self.assertIn("0x{:x}", text)
        conf = conf_in.read_text(encoding="utf-8")
        self.assertIn("@VENTANAS@ minimize", conf)
        self.assertIn("@VENTANAS@ max", conf)
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("setup-csd-minimize.sh", installer)
        self.assertIn("jugoo_csd_minimize.conf", installer)


class HyprbarsSetupLogicTests(unittest.TestCase):
    """Exercise setup helpers without requiring a full apt install."""

    def test_version_h_parsers(self) -> None:
        helper = textwrap.dedent(
            r"""
            set -euo pipefail
            COMPAT_ROOT=packaging/hyprland/compat-headers
            eval "$(sed -n '/^hyprland_built_hyprutils()/,/^}/p;/^hyprland_built_aquamarine()/,/^}/p;/^compat_hyprutils_dir()/,/^}/p' packaging/hyprland/setup-hyprbars.sh)"
            vh=$(mktemp)
            printf '%s\n' \
              '#pragma once' \
              '#define AQUAMARINE_VERSION "0.11.0"' \
              '#define HYPRUTILS_VERSION    "0.13.1"' >"$vh"
            test "$(hyprland_built_hyprutils "$vh")" = "0.13.1"
            test "$(hyprland_built_aquamarine "$vh")" = "0.11.0"
            dir=$(compat_hyprutils_dir 0.13.1)
            test -d "$dir/hyprutils/memory"
            rm -f "$vh"
            """
        )
        result = _bash(helper)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_bool_detector(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            good = root / "good" / "hyprutils" / "memory"
            bad = root / "bad" / "hyprutils" / "memory"
            good.mkdir(parents=True)
            bad.mkdir(parents=True)
            (good / "SharedPtr.hpp").write_text(
                "operator bool() const { return true; }\n",
                encoding="utf-8",
            )
            (bad / "SharedPtr.hpp").write_text(
                "explicit operator bool() const { return true; }\n",
                encoding="utf-8",
            )
            script = r"""
set -euo pipefail
ROOT_TMP="$1"
eval "$(sed -n '/^hyprutils_has_explicit_bool()/,/^}/p' packaging/hyprland/setup-hyprbars.sh)"
export PKG_CONFIG_PATH="$ROOT_TMP/good-pc"
mkdir -p "$ROOT_TMP/good-pc"
cat >"$ROOT_TMP/good-pc/hyprutils.pc" <<EOF
Name: hyprutils
Description: test
Version: 0.13.1
includedir=$ROOT_TMP/good
Cflags: -I\${includedir}
EOF
if hyprutils_has_explicit_bool; then echo GOOD_SHOULD_BE_FALSE; exit 1; fi
cat >"$ROOT_TMP/good-pc/hyprutils.pc" <<EOF
Name: hyprutils
Description: test
Version: 0.14.2
includedir=$ROOT_TMP/bad
Cflags: -I\${includedir}
EOF
hyprutils_has_explicit_bool
"""
            # pkg-config may be missing on minimal CI images; skip detector runtime then.
            if shutil.which("pkg-config") is None and shutil.which("pkgconf") is None:
                self.skipTest("pkg-config not installed")
            result = subprocess.run(
                ["bash", "-c", script, "_", str(root)],
                check=False,
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_idempotent_source_line(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            hypr = home / ".config" / "hypr"
            hypr.mkdir(parents=True)
            aidycos = hypr / "aidycos.conf"
            aidycos.write_text("# existing\n", encoding="utf-8")
            plugin_dir = home / ".local" / "lib" / "jugoo"
            plugin_dir.mkdir(parents=True)
            # Pretend plugin already built for current dpkg version.
            running = subprocess.run(
                ["dpkg-query", "-W", "-f=${Version}", "hyprland"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            if not running:
                self.skipTest("hyprland package not installed")
            (plugin_dir / "hyprbars.so").write_bytes(b"\x7fELF fake")
            (plugin_dir / "hyprbars.hyprland-version").write_text(running + "\n", encoding="utf-8")

            env = os.environ.copy()
            env["HOME"] = str(home)
            env["XDG_CONFIG_HOME"] = str(home / ".config")
            # No live Hyprland session in the fake HOME.
            env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)

            first = subprocess.run(
                ["bash", str(SETUP)],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(ROOT),
            )
            # May fail before early-exit if hyprland-dev missing and needs_build triggers;
            # with stamp+plugin matching it should early-exit 0 after write_conf/ensure_source.
            self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
            conf = hypr / "config" / "jugoo_hyprbars.conf"
            self.assertTrue(conf.is_file())
            text1 = aidycos.read_text(encoding="utf-8")
            self.assertEqual(text1.count("source = ~/.config/hypr/config/jugoo_hyprbars.conf"), 1)

            second = subprocess.run(
                ["bash", str(SETUP)],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(ROOT),
            )
            self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
            text2 = aidycos.read_text(encoding="utf-8")
            self.assertEqual(text2.count("source = ~/.config/hypr/config/jugoo_hyprbars.conf"), 1)

    def test_missing_dependency_message_path(self) -> None:
        text = SETUP.read_text(encoding="utf-8")
        self.assertIn('die "hyprland-dev no está instalado', text)
        self.assertIn("no coinciden", text)
        self.assertIn("faltan headers compatibles para hyprutils", text)
        self.assertIn("falló la compilación de hyprbars", text)


class HyprbarsCompileIntegrationTests(unittest.TestCase):
    """Full compile when hyprland-dev is present on the machine."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.has_dev = (
            subprocess.run(
                ["dpkg-query", "-W", "-f=${Version}", "hyprland-dev"],
                capture_output=True,
                text=True,
                check=False,
            ).returncode
            == 0
            and bool(
                subprocess.run(
                    ["dpkg-query", "-W", "-f=${Version}", "hyprland-dev"],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout.strip()
            )
        )
        cls.has_gpp = shutil.which("g++") is not None
        cls.has_pkg = shutil.which("pkg-config") is not None or shutil.which("pkgconf") is not None

    def test_force_rebuild_produces_plugin(self) -> None:
        if not (self.has_dev and self.has_gpp and self.has_pkg):
            self.skipTest("hyprland-dev/g++/pkg-config required for compile integration")

        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["XDG_CONFIG_HOME"] = str(home / ".config")
            env["HYPRBARS_FORCE"] = "1"
            env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)

            result = subprocess.run(
                ["bash", str(SETUP)],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(ROOT),
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            plugin = home / ".local" / "lib" / "jugoo" / "hyprbars.so"
            conf = home / ".config" / "hypr" / "config" / "jugoo_hyprbars.conf"
            stamp = home / ".local" / "lib" / "jugoo" / "hyprbars.hyprland-version"
            self.assertTrue(plugin.is_file(), result.stdout + result.stderr)
            self.assertGreater(plugin.stat().st_size, 10_000)
            self.assertTrue(conf.is_file())
            self.assertIn(str(plugin), conf.read_text(encoding="utf-8"))
            self.assertTrue(stamp.is_file())
            # ELF shared object
            self.assertEqual(plugin.read_bytes()[:4], b"\x7fELF")

            # Force again must succeed (rebuild path).
            result2 = subprocess.run(
                ["bash", str(SETUP)],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(ROOT),
            )
            self.assertEqual(result2.returncode, 0, result2.stderr + result2.stdout)

    def test_live_plugin_load_when_session_available(self) -> None:
        if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            self.skipTest("no live Hyprland session")
        if not (self.has_dev and self.has_gpp and self.has_pkg):
            self.skipTest("hyprland-dev/g++/pkg-config required")
        if not shutil.which("hyprctl"):
            self.skipTest("hyprctl missing")

        result = subprocess.run(
            ["bash", str(SETUP)],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env={**os.environ, "HYPRBARS_FORCE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        listed = subprocess.run(
            ["hyprctl", "plugin", "list"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertRegex(listed.stdout, re.compile(r"(?im)^Plugin hyprbars"))


if __name__ == "__main__":
    unittest.main()
