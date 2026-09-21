"""Load and apply the human-reviewed benefit classification mapping.

Prepared clauses carry only ``clause_id``, ``text``, ``source_id``, and
``terms_version``. The structured rule fields a clause needs to become an
active rule (``benefit_id``, ``card``, ``period_type``,
``period_amount_minor``, merchant-group eligibility, enrollment/portal flags)
can only come from a human review of the real guide text. That review is
stored as a local-only mapping under ``PERKWATCH_DATA_DIR`` and is never
derived from prose.

Applying the mapping requires an explicit ``reviewed: true`` marker. Drafts are
written to a different filename and are never read by the apply path.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

DISPOSITIONS = frozenset({"supported", "indeterminate", "known_untrackable"})
REVIEWED_FILENAME = "benefit-classification.json"
DRAFT_FILENAME = "benefit-classification.draft.json"

_INDEX_SUFFIX = re.compile(r"-\d{3,}$")
_SLUG_CHARS = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class BenefitMapping:
    """A validated mapping plus lookup indexes keyed by benefit/slug/clause."""

    reviewed: bool
    fingerprint: str
    rows: tuple[Mapping[str, Any], ...]
    by_benefit_id: Mapping[str, Mapping[str, Any]]
    by_slug: Mapping[str, Mapping[str, Any]]
    by_clause_id: Mapping[str, Mapping[str, Any]]

    def lookup(self, clause: Mapping[str, Any]) -> Mapping[str, Any] | None:
        benefit_id = str(clause.get("benefit_id") or "").strip()
        if benefit_id and benefit_id in self.by_benefit_id:
            return self.by_benefit_id[benefit_id]
        slug = clause_slug(clause)
        if slug and slug in self.by_slug:
            return self.by_slug[slug]
        return self.by_clause_id.get(str(clause.get("clause_id")))


def empty_mapping() -> BenefitMapping:
    return BenefitMapping(False, "", (), {}, {}, {})


def registry_dir(root: str | Path | None = None) -> Path:
    if root is None:
        from .raw_data import data_root
        root = data_root()
    return Path(root).expanduser() / "derived" / "registry"


def load_benefit_mapping(root: str | Path, *, require_reviewed: bool = True) -> BenefitMapping:
    """Load the reviewed mapping; refuse to apply a file that is not reviewed."""
    path = registry_dir(root) / REVIEWED_FILENAME
    if not path.exists():
        return empty_mapping()
    text = path.read_text(encoding="utf-8")
    document = json.loads(text)
    if require_reviewed and document.get("reviewed") is not True:
        raise ValueError(f"{path} is not marked reviewed:true; refusing to apply it")
    return from_document(document, fingerprint=hashlib.sha256(text.encode("utf-8")).hexdigest())


def from_document(document: Mapping[str, Any], *, fingerprint: str = "") -> BenefitMapping:
    rows = tuple(document.get("benefits", []))
    _validate(rows)
    by_benefit_id: dict[str, Mapping[str, Any]] = {}
    by_slug: dict[str, Mapping[str, Any]] = {}
    by_clause_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        by_benefit_id[str(row["benefit_id"])] = row
        slug = str(row.get("clause_slug") or "").strip()
        if slug:
            by_slug[slug] = row
        for clause_id in row.get("governing_clause_ids", []):
            by_clause_id[str(clause_id)] = row
    return BenefitMapping(
        reviewed=bool(document.get("reviewed")),
        fingerprint=fingerprint,
        rows=rows,
        by_benefit_id=by_benefit_id,
        by_slug=by_slug,
        by_clause_id=by_clause_id,
    )


def _validate(rows: Iterable[Mapping[str, Any]]) -> None:
    seen: set[str] = set()
    for row in rows:
        benefit_id = str(row.get("benefit_id") or "").strip()
        disposition = row.get("disposition")
        if not benefit_id:
            raise ValueError("mapping row is missing benefit_id")
        if benefit_id in seen:
            raise ValueError(f"duplicate mapping benefit_id {benefit_id}")
        seen.add(benefit_id)
        if disposition not in DISPOSITIONS:
            raise ValueError(f"mapping row {benefit_id} has invalid disposition {disposition!r}")
        if disposition == "supported":
            if not str(row.get("merchant_group") or "").strip():
                raise ValueError(f"supported row {benefit_id} is missing merchant_group")
            if not str(row.get("period_type") or "").strip():
                raise ValueError(f"supported row {benefit_id} is missing period_type")
        if disposition == "known_untrackable" and not str(row.get("missing_data_source") or "").strip():
            raise ValueError(f"known_untrackable row {benefit_id} is missing missing_data_source")


def clause_slug(clause: Mapping[str, Any]) -> str:
    """Recover the title/paragraph slug from a prepared clause id."""
    clause_id = str(clause.get("clause_id") or "")
    source_id = str(clause.get("source_id") or "")
    prefix = source_id + ":"
    key = clause_id[len(prefix):] if prefix and clause_id.startswith(prefix) else clause_id.rsplit(":", 1)[-1]
    return _INDEX_SUFFIX.sub("", key)


def derive_card(source_id: Any) -> str | None:
    value = str(source_id or "")
    for prefix in ("amex_platinum", "chase_sapphire_preferred"):
        if value.startswith(prefix):
            return prefix
    return None


def annotate_clauses(
    clauses: Iterable[Mapping[str, Any]], mapping: BenefitMapping,
) -> list[dict[str, Any]]:
    """Copy clauses, filling structured fields only from supported mapping rows."""
    annotated: list[dict[str, Any]] = []
    for clause in clauses:
        row = mapping.lookup(clause)
        if row is None or row.get("disposition") != "supported":
            annotated.append(dict(clause))
            continue
        updated = dict(clause)
        updated["benefit_id"] = row["benefit_id"]
        updated["card"] = row.get("card")
        updated["period_type"] = row.get("period_type")
        updated["period_amount_minor"] = row.get("period_amount_minor")
        merchant_group = row.get("merchant_group")
        updated["eligibility"] = {"merchant_group": merchant_group} if merchant_group else {}
        updated["enrollment_required"] = bool(row.get("enrollment_required", False))
        updated["portal_gated"] = bool(row.get("portal_gated", False))
        if row.get("effective_from") is not None:
            updated["effective_from"] = row["effective_from"]
        if row.get("effective_to") is not None:
            updated["effective_to"] = row["effective_to"]
        annotated.append(updated)
    return annotated


def build_draft_mapping(
    clauses: Iterable[Mapping[str, Any]], terms_version: str, *, generated_at: str | None = None,
) -> dict[str, Any]:
    """Scaffold a draft mapping with one indeterminate row per distinct clause slug."""
    groups: dict[tuple[str | None, str], list[str]] = {}
    for clause in clauses:
        key = (derive_card(clause.get("source_id")), clause_slug(clause))
        groups.setdefault(key, []).append(str(clause["clause_id"]))
    benefits: list[dict[str, Any]] = []
    for (card, slug) in sorted(groups):
        benefits.append({
            "benefit_id": _suggest_benefit_id(card, slug),
            "card": card,
            "clause_slug": slug,
            "period_type": None,
            "period_amount_minor": None,
            "eligibility": {"merchant_group": None},
            "enrollment_required": None,
            "portal_gated": None,
            "effective_from": None,
            "effective_to": None,
            "governing_clause_ids": sorted(groups[(card, slug)]),
            "disposition": "indeterminate",
        })
    return {
        "reviewed": False,
        "status": "draft",
        "terms_version": terms_version,
        "generated_at": generated_at,
        "benefits": benefits,
        "tallies": {
            "total_real_benefits": len(benefits),
            "supported": 0,
            "indeterminate": len(benefits),
            "known_untrackable": 0,
        },
    }


def _suggest_benefit_id(card: str | None, slug: str) -> str:
    cleaned = _SLUG_CHARS.sub("_", slug.lower()).strip("_")
    return f"{card}_{cleaned}" if card else cleaned
