"""Validated, evidence-grounded tools available to the question agent."""
from __future__ import annotations

import sqlite3
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from .calculations import calculate_benefit
from .retrieval.search import search_benefits, search_community_ideas

NonEmpty = Annotated[str, Field(min_length=1)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SearchBenefitsInput(_Input):
    question: NonEmpty


class SearchCommunityIdeasInput(_Input):
    question: NonEmpty
    card_id: str | None = None
    benefit_id: str | None = None


class EvaluateBenefitsInput(_Input):
    benefit_id: Annotated[NonEmpty, Field(description="Copy the exact benefit_id from a prior search_benefits result; never invent or paraphrase it.")]
    as_of: str | None = None
    account_year_start: str | None = None


class TransactionEvidenceInput(_Input):
    transaction_ids: list[NonEmpty] = Field(max_length=100)


class _BenefitResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    benefit_id: str


class _SearchResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    benefit_id: str
    source_reference: dict[str, Any]


class _TransactionResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    transaction_id: str
    posted_date: str
    amount_minor: int


_SEARCH = TypeAdapter(list[_SearchResult])
_TRANSACTIONS = TypeAdapter(list[_TransactionResult])
_COMMUNITY = TypeAdapter(list[dict[str, Any]])

TOOLS = {
    "search_benefits": (SearchBenefitsInput, "Search official benefit terms. Call this first to discover the exact benefit_id before evaluating a benefit."),
    "evaluate_benefits": (EvaluateBenefitsInput, "Calculate one benefit using the exact benefit_id returned by search_benefits."),
    "search_community_ideas": (SearchCommunityIdeasInput, "Search source-linked community suggestions. These are not official rules and cannot establish benefit facts."),
    "get_transaction_evidence": (TransactionEvidenceInput, "Fetch transaction IDs returned by a benefit calculation."),
}


def definitions() -> list[dict]:
    return [{"type": "function", "function": {"name": name, "description": description,
            "parameters": schema.model_json_schema()}} for name, (schema, description) in TOOLS.items()]


def dispatch(db: sqlite3.Connection, name: str, args: dict, *, searched_ids: set[str],
             evaluated_ids: set[str], embedder=None) -> list[dict] | dict:
    if name == "search_benefits":
        result = search_benefits(db, args["question"], embedder=embedder)
        _SEARCH.validate_python(result)
        searched_ids.update(item["benefit_id"] for item in result)
        return result
    if name == "search_community_ideas":
        try:
            result = search_community_ideas(db, args["question"], card_id=args.get("card_id"),
                                            benefit_id=args.get("benefit_id"), embedder=embedder)
            _COMMUNITY.validate_python(result)
            return result
        except Exception:
            return []
    if name == "evaluate_benefits":
        if args["benefit_id"] not in searched_ids:
            raise ValueError("benefit_id must come from search_benefits results; search first")
        result = calculate_benefit(db, args["benefit_id"], as_of=args.get("as_of"),
                                   account_year_start=args.get("account_year_start"))
        _BenefitResult.model_validate(result)
        evaluated_ids.update(result.get("supporting_transaction_ids", []))
        return result
    if name == "get_transaction_evidence":
        ids = args["transaction_ids"]
        if any(item not in evaluated_ids for item in ids):
            raise ValueError("transaction IDs must come from evaluate_benefits")
        if not ids:
            return []
        rows = db.execute(
            "SELECT transaction_id, posted_date, description, amount_minor, currency, merchant "
            "FROM transactions WHERE transaction_id IN (" + ",".join("?" for _ in ids) + ")", ids).fetchall()
        by_id = {row[0]: {"transaction_id": row[0], "posted_date": row[1], "description": row[2],
                          "amount_minor": row[3], "currency": row[4], "merchant": row[5]} for row in rows}
        result = [by_id[item] for item in ids if item in by_id]
        _TRANSACTIONS.validate_python(result)
        return result
    raise ValueError("unknown tool")
