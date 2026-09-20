# Local card data

PerkWatch keeps collected data under `PERKWATCH_DATA_DIR`, grouped by card:

```text
raw/
  amex-platinum/
    benefits/
    transactions/
    community/<collection-version>/
    sources.json
  chase-sapphire-preferred/
    benefits/
    transactions/
    community/<collection-version>/
    sources.json
prepared/
  benefits/
  transactions/ledger.sqlite3
  community/
  report.json
```

`raw/` is manually collected input. `prepared/` is the normalized data model
PerkWatch reads. Both are local-only and must never be committed.

## Add raw issuer files

The collection skill imports each manually downloaded guide or transaction
export with its card ID:

```python
from perk_watch.raw_data import import_benefit_guide, import_transactions

import_benefit_guide("/path/to/guide.pdf", card="amex_platinum",
                     url="https://issuer.example/guide.pdf")
import_transactions("/path/to/export.csv", card="amex_platinum")
```

Imports are content-addressed and idempotent. The library writes provenance to
the card's single `sources.json` file.

Community collection writes sanitized `candidates.json`,
`model_judgments.json`, and `collection_results.json` to
`raw/<card>/community/<collection-version>/`. Never store full Reddit threads,
usernames, credentials, cookies, or private/deleted content.

## Prepare everything

After collecting or replacing any raw input, run one command:

```sh
PYTHONPATH=src PERKWATCH_DATA_DIR="$HOME/.local/share/perk-watch" \
  python3 scripts/prepare_data.py
```

It performs no network access. It:

1. hashes and chunks benefit guides, versions changed terms, and reports stale artifacts;
2. normalizes and deduplicates transaction exports into the local SQLite ledger;
3. deduplicates community ideas, applies their current-terms reviews, and replaces the prepared card snapshot;
4. writes `prepared/report.json`.

If benefit terms changed, community notes reviewed against the old terms are
rejected. Re-review them with the collection skill, then rerun the command.

PDF extraction requires `pdfplumber`. User login, MFA, CAPTCHA, consent, and
source downloads remain manual.
