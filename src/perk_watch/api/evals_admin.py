"""Backs the Evals admin tab: reruns eval suites against synthetic fixtures only.

Never touches real data. `retrieval` has no synthetic mode (it needs the real prepared
DB and its embeddings, per evals/run.py), so it is always reported as CLI-only here.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "evals"))
from fixture import FixtureEmbedder, build_fixture  # noqa: E402
from suites import CountingClient, run_chat, run_tracker  # noqa: E402

CASES = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
SYNTHETIC_AS_OF = date(2026, 9, 26)

SUITES: dict[str, dict[str, Any]] = {
    "tracker": {"title": "Tracker", "rerunnable": True, "network": False, "call_estimate": 0,
                "description": "Every synthetic period's status and amount. No network, no cost."},
    "retrieval": {"title": "Retrieval", "rerunnable": False, "network": True, "call_estimate": None,
                  "description": "recall@3 on the real prepared DB and its OpenAI embeddings. "
                                  "Has no synthetic mode; run it from the CLI with --real."},
    "chat": {"title": "Chat", "rerunnable": True, "network": True, "call_estimate": 2 * len(CASES["chat"]),
             "description": "Code checks plus an LLM judge, on the synthetic fixture."},
}

def _run_tracker() -> dict:
    return {"synthetic": run_tracker(build_fixture(), CASES["tracker"])}


def _run_chat(client: Any) -> dict:
    return run_chat(build_fixture(), CASES["chat"], as_of=SYNTHETIC_AS_OF, client=client, embedder=FixtureEmbedder())


def _default_client() -> Any:
    from ..embeddings import _api_key
    key = _api_key()
    if not key:
        return None
    from openai import OpenAI
    return CountingClient(OpenAI(api_key=key))


class EvalsAdmin:
    """One instance per running app: state never leaks across app instances or tests."""

    def __init__(self, *, chat_client: Any = None) -> None:
        self._chat_client = chat_client
        self._lock = threading.Lock()
        self._state: dict[str, dict[str, Any]] = {
            name: {"status": "idle", "result": None, "started_at": None, "finished_at": None, "error": None}
            for name in SUITES
        }

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {name: {**SUITES[name], **self._state[name]} for name in SUITES}

    def start(self, name: str) -> None:
        """Kick off a background run. No-op if that suite is already running."""
        if name not in SUITES:
            raise KeyError(name)
        if not SUITES[name]["rerunnable"]:
            raise ValueError(f"{name} has no synthetic mode; run it from the CLI with --real")
        with self._lock:
            if self._state[name]["status"] == "running":
                return
            self._state[name] = {"status": "running", "result": None, "started_at": time.time(),
                                  "finished_at": None, "error": None}

        def worker() -> None:
            try:
                if name == "tracker":
                    result = _run_tracker()
                else:
                    client = self._chat_client if self._chat_client is not None else _default_client()
                    if client is None:
                        raise RuntimeError("OPENAI_API_KEY not set")
                    result = _run_chat(client)
                with self._lock:
                    self._state[name].update(status="done", result=result, finished_at=time.time())
            except Exception as error:  # background thread: surface to the UI, never crash silently
                with self._lock:
                    self._state[name].update(status="error", error=str(error), finished_at=time.time())

        threading.Thread(target=worker, daemon=True).start()
