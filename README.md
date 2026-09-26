# PerkWatch

PerkWatch answers questions about card benefits using locally prepared benefit terms, transactions, and public community ideas. Issuer collection and Reddit collection are **explicit offline actions**. Answering a question never collects new data or changes the prepared database. See the [V2 design](docs/explanation/perk-watch-v2-design.md).

## 0. Install and choose a local data root

From the repository root, use Python 3.13 and install the project:

```sh
uv sync
export PERKWATCH_DATA_DIR="$HOME/perk-watch-local-data"
```

`data/real/` is the local default in the application, but setting an absolute directory outside the repository makes the privacy boundary easier to see. Never commit raw guides, transaction exports, community sources, SQLite files, credentials, or generated reports. Keep `PERKWATCH_DATA_DIR` set for **both** preparation and the CLI. The preparation script also reads a repository-root `.env` when present; `scripts/ask.py` does **not** load `.env` for the data-root setting.

For real embedding search and model-backed extraction/agent answers, configure `OPENAI_API_KEY` in your shell (or load your local `.env` into the shell before the CLI). This sends prepared benefit/community text during index building and questions during search to OpenAI. Review that privacy tradeoff before enabling it. Without a key, preparation can still produce SQLite rows, but the CLI cannot perform production embedding search and no vectors are built.

## 1. Add a card (only if it is not already supported)

The supported card IDs are `amex_platinum` and `chase_sapphire_preferred`. Reuse the **same ID** each month. Adding a provider is a code change, not a configuration-only step:

1. Add its stable ID and display name to `src/perk_watch/prepare/benefits.py:CARDS`. The raw directory uses the ID with underscores changed to hyphens.
2. Check its guide format and benefit fields against `prepare/benefits.py`; adapt extraction/validation only where needed. Check CSV/OFX column names, date and amount signs in `prepare/transactions.py`. PDF import is **not implemented**.
3. Define the card's statement-credit sign in `prepare/credits.py:_is_credit`, and review merchant matching in `prepare/merchants.py` and usage calculations in `runtime/calculations.py`. Do not assume the existing issuers' signs or merchant list apply.
4. Add synthetic card, import, credit/refund, and period cases in `tests/` and `evals/cases.json`. Update the community-collection skill's search scope for the new card. Run the checks in step 6 before using real data.

The preparation coordinator in `prepare/run.py` loops over `CARDS`, so registering the ID includes it in monthly preparation. This is deliberately not a generic provider plugin system.

## 2. Collect benefits, transactions, and community ideas

Run the instructions in [`.agents/skills/local-card-data-staging/SKILL.md`](.agents/skills/local-card-data-staging/SKILL.md) with an agent for each card. **You** complete issuer login, MFA, account selection, consent, and the transaction export. Collect the current benefit terms and year-to-date CSV/OFX transactions, not pending charges. Do not automate issuer login or use bank APIs.

Then explicitly run [`.agents/skills/community-corpus-collection/SKILL.md`](.agents/skills/community-corpus-collection/SKILL.md) for approved benefits. It reads public Reddit pages without login and writes a fresh, versioned local corpus of IDs, URLs, short paraphrases, ideas, and current-terms checks. A login wall is a blocker. Collection never runs as part of preparation or while answering a question.

## 3. Stage raw issuer files

The local-card-data skill calls these functions after the files have been saved. For a manually supplied file, you can call them yourself from the repository root:

```sh
uv run python - <<'PY'
from perk_watch.staging.raw_data import import_benefit_guide, import_transactions

import_benefit_guide('/path/to/guide.json', card='amex_platinum', url='https://issuer.example/terms')
import_transactions('/path/to/export.csv', card='amex_platinum')
PY
```

Supported guide formats are `.json` and `.txt`; transaction formats are `.csv` and `.ofx`. Substitute the actual local paths and, if known, the real issuer source URL. Staging copies files into `PERKWATCH_DATA_DIR/raw/<card>/`, records a SHA-256 hash and source ID in `sources.json`, and recognizes repeated content. It does **not** parse, normalize, or embed the contents. The community skill writes its versioned corpus directly under `raw/<card>/community/`; do not pass it through the issuer-file staging functions.

## 4. Normalize and build the search indexes

After collection and staging for both cards:

```sh
uv run python scripts/prepare_data.py --data-dir "$PERKWATCH_DATA_DIR"
python3 scripts/check_local_data_guard.py
```

`prepare/run.py` reads registered guides and exports, validates benefit extraction, normalizes and deduplicates transactions, matches merchants and explicit credits, and keeps only community ideas with a current, `no_known_conflict` terms check. It writes `prepared/perkwatch.sqlite` and `prepared/report.json`. Unknown or skipped fields are reported, not guessed.

With `OPENAI_API_KEY` set, the same preparation command builds **two** stored embedding indexes via `prepare/rag_search_index.py`: official benefit text and community ideas. Check the printed `embeddings`, `community_embeddings`, and `skipped` counts and the local report. Transactions remain in SQLite; they are never embedded. Re-run this command after changing raw files or an embedding provider/model. Missing or stale vectors are skipped at search time, not rebuilt during a question.

## 5. Ask through the read-only agent loop

```sh
uv run python scripts/ask.py "Which benefits still have value this month?"
uv run python scripts/show_benefits.py --data-root "$PERKWATCH_DATA_DIR" --as-of 2026-10-15
```

`runtime/app.py` opens the prepared SQLite database read-only. `runtime/agent.py` runs a bounded tool-selection loop (default: at most **6 tool calls**, **2 retries**). Its tools in `runtime/tools.py` search official terms, calculate benefit usage, find labeled community suggestions, and fetch only transactions referenced by a calculation. `runtime/retrieval/search.py` embeds the question and reads stored vectors; `runtime/calculations.py` computes amounts, refunds, and dates with code. The CLI does not collect, import, or index data. The optional community results are suggestions, never official rules.

`show_benefits.py` is a direct calculation path without the agent. Its `--as-of` date is illustrative above; use the date you want to inspect.

## 6. Test a feature change and run evaluations

```sh
uv run python -m unittest discover -s tests
python3 scripts/check_local_data_guard.py
uv run python evals/run.py > /tmp/perkwatch-eval.json
```

Unit tests and the guard are local checks. The eval runner rebuilds only the **synthetic** `evals/fixture.sqlite`; it never reads `PERKWATCH_DATA_DIR`. It requires `OPENAI_API_KEY` and incurs model calls for the live agent, query rewording, reranking, and answer-quality judge. Rewriting and reranking are **experiments**, not enabled in the runtime search path.

After a feature update, add or adjust a synthetic case in `evals/cases.json` and a focused test. Compare `fixture_check_failures` and `live_agent_failures` with the tool trace and selected answer in the JSON report. Factual checks verify structured amounts, dates, IDs, citations, and labels; the LLM judge scores answer quality **only**. Re-run the eval to check for unstable behavior before keeping a retrieval change. The fixture uses deterministic word-count vectors, so its search scores do not measure production embedding quality.

Earlier measured results and the limits of those measurements are recorded in the [Phase 5 evaluation ticket](docs/explanation/perk-watch-v2-phase-5-evaluation.md). Do not treat them as results of the current code until the evaluation is rerun.
