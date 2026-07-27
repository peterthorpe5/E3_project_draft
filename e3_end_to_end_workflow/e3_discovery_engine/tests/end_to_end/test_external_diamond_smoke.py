import os
import shutil
import unittest

from e3_discovery.diamond import get_diamond_version


@unittest.skipUnless(
    os.environ.get("RUN_DIAMOND_E2E") == "1" and shutil.which("diamond"),
    "Set RUN_DIAMOND_E2E=1 in an environment containing DIAMOND",
)
class ExternalDiamondSmokeTests(unittest.TestCase):
    def test_diamond_version_is_detectable(self):
        version = get_diamond_version()
        self.assertGreaterEqual(version.major, 2)


if __name__ == "__main__":
    unittest.main()
