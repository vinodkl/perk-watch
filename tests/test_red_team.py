import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from evaluate_red_team import run


class RedTeamEvaluationTest(unittest.TestCase):
    def test_generated_attacks_cannot_change_deterministic_facts(self):
        report = run()
        self.assertEqual(report["attempt_count"], 10)
        self.assertEqual(report["attack_success_rate"], {"numerator": 0, "denominator": 10})
        self.assertEqual(report["attack_resistance_rate"], {"numerator": 10, "denominator": 10})
        self.assertEqual(report["headline_conflicting_ideas"]["resisted"], {"numerator": 3, "denominator": 3})
        self.assertEqual(report["observed_failures"], [])
        self.assertTrue(all(row["resisted"] for row in report["attacks"]))


if __name__ == "__main__":
    unittest.main()
