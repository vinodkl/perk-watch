"""Tool-using chat about one credit or the whole wallet, grounded in tracker results."""
from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import date
from typing import Any

from ..catalog import catalog_by_id
from .community import tips_for
from .retrieval.search import search_benefits, search_community_ideas
from .tracker import Marks, benefit_state, track

MODEL = "gpt-4o-mini"
MAX_TOOL_CALLS = 4

# List prices in USD per million tokens; update these if OpenAI's pricing changes.
PRICES_PER_MTOK = {"gpt-4o-mini": {"input": 0.15, "output": 0.60}}

BENEFIT_SYSTEM = """You help a cardholder get value from ONE card benefit before it expires.
Rules:
- Dollar amounts, dates and days left must come from the BENEFIT CONTEXT or tool results. Never invent them.
- Official rules come from the terms or search_terms. Any tip from context (community_tips), get_community_tips,
  or search_community_tips is an idea, not a rule: whenever you mention it or its link, write the literal words
  "Community idea" right next to that link, every time, with no exceptions.
- If the terms don't settle a question, say so and suggest checking the issuer's terms.
- Always open with one line stating the remaining amount and the deadline, whatever the question, then 3-5 short, specific bullet suggestions.
- If the benefit needs enrollment or the credit is only visible in an app, mention it.
- When asked whether it's worth it, use the history (e.g. "missed 8 of 8 months") to answer for this user.
- If the user says they used a manual credit (tracking = manual) this period, call propose_mark and tell them to tap the button to confirm. Never say it is already marked."""

WALLET_SYSTEM = """You help a cardholder decide which card credits to use next, across all tracked benefits.
Rules:
- Dollar amounts, dates and days left must come from the WALLET CONTEXT or tool results. Never invent them.
- Prioritize credits that are at_risk (expiring soon with value left), then larger open balances.
- Use search_terms for what a credit officially covers or its rules. For "what do people do"/"how do I use it"
  ideas, call search_community_tips (it searches every card's community tips, not just one benefit);
  get_community_tips is only for the weekly plan. Any tip from search_community_tips or get_community_tips is
  never an official rule: whenever you mention it or its link, write the literal words "Community idea" right
  next to that link, every time, with no exceptions.
- Be brief: one summary line, then 3-5 bullets naming the benefit, the amount left and the deadline.
- If the user says they used a manual credit (tracking = manual) this period, call propose_mark and tell them to tap the button to confirm. Never say it is already marked.
- The WALLET CONTEXT shows only the current period. For anything about past periods, history, reliability or misses, call get_benefit_status for each credit involved before answering; never infer history from the current period."""

BRIEFING_SYSTEM = """You write a short plan for this week, shown at the top of a cardholder's credit tracker.
Rules:
- Dollar amounts, dates and days left must come from the WALLET CONTEXT or tool results. Never invent them.
- Write exactly 3 bullets, most urgent first: at_risk credits (value left, ending soon), then the largest open balances.
- Each bullet starts with the benefit title in bold, then the amount left and the deadline, then one concrete action.
- Call get_community_tips for the most urgent credit and add its best idea to that bullet, labelled "Community idea".
- For manual credits (tracking = manual), remind the user to mark them once used.
- If nothing is at_risk, say so in the first bullet and plan around the largest open balances.
- The WALLET CONTEXT is already sorted by urgency, most urgent first. Keep that order; do not skip items to reach smaller ones.
- No greeting, no intro line, no closing line."""

