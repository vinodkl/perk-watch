from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class Phase8Test(unittest.TestCase):
    def test_demo_builder_uses_real_preparation_pipeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, "scripts/build_demo_data.py", "--root", str(Path(temporary) / "demo-output")],
                cwd=Path(__file__).parents[1], text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)["unresolved_count"], 0)

        refused = subprocess.run(
            [sys.executable, "scripts/build_demo_data.py", "--root", "demo/output"],
            cwd=Path(__file__).parents[1], text=True, capture_output=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("outside the repository", refused.stderr)


if __name__ == "__main__":
    unittest.main()
