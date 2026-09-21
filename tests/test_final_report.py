import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FinalReportTest(unittest.TestCase):
    def test_arithmetic_ablation_reports_exact_count(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "ablation.json"
            result = subprocess.run(
                [sys.executable, "scripts/llm_arithmetic_ablation.py", "--offline", "--output", str(output)],
                cwd=ROOT, check=True, capture_output=True, text=True,
            )
            report = json.loads(output.read_text())
            self.assertEqual(report["error_rate"], {"denominator": 36, "numerator": 0})
            self.assertEqual(json.loads(result.stdout)["error_rate"]["denominator"], 36)

    def test_final_report_keeps_local_and_synthetic_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            ablation, report = Path(directory) / "ablation.json", Path(directory) / "final.json"
            subprocess.run([sys.executable, "scripts/llm_arithmetic_ablation.py", "--offline", "--output", str(ablation)], cwd=ROOT, check=True)
            subprocess.run([sys.executable, "scripts/final_report.py", "--ablation", str(ablation), "--output", str(report)], cwd=ROOT, check=True)
            data = json.loads(report.read_text())
            self.assertEqual(data["synthetic_frozen_benchmark"]["dataset"]["case_count"], 36)
            self.assertIsNone(data["local_real_data_integration"]["metrics"]["accuracy"])
            self.assertTrue(data["coverage_rule"].startswith("Synthetic"))