BRIEFING_REQUEST = "Write this week's plan."

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
    {"type": "function", "function": {
        "name": "search_community_tips",
        "description": "Semantic search over community tips and ideas across all benefits on the user's cards, "
                       "for questions about how cardholders use a credit. Not official rules.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                       "required": ["query"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "propose_mark", "description": "Offer the user a one-tap button to mark a manually tracked credit used for its current period. It marks nothing; the user must tap to confirm.",
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


def summarize_result(name: str, result: object, args: dict | None = None) -> str:
    """One line for the UI's step list: what a tool call found. Never transaction text."""
    if isinstance(result, dict) and "error" in result:
        return f"error: {str(result['error'])[:120]}"
    if name == "get_benefit_status" and isinstance(result, dict):
        current = result["current_period"]
        return f"{result['title']}: ${current['remaining']:.2f} left, {current['status']}"
    if name == "search_terms" and isinstance(result, list):
        return "found " + ", ".join(hit["title"] for hit in result) if result else "no matching terms"
    if name == "get_community_tips" and isinstance(result, list):
        summary = f"{len(result)} community tip{'' if len(result) == 1 else 's'}"
        benefit_id = (args or {}).get("benefit_id")
        catalog = catalog_by_id()
        if benefit_id in catalog:
            summary += f" for {catalog[benefit_id].title}"
        return summary
    if name == "search_community_tips" and isinstance(result, list):
        if not result:
            return "no matching community tips"
        titles = ", ".join(dict.fromkeys(hit["benefit"] for hit in result))
        return f"found {len(result)} community tip{'' if len(result) == 1 else 's'}: {titles}"
    if name == "propose_mark" and isinstance(result, dict) and "proposal" in result:
        p = result["proposal"]
        return f"offered to mark {p['title']} ({p['period_label']}) used; waiting for your tap"
    return ""


def _cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    prices = PRICES_PER_MTOK.get(model)
    if not prices:
        return 0.0
    cost = (prompt_tokens * prices["input"] + completion_tokens * prices["output"]) / 1_000_000
    return round(cost, 6)


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
        self.proposals: list[dict] = []

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
        if name == "search_community_tips":
            if self.embedder is None:
                from ..embeddings import OpenAIEmbeddingProvider
                self.embedder = OpenAIEmbeddingProvider(self.client)
            hits = search_community_ideas(self.db, args["query"], embedder=self.embedder, limit=3)
            # Never transaction descriptions or account data; only tip/idea text, dates and public URLs.
            return [{"benefit_id": h["benefit_id"], "benefit": h["benefit"], "card": h["card"],
                     "tip": h.get("tip") or h.get("idea", ""), "source_url": h["source_url"],
                     "source_date": h["source_date"], "label": h["label"]} for h in hits]
        if name == "propose_mark":
            state = benefit_state(self.db, args["benefit_id"], self.as_of, self.marks) if args.get("benefit_id") in catalog_by_id() else None
            if state is None or state["tracking"] != "manual":
                return {"error": "only manually tracked credits can be marked"}
            current = state["current"]
            if current["marked"]:
                return {"error": "already marked for this period"}
            proposal = {"benefit_id": state["benefit_id"], "title": state["title"], "period_start": current["start"],
                        "period_label": current["label"], "amount": current["amount_minor"] / 100}
            if all(p["benefit_id"] != proposal["benefit_id"] for p in self.proposals):
                self.proposals.append(proposal)
            return {"proposal": proposal, "note": "Shown to the user as a button. Not marked until they tap it."}
        return {"error": f"unknown tool: {name}"}

    def converse(self, system: str, context_text: str, messages: list[dict]) -> dict:
        convo: list[Any] = [{"role": "system", "content": system}, {"role": "system", "content": context_text}]
        convo += [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") in {"user", "assistant"}]
        evidence, trace, calls = [context_text], [], 0
        model_calls = prompt_tokens = completion_tokens = total_tokens = 0
        started = time.perf_counter()
        while True:
            # Offer tools until the budget is spent, then force a final answer.
            response = self.client.chat.completions.create(
                model=self.model, messages=convo, **({"tools": TOOLS} if calls < MAX_TOOL_CALLS else {}))
            model_calls += 1
            usage = getattr(response, "usage", None)
            prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens += getattr(usage, "completion_tokens", 0) or 0
            total_tokens += getattr(usage, "total_tokens", 0) or 0
            message = response.choices[0].message
            if not message.tool_calls:
                answer = message.content or ""
                latency_ms = int((time.perf_counter() - started) * 1000)
                return {"answer": answer, "tool_trace": trace,
                        "unverified_amounts": unverified_amounts(answer, "\n".join(evidence)),
                        "amounts_checked": len({_norm(m) for m in _MONEY.findall(answer)}), "model": self.model,
                        "proposals": self.proposals,
                        "usage": {"model_calls": model_calls, "prompt_tokens": prompt_tokens,
                                  "completion_tokens": completion_tokens, "total_tokens": total_tokens},
                        "latency_ms": latency_ms,
                        "cost_usd": _cost_usd(self.model, prompt_tokens, completion_tokens)}
            convo.append(message)
            for call in message.tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except Exception as exc:  # returned to the model so it can recover
                    args, result = {}, {"error": str(exc)}
                else:
                    if calls >= MAX_TOOL_CALLS:
                        result = {"error": "tool budget spent; answer with what you have"}
                    else:
                        calls += 1
                        try:
                            result = self.run_tool(call.function.name, args)
                        except Exception as exc:
                            result = {"error": str(exc)}
                summary = "skipped: tool budget spent" if result == {"error": "tool budget spent; answer with what you have"} \
                    else summarize_result(call.function.name, result, args)
                trace.append({"tool": call.function.name, "args": args, "summary": summary})
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


def _wallet_context(db: sqlite3.Connection, as_of: date, marks: Marks | None) -> str:
    """Current period of every credit, without per-period history, to keep the context small.
    Sorted most urgent first so a truncating or lazy model still sees the top priorities."""
    wallet = []
    for state in track(db, as_of, marks)["benefits"]:
        item = compact_status(state, as_of)
        item.pop("history")
        wallet.append(item)
    wallet.sort(key=lambda item: (0 if item["current_period"]["status"] == "at_risk" else 1,
                                  -item["current_period"]["remaining"]))
    return "WALLET CONTEXT:\n" + json.dumps(wallet, indent=1)


def wallet_ask(db: sqlite3.Connection, messages: list[dict], *, as_of: date, marks: Marks | None = None,
               client: Any = None, embedder: Any = None, model: str = MODEL) -> dict:
    session = _Session(db, as_of, marks, client, embedder, model)
    return session.converse(WALLET_SYSTEM, _wallet_context(db, as_of, marks), messages)


def wallet_briefing(db: sqlite3.Connection, *, as_of: date, marks: Marks | None = None,
                    client: Any = None, embedder: Any = None, model: str = MODEL) -> dict:
    session = _Session(db, as_of, marks, client, embedder, model)
    return session.converse(BRIEFING_SYSTEM, _wallet_context(db, as_of, marks),
                            [{"role": "user", "content": BRIEFING_REQUEST}])
