from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNINSTALL = ROOT / "scripts" / "uninstall-debian-profile.sh"
INSTALLER = ROOT / "scripts" / "install-debian-profile.sh"
BOOT = ROOT / "packaging" / "boot" / "apply-aidycos-boot.sh"
DESKTOP = ROOT / "packaging" / "applications" / "aidycos-uninstall.desktop"
REMOTE = ROOT / "uninstall.sh"


class UninstallProfileTests(unittest.TestCase):
    def test_scripts_are_executable_and_wired(self) -> None:
        self.assertTrue(UNINSTALL.is_file())
        self.assertTrue(UNINSTALL.stat().st_mode & stat.S_IXUSR)
        self.assertTrue(REMOTE.is_file())
        self.assertTrue(DESKTOP.is_file())
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("aidycos-uninstall", installer)
        self.assertIn("aidycos-uninstall.desktop", installer)
        self.assertIn("created-apt-sources", installer)
        self.assertIn("profile-installed", installer)
        boot = BOOT.read_text(encoding="utf-8")
        self.assertIn("plymouthd.conf.aidycos-backup", boot)
        desktop = DESKTOP.read_text(encoding="utf-8")
        self.assertIn("Quitar AidyCOS", desktop)
        self.assertIn("Exec=aidycos-uninstall", desktop)

    def test_dry_run_lists_restore_steps(self) -> None:
        result = subprocess.run(
            ["bash", str(UNINSTALL), "--dry-run"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("gestor de pantalla", result.stdout)
        self.assertIn("GRUB", result.stdout)
        self.assertIn("no hace apt remove", result.stdout.lower() + result.stdout)

    def test_sysroot_restores_backups_and_removes_profile_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            # System-ish layout under fake root.
            (root / "etc/default").mkdir(parents=True)
            (root / "etc/default/grub.d").mkdir(parents=True)
            (root / "etc/sddm.conf.d").mkdir(parents=True)
            (root / "etc/network").mkdir(parents=True)
            (root / "etc/NetworkManager/conf.d").mkdir(parents=True)
            (root / "etc/plymouth").mkdir(parents=True)
            (root / "etc/apt/sources.list.d").mkdir(parents=True)
            (root / "var/lib/aidycos").mkdir(parents=True)
            (root / "usr/local/bin").mkdir(parents=True)
            (root / "usr/share/sddm/themes/aidycos").mkdir(parents=True)
            (root / "usr/share/plymouth/themes/aidycos").mkdir(parents=True)
            (root / "opt/aidyc/jugoo").mkdir(parents=True)
            (root / "opt/aidyc/jugoo.aidycos-preserved").mkdir(parents=True)
            (root / "home/testuser/.config/hypr").mkdir(parents=True)
            (root / "home/testuser/.local/bin").mkdir(parents=True)
            (root / "home/testuser/.local/share/applications").mkdir(parents=True)

            grub = root / "etc/default/grub"
            grub.write_text('GRUB_TIMEOUT=0\nGRUB_DISTRIBUTOR="AidyCOS"\n', encoding="utf-8")
            (root / "etc/default/grub.aidycos-backup").write_text(
                'GRUB_TIMEOUT=5\nGRUB_DISTRIBUTOR="Debian"\n', encoding="utf-8"
            )
            (root / "etc/default/grub.d/zz-aidycos.cfg").write_text("# managed\n", encoding="utf-8")

            (root / "etc/sddm.conf.d/99-aidycos.conf").write_text("Current=aidycos\n", encoding="utf-8")
            (root / "var/lib/aidycos/previous-display-manager").write_text("gdm3.service\n", encoding="utf-8")
            (root / "etc/systemd/system").mkdir(parents=True)
            (root / "etc/systemd/system/display-manager.service").symlink_to(
                "/lib/systemd/system/sddm.service"
            )

            interfaces = root / "etc/network/interfaces"
            interfaces.write_text("auto lo\niface lo inet loopback\n", encoding="utf-8")
            (root / "etc/network/interfaces.aidycos-backup-20250101000000").write_text(
                "auto lo\niface lo inet loopback\nallow-hotplug wlan0\n",
                encoding="utf-8",
            )
            (root / "etc/NetworkManager/conf.d/99-aidycos-ifupdown.conf").write_text(
                "managed=true\n", encoding="utf-8"
            )
            (root / "etc/apt/sources.list.d/aidycos-backports.sources").write_text("Types: deb\n", encoding="utf-8")
            (root / "var/lib/aidycos/created-apt-sources").write_text(
                "/etc/apt/sources.list.d/aidycos-backports.sources\n", encoding="utf-8"
            )
            (root / "var/lib/aidycos/profile-installed").write_text("2026-01-01T00:00:00Z\n", encoding="utf-8")

            (root / "usr/local/bin/jugoo").write_text("#!/bin/sh\n", encoding="utf-8")
            (root / "usr/local/bin/aidycos-uninstall").write_text("#!/bin/sh\n", encoding="utf-8")
            (root / "usr/share/sddm/themes/aidycos/theme.conf").write_text("x=1\n", encoding="utf-8")
            (root / "opt/aidyc/jugoo/marker").write_text("new\n", encoding="utf-8")
            (root / "opt/aidyc/jugoo.aidycos-preserved/marker").write_text("old\n", encoding="utf-8")

            hypr = root / "home/testuser/.config/hypr/hyprland.conf"
            hypr.write_text(
                "source = ~/.config/hypr/aidycos.conf\nexec-once = /usr/local/bin/jugoo\nbind = SUPER, Q, killactive\n",
                encoding="utf-8",
            )
            (root / "home/testuser/.config/hypr/hyprland.conf.aidycos-backup-20250101000000").write_text(
                "bind = SUPER, Q, killactive\n",
                encoding="utf-8",
            )
            (root / "home/testuser/.config/hypr/aidycos.conf").write_text("bind = SUPER, SPACE, exec, jugoo\n", encoding="utf-8")
            (root / "home/testuser/.local/share/applications/aidycos-uninstall.desktop").write_text(
                "[Desktop Entry]\nName=Quitar\n", encoding="utf-8"
            )

            env = os.environ.copy()
            env["AIDYCOS_SYSROOT"] = str(root)
            env["HOME"] = str(root / "home/testuser")
            env.pop("XDG_CONFIG_HOME", None)
            env.pop("XDG_DATA_HOME", None)
            result = subprocess.run(
                ["bash", str(UNINSTALL), "--yes", "--no-reboot"],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertIn("AidyCOS se quitó", result.stdout)

            self.assertEqual(
                grub.read_text(encoding="utf-8"),
                'GRUB_TIMEOUT=5\nGRUB_DISTRIBUTOR="Debian"\n',
            )
            self.assertFalse((root / "etc/default/grub.d/zz-aidycos.cfg").exists())
            self.assertFalse((root / "etc/sddm.conf.d/99-aidycos.conf").exists())
            self.assertFalse((root / "etc/NetworkManager/conf.d/99-aidycos-ifupdown.conf").exists())
            self.assertFalse((root / "etc/apt/sources.list.d/aidycos-backports.sources").exists())
            self.assertFalse((root / "usr/local/bin/jugoo").exists())
            self.assertFalse((root / "usr/share/sddm/themes/aidycos").exists())
            self.assertTrue((root / "opt/aidyc/jugoo").is_dir())
            self.assertEqual(
                (root / "opt/aidyc/jugoo/marker").read_text(encoding="utf-8"),
                "old\n",
            )
            self.assertFalse((root / "opt/aidyc/jugoo.aidycos-preserved").exists())
            self.assertEqual(hypr.read_text(encoding="utf-8"), "bind = SUPER, Q, killactive\n")
            self.assertFalse((root / "home/testuser/.config/hypr/aidycos.conf").exists())
            self.assertIn(
                "gdm3.service",
                str((root / "etc/systemd/system/display-manager.service").readlink()),
            )
            self.assertIn("wlan0", interfaces.read_text(encoding="utf-8"))
            self.assertFalse((root / "var/lib/aidycos/previous-display-manager").exists())
            self.assertFalse(
                (root / "home/testuser/.local/share/applications/aidycos-uninstall.desktop").exists()
            )

    def test_cli_exposes_uninstall(self) -> None:
        from aidycos.cli import _parser

        parser = _parser()
        args = parser.parse_args(["uninstall", "--dry-run", "--no-reboot"])
        self.assertEqual(args.command, "uninstall")
        self.assertTrue(args.dry_run)
        self.assertTrue(args.no_reboot)


if __name__ == "__main__":
    unittest.main()
