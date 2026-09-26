"""Bounded tool loop that renders only model-selected tool evidence."""
from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import tools

MAX_CALLS = 6
MAX_RETRIES = 2


class EvidenceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    evidence_indices: list[Annotated[int, Field(ge=0)]]


def _ground_selection(evidence: list[dict[str, Any]], selection: EvidenceSelection) -> EvidenceSelection:
    if len(set(selection.evidence_indices)) != len(selection.evidence_indices):
        raise ValueError("duplicate evidence index")
    if any(index >= len(evidence) for index in selection.evidence_indices):
        raise ValueError("evidence index is out of range")
    indices = []
    for index in selection.evidence_indices:
        item = evidence[index]
        result = item["result"]
        if item["tool"] in {"evaluate_benefits", "search_community_ideas"} and isinstance(result, dict):
            benefit_id = result.get("benefit_id")
            official = next((i for i, candidate in enumerate(evidence)
                             if candidate["tool"] == "search_benefits"
                             and candidate["result"].get("benefit_id") == benefit_id), None)
            if official is not None and official not in indices:
                indices.append(official)
        if index not in indices:
            indices.append(index)
    return EvidenceSelection(evidence_indices=indices)


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
                   max_retries: int = MAX_RETRIES, on_tool_result=None,
                   metrics: dict[str, int] | None = None, embedder=None) -> str:
    if not isinstance(question, str) or not question.strip():
        return "Please ask a question about your prepared card benefits."
    if max_calls < 1 or max_retries < 0:
        raise ValueError("invalid call or retry limit")
    if client is None:
        from openai import OpenAI
        client = OpenAI()

    evaluated_ids: set[str] = set()
    searched_benefit_ids: set[str] = set()
    evidence: list[dict[str, Any]] = []
    messages = [
        {"role": "system", "content": "Use tools to find evidence. Never guess a benefit_id from the user's wording. Before evaluate_benefits, call search_benefits and copy the exact benefit_id from its results. If evaluation says a benefit was not found, search for the benefit and retry with the exact returned ID. For benefit-specific community suggestions, resolve the benefit with search_benefits first and pass its exact benefit_id to search_community_ideas; only search community when the user asks for suggestions. Evaluate only the best-matching benefit unless search results are genuinely ambiguous. Once the needed evidence is collected, stop and select it rather than exploring alternatives. If a calculation returns status unknown, preserve that result and stop; do not try other benefits to replace unknown with a guess. Do not call get_transaction_evidence when the calculation returned no supporting transaction IDs. For a usage or remaining-value answer, select the calculation result; when the user asks which transactions, select their transaction evidence too. When official terms are requested or explain the answer, select the official search result as well. Use get_transaction_evidence only with transaction IDs returned by evaluate_benefits. Tool results include explicit evidence_index values. When done, return ONLY a JSON object matching {\"evidence_indices\": [0, 1]} selecting relevant evidence_index values in the order they should be shown. Do not write prose or facts. Select [] if no result is relevant."},
        {"role": "user", "content": question},
    ]
    seen: set[str] = set()
    calls = retries = 0
    while calls < max_calls:
        response = client.chat.completions.create(model=model, messages=messages,
                                                  tools=tools.definitions(), tool_choice="auto")
        if metrics is not None:
            metrics["model_calls"] = metrics.get("model_calls", 0) + 1
            usage = getattr(response, "usage", None)
            metrics["tokens"] = metrics.get("tokens", 0) + (getattr(usage, "total_tokens", 0) or 0)
        message = response.choices[0].message
        if not message.tool_calls:
            try:
                selection = EvidenceSelection.model_validate_json(message.content or "")
                return _render(evidence, _ground_selection(evidence, selection))
            except (ValidationError, ValueError):
                # Keep the answer grounded when model-selected indexes are malformed.
                selection = EvidenceSelection(evidence_indices=list(range(len(evidence))))
                return _render(evidence, _ground_selection(evidence, selection))
        messages.append(message)
        for call in message.tool_calls:
            calls += 1
            if calls > max_calls:
                break
            name, raw = call.function.name, call.function.arguments
            try:
                if name not in tools.TOOLS:
                    raise ValueError("unknown tool")
                args = tools.TOOLS[name][0].model_validate_json(raw).model_dump()
                key = json.dumps([name, args], sort_keys=True)
                if key in seen:
                    raise ValueError("repeated identical tool call")
                seen.add(key)
                result = tools.dispatch(db, name, args, searched_ids=searched_benefit_ids,
                                        evaluated_ids=evaluated_ids, embedder=embedder)
                if metrics is not None:
                    metrics["tool_calls"] = metrics.get("tool_calls", 0) + 1
                if on_tool_result is not None:
                    on_tool_result(name, result)
                results = result if isinstance(result, list) else [result]
                start = len(evidence)
                evidence.extend({"tool": name, "result": item} for item in results)
                result = [{"evidence_index": start + index, "result": item}
                          for index, item in enumerate(results)]
                error = False
            except Exception as exc:
                if metrics is not None:
                    metrics["tool_calls"] = metrics.get("tool_calls", 0) + 1
                    metrics["failures"] = metrics.get("failures", 0) + 1
                result, error = {"error": str(exc)}, True
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": json.dumps(result, default=str)})
            if error:
                retries += 1
                if metrics is not None:
                    metrics["retries"] = retries
                if retries > max_retries:
                    return "I couldn't answer safely because a tool call failed or was invalid."
    partial = _render(evidence, _ground_selection(
        evidence, EvidenceSelection(evidence_indices=list(range(len(evidence)))))
    ) if evidence else "No usable evidence was collected."
    return f"Partial results (tool-call limit reached; may be incomplete)\n\n{partial}"
