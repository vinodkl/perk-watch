"""PROTOTYPE (throwaway): benefit tracker page + per-benefit chat over real prepared data.

Run:  uv run --extra ui python prototype/app_proto.py   then open http://127.0.0.1:8765
Manual "mark used" state lives in memory only and is lost on restart.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tracker_proto import BY_ID, community_for, open_db, track  # noqa: E402

from perk_watch.embeddings import OpenAIEmbeddingProvider, _api_key  # noqa: E402
from perk_watch.runtime.retrieval.search import search_benefits  # noqa: E402

MODEL = "gpt-4o-mini"
MAX_TOOL_CALLS = 4
AS_OF = date.fromisoformat(os.environ.get("PROTO_AS_OF", date.today().isoformat()))

db = open_db()
marks: dict[tuple[str, str], int] = {}
blurbs: dict[str, dict] = {}
_client = None


def client():
    global _client
    if _client is None:
        from openai import OpenAI
        key = _api_key()
        if not key:
            raise HTTPException(503, "OPENAI_API_KEY is not set (shell or .env)")
        _client = OpenAI(api_key=key)
    return _client


def _as_of(value: str | None) -> date:
    return date.fromisoformat(value) if value else AS_OF


def benefit_state(benefit_id: str, as_of: date = AS_OF) -> dict:
    state = next((b for b in track(db, as_of, marks)["benefits"] if b["benefit_id"] == benefit_id), None)
    if state is None:
        raise HTTPException(404, "unknown benefit")
    return state


def compact_status(state: dict, as_of: date = AS_OF) -> dict:
    """What the model may see: amounts and dates, never transaction descriptions."""
    c = state["current"]
    return {"benefit_id": state["benefit_id"], "title": state["title"], "card": state["card"],
            "period": state["period"], "tracking": state["tracking"],
            "current_period": {"label": c["label"], "ends": c["end"], "days_left": c["days_left"],
                               "used": c["used_minor"] / 100, "remaining": c["remaining_minor"] / 100,
                               "amount": c["amount_minor"] / 100, "status": c["status"]},
            "history": [{"period": p["label"], "status": p["status"], "used": p["used_minor"] / 100,
                         "amount": p["amount_minor"] / 100} for p in state["periods"]],
            "missed_this_year": state["ytd"]["missed_minor"] / 100,
            "as_of": as_of.isoformat()}


# ---- tools the chat model can call -------------------------------------------------------

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


def run_tool(name: str, args: dict, as_of: date = AS_OF) -> object:
    if name == "get_benefit_status":
        if args["benefit_id"] not in BY_ID:
            return {"error": f"not a tracked benefit; tracked ids: {sorted(BY_ID)}"}
        return compact_status(benefit_state(args["benefit_id"], as_of), as_of)
    if name == "search_terms":
        hits = search_benefits(db, args["query"], embedder=OpenAIEmbeddingProvider(client()), limit=3)
        return [{"benefit_id": h["benefit_id"], "title": h["title"], "text": h["text"][:700],
                 "score": round(h["score"], 3)} for h in hits]
    if name == "get_community_tips":
        return [{"tip": t["tip"], "source_url": t["source_url"], "source_date": t.get("source_date", "")}
                for t in community_for(db, args["benefit_id"])]
    return {"error": "unknown tool"}


# ---- grounding check -------------------------------------------------------------------

_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{1,2})?)")


def _norm(value: str) -> str:
    number = float(value.replace(",", ""))
    return f"{number:.2f}"


def unverified_amounts(answer: str, evidence_text: str) -> list[str]:
    """Dollar amounts in the answer that appear nowhere in the context or tool results."""
    known = {_norm(m) for m in _MONEY.findall(evidence_text)}
    known |= {_norm(m) for m in re.findall(r"(?<![\w.])(\d+(?:\.\d{1,2})?)(?![\w])", evidence_text)}
    return sorted({f"${m}" for m in _MONEY.findall(answer) if _norm(m) not in known})


SYSTEM = """You help a cardholder get value from ONE card benefit before it expires.
Rules:
- Dollar amounts, dates and days left must come from the BENEFIT CONTEXT or tool results. Never invent them.
- Official rules come from the terms. Community tips are ideas, not rules: label them "Community idea" and link the source.
- If the terms don't settle a question, say so and suggest checking the issuer's terms.
- Be concrete and brief: start with one line on what's left and the deadline, then 3-5 short bullet suggestions.
- If the benefit needs enrollment or the credit is only visible in an app, mention it.
- When asked whether it's worth it, use the history (e.g. "missed 8 of 8 months") to answer for this user."""


