import tempfile
import unittest
from pathlib import Path

from aidycos.distro import detect_distribution, parse_os_release


class DistributionTests(unittest.TestCase):
    def test_parse_os_release_values(self):
        values = parse_os_release('ID=debian\nVERSION_ID="13"\nID_LIKE="debian"\n')
        self.assertEqual(values["ID"], "debian")
        self.assertEqual(values["VERSION_ID"], "13")

    def test_detect_distribution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "os-release"
            path.write_text('ID=debian\nVERSION_ID="13"\nPRETTY_NAME="Debian GNU/Linux 13"\n')
            distro = detect_distribution(path)
        self.assertEqual(distro.id, "debian")
        self.assertEqual(distro.family, "debian")
