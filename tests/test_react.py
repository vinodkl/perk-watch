from datetime import date
import unittest

from perk_watch.benefits import StatusResult
from perk_watch.react import ReActRuntime, ScriptedModel


class RetryModel:
    def __init__(self):
        self.n = 0

    def next(self, question, observations):
        self.n += 1
        if self.n == 1:
            return {"call": {"tool": "get_verified_statuses", "arguments": {"unexpected": True}}}
        if self.n == 2:
            return {"call": {"tool": "get_verified_statuses", "arguments": {}}}
        return {"final": "done"}


class ReactSmokeTest(unittest.TestCase):
    def runtime(self, retrieve_official=None):
        facts = [StatusResult("unused", ("no_eligible_transactions",), ("benefit:hotel", "period:x"), 0, 2500, date(2026, 9, 30))]
        return ReActRuntime(
            question="What benefits should I use before month-end?", as_of=date(2026, 9, 20),
            evaluate=lambda as_of: facts, retrieve_official=retrieve_official,
        )

    def test_typed_loop_retries_and_keeps_tool_error_as_data(self):
        answer = self.runtime().run(RetryModel())
        self.assertEqual(answer.validation_retries, 1)
        self.assertEqual(answer.statuses[0].status, "unused")

    def test_demo_connects_official_and_explicit_community_unavailable(self):
        def official(query, question, benefit_ids, as_of):
            return [{"clause_id": "hotel-clause", "citation": "guide#hotel", "clause_text": "Use by month end", "terms_version": "t1"}]

        answer = self.runtime(official).run(ScriptedModel())
        self.assertEqual(answer.citations[0].clause_id, "hotel-clause")
        self.assertFalse(answer.community["available"])
        self.assertEqual(answer.community["ideas"], [])


if __name__ == "__main__":
    unittest.main()
