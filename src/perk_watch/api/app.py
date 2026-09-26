"""Read-only localhost API for prepared PerkWatch data."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, HTTPException, Query

from ..runtime.app import database
from ..runtime.briefing import build_briefing, statement_ranges
from ..runtime.calculations import calculate_benefit


def create_app(root: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="PerkWatch", docs_url="/api/docs", redoc_url=None)

    @contextmanager
    def connection() -> Iterator[sqlite3.Connection]:
        db = database(root)
        try:
            yield db
        finally:
            db.close()

    @app.get("/api/status")
    def status() -> dict[str, object]:
        with connection() as db:
            cards = statement_ranges(db)
        report = _report(root)
        return {
            "cards": cards,
            "last_preparation_time": report.get("finished_at"),
            "counts": report.get("cards", {}),
            "unresolved_count": report.get("unresolved_count", 0),
        }

    @app.get("/api/briefing")
    def briefing(as_of: date | None = None, account_year_start: date | None = None,
                 window_days: int = Query(14, ge=0, le=366)) -> dict[str, object]:
        with connection() as db:
            return build_briefing(db, as_of=as_of, account_year_start=account_year_start,
                                  window_days=window_days)

    @app.get("/api/benefits/{benefit_id}")
    def benefit(benefit_id: str, as_of: date | None = None) -> dict[str, object]:
        with connection() as db:
            row = _benefit(db, benefit_id)
            if row is None:
                raise HTTPException(status_code=404, detail="benefit not found")
            row["calculation"] = calculate_benefit(db, benefit_id, as_of=as_of)
            return row

    @app.get("/api/benefits/{benefit_id}/transactions")
    def transactions(benefit_id: str, as_of: date | None = None) -> dict[str, object]:
        with connection() as db:
            if _benefit(db, benefit_id) is None:
                raise HTTPException(status_code=404, detail="benefit not found")
            calculation = calculate_benefit(db, benefit_id, as_of=as_of)
            transaction_ids = list(calculation["supporting_transaction_ids"])
            return {"benefit_id": benefit_id,
                    "transactions": _transactions(db, benefit_id, transaction_ids)}

    return app


def _benefit(db: sqlite3.Connection, benefit_id: str) -> dict[str, object] | None:
    row = db.execute(
        "SELECT b.benefit_id, b.card_id, c.display_name, b.title, b.amount_minor, "
        "b.period, b.eligible_merchants, b.enrollment_required, b.booking_required, "
        "b.terms, s.source_id, s.path FROM benefits b "
        "JOIN cards c ON c.card_id = b.card_id "
        "JOIN sources s ON s.source_id = b.source_id WHERE b.benefit_id = ?",
        (benefit_id,),
    ).fetchone()
    if row is None:
        return None
    keys = ("benefit_id", "card_id", "card_name", "title", "amount_minor", "period",
            "eligible_merchants", "enrollment_required", "booking_required", "terms",
            "source_id", "source_path")
    result = dict(zip(keys, row))
    result["eligible_merchants"] = [
        value.strip() for value in str(result["eligible_merchants"] or "").split(",") if value.strip()]
    result["enrollment_required"] = _bool(result["enrollment_required"])
    result["booking_required"] = _bool(result["booking_required"])
    result["source_reference"] = {
        "source_id": result.pop("source_id"), "path": result.pop("source_path")}
    return result


def _transactions(db: sqlite3.Connection, benefit_id: str,
                  transaction_ids: list[str]) -> list[dict[str, object]]:
    if not transaction_ids:
        return []
    placeholders = ",".join("?" for _ in transaction_ids)
    rows = db.execute(
        f"SELECT t.transaction_id, t.posted_date, t.description, t.amount_minor, "
        f"t.currency, t.merchant, mm.confidence, cm.benefit_id "
        f"FROM transactions t LEFT JOIN merchant_matches mm "
        f"ON mm.transaction_id = t.transaction_id LEFT JOIN credit_matches cm "
        f"ON cm.transaction_id = t.transaction_id WHERE t.transaction_id IN ({placeholders})",
        transaction_ids,
    ).fetchall()
    by_id = {
        row[0]: {"transaction_id": row[0], "posted_date": row[1], "description": row[2],
                 "amount_minor": row[3], "currency": row[4], "merchant": row[5],
                 "matched_by": "issuer_credit" if row[7] == benefit_id
                 else f"merchant_{row[6]}" if row[6] in {"exact", "model"} else None}
        for row in rows
    }
    return [by_id[transaction_id] for transaction_id in transaction_ids if transaction_id in by_id]


def _report(root: str | Path | None) -> dict[str, object]:
    data_root = Path(root or os.environ.get("PERKWATCH_DATA_DIR", "data/real"))
    path = data_root / "prepared" / "report.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _bool(value: object) -> bool | None:
    return None if value is None else bool(value)


app = create_app()
