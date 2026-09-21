from datetime import date
import unittest

from perk_watch.benefits import StatusResult
from perk_watch.react import OpenAIModel, ReActRuntime, ScriptedModel


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


class MalformedForeverModel:
    def next(self, question, observations):
        return {"call": {"tool": "not-a-tool", "arguments": []}}


class FakeOpenAIResponse:
    class Choice:
        class Message:
            content = '{"call":{"tool":"retrieve_community_uses","arguments":["benefit-a","benefit-b"]}}'
        message = Message()
    choices = [Choice()]


class FakeOpenAICompletions:
    def create(self, **kwargs):
        return FakeOpenAIResponse()


class FakeOpenAIClient:
    class Chat:
        completions = FakeOpenAICompletions()
    chat = Chat()


class ReactSmokeTest(unittest.TestCase):
    def runtime(self, retrieve_official=None):
        facts = [StatusResult("unused", ("no_eligible_transactions",), ("benefit:hotel", "period:x"), 0, 2500, date(2026, 9, 30))]
        return ReActRuntime(
            question="What benefits should I use before month-end?", as_of=date(2026, 9, 20),
            evaluate=lambda as_of: facts, retrieve_official=retrieve_official,
        )

    def test_typed_loop_retries_and_advances_past_duplicate_and_premature_steps(self):
        answer = self.runtime(lambda *args: [{"clause_id": "c", "citation": "guide#c", "clause_text": "terms", "terms_version": "t1"}]).run(RetryModel())
        self.assertGreaterEqual(answer.validation_retries, 1)
        self.assertEqual(answer.statuses[0].status, "unused")
        self.assertTrue(answer.values)
        self.assertTrue(answer.deadlines)

    def test_repeated_malformed_model_recovers_with_bounded_budget(self):
        answer = self.runtime(lambda *args: [{"clause_id": "c", "citation": "guide#c", "clause_text": "terms", "terms_version": "t1"}]).run(MalformedForeverModel())
        self.assertTrue(answer.statuses and answer.values and answer.deadlines)

    def test_repeated_malformed_model_exhausts_explicitly_when_budget_is_too_small(self):
        with self.assertRaisesRegex(ValueError, "exceeded step limit"):
            ReActRuntime(
                question="q", as_of=date(2026, 9, 20),
                evaluate=lambda as_of: [StatusResult("unused", (), ("benefit:x",), 0, 1, date(2026, 9, 30))],
                retrieve_official=None, max_steps=5,
            ).run(MalformedForeverModel())

    def test_openai_boundary_normalizes_list_for_community_tool(self):
        step = OpenAIModel(client=FakeOpenAIClient()).next("Which benefits are unused?", [])
        self.assertEqual(step["call"]["arguments"], {"benefit_ids": ["benefit-a", "benefit-b"]})

    def test_demo_connects_official_and_explicit_community_unavailable(self):
        def official(query, question, benefit_ids, as_of):
            return [{"clause_id": "hotel-clause", "citation": "guide#hotel", "clause_text": "Use by month end", "terms_version": "t1"}]

        answer = self.runtime(official).run(ScriptedModel())
        self.assertEqual(answer.citations[0].clause_id, "hotel-clause")
        self.assertFalse(answer.community["available"])
        self.assertEqual(answer.community["ideas"], [])


if __name__ == "__main__":
    unittest.main()
