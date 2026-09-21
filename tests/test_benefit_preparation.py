import unittest

from perk_watch.benefit_preparation import _line_benefits


class BenefitPreparationTest(unittest.TestCase):
    def test_chase_lines_become_individual_clauses(self):
        clauses = _line_benefits(
            "Featured benefits\nMaximize your credits\n"
            "Global Entry/TSA PreCheck®/NEXUS credit*\n$120\n"
            "$100 annual Chase Travel hotel credit*\nAnnual value\n"
            "*For details, please see .\n",
            "chase_sapphire_preferred:local",
        )
        self.assertEqual([row[1] for row in clauses], [
            "Global Entry/TSA PreCheck®/NEXUS credit*",
            "$100 annual Chase Travel hotel credit*",
        ])


if __name__ == "__main__":
    unittest.main()
