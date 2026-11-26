import unittest
from unittest.mock import patch
import subprocess
from configparser import ConfigParser
import hashlib
from pathlib import Path
import struct

from aidycos.nemo_actions.change_usb_label import ActionError, change_label, validate_label


class UsbLabelActionTests(unittest.TestCase):
    def test_nemo_action_wraps_script_and_device_token_together(self):
        action = ConfigParser(interpolation=None)
        action.read(Path(__file__).parents[1] / "aidycos/nemo_actions/aidyc-change-usb-label.nemo_action")
        self.assertEqual(action["Nemo Action"]["Exec"], "<change_usb_label.py %D>")

    def test_launcher_is_branded_and_uses_nemo(self):
        launcher = ConfigParser(interpolation=None)
        launcher.read(Path(__file__).parents[1] / "aidycos/nemo_actions/aidyc-explorer.desktop")
        self.assertEqual(launcher["Desktop Entry"]["Name"], "AidyC Explorer")
        self.assertEqual(launcher["Desktop Entry"]["Exec"], "nemo %U")
        self.assertEqual(launcher["Desktop Entry"]["Icon"], "aidyc-explorer")

    def test_brand_icon_is_valid_png(self):
        icon = Path(__file__).parents[1] / "aidycos/nemo_actions/aidyc-explorer.png"
        data = icon.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", data[16:24]), (1254, 1254))
        self.assertEqual(
            hashlib.sha256(data).hexdigest(),
            "81fadb97277ca868cada8bd1b46b544e0d3f685f3dc1961697a8a930365ad599",
        )

    def test_accepts_unicode_label(self):
        self.assertEqual(validate_label("Mi USB ñ"), "Mi USB ñ")

    def test_rejects_empty_trimmed_and_control_labels(self):
        for label in ("", " USB", "USB ", "USB\n2"):
            with self.subTest(label=label), self.assertRaises(ActionError):
                validate_label(label)

    @patch("aidycos.nemo_actions.change_usb_label.run")
    def test_unmounts_sets_label_and_remounts_without_shell(self, mocked_run):
        mocked_run.side_effect = [
            subprocess.CompletedProcess([], 0, "/media/USB\n", ""),
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "()", ""),
            subprocess.CompletedProcess([], 0, "", ""),
        ]

        change_label(
            "/dev/sdb1", "exfat", "/org/freedesktop/UDisks2/block_devices/sdb1", 'USB "2"'
        )

        commands = [call.args[0] for call in mocked_run.call_args_list]
        self.assertEqual(commands[0][:2], ["findmnt", "--noheadings"])
        self.assertEqual(commands[1][:2], ["udisksctl", "unmount"])
        self.assertEqual(commands[2][0], "gdbus")
        self.assertEqual(commands[2][-2], '"USB \\"2\\""')
        self.assertEqual(commands[3][:2], ["udisksctl", "mount"])

    @patch("aidycos.nemo_actions.change_usb_label.run")
    def test_does_not_set_label_if_unmount_fails(self, mocked_run):
        mocked_run.side_effect = [
            subprocess.CompletedProcess([], 0, "/media/USB\n", ""),
            subprocess.CompletedProcess([], 1, "", "Device busy"),
        ]
        with self.assertRaisesRegex(ActionError, "Cierra archivos"):
            change_label("/dev/sdb1", "vfat", "/org/freedesktop/UDisks2/block_devices/sdb1", "NUEVA")
        self.assertEqual(mocked_run.call_count, 2)

    @patch("aidycos.nemo_actions.change_usb_label.run")
    def test_rejects_unsupported_filesystem_before_touching_device(self, mocked_run):
        with self.assertRaisesRegex(ActionError, "no habilitado"):
            change_label("/dev/sdb1", "ext4", "/org/freedesktop/UDisks2/block_devices/sdb1", "NUEVA")
        mocked_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
