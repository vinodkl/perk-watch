import json
import sqlite3
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from perk_watch.agent import answer_with_db


class FakeClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return next(self.replies)


def response(content=None, calls=()):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls))])


def tool_call(name, args, call_id="call-1"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def select(*indices):
    return json.dumps({"evidence_indices": list(indices)})


def search_call():
    return tool_call("search_benefits", {"question": "benefit"})


def search_result(benefit_id="missing"):
    return [{"benefit_id": benefit_id, "source_reference": {"source_id": "terms", "path": "terms.json"}}]


def missing_benefit(*_args, **_kwargs):
    return {"benefit_id": "missing", "status": "unknown", "reason": "benefit was not found",
            "supporting_transaction_ids": []}


class Phase3Tests(unittest.TestCase):
    def test_system_prompt_requires_exact_search_result_ids_before_calculation(self):
        client = FakeClient([response(select())])
        answer_with_db(sqlite3.connect(":memory:"), "check a benefit", client=client)
        instructions = client.requests[0]["messages"][0]["content"]
        self.assertIn("Never guess a benefit_id", instructions)
        self.assertIn("call search_benefits", instructions)
        self.assertIn("exact benefit_id", instructions)

    def test_missing_benefit_is_reported_without_inventing_details(self):
        client = FakeClient([
            response(calls=[search_call()]),
            response(calls=[tool_call("evaluate_benefits", {"benefit_id": "missing"})]),
            response(select(1)),
        ])
        with patch("perk_watch.agent.search_benefits", return_value=search_result()), \
             patch("perk_watch.agent.calculate_benefit", side_effect=missing_benefit):
            result = answer_with_db(sqlite3.connect(":memory:"), "check benefit", client=client)
        self.assertIn('"reason": "benefit was not found"', result)

    def test_invalid_call_stops_at_retry_limit(self):
        client = FakeClient([response(calls=[tool_call("not_a_tool", {})])])
        result = answer_with_db(sqlite3.connect(":memory:"), "check", client=client, max_retries=0)
        self.assertIn("couldn't answer safely", result)

    def test_bad_schema_and_extra_arguments_are_rejected(self):
        client = FakeClient([response(calls=[tool_call("evaluate_benefits", {"benefit_id": 2, "extra": True})])])
        result = answer_with_db(sqlite3.connect(":memory:"), "check", client=client, max_retries=0)
        self.assertIn("couldn't answer safely", result)

    def test_identical_calls_are_rejected(self):
        client = FakeClient([
            response(calls=[search_call()]),
            response(calls=[tool_call("evaluate_benefits", {"benefit_id": "missing"})]),
            response(calls=[tool_call("evaluate_benefits", {"benefit_id": "missing"}, "call-2")]),
            response(select(1)),
        ])
        with patch("perk_watch.agent.search_benefits", return_value=search_result()), \
             patch("perk_watch.agent.calculate_benefit", side_effect=missing_benefit):
            result = answer_with_db(sqlite3.connect(":memory:"), "check", client=client)
        self.assertIn("Benefit calculation", result)
        self.assertTrue(any("repeated identical tool call" in message["content"]
                            for request in client.requests for message in request["messages"]
                            if isinstance(message, dict) and message.get("role") == "tool"))

    def test_unverified_numeric_claim_is_withheld(self):
        client = FakeClient([
            response(calls=[search_call()]),
            response(calls=[tool_call("evaluate_benefits", {"benefit_id": "missing"})]),
            response('{"evidence_indices": [1], "answer": "You have $500 remaining."}'),
        ])
        with patch("perk_watch.agent.search_benefits", return_value=search_result()), \
             patch("perk_watch.agent.calculate_benefit", side_effect=missing_benefit):
            result = answer_with_db(sqlite3.connect(":memory:"), "check", client=client)
        self.assertIn("Benefit calculation", result)
        self.assertNotIn("$500 remaining", result)

    def test_calculated_transaction_evidence_is_read_only(self):
        db = sqlite3.connect(":memory:")
        db.execute("CREATE TABLE transactions (transaction_id, posted_date, description, amount_minor, currency, merchant)")
        db.execute("INSERT INTO transactions VALUES ('tx1', '2025-01-02', 'CARD CREDIT', 2500, 'USD', 'Store')")
        db.commit()
        changes = db.total_changes
        client = FakeClient([
            response(calls=[search_call()]),
            response(calls=[tool_call("evaluate_benefits", {"benefit_id": "b1"})]),
            response(calls=[tool_call("get_transaction_evidence", {"transaction_ids": ["tx1"]}, "call-2")]),
            response(select(2)),
        ])
        calculated = {"benefit_id": "b1", "status": "available", "remaining_amount_minor": 2500,
                      "deadline": "2025-01-31", "supporting_transaction_ids": ["tx1"]}
        with patch("perk_watch.agent.search_benefits", return_value=search_result("b1")), \
             patch("perk_watch.agent.calculate_benefit", return_value=calculated):
            result = answer_with_db(db, "what transaction supports this?", client=client)
        self.assertIn('"transaction_id": "tx1"', result)
        self.assertIn('"amount_minor": 2500', result)
        self.assertEqual(db.total_changes, changes)
        db.close()

    def test_transaction_evidence_requires_calculation_ids(self):
        client = FakeClient([response(calls=[tool_call("get_transaction_evidence", {"transaction_ids": ["guessed"]})])])
        result = answer_with_db(sqlite3.connect(":memory:"), "check", client=client, max_retries=0)
        self.assertIn("couldn't answer safely", result)

    def test_call_limit(self):
        client = FakeClient([response(calls=[tool_call("not_a_tool", {}, "1")])])
        result = answer_with_db(sqlite3.connect(":memory:"), "check", client=client, max_calls=1)
        self.assertIn("tool-call limit", result)
        self.assertIn("No usable evidence was collected.", result)

    def test_call_limit_returns_evidence_already_collected(self):
        found = [{"benefit_id": "b1", "source_reference": {"source_id": "s1", "path": "terms.pdf"},
                  "text": "Official benefit terms"}]
        client = FakeClient([response(calls=[tool_call("search_benefits", {"question": "credit"})])])
        with patch("perk_watch.agent.search_benefits", return_value=found):
            result = answer_with_db(sqlite3.connect(":memory:"), "check", client=client, max_calls=1)
        self.assertIn("Partial results", result)
        self.assertIn("Official benefit search", result)
        self.assertIn("terms.pdf", result)
    def test_calculation_facts_must_be_in_tool_results(self):
        client = FakeClient([
            response(calls=[search_call()]),
            response(calls=[tool_call("evaluate_benefits", {"benefit_id": "b1"})]),
            response(select(1)),
        ])
        result = {"benefit_id": "b1", "status": "available", "remaining_amount_minor": 5000,
                  "deadline": "2025-12-31", "supporting_transaction_ids": []}
        with patch("perk_watch.agent.search_benefits", return_value=search_result("b1")), \
             patch("perk_watch.agent.calculate_benefit", return_value=result):
            result_text = answer_with_db(sqlite3.connect(":memory:"), "how much remains?", client=client)
        self.assertIn('"remaining_amount_minor": 5000', result_text)
        self.assertIn('"deadline": "2025-12-31"', result_text)

    def test_invalid_evidence_index_falls_back_to_valid_results(self):
        found = [{"benefit_id": "b1", "source_reference": {"source_id": "s1", "path": "terms.pdf"}, "text": "Benefit terms"}]
        client = FakeClient([
            response(calls=[tool_call("search_benefits", {"question": "credit"})]),
            response(select(99)),
        ])
        with patch("perk_watch.agent.search_benefits", return_value=found):
            result = answer_with_db(sqlite3.connect(":memory:"), "credit", client=client)
        self.assertIn('"source_id": "s1"', result)

    def test_calculation_selection_keeps_matching_official_citation(self):
        found = [{"benefit_id": "b1", "source_reference": {"source_id": "s1", "path": "terms.pdf"}, "text": "Benefit terms"}]
        client = FakeClient([
            response(calls=[tool_call("search_benefits", {"question": "credit"})]),
            response(calls=[tool_call("evaluate_benefits", {"benefit_id": "b1"})]),
            response(select(1)),
        ])
        with patch("perk_watch.agent.search_benefits", return_value=found), \
             patch("perk_watch.agent.calculate_benefit", return_value={"benefit_id": "b1", "status": "available"}):
            result = answer_with_db(sqlite3.connect(":memory:"), "how much remains?", client=client)
        self.assertIn("Official benefit search", result)
        self.assertIn('"source_id": "s1"', result)
        self.assertIn("Benefit calculation", result)

    def test_search_and_calculation_answers_only_use_returned_numbers(self):
        found = [{"benefit_id": "b1", "source_reference": {"source_id": "s1", "path": "terms.pdf"}, "text": "Benefit terms"}]
        client = FakeClient([
            response(calls=[tool_call("search_benefits", {"question": "travel credit"})]),
            response(select(0)),
        ])
        with patch("perk_watch.agent.search_benefits", return_value=found):
            result = answer_with_db(sqlite3.connect(":memory:"), "travel credit", client=client)
        self.assertIn("Official benefit search", result)
        self.assertIn('"source_id": "s1"', result)


if __name__ == "__main__":
    unittest.main()
