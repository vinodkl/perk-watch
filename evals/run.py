"""Evaluate the tool agent against a synthetic, deterministic fixture."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from openai import OpenAI
from fixture import open_fixture
from perk_watch.agent import EvidenceSelection, _render, answer_with_db
from perk_watch.search import BenefitSearch, CommunitySearch


class FixtureEmbedder:
    """Tiny deterministic word-vector provider; avoids external embedding calls."""
    model = "fixture-word-count-v1"
    words = ("airline", "fee", "credit", "travel", "hotel", "purchase", "monthly",
             "dining", "quarterly", "yearly", "calendar", "account", "year", "reset",
             "refund", "transaction", "merchant", "community", "suggestion", "eligible",
             "incidental", "unknown", "terms", "benefit", "cover", "booking")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(text.lower().count(word)) for word in self.words] for text in texts]


def _contains(actual, expected) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and _contains(actual[key], value)
                                                for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and all(any(_contains(item, wanted) for item in actual)
                                                for wanted in expected)
    return actual == expected


class PlannedAgentClient:
    """Deterministic tool-selection driver; the separate judge remains an LLM."""
    def __init__(self, plan: list[dict]):
        from types import SimpleNamespace
        self.plan = iter(plan)
        self.sent_plan = False
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **_kwargs):
        from types import SimpleNamespace
        if not self.sent_plan:
            self.sent_plan = True
            calls = [SimpleNamespace(id=f"eval-{i}", function=SimpleNamespace(
                name=item["tool"], arguments=json.dumps(item["arguments"])))
                for i, item in enumerate(self.plan)]
            message = SimpleNamespace(content=None, tool_calls=calls)
        else:
            indexes = []
            for item in _kwargs["messages"]:
                if not isinstance(item, dict) or item.get("role") != "tool":
                    continue
                try:
                    payload = json.loads(item["content"])
                except (TypeError, json.JSONDecodeError):
                    continue
                for row in (payload if isinstance(payload, list) else [payload]):
                    if isinstance(row, dict) and isinstance(row.get("evidence_index"), int):
                        indexes.append(row["evidence_index"])
            message = SimpleNamespace(content=json.dumps({"evidence_indices": sorted(set(indexes))}), tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


def tool_plan(case: dict) -> list[dict]:
    expected = case.get("expected", {})
    plan = []
    query = case.get("search_question") or case["question"]
    if case.get("search_question") or "evaluate_benefits" in expected.get("tool_results", {}):
        plan.append({"tool": "search_benefits", "arguments": {"question": query}})
    for tool, value in expected.get("tool_results", {}).items():
        if tool == "evaluate_benefits":
            args = {"benefit_id": value["benefit_id"]}
            args.update({key: expected.get("answer_fields", {}).get(key)
                         for key in ("as_of", "account_year_start")
                         if expected.get("answer_fields", {}).get(key)})
            plan.append({"tool": tool, "arguments": args})
        elif tool == "search_community_ideas":
            args = {"question": case["question"]}
            if case.get("community_benefit_id"):
                args["benefit_id"] = case["community_benefit_id"]
            plan.append({"tool": tool, "arguments": args})
    if expected.get("transaction_ids"):
        plan.append({"tool": "get_transaction_evidence",
                     "arguments": {"transaction_ids": expected["transaction_ids"]}})
    return plan


def factual_checks(expected: dict, tool_results: list[dict], answer: str) -> list[str]:
    failures = []
    for tool, wanted in expected.get("tool_results", {}).items():
        matches = [item["result"] for item in tool_results
                   if item["tool"] == tool and _contains(item["result"], wanted)]
        if not matches:
            failures.append(f"{tool}: expected structured result not returned")
            continue
        visible = [row for result in matches for row in (result if isinstance(result, list) else [result])]
        for row in visible:
            if row and json.dumps(row, ensure_ascii=False, indent=2, default=str) not in answer:
                failures.append(f"{tool}: matching tool result was not selected into the answer")
                break
    sources = {str(row.get("source_reference", {}).get("source_id"))
               for call in tool_results for row in (call["result"] if isinstance(call["result"], list) else [call["result"]])
               if isinstance(row, dict) and row.get("source_reference")}
    for source_id in expected.get("required_source_ids", []):
        if source_id not in sources or source_id not in answer:
            failures.append(f"required source ID missing from selected answer: {source_id}")
    tx_ids = {str(row.get("transaction_id")) for call in tool_results
              for row in (call["result"] if isinstance(call["result"], list) else [call["result"]])
              if isinstance(row, dict) and row.get("transaction_id")}
    for transaction_id in expected.get("transaction_ids", []):
        if transaction_id not in tx_ids or transaction_id not in answer:
            failures.append(f"required transaction ID missing from selected answer: {transaction_id}")
    fields = expected.get("answer_fields", {})
    if fields.get("community_suggestion") and "Community suggestions (not official rules)" not in answer:
        failures.append("community suggestion not labeled")
    if fields.get("must_preserve_unknown") and '"status": "unknown"' not in answer:
        failures.append("unknown status not shown")
    if fields.get("must_not_invent_suggestions") and "Community suggestions (not official rules)" in answer:
        failures.append("answer invented a community suggestion despite empty results")
    return failures


def request(client, usage: dict, **kwargs):
    for attempt in range(2):
        usage["calls"] += 1
        try:
            response = client.chat.completions.create(**kwargs)
            usage["tokens"] += getattr(response.usage, "total_tokens", 0) or 0
            return response
        except Exception:
            if attempt:
                usage["failures"] += 1
                raise
            usage["retries"] += 1


def reword(client, model: str, question: str, usage: dict) -> str:
    response = request(client, usage, model=model, messages=[
        {"role": "system", "content": "Rewrite the user's question as one concise search query. Preserve the intent and all named benefits. Return only the query."},
        {"role": "user", "content": question}])
    return (response.choices[0].message.content or question).strip()


def rerank(client, model: str, question: str, results: list[dict], usage: dict) -> list[dict]:
    if len(results) < 2:
        return results
    response = request(client, usage, model=model, response_format={"type": "json_object"}, messages=[
        {"role": "system", "content": "Order candidate benefit IDs by relevance to the question. Use each ID exactly once. Return JSON {\"ids\":[...]} only."},
        {"role": "user", "content": json.dumps({"question": question, "candidates": [
            {"benefit_id": row["benefit_id"], "title": row["title"], "text": row["text"][:1000]} for row in results]})}])
    try:
        ids = json.loads(response.choices[0].message.content)["ids"]
        by_id = {row["benefit_id"]: row for row in results}
        if len(ids) != len(results) or set(ids) != set(by_id):
            raise ValueError("reranker did not return a permutation of candidates")
        return [by_id[item] for item in ids]
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return results


def judge(client, model: str, question: str, evidence: list[dict], answer: str, usage: dict) -> dict:
    response = request(client, usage,
        model=model, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": "Score only clarity, usefulness, relevance, and whether the supplied evidence supports the explanation. Do not check factual amounts, dates, statuses, transaction IDs, or citations. Return JSON with integer scores 1-5 named clarity, usefulness, relevance, evidence_support, plus reason."},
                  {"role": "user", "content": json.dumps({"question": question, "evidence": evidence, "answer": answer})}])
    return json.loads(response.choices[0].message.content)


def main() -> int:
    cases = json.loads((ROOT / "evals/cases.json").read_text(encoding="utf-8"))
    client = OpenAI()
    model = os.getenv("PERKWATCH_EVAL_JUDGE_MODEL", "gpt-4o-mini")
    embedder = FixtureEmbedder()
    results = []
    api_usage = {"calls": 0, "tokens": 0, "failures": 0, "retries": 0}
    with open_fixture(ROOT / "evals/fixture.sqlite") as db:
        for case in cases:
            captured: list[dict] = []
            metrics: dict[str, int] = {}
            usage_before = api_usage.copy()
            started = time.perf_counter()
            # Route searches to this fixture and deterministic local embeddings only.
            with patch("perk_watch.agent.search_benefits",
                       side_effect=lambda conn, question, **kw: BenefitSearch(conn, embedder).search(question, **kw)), \
                 patch("perk_watch.agent.search_community_ideas",
                       side_effect=lambda conn, question, **kw: CommunitySearch(conn, embedder).search(question, **kw)):
                answer = answer_with_db(db, case["question"], client=PlannedAgentClient(tool_plan(case)), model=model,
                                        on_tool_result=lambda tool, result: captured.append({"tool": tool, "result": result}),
                                        metrics=metrics)
            planned_failures = factual_checks(case.get("expected", {}), captured, answer)
            live_captured: list[dict] = []
            live_metrics: dict[str, int] = {}
            live_started = time.perf_counter()
            with patch("perk_watch.agent.search_benefits",
                       side_effect=lambda conn, question, **kw: BenefitSearch(conn, embedder).search(question, **kw)), \
                 patch("perk_watch.agent.search_community_ideas",
                       side_effect=lambda conn, question, **kw: CommunitySearch(conn, embedder).search(question, **kw)):
                live_answer = answer_with_db(db, case["question"], client=client, model=model,
                                             on_tool_result=lambda tool, result: live_captured.append({"tool": tool, "result": result}),
                                             metrics=live_metrics)
            live_failures = factual_checks(case.get("expected", {}), live_captured, live_answer)
            basic = BenefitSearch(db, embedder).search(case.get("search_question", case["question"]))
            no_tool_answer = _render([{"tool": "search_benefits", "result": row} for row in basic],
                                     EvidenceSelection(evidence_indices=list(range(len(basic)))))
            rewritten_question = reword(client, model, case["question"], api_usage)
            rewritten = BenefitSearch(db, embedder).search(rewritten_question)
            reordered = rerank(client, model, case["question"], basic, api_usage)
            targets = set(case.get("relevant_benefit_ids", []))
            def hit(rows):
                return bool(targets.intersection(row["benefit_id"] for row in rows)) if targets else None
            tool_judge = judge(client, model, case["question"], live_captured, live_answer, api_usage)
            no_tool_judge = judge(client, model, case["question"], basic, no_tool_answer, api_usage)
            results.append({"id": case["id"], "question": case["question"], "tool_results": live_captured,
                            "answer": live_answer, "no_tool_answer": no_tool_answer,
                            "fixture_check_failures": planned_failures, "live_agent_failures": live_failures,
                            "judge": {"with_tools": tool_judge, "without_tools": no_tool_judge},
                            "live_agent_elapsed_seconds": round(time.perf_counter() - live_started, 3),
                            "live_agent_metrics": live_metrics,
                            "search": {"basic_hit_at_5": hit(basic), "rewritten_query": rewritten_question,
                                       "rewritten_hit_at_5": hit(rewritten), "reranked_top_hit": hit(reordered[:1]),
                                       "basic_ids": [row["benefit_id"] for row in basic],
                                       "reranked_ids": [row["benefit_id"] for row in reordered]},
                            "elapsed_seconds": round(time.perf_counter() - started, 3),
                            "external_model_calls": api_usage["calls"] - usage_before["calls"],
                            "external_tokens": api_usage["tokens"] - usage_before["tokens"],
                            "external_failures": api_usage["failures"] - usage_before["failures"],
                            "external_retries": api_usage["retries"] - usage_before["retries"],
                            "planned_agent_metrics": metrics})
    report = {"fixture": "evals/fixture.sqlite (synthetic; rebuilt for this run)",
              "passed": sum(not item["fixture_check_failures"] for item in results),
              "live_agent_passed": sum(not item["live_agent_failures"] for item in results),
              "total": len(results), "tool_selection": "live model; deterministic planned calls also checked",
              "api_usage": api_usage, "results": results}
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return int(any(item["fixture_check_failures"] for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
