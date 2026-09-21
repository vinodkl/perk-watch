import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliTest(unittest.TestCase):
    def test_scripted_cli_runs_local_end_to_end(self):
        env = {**os.environ, "PYTHONPATH": "src", "PERKWATCH_DATA_DIR": "data/real"}
        result = subprocess.run(
            [sys.executable, "scripts/perkwatch_cli.py", "Which benefits are unused?", "--scripted"],
            cwd=ROOT, env=env, check=True, capture_output=True, text=True,
        )
        output = json.loads(result.stdout)
        self.assertTrue(output["answer"]["citations"])
        self.assertTrue(output["answer"]["community"]["available"])
        self.assertTrue(output["planner"]["actions"])
        self.assertEqual(output["merchant_fallback"]["unresolved_descriptor_count"], 188)