ASK_SYSTEM = """You help a cardholder decide which card credits to use next, across all tracked benefits.
Rules:
- Dollar amounts, dates and days left must come from the WALLET CONTEXT or tool results. Never invent them.
- Prioritize credits that are at_risk (expiring soon with value left), then larger open balances.
- Use search_terms for questions about what a credit covers; label community tips "Community idea" with the source.
- Be brief: one summary line, then 3-5 bullets naming the benefit, the amount left and the deadline."""


class ChatRequest(BaseModel):
    messages: list[dict]
    as_of: str | None = None


class MarkRequest(BaseModel):
    period_start: str
    amount_minor: int | None = None
    as_of: str | None = None


def chat(benefit_id: str, messages: list[dict], as_of: date = AS_OF) -> dict:
    state = benefit_state(benefit_id, as_of)
    context = {"status": compact_status(state, as_of), "official_terms": state["terms"][:2500],
               "community_tips": run_tool("get_community_tips", {"benefit_id": benefit_id})}
    return _converse(SYSTEM, "BENEFIT CONTEXT:\n" + json.dumps(context, indent=1), messages, as_of)


def ask(messages: list[dict], as_of: date = AS_OF) -> dict:
    wallet = [compact_status(b, as_of) for b in track(db, as_of, marks)["benefits"]]
    for item in wallet:
        item.pop("history")
    return _converse(ASK_SYSTEM, "WALLET CONTEXT:\n" + json.dumps(wallet, indent=1), messages, as_of)


def _converse(system: str, context_text: str, messages: list[dict], as_of: date) -> dict:
    convo = [{"role": "system", "content": system}, {"role": "system", "content": context_text}]
    convo += [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") in {"user", "assistant"}]
    evidence = [context_text]
    trace, calls = [], 0
    while True:
        response = client().chat.completions.create(
            model=MODEL, messages=convo, tools=TOOLS if calls < MAX_TOOL_CALLS else None)
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
                result = run_tool(call.function.name, args, as_of)
            except Exception as exc:  # surfaced to the model so it can recover
                args, result = {}, {"error": str(exc)}
            trace.append({"tool": call.function.name, "args": args})
            payload = json.dumps(result, default=str)
            evidence.append(payload)
            convo.append({"role": "tool", "tool_call_id": call.id, "content": payload})


def blurb(benefit_id: str) -> dict:
    if benefit_id in blurbs:
        return blurbs[benefit_id]
    tips = community_for(db, benefit_id)
    if not tips:
        result = {"blurb": "", "tips": []}
    else:
        prompt = ("In at most 2 short sentences, summarize what cardholders do with this benefit, "
                  "based only on these tips. Start with 'People'. No links.\n" +
                  "\n".join(f"- {t['tip']}" for t in tips))
        response = client().chat.completions.create(model=MODEL, messages=[{"role": "user", "content": prompt}])
        result = {"blurb": response.choices[0].message.content.strip(), "tips": tips}
    blurbs[benefit_id] = result
    return result


app = FastAPI(title="PerkWatch tracker prototype")


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return (Path(__file__).parent / "page_proto.html").read_text()


@app.get("/api/tracker")
def tracker(as_of: str | None = None) -> dict:
    return track(db, _as_of(as_of), marks)


@app.post("/api/benefits/{benefit_id}/mark")
def mark(benefit_id: str, request: MarkRequest) -> dict:
    state = benefit_state(benefit_id, _as_of(request.as_of))
    period = next((p for p in state["periods"] if p["start"] == request.period_start), None)
    if period is None:
        raise HTTPException(400, "unknown period")
    key = (benefit_id, request.period_start)
    if key in marks:
        del marks[key]
    else:
        marks[key] = request.amount_minor or period["amount_minor"]
    return benefit_state(benefit_id, _as_of(request.as_of))


@app.get("/api/benefits/{benefit_id}/community")
def community(benefit_id: str) -> dict:
    return blurb(benefit_id)


@app.post("/api/benefits/{benefit_id}/chat")
def benefit_chat(benefit_id: str, request: ChatRequest) -> dict:
    return chat(benefit_id, request.messages, _as_of(request.as_of))


@app.post("/api/ask")
def wallet_ask(request: ChatRequest) -> dict:
    return ask(request.messages, _as_of(request.as_of))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PROTO_PORT", "8765")))
