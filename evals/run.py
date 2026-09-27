"""Run PerkWatch evals and print a JSON report.

    uv run python evals/run.py [--suite tracker|retrieval|chat|all] [--real]

E1 tracker   : synthetic fixture (always); with --real also the local MaxRewards answer key.
E2 retrieval : recall@3 on the real prepared DB (--real and an OpenAI key only).
E3 chat      : code checks + LLM judge; real DB with --real, else the synthetic fixture. Needs a key.
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
from suites import CountingClient, run_answer_key, run_chat, run_retrieval, run_tracker  # noqa: E402

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
    if not real:
        return {"skipped": "needs --real (the real prepared DB and its OpenAI embeddings)"}
    if client is None:
        return {"skipped": "OPENAI_API_KEY not set"}
    from perk_watch.embeddings import OpenAIEmbeddingProvider
    return run_retrieval(open_real_db(), CASES["retrieval"], OpenAIEmbeddingProvider(client))


def chat_suite(real: bool, client) -> dict:
    if client is None:
        return {"skipped": "OPENAI_API_KEY not set"}
    if real:
        from perk_watch.runtime.profile import load_marks
        report = run_chat(open_real_db(), CASES["chat"], as_of=date.today(), client=client,
                          marks=load_marks(data_dir()))
    else:
        report = run_chat(build_fixture(), CASES["chat"], as_of=SYNTHETIC_AS_OF, client=client,
                          embedder=FixtureEmbedder())
    return {"data": "real" if real else "synthetic", **report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", choices=["tracker", "retrieval", "chat", "all"], default="all")
    parser.add_argument("--real", action="store_true", help="also evaluate local real data under PERKWATCH_DATA_DIR")
    args = parser.parse_args(argv)
    suites = ["tracker", "retrieval", "chat"] if args.suite == "all" else [args.suite]
    client = openai_client() if {"retrieval", "chat"} & set(suites) else None
    report: dict = {}
    if "tracker" in suites:
        report["e1_tracker"] = tracker_suite(args.real)
    if "retrieval" in suites:
        report["e2_retrieval"] = retrieval_suite(args.real, client)
    if "chat" in suites:
        report["e3_chat"] = chat_suite(args.real, client)
    if client is not None:
        report["api_calls"] = client.calls
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return int(bool(report.get("e1_tracker", {}).get("synthetic", {}).get("mismatches")))


if __name__ == "__main__":
    raise SystemExit(main())
