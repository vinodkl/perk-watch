"""File transaction ingest and model-owned merchant resolution."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Callable, Mapping


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


@dataclass(frozen=True)
class MerchantDecision:
    canonical_merchant: str | None
    resolution_status: str
    confidence: float | None = None
    metadata: Mapping[str, object] = ()


class SQLiteLedger:
    """Local, structured transaction facts and persisted merchant decisions."""

    def __init__(self, root: str | Path | None = None, *, path: str | Path | None = None):
        if path is not None and root is not None:
            raise ValueError("pass root or path, not both")
        if path is None:
            from .staging import data_root
            path = (Path(root).expanduser() if root is not None else data_root()) / "derived" / "ledger" / "ledger.sqlite3"
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id TEXT PRIMARY KEY,
                    card TEXT NOT NULL,
                    transaction_date TEXT NOT NULL,
                    posted_date TEXT NOT NULL,
                    descriptor TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL,
                    mcc INTEGER,
                    canonical_merchant TEXT,
                    resolution_status TEXT NOT NULL,
                    unresolved_reason TEXT,
                    evidence_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS merchant_decisions (
                    descriptor TEXT PRIMARY KEY,
                    canonical_merchant TEXT,
                    resolution_status TEXT NOT NULL,
                    confidence REAL,
                    metadata_json TEXT NOT NULL,
                    unresolved_reason TEXT,
                    evidence_id TEXT NOT NULL
                );
            """)

    def ingest(
        self, transactions: list[Transaction],
        resolve_descriptor: Callable[[str], object] | None = None,
    ) -> list[ResolvedTransaction]:
        """Persist rows once, consulting the resolver only for new descriptors."""
        with self._connect() as connection:
            for transaction in transactions:
                existing = connection.execute(
                    "SELECT * FROM transactions WHERE transaction_id = ?", (transaction.transaction_id,)
                ).fetchone()
                if existing is not None and _row_transaction(existing) != transaction:
                    raise ValueError(f"transaction ID already has different normalized facts: {transaction.transaction_id}")
                decision = connection.execute(
                    "SELECT * FROM merchant_decisions WHERE descriptor = ?", (transaction.descriptor,)
                ).fetchone()
                if decision is None:
                    value = resolve_descriptor(transaction.descriptor) if resolve_descriptor else None
                    normalized = _decision(value)
                    connection.execute(
                        "INSERT INTO merchant_decisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (transaction.descriptor, normalized.canonical_merchant, normalized.resolution_status,
                         normalized.confidence, json.dumps(dict(normalized.metadata), sort_keys=True),
                         _unresolved_reason(normalized), _merchant_evidence_id(transaction.descriptor)),
                    )
                    decision = connection.execute(
                        "SELECT * FROM merchant_decisions WHERE descriptor = ?", (transaction.descriptor,)
                    ).fetchone()
                resolved = _row_decision(decision)
                connection.execute(
                    """INSERT OR IGNORE INTO transactions
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (*_transaction_values(transaction), resolved.canonical_merchant,
                     resolved.resolution_status, _unresolved_reason(resolved),
                     f"transaction:{transaction.transaction_id}"),
                )
            return self.load_resolved_transactions(connection=connection)

    def load_resolved_transactions(self, *, connection: sqlite3.Connection | None = None) -> list[ResolvedTransaction]:
        own = connection is None
        connection = connection or self._connect()
        try:
            rows = connection.execute("SELECT * FROM transactions ORDER BY transaction_id").fetchall()
            return [ResolvedTransaction(_row_transaction(row), row["canonical_merchant"], row["resolution_status"]) for row in rows]
        finally:
            if own:
                connection.close()

    def decisions(self) -> list[MerchantDecision]:
        with self._connect() as connection:
            return [_row_decision(row) for row in connection.execute("SELECT * FROM merchant_decisions ORDER BY descriptor")]


TransactionLedger = SQLiteLedger


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


def process_transactions(
    source: TransactionSource, resolve_descriptor: Callable[[str], object] | None = None,
    *, root: str | Path | None = None, path: str | Path | None = None,
) -> SQLiteLedger:
    """Normalize an export and persist it with its descriptor decisions."""
    return persist_ledger(source.load(), resolve_descriptor, root=root, path=path)


def persist_ledger(
    transactions: list[Transaction], resolve_descriptor: Callable[[str], object] | None = None,
    *, root: str | Path | None = None, path: str | Path | None = None,
) -> SQLiteLedger:
    ledger = SQLiteLedger(root, path=path)
    ledger.ingest(transactions, resolve_descriptor)
    return ledger


def load_ledger(*, root: str | Path | None = None, path: str | Path | None = None) -> list[ResolvedTransaction]:
    return SQLiteLedger(root, path=path).load_resolved_transactions()


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


def _decision(value: object) -> MerchantDecision:
    if isinstance(value, MerchantDecision):
        decision = value
    elif isinstance(value, Mapping):
        decision = MerchantDecision(
            value.get("canonical_merchant"), str(value.get("resolution_status") or ("resolved" if value.get("canonical_merchant") else "indeterminate")),
            value.get("confidence"), value.get("metadata", {}),
        )
    else:
        decision = MerchantDecision(value, "resolved" if value else "indeterminate")
    merchant = decision.canonical_merchant
    if merchant is not None and (not isinstance(merchant, str) or not merchant.strip()):
        raise ValueError("merchant resolver must return a non-empty canonical merchant or None")
    if decision.resolution_status not in {"resolved", "indeterminate"}:
        raise ValueError("merchant resolution status must be resolved or indeterminate")
    return MerchantDecision(merchant.strip() if merchant else None, decision.resolution_status, decision.confidence, dict(decision.metadata))


def _unresolved_reason(decision: MerchantDecision) -> str | None:
    return None if decision.canonical_merchant else "unresolved_merchant"


def _merchant_evidence_id(descriptor: str) -> str:
    return "merchant:" + hashlib.sha256(descriptor.encode("utf-8")).hexdigest()[:16]


def _transaction_values(transaction: Transaction) -> tuple[object, ...]:
    return (transaction.transaction_id, transaction.card, transaction.transaction_date.isoformat(),
            transaction.posted_date.isoformat(), transaction.descriptor, transaction.amount_minor, transaction.mcc)


def _row_transaction(row: sqlite3.Row) -> Transaction:
    return Transaction(row["transaction_id"], row["card"], _date(row["transaction_date"]),
                       _date(row["posted_date"]), row["descriptor"], row["amount_minor"], row["mcc"])


def _row_decision(row: sqlite3.Row) -> MerchantDecision:
    return MerchantDecision(row["canonical_merchant"], row["resolution_status"], row["confidence"],
                            json.loads(row["metadata_json"]))


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
