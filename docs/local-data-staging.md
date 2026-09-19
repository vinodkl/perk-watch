# Local real-data staging (Slice 0.5)

PerkWatch never logs in to accounts and never stores credentials. Supply a
public guide or a CSV/OFX export manually.

The root is `PERKWATCH_DATA_DIR`, or `~/.local/share/perk-watch` when unset.
If a repository-local root is needed for a smoke test, use the explicitly
gitignored `data/local/` path and set the variable first. Do not put personal
data in tracked `data/` fixtures.

```sh
export PERKWATCH_DATA_DIR="$HOME/.local/share/perk-watch"
PYTHONPATH=src python3 - <<'PY'
from perk_watch.staging import import_benefit_guide, import_transactions

import_benefit_guide("/path/to/manually-downloaded-guide.pdf",
                    url="https://issuer.example/guide.pdf",
                    terms_version="issuer-2026-01")
import_transactions("/path/to/export.csv")
PY
```

The staging layout is created on first import:

- `raw/benefits/` and `raw/transactions/`: content-addressed copies.
- `manifests/`: JSON provenance with source type, URL or filename, UTC import
  timestamp, SHA-256 content hash, and optional `terms_version`.
- `derived/registry/`, `derived/ledger/`, and `derived/indexes/`: reserved for
  later local-only processing.

Imports are idempotent by SHA-256 content hash. They only write below the
configured root. PDFs, statements, CSV/OFX exports, databases, indexes,
derived output, credentials, and personal transaction data must stay local;
the repository guard checks tracked files:

```sh
python3 scripts/check_local_data_guard.py
```

Frozen evaluation data remains under `data/` and is synthetic. Run its
validator and the transaction validator normally; local staging is not part
of either evaluation.
