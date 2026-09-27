"""Tool-using chat about one credit or the whole wallet, grounded in tracker results."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from typing import Any

from ..catalog import catalog_by_id
from .community import tips_for
from .retrieval.search import search_benefits
from .tracker import Marks, benefit_state, track

MODEL = "gpt-4o-mini"
MAX_TOOL_CALLS = 4

BENEFIT_SYSTEM = """You help a cardholder get value from ONE card benefit before it expires.
Rules:
- Dollar amounts, dates and days left must come from the BENEFIT CONTEXT or tool results. Never invent them.
- Official rules come from the terms. Community tips are ideas, not rules: label them "Community idea" and link the source.
- If the terms don't settle a question, say so and suggest checking the issuer's terms.
- Always open with one line stating the remaining amount and the deadline, whatever the question, then 3-5 short, specific bullet suggestions.
- If the benefit needs enrollment or the credit is only visible in an app, mention it.
- When asked whether it's worth it, use the history (e.g. "missed 8 of 8 months") to answer for this user."""

WALLET_SYSTEM = """You help a cardholder decide which card credits to use next, across all tracked benefits.
Rules:
- Dollar amounts, dates and days left must come from the WALLET CONTEXT or tool results. Never invent them.
- Prioritize credits that are at_risk (expiring soon with value left), then larger open balances.
- Use search_terms for questions about what a credit covers; label community tips "Community idea" with the source.
- Be brief: one summary line, then 3-5 bullets naming the benefit, the amount left and the deadline."""

TOOLS = [
    {"type": "function", "function": {
        "name": "get_benefit_status", "description": "Current period and history for one tracked benefit.",
        "parameters": {"type": "object", "properties": {"benefit_id": {"type": "string"}},
                       "required": ["benefit_id"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "search_terms", "description": "Semantic search over official issuer terms for all benefits on the user's cards.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                       "required": ["query"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "get_community_tips", "description": "Source-linked community tips for one benefit. Not official rules.",
        "parameters": {"type": "object", "properties": {"benefit_id": {"type": "string"}},
                       "required": ["benefit_id"], "additionalProperties": False}}},
]


def compact_status(state: dict, as_of: date) -> dict:
    """What the model may see: amounts and dates, never transaction descriptions."""
    c = state["current"]
    return {"benefit_id": state["benefit_id"], "title": state["title"], "card": state["card"],
            "period": state["period"], "tracking": state["tracking"],
            "enrollment_required": state.get("enrollment_required", False),
            "current_period": {"label": c["label"], "ends": c["end"], "days_left": c["days_left"],
                               "used": c["used_minor"] / 100, "remaining": c["remaining_minor"] / 100,
                               "amount": c["amount_minor"] / 100, "status": c["status"]},
            "history": [{"period": p["label"], "status": p["status"], "used": p["used_minor"] / 100,
                         "amount": p["amount_minor"] / 100} for p in state["periods"]],
            "missed_this_year": state["ytd"]["missed_minor"] / 100,
            "as_of": as_of.isoformat()}


_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")
_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d{1,2})?)(?![\w])")


def _norm(value: str) -> str:
    return f"{float(value.replace(',', '')):.2f}"


def unverified_amounts(answer: str, evidence_text: str) -> list[str]:
    """Dollar amounts in the answer that appear nowhere in the context or tool results."""
    known = {_norm(m) for m in _MONEY.findall(evidence_text)} | {_norm(m) for m in _NUMBER.findall(evidence_text)}
    return sorted({f"${m}" for m in _MONEY.findall(answer) if _norm(m) not in known})


def _default_client():
    from openai import OpenAI
    from ..embeddings import _api_key
    key = _api_key()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set (shell or .env)")
    return OpenAI(api_key=key)


class _Session:
    def __init__(self, db: sqlite3.Connection, as_of: date, marks: Marks | None, client: Any, embedder: Any, model: str):
        self.db, self.as_of, self.marks, self.model = db, as_of, marks or {}, model
        self.client = client or _default_client()
        self.embedder = embedder

    def run_tool(self, name: str, args: dict) -> object:
        if name == "get_benefit_status":
            if args.get("benefit_id") not in catalog_by_id():
                return {"error": f"not a tracked benefit; tracked ids: {sorted(catalog_by_id())}"}
            return compact_status(benefit_state(self.db, args["benefit_id"], self.as_of, self.marks), self.as_of)
        if name == "search_terms":
            if self.embedder is None:
                from ..embeddings import OpenAIEmbeddingProvider
                self.embedder = OpenAIEmbeddingProvider(self.client)
            hits = search_benefits(self.db, args["query"], embedder=self.embedder, limit=3)
            return [{"benefit_id": h["benefit_id"], "title": h["title"], "text": h["text"][:700],
                     "score": round(h["score"], 3)} for h in hits]
        if name == "get_community_tips":
            return [{"tip": t["tip"], "source_url": t["source_url"], "source_date": t["source_date"]}
                    for t in tips_for(self.db, args.get("benefit_id", ""))]
        return {"error": f"unknown tool: {name}"}

    def converse(self, system: str, context_text: str, messages: list[dict]) -> dict:
        convo: list[Any] = [{"role": "system", "content": system}, {"role": "system", "content": context_text}]
        convo += [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") in {"user", "assistant"}]
        evidence, trace, calls = [context_text], [], 0
        while True:
            # Offer tools until the budget is spent, then force a final answer.
            response = self.client.chat.completions.create(
                model=self.model, messages=convo, **({"tools": TOOLS} if calls < MAX_TOOL_CALLS else {}))
            message = response.choices[0].message
            if not message.tool_calls:
                answer = message.content or ""
                return {"answer": answer, "tool_trace": trace,
                        "unverified_amounts": unverified_amounts(answer, "\n".join(evidence))}
            convo.append(message)
            for call in message.tool_calls:
                calls += 1
                try:
                    args = json.loads(call.function.arguments or "{}")
                    result = self.run_tool(call.function.name, args)
                except Exception as exc:  # returned to the model so it can recover
                    args, result = {}, {"error": str(exc)}
                trace.append({"tool": call.function.name, "args": args})
                payload = json.dumps(result, default=str)
                evidence.append(payload)
                convo.append({"role": "tool", "tool_call_id": call.id, "content": payload})


def benefit_chat(db: sqlite3.Connection, benefit_id: str, messages: list[dict], *, as_of: date,
                 marks: Marks | None = None, client: Any = None, embedder: Any = None, model: str = MODEL) -> dict:
    state = benefit_state(db, benefit_id, as_of, marks)
    if state is None:
        raise KeyError(benefit_id)
    session = _Session(db, as_of, marks, client, embedder, model)
    context = {"status": compact_status(state, as_of), "official_terms": state["terms"][:2500],
               "community_tips": session.run_tool("get_community_tips", {"benefit_id": benefit_id})}
    return session.converse(BENEFIT_SYSTEM, "BENEFIT CONTEXT:\n" + json.dumps(context, indent=1), messages)


def wallet_ask(db: sqlite3.Connection, messages: list[dict], *, as_of: date, marks: Marks | None = None,
               client: Any = None, embedder: Any = None, model: str = MODEL) -> dict:
    wallet = []
    for state in track(db, as_of, marks)["benefits"]:
        item = compact_status(state, as_of)
        item.pop("history")
        wallet.append(item)
    session = _Session(db, as_of, marks, client, embedder, model)
    return session.converse(WALLET_SYSTEM, "WALLET CONTEXT:\n" + json.dumps(wallet, indent=1), messages)
