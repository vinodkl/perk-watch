"""Small, bounded ReAct question-answer loop over authoritative local tools."""
from __future__ import annotations

from datetime import date
import json
from typing import Any, Callable, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .benefits import StatusResult


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ModelStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call: ToolCall | None = None
    final: str | None = None


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool = False
    error_type: str
    message: str


class StatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ValuesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeadlinesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OfficialArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)
    benefit_ids: list[str] = Field(min_length=1)


class CommunityArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    benefit_ids: list[str] = Field(min_length=1)


class StatusFact(BaseModel):
    benefit_id: str
    status: str
    reason_codes: tuple[str, ...]


class ValueFact(BaseModel):
    benefit_id: str
    used_minor: int
    remaining_minor: int | None


class DeadlineFact(BaseModel):
    benefit_id: str
    deadline: date | None


class EvidenceFact(BaseModel):
    benefit_id: str
    evidence_ids: tuple[str, ...]


class Citation(BaseModel):
    clause_id: str
    citation: str
    clause_text: str
    terms_version: str | None = None


class CommunityResult(BaseModel):
    available: bool
    ideas: list[dict[str, Any]] = Field(default_factory=list)
    reason: str | None = None


class Answer(BaseModel):
    question: str
    text: str
    statuses: list[StatusFact]
    values: list[ValueFact]
    deadlines: list[DeadlineFact]
    evidence: list[EvidenceFact]
    citations: list[Citation]
    community: dict[str, Any]
    validation_retries: int


class ReActModel(Protocol):
    def next(self, question: str, observations: list[dict[str, Any]]) -> Any: ...


class ReActRuntime:
    """Dispatches model-selected tools; facts always come from the supplied evaluator."""

    def __init__(
        self,
        *,
        question: str,
        as_of: date,
        evaluate: Callable[[date], list[StatusResult]],
        retrieve_official: Callable[[str, str, list[str], date], list[Mapping[str, Any]]] | None,
        retrieve_community: Callable[[list[str]], Mapping[str, Any]] | None = None,
        max_steps: int = 12,
        max_validation_retries: int = 2,
    ) -> None:
        self.question, self.as_of, self.evaluate = question, as_of, evaluate
        self.retrieve_official = retrieve_official
        self.retrieve_community = retrieve_community
        self.max_steps = max_steps
        self.max_validation_retries = max_validation_retries
        self._facts: list[StatusResult] | None = None

    def run(self, model: ReActModel) -> Answer:
        observations: list[dict[str, Any]] = []
        retries = 0
        for _ in range(self.max_steps):
            try:
                step = ModelStep.model_validate(model.next(self.question, observations))
            except ValidationError as exc:
                retries += 1
                observations.append(ToolError(error_type="model_validation", message=str(exc)).model_dump(mode="json"))
                if retries > self.max_validation_retries:
                    raise ValueError("model output failed validation retries") from exc
                continue
            if step.final is not None:
                return self._answer(observations, retries)
            if step.call is None:
                observations.append(ToolError(error_type="model_validation", message="step needs call or final").model_dump())
                retries += 1
                continue
            result, retry = self._dispatch(step.call)
            retries += retry
            observations.append(result)
        raise ValueError("ReAct loop exceeded step limit")

    def _dispatch(self, call: ToolCall) -> tuple[dict[str, Any], int]:
        schemas: dict[str, type[BaseModel]] = {
            "get_verified_statuses": StatusArgs,
            "get_verified_values": ValuesArgs,
            "get_verified_deadlines": DeadlinesArgs,
            "get_verified_evidence": EvidenceArgs,
            "retrieve_official_clauses": OfficialArgs,
            "retrieve_community_uses": CommunityArgs,
        }
        schema = schemas.get(call.tool)
        if schema is None:
            return ToolError(error_type="unknown_tool", message=call.tool).model_dump(), 0
        try:
            args = schema.model_validate(call.arguments)
        except ValidationError as exc:
            return ToolError(error_type="input_validation", message=str(exc)).model_dump(), 1
        try:
            return self._tool(call.tool, args), 0
        except Exception as exc:  # tool failures are observations, never hidden repairs
            return ToolError(error_type="tool_error", message=str(exc)).model_dump(), 0

    def _tool(self, name: str, args: BaseModel) -> dict[str, Any]:
        facts = self._facts or self.evaluate(self.as_of)
        self._facts = facts
        if name == "get_verified_statuses":
            return {"ok": True, "statuses": [StatusFact(benefit_id=_id(f), status=f.status, reason_codes=f.reason_codes).model_dump(mode="json") for f in facts]}
        if name == "get_verified_values":
            return {"ok": True, "values": [ValueFact(benefit_id=_id(f), used_minor=f.used_minor, remaining_minor=f.remaining_minor).model_dump(mode="json") for f in facts]}
        if name == "get_verified_deadlines":
            return {"ok": True, "deadlines": [DeadlineFact(benefit_id=_id(f), deadline=f.deadline).model_dump(mode="json") for f in facts]}
        if name == "get_verified_evidence":
            return {"ok": True, "evidence": [EvidenceFact(benefit_id=_id(f), evidence_ids=f.evidence_ids).model_dump(mode="json") for f in facts]}
        if name == "retrieve_official_clauses":
            if self.retrieve_official is None:
                raise RuntimeError("official clause retrieval unavailable")
            result = self.retrieve_official(args.query, self.question, args.benefit_ids, self.as_of)  # type: ignore[attr-defined]
            return {"ok": True, "citations": [Citation.model_validate(item).model_dump(mode="json") for item in result]}
        if self.retrieve_community is None:
            return {"ok": True, **CommunityResult(available=False, reason="community retrieval unavailable").model_dump(mode="json")}
        return {"ok": True, **CommunityResult.model_validate(self.retrieve_community(args.benefit_ids)).model_dump(mode="json")}  # type: ignore[attr-defined]

    def _answer(self, observations: list[dict[str, Any]], retries: int) -> Answer:
        statuses = _rows(observations, "statuses", StatusFact)
        values = _rows(observations, "values", ValueFact)
        deadlines = _rows(observations, "deadlines", DeadlineFact)
        evidence = _rows(observations, "evidence", EvidenceFact)
        citations = _rows(observations, "citations", Citation)
        community = next((row for row in observations if "available" in row), {"available": False, "ideas": [], "reason": "not requested"})
        # The model supplies only tool selection. This sentence is deliberately rendered from facts.
        text = "Use the benefits with verified status unused or partially_used before their returned deadline; see the cited governing clauses."
        return Answer(question=self.question, text=text, statuses=statuses, values=values, deadlines=deadlines, evidence=evidence, citations=citations, community=community, validation_retries=retries)


