"""Run PerkWatch evals and print a JSON report.

    uv run python evals/run.py [--suite tracker|retrieval|chat|perf|all] [--real]
        [--judge-model MODEL] [--judge-runs N] [--repeats N]

E1 tracker   : synthetic fixture (always); with --real also the local MaxRewards answer key.
E2 retrieval : recall@3 on the real prepared DB (--real and an OpenAI key only). Reports official-terms
               search (search_benefits) and community-tip search (search_community_ideas) separately,
               plus a combined recall.
E3 chat      : code checks + LLM judge; real DB with --real, else the synthetic fixture. Needs a key.
               --judge-model picks the judge (default gpt-4o-mini, kept for backward compatibility;
               gpt-4o is recommended for more reliable judging). --judge-runs averages N judge calls
               per case and reports the per-case spread alongside the mean.
perf         : cost and latency only (no judge calls), on a small fixed set of synthetic-fixture requests
               covering benefit_chat, wallet_ask (including a search_terms and a search_community_tips
               case) and the weekly briefing. --repeats controls how many times each request runs
               (default 1). Not part of --suite all: it is a repeatable measurement you size yourself
               (more repeats = steadier percentiles = more cost), not a pass/fail gate, and doubling
               every "all" run's cost by default isn't worth it. Run it on its own when you want
               cost/latency numbers.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from fixture import FixtureEmbedder, build_fixture  # noqa: E402
from suites import (CountingClient, JUDGE_MODEL, run_answer_key, run_chat, run_community_retrieval,  # noqa: E402
                    run_perf, run_retrieval, run_tracker)

CASES = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
SYNTHETIC_AS_OF = date(2026, 9, 26)


def data_dir() -> Path:
    return Path(os.environ.get("PERKWATCH_DATA_DIR", ROOT / "data" / "real"))


def open_real_db():
    from perk_watch.runtime.app import database
    db = database(data_dir())
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not {"benefits", "transactions", "benefit_embeddings"} <= tables or not db.execute(
            "SELECT COUNT(*) FROM benefit_embeddings").fetchone()[0]:
        raise RuntimeError("prepared DB is incomplete (preparation may be running); retry in a few minutes")
    return db


def openai_client():
    from perk_watch.embeddings import _api_key
    key = _api_key()
    if not key:
        return None
    from openai import OpenAI
    return CountingClient(OpenAI(api_key=key))


def tracker_suite(real: bool) -> dict:
    report = {"synthetic": run_tracker(build_fixture(), CASES["tracker"])}
    if real:
        key_path = data_dir() / "eval" / "maxrewards_answer_key.json"
        if key_path.exists():
            report["real"] = run_answer_key(open_real_db(), json.loads(key_path.read_text(encoding="utf-8")))
        else:
            report["real"] = {"skipped": f"no answer key at {key_path}"}
    return report


def retrieval_suite(real: bool, client) -> dict:
    """recall@3 on the real prepared DB: official terms (search_benefits) and community tips/ideas
    (search_community_ideas) reported separately, plus a combined recall across both case sets."""
    if not real:
        return {"skipped": "needs --real (the real prepared DB and its OpenAI embeddings)"}
    if client is None:
        return {"skipped": "OPENAI_API_KEY not set"}
    from perk_watch.embeddings import OpenAIEmbeddingProvider
    db = open_real_db()
    provider = OpenAIEmbeddingProvider(client)
    terms = run_retrieval(db, CASES["retrieval"], provider)
    community_cases = CASES.get("retrieval_community", [])
    community = run_community_retrieval(db, community_cases, provider)
    combined_cases = terms["cases"] + community["cases"]
    combined_hits = terms["hits"] + community["hits"]
    combined = {"cases": combined_cases, "hits": combined_hits,
                "recall_at_3": round(combined_hits / combined_cases, 3) if combined_cases else None}
    return {"terms": terms, "community": community, "combined": combined}


def chat_suite(real: bool, client, *, judge_model: str = JUDGE_MODEL, judge_runs: int = 1) -> dict:
    if client is None:
        return {"skipped": "OPENAI_API_KEY not set"}
    if real:
        from perk_watch.runtime.profile import load_marks
        report = run_chat(open_real_db(), CASES["chat"], as_of=date.today(), client=client,
                          marks=load_marks(data_dir()), judge_model=judge_model, judge_runs=judge_runs)
    else:
        report = run_chat(build_fixture(), CASES["chat"], as_of=SYNTHETIC_AS_OF, client=client,
                          embedder=FixtureEmbedder(), judge_model=judge_model, judge_runs=judge_runs)
    return {"data": "real" if real else "synthetic", **report}


def perf_suite(real: bool, client, *, repeats: int = 1) -> dict:
    """Cost/latency only; no judge calls. Real DB + marks with --real, else the synthetic fixture."""
    if client is None:
        return {"skipped": "OPENAI_API_KEY not set"}
    cases = CASES.get("perf", [])
    if not cases:
        return {"skipped": "no perf cases defined"}
    if real:
        from perk_watch.runtime.profile import load_marks
        report = run_perf(open_real_db(), cases, as_of=date.today(), client=client,
                          marks=load_marks(data_dir()), repeats=repeats)
    else:
        report = run_perf(build_fixture(), cases, as_of=SYNTHETIC_AS_OF, client=client,
                          embedder=FixtureEmbedder(), repeats=repeats)
    return {"data": "real" if real else "synthetic", "repeats": repeats, **report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", choices=["tracker", "retrieval", "chat", "perf", "all"], default="all")
    parser.add_argument("--real", action="store_true", help="also evaluate local real data under PERKWATCH_DATA_DIR")
    parser.add_argument("--judge-model", default=JUDGE_MODEL,
                        help=f"chat judge model (default {JUDGE_MODEL}, kept for backward compatibility; "
                             "gpt-4o is recommended)")
    parser.add_argument("--judge-runs", type=int, default=1,
                        help="judge calls to average per chat case (default 1)")
    parser.add_argument("--repeats", type=int, default=1,
                        help="repeats per perf case (default 1)")
    args = parser.parse_args(argv)
    # "all" stays tracker+retrieval+chat; perf is opt-in (see module docstring).
    suites = ["tracker", "retrieval", "chat"] if args.suite == "all" else [args.suite]
    client = openai_client() if {"retrieval", "chat", "perf"} & set(suites) else None
    report: dict = {}
    if "tracker" in suites:
        report["e1_tracker"] = tracker_suite(args.real)
    if "retrieval" in suites:
        report["e2_retrieval"] = retrieval_suite(args.real, client)
    if "chat" in suites:
        report["e3_chat"] = chat_suite(args.real, client, judge_model=args.judge_model, judge_runs=args.judge_runs)
    if "perf" in suites:
        report["perf"] = perf_suite(args.real, client, repeats=args.repeats)
    if client is not None:
        report["api_calls"] = client.calls
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return int(bool(report.get("e1_tracker", {}).get("synthetic", {}).get("mismatches")))


if __name__ == "__main__":
    raise SystemExit(main())
