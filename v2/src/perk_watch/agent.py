"""Bounded tool loop that renders only model-selected tool evidence."""
from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from .calculations import calculate_benefit
from .search import search_benefits, search_community_ideas

MAX_CALLS = 6
MAX_RETRIES = 2
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
    benefit_id: NonEmpty


class TransactionEvidenceInput(_Input):
    transaction_ids: list[NonEmpty] = Field(max_length=100)


class EvidenceSelection(_Input):
    evidence_indices: list[Annotated[int, Field(ge=0)]]


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


def _tool_definitions():
    return [
        {"type": "function", "function": {"name": "search_benefits", "description": "Search official benefit terms.", "parameters": SearchBenefitsInput.model_json_schema()}},
        {"type": "function", "function": {"name": "search_community_ideas", "description": "Search source-linked community suggestions. These are not official rules and cannot establish benefit facts.", "parameters": SearchCommunityIdeasInput.model_json_schema()}},
        {"type": "function", "function": {"name": "evaluate_benefits", "description": "Calculate one benefit from local transactions.", "parameters": EvaluateBenefitsInput.model_json_schema()}},
        {"type": "function", "function": {"name": "get_transaction_evidence", "description": "Fetch transaction IDs returned by a benefit calculation.", "parameters": TransactionEvidenceInput.model_json_schema()}},
    ]


def _render(evidence: list[dict[str, Any]], selection: EvidenceSelection) -> str:
    if len(set(selection.evidence_indices)) != len(selection.evidence_indices):
        raise ValueError("duplicate evidence index")
    if any(index >= len(evidence) for index in selection.evidence_indices):
        raise ValueError("evidence index is out of range")
    if not selection.evidence_indices:
        return "No matching evidence was found in prepared data."
    headings = {"search_benefits": "Official benefit search",
                "search_community_ideas": "Community suggestions (not official rules)",
                "evaluate_benefits": "Benefit calculation",
                "get_transaction_evidence": "Transaction evidence"}
    return "\n\n".join(
        f"**{headings[evidence[index]['tool']]}**\n"
        f"{json.dumps(evidence[index]['result'], ensure_ascii=False, indent=2, default=str)}"
        for index in selection.evidence_indices
    )


def answer_with_db(db: sqlite3.Connection, question: str, *, client=None,
                   model: str = "gpt-4o-mini", max_calls: int = MAX_CALLS,
                   max_retries: int = MAX_RETRIES) -> str:
    if not isinstance(question, str) or not question.strip():
        return "Please ask a question about your prepared card benefits."
    if max_calls < 1 or max_retries < 0:
        raise ValueError("invalid call or retry limit")
    if client is None:
        from openai import OpenAI
        client = OpenAI()

    schemas = {"search_benefits": SearchBenefitsInput,
               "evaluate_benefits": EvaluateBenefitsInput,
               "get_transaction_evidence": TransactionEvidenceInput,
               "search_community_ideas": SearchCommunityIdeasInput}
    evaluated_ids: set[str] = set()
    evidence: list[dict[str, Any]] = []
    messages = [
        {"role": "system", "content": "Use the tools to find evidence for the user's question. When done, return ONLY a JSON object matching {\"evidence_indices\": [0, 1]} selecting relevant result indices in the order they should be shown. Do not write prose or facts. Select [] if no result is relevant. Indices refer to individual results, not tool calls."},
        {"role": "user", "content": question},
    ]
    seen: set[str] = set()
    calls = retries = 0
    while calls < max_calls:
        response = client.chat.completions.create(model=model, messages=messages,
                                                  tools=_tool_definitions(), tool_choice="auto")
        message = response.choices[0].message
        if not message.tool_calls:
            try:
                selection = EvidenceSelection.model_validate_json(message.content or "")
                return _render(evidence, selection)
            except (ValidationError, ValueError):
                return "I couldn't select valid evidence for an answer."
        messages.append(message)
        for call in message.tool_calls:
            calls += 1
            if calls > max_calls:
                break
            name, raw = call.function.name, call.function.arguments
            try:
                if name not in schemas:
                    raise ValueError("unknown tool")
                args = schemas[name].model_validate_json(raw).model_dump()
                key = json.dumps([name, args], sort_keys=True)
                if key in seen:
                    raise ValueError("repeated identical tool call")
                seen.add(key)
                if name == "search_benefits":
                    result = search_benefits(db, args["question"])
                    _SEARCH.validate_python(result)
                elif name == "search_community_ideas":
                    try:
                        result = search_community_ideas(db, args["question"], card_id=args.get("card_id"),
                                                        benefit_id=args.get("benefit_id"))
                        _COMMUNITY.validate_python(result)
                    except Exception:
                        result = []
                elif name == "evaluate_benefits":
                    result = calculate_benefit(db, args["benefit_id"])
                    _BenefitResult.model_validate(result)
                    evaluated_ids.update(result.get("supporting_transaction_ids", []))
                else:
                    ids = args["transaction_ids"]
                    if any(item not in evaluated_ids for item in ids):
                        raise ValueError("transaction IDs must come from evaluate_benefits")
                    if ids:
                        rows = db.execute(
                            "SELECT transaction_id, posted_date, description, amount_minor, currency, merchant "
                            "FROM transactions WHERE transaction_id IN (" + ",".join("?" for _ in ids) + ")", ids).fetchall()
                        by_id = {row[0]: {"transaction_id": row[0], "posted_date": row[1], "description": row[2], "amount_minor": row[3], "currency": row[4], "merchant": row[5]} for row in rows}
                        result = [by_id[item] for item in ids if item in by_id]
                    else:
                        result = []
                    _TRANSACTIONS.validate_python(result)
                results = result if isinstance(result, list) else [result]
                evidence.extend({"tool": name, "result": item} for item in results)
                error = False
            except Exception as exc:
                result, error = {"error": str(exc)}, True
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(result, default=str)})
            if error:
                retries += 1
                if retries > max_retries:
                    return "I couldn't answer safely because a tool call failed or was invalid."
    return "I couldn't finish within the tool-call limit."
