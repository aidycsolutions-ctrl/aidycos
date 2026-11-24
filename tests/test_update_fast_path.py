"""The profile reapply used by aidycos-update must skip work that already matches."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-debian-profile.sh"
UPDATER = ROOT / "scripts" / "aidycos-update"
BOOT = ROOT / "packaging" / "boot" / "apply-aidycos-boot.sh"
NETWORK = ROOT / "packaging" / "network" / "apply-aidycos-network.sh"
HYPRBARS = ROOT / "packaging" / "hyprland" / "setup-hyprbars.sh"
CSD = ROOT / "packaging" / "hyprland" / "setup-csd-minimize.sh"


class UpdateFastPathTests(unittest.TestCase):
    def test_updater_timer_stays_quiet_when_current(self) -> None:
        text = UPDATER.read_text(encoding="utf-8")
        self.assertIn("INVOCATION_ID", text)
        self.assertLess(text.index("INVOCATION_ID"), text.index("Ya está actualizado"))

    def test_updater_asks_password_without_a_console(self) -> None:
        text = UPDATER.read_text(encoding="utf-8")
        self.assertIn("SUDO_ASKPASS", text)
        self.assertIn("zenity --password", text)
        self.assertIn("setsid bash", text)
        self.assertIn("segundo plano", text)
        self.assertNotIn("find_terminal", text)
        self.assertNotIn("hyprctl dispatch exec", text)
        self.assertNotIn("Pulsa Enter para cerrar", text)

    def test_update_question_accepts_enter_as_yes(self) -> None:
        text = UPDATER.read_text(encoding="utf-8")
        self.assertIn('dialog.set_buttons(["_No", "_Sí"])', text)
        self.assertLess(text.index('dialog.set_buttons(["_No", "_Sí"])'), text.index("dialog.set_default_button(1)"))
        self.assertIn("dialog.set_cancel_button(0)", text)
        self.assertLess(text.index("self.hold()"), text.index("dialog.choose"))
        self.assertIn("Pulsa Enter para actualizar", text)

    def test_finished_update_does_not_keep_the_lock(self) -> None:
        text = UPDATER.read_text(encoding="utf-8")
        self.assertIn("FD_CLOEXEC", text)
        self.assertIn("update_lock_is_live", text)
        self.assertLess(text.index("lock_fd_cloexec 9"), text.index("flock -n 9"))
        start = text.index("lock_fd_cloexec()")
        end = text.index("# end lock-helpers\n")
        helpers = text[start:end]
        script = (
            "set -euo pipefail\n"
            + helpers
            + """
LOCK="$(mktemp)"
python3 - "$LOCK" <<'PY' &
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_RDWR)
fcntl.flock(fd, fcntl.LOCK_EX)
time.sleep(30)
PY
holder=$!
sleep 0.2
if acquire_update_lock; then
  echo recovered
else
  echo blocked
fi
kill "$holder" 2>/dev/null || true
wait "$holder" 2>/dev/null || true
rm -f "$LOCK"
"""
        )
        import subprocess
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("recovered", result.stdout)
        self.assertNotIn("blocked", result.stdout)

    def test_installer_skips_repeated_apt_and_deploys(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("PROFILE_REFRESH", text)
        self.assertIn("apt_install_missing", text)
        self.assertIn("sources_changed", text)
        self.assertIn("desktop_packages_present", text)
        self.assertIn("jugoo-deploy-stamp", text)
        self.assertIn("printers-stamp", text)
        self.assertIn("refresh_icon_cache", text)
        self.assertNotIn("gtk-update-icon-cache -f", text)

    def test_boot_skips_grub_and_initramfs_when_files_match(self) -> None:
        text = BOOT.read_text(encoding="utf-8")
        self.assertLess(
            text.index("if boot_already_current; then"),
            text.index('run_root "${UPDATE_GRUB}"'),
        )
        self.assertIn('"${UPDATE_INITRAMFS}"', text)

    def test_network_does_not_restart_when_profile_matches(self) -> None:
        text = NETWORK.read_text(encoding="utf-8")
        self.assertLess(
            text.index("if network_profile_current; then"),
            text.rindex("run_root systemctl restart NetworkManager.service"),
        )

    def test_plugins_do_not_reload_when_already_built(self) -> None:
        for path in (HYPRBARS, CSD):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("ya compilado para", text)
            self.assertIn("plugin_loaded", text)


if __name__ == "__main__":
    unittest.main()