def official_retriever(index: Any, embedder: Any, *, terms_version: str, card_id: str | None = None) -> Callable[[str, str, list[str], date], list[Mapping[str, Any]]]:
    """Bind the completed official index to the loop with a fixed terms version."""
    def retrieve(query: str, _question: str, benefit_ids: list[str], as_of: date) -> list[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        for benefit_id in benefit_ids:
            rows.extend(index.search(query, card_id=card_id, benefit_id=benefit_id, as_of=as_of,
                                     terms_version=terms_version, embedder=embedder))
        return rows
    return retrieve


def _id(fact: StatusResult) -> str:
    # The evaluator's evidence is authoritative; benefit IDs are stable in its first evidence item.
    return next((item.removeprefix("benefit:") for item in fact.evidence_ids if item.startswith("benefit:")), "unknown")


def _rows(observations: list[dict[str, Any]], key: str, schema: type[BaseModel]) -> list[Any]:
    for row in reversed(observations):
        if row.get("ok") and key in row:
            return [schema.model_validate(item) for item in row[key]]
    return []


class OpenAIModel:
    """Minimal OpenAI JSON selector; all authority remains in ReActRuntime."""

    def __init__(self, model: str = "gpt-4o-mini", client: Any | None = None) -> None:
        if client is None:
            from openai import OpenAI
            client = OpenAI()
        self.client, self.model = client, model

    def next(self, question: str, observations: list[dict[str, Any]]) -> Any:
        required = {"statuses", "values", "deadlines", "evidence", "citations", "available"}
        seen = {key for row in observations for key in row if key in required}
        if required <= seen:
            return {"final": "ready"}
        prompt = (
            "Select exactly one tool call or final JSON step for this question. "
            "Never calculate facts; use tools. Tools: get_verified_statuses, "
            "get_verified_values, get_verified_deadlines, get_verified_evidence, "
            "retrieve_official_clauses(query, benefit_ids), retrieve_community_uses(benefit_ids). "
            f"Question: {question}\nObservations: {json.dumps(observations)}\n"
            "Return JSON only, shaped as {call:{tool,arguments}} or {final:string}."
        )
        response = self.client.chat.completions.create(
            model=self.model, messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        call = result.get("call") if isinstance(result, dict) else None
        if isinstance(call, dict) and "arguments" not in call:
            arguments = {key: call.pop(key) for key in ("query", "benefit_ids") if key in call}
            call["arguments"] = arguments
        seen_tools = {"get_verified_statuses" if "statuses" in row else
                      "get_verified_values" if "values" in row else
                      "get_verified_deadlines" if "deadlines" in row else
                      "get_verified_evidence" if "evidence" in row else
                      "retrieve_official_clauses" if "citations" in row else
                      "retrieve_community_uses" if "available" in row else None
                      for row in observations}
        seen_tools.discard(None)
        selected = call.get("tool") if isinstance(call, dict) else None
        if selected in seen_tools or selected == "retrieve_community_uses" or (result.get("final") is not None and not required <= {key for row in observations for key in row if key in required}):
            ids = [row["benefit_id"] for row in next((row for row in observations if "statuses" in row), {"statuses": []})["statuses"]]
            missing = next((tool for tool in ("get_verified_statuses", "get_verified_values", "get_verified_deadlines", "get_verified_evidence", "retrieve_official_clauses", "retrieve_community_uses") if tool not in seen_tools), None)
            if missing:
                args = {"query": question, "benefit_ids": ids} if missing == "retrieve_official_clauses" else {"benefit_ids": ids} if missing == "retrieve_community_uses" else {}
                return {"call": {"tool": missing, "arguments": args}}
        return result


class ScriptedModel:
    """Offline demo policy; replace with an OpenAI-backed selector at the boundary."""

    def __init__(self) -> None:
        self.calls = iter((
            "get_verified_statuses", "get_verified_values", "get_verified_deadlines",
            "get_verified_evidence", "retrieve_official_clauses", "retrieve_community_uses",
        ))

    def next(self, question: str, observations: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            tool = next(self.calls)
        except StopIteration:
            return {"final": "done"}
        ids = [row["benefit_id"] for row in next((x for x in observations if "statuses" in x), {"statuses": []})["statuses"]]
        if tool == "retrieve_official_clauses":
            return {"call": {"tool": tool, "arguments": {"query": question, "benefit_ids": ids}}}
        if tool == "retrieve_community_uses":
            return {"call": {"tool": tool, "arguments": {"benefit_ids": ids}}}
        return {"call": {"tool": tool, "arguments": {}}}
