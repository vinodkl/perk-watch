"""Localhost API for the PerkWatch credit tracker UI (web/src/main.tsx)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import evals_admin
from ..catalog import catalog_by_id
from ..runtime.app import data_root, database
from ..runtime.chat import benefit_chat, wallet_ask, wallet_briefing
from ..runtime.community import blurb_for, tips_for
from ..runtime.profile import load_marks, toggle_mark
from ..runtime.tracker import benefit_state, data_through, track


class MarkRequest(BaseModel):
    period_start: str
    as_of: date | None = None
    amount_minor: int | None = None
    used: bool | None = None


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    as_of: date | None = None


def create_app(root: str | Path | None = None, *, chat_client=None, embedder=None) -> FastAPI:
    app = FastAPI(title="PerkWatch", docs_url="/api/docs", redoc_url=None)

    @contextmanager
    def connection() -> Iterator[sqlite3.Connection]:
        db = database(root)
        try:
            yield db
        finally:
            db.close()

    def marks():
        return load_marks(data_root(root))

    def require_benefit(benefit_id: str) -> None:
        if benefit_id not in catalog_by_id():
            raise HTTPException(404, "unknown benefit")

    def report() -> dict:
        try:
            return json.loads((data_root(root) / "prepared" / "report.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    # In memory only: runtime never writes prepared data. A new mark or a re-prepare changes the key.
    briefings: dict[tuple, dict] = {}
    evals = evals_admin.EvalsAdmin(chat_client=chat_client)

    def converse(call, *args, request: ChatRequest) -> dict:
        messages = [message.model_dump() for message in request.messages]
        with connection() as db:
            try:
                return call(db, *args, messages, as_of=request.as_of or date.today(), marks=marks(),
                            client=chat_client, embedder=embedder)
            except KeyError:
                raise HTTPException(404, "unknown benefit")
            except RuntimeError as error:
                raise HTTPException(503, str(error))

    @app.get("/api/tracker")
    def tracker(as_of: date | None = None) -> dict:
        with connection() as db:
            return track(db, as_of or date.today(), marks())

    @app.post("/api/benefits/{benefit_id}/mark")
    def mark(benefit_id: str, request: MarkRequest) -> dict:
        require_benefit(benefit_id)
        as_of = request.as_of or date.today()
        with connection() as db:
            state = benefit_state(db, benefit_id, as_of, marks())
            if state["tracking"] != "manual":
                raise HTTPException(400, "only manually tracked credits can be marked")
            period = next((p for p in state["periods"] if p["start"] == request.period_start), None)
            if period is None:
                raise HTTPException(400, "unknown period")
            if request.used is not None and period["marked"] == request.used:
                return state  # already in the requested state; a toggle here would undo it
            updated = toggle_mark(data_root(root), benefit_id, request.period_start,
                                  request.amount_minor or period["amount_minor"])
            return benefit_state(db, benefit_id, as_of, updated)

    @app.get("/api/benefits/{benefit_id}/community")
    def community(benefit_id: str) -> dict:
        require_benefit(benefit_id)
        with connection() as db:
            return {"blurb": blurb_for(db, benefit_id), "tips": tips_for(db, benefit_id)}

    @app.post("/api/benefits/{benefit_id}/chat")
    def chat(benefit_id: str, request: ChatRequest) -> dict:
        return converse(benefit_chat, benefit_id, request=request)

    @app.post("/api/ask")
    def ask(request: ChatRequest) -> dict:
        return converse(wallet_ask, request=request)

    @app.get("/api/briefing")
    def briefing(as_of: date | None = None) -> dict:
        day, current = as_of or date.today(), marks()
        key = (day.isoformat(), tuple(sorted(current.items())), report().get("finished_at"))
        if key in briefings:
            return {**briefings[key], "cached": True}
        with connection() as db:
            try:
                briefings[key] = wallet_briefing(db, as_of=day, marks=current, client=chat_client, embedder=embedder)
            except RuntimeError as error:
                raise HTTPException(503, str(error))
        return {**briefings[key], "cached": False}

    @app.get("/api/status")
    def status() -> dict:
        with connection() as db:
            through = data_through(db)
        return {"last_preparation_time": report().get("finished_at"), "data_through": through}

    @app.get("/api/admin/evals")
    def admin_evals() -> dict:
        return evals.snapshot()

    @app.post("/api/admin/evals/{name}/run")
    def admin_evals_run(name: str) -> dict:
        if name not in evals_admin.SUITES:
            raise HTTPException(404, "unknown suite")
        try:
            evals.start(name)
        except ValueError as error:
            raise HTTPException(400, str(error))
        return evals.snapshot()[name]

    return app


app = create_app()
