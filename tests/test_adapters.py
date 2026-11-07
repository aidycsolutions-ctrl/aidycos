import unittest

from aidycos.adapters.apt import AptAdapter
from aidycos.adapters.factory import UnsupportedDistribution, adapter_for
from aidycos.distro import Distribution


class AdapterTests(unittest.TestCase):
    def test_debian_13_uses_apt(self):
        self.assertIsInstance(adapter_for(Distribution("debian", "13")), AptAdapter)

    def test_debian_12_is_not_claimed_as_supported(self):
        with self.assertRaises(UnsupportedDistribution):
            adapter_for(Distribution("debian", "12"))

    def test_apt_install_uses_argv_and_updates_first(self):
        calls = []
        def runner(argv, check=False):
            calls.append(argv)
            return 0
        adapter_for(Distribution("debian", "13")).install(("wtype",), is_root=False, runner=runner)
        self.assertEqual(calls[0], ["sudo", "apt-get", "update"])
        self.assertEqual(calls[1], ["sudo", "apt-get", "install", "--no-install-recommends", "-y", "wtype"])

    def test_failed_update_stops_before_install(self):
        calls = []
        def runner(argv, check=False):
            calls.append(argv)
            return 9
        result = AptAdapter().install(("wtype",), is_root=True, runner=runner)
        self.assertEqual(result, 9)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
