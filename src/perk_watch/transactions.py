"""File transaction ingest and model-owned merchant resolution."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import re
from typing import Callable


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    card: str
    transaction_date: date
    posted_date: date
    descriptor: str
    amount_minor: int
    mcc: int | None


@dataclass(frozen=True)
class ResolvedTransaction:
    transaction: Transaction
    canonical_merchant: str | None
    resolution_status: str


class TransactionSource:
    """Read a CSV or OFX export into the normalized, non-embedded ledger."""

    def __init__(self, path: str | Path, *, card: str | None = None, mcc: int | None = None):
        self.path = Path(path)
        self.card = card
        self.mcc = mcc

    def load(self) -> list[Transaction]:
        if self.path.suffix.lower() == ".csv":
            return self._csv()
        if self.path.suffix.lower() == ".ofx":
            return self._ofx()
        raise ValueError("transaction source must be a .csv or .ofx file")

    def _csv(self) -> list[Transaction]:
        with self.path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        required = {"transaction_id", "card", "transaction_date", "posted_date", "descriptor", "amount_minor", "mcc"}
        if not rows or not required <= set(rows[0]):
            raise ValueError("CSV export is missing normalized transaction columns")
        return [
            _transaction(
                row["transaction_id"], row["card"], row["transaction_date"], row["posted_date"],
                row["descriptor"], row["amount_minor"], row["mcc"],
            )
            for row in rows
        ]

    def _ofx(self) -> list[Transaction]:
        if not self.card:
            raise ValueError("OFX imports require the card because OFX does not standardize it")
        text = self.path.read_text(encoding="utf-8")
        blocks = re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>|</BANKTRANLIST>))", text, re.DOTALL | re.IGNORECASE)
        if not blocks:
            raise ValueError("OFX export contains no transactions")
        rows = []
        for block in blocks:
            fields = {name.upper(): value.strip() for name, value in re.findall(r"<([A-Z0-9]+)>([^<\r\n]+)", block, re.IGNORECASE)}
            descriptor = fields.get("NAME") or fields.get("MEMO")
            if not {"FITID", "DTPOSTED", "TRNAMT"} <= fields.keys() or not descriptor:
                raise ValueError("OFX transaction is missing FITID, DTPOSTED, TRNAMT, or NAME/MEMO")
            rows.append(_transaction(
                fields["FITID"], self.card, _ofx_date(fields["DTUSER"] if "DTUSER" in fields else fields["DTPOSTED"]),
                _ofx_date(fields["DTPOSTED"]), descriptor, _minor_units(fields["TRNAMT"]), fields.get("MCC", self.mcc),
            ))
        return rows


def resolve_merchants(
    transactions: list[Transaction], resolve_descriptor: Callable[[str], str | None],
) -> list[ResolvedTransaction]:
    """Accept merchant facts only from the supplied model resolver."""
    resolved = []
    for transaction in transactions:
        merchant = resolve_descriptor(transaction.descriptor)
        if merchant is not None and (not isinstance(merchant, str) or not merchant.strip()):
            raise ValueError("merchant resolver must return a non-empty canonical merchant or None")
        resolved.append(ResolvedTransaction(
            transaction, merchant.strip() if merchant else None, "resolved" if merchant else "indeterminate",
        ))
    return resolved


def _transaction(transaction_id, card, transaction_date, posted_date, descriptor, amount_minor, mcc) -> Transaction:
    try:
        transaction_id, card, descriptor = str(transaction_id).strip(), str(card).strip(), str(descriptor).strip()
        if not transaction_id or not card or not descriptor:
            raise ValueError("transaction ID, card, and descriptor are required")
        return Transaction(
            transaction_id, card, _date(str(transaction_date)), _date(str(posted_date)), descriptor,
            int(amount_minor), int(mcc) if mcc not in (None, "") else None,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid transaction {transaction_id!r}") from exc


def _date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _ofx_date(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def _minor_units(value: str) -> int:
    return int((Decimal(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
