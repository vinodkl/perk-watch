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

## 1. Choose a card

The shared [`src/perk_watch/cards.json`](src/perk_watch/cards.json) currently supports `amex_platinum` and `chase_sapphire_preferred`. Use the existing ID when refreshing a card; for a new card, complete the setup in step 2 before collecting real data. Preparation loops over this catalog. Keep credentials, account details, and issuer URLs out of it.

## 2. Add or refresh card data with the skills

### New card: create an ID and verify support first

1. Generate a **stable card ID** from the issuer and product name: lowercase ASCII letters and digits, words joined by underscores. For example, “Chase Sapphire Reserve” becomes `chase_sapphire_reserve`. Check that the ID is not already in [`cards.json`](src/perk_watch/cards.json); never rename an existing ID after collecting data. The raw directory uses hyphens (`chase-sapphire-reserve`).
2. Inspect a sample export to verify its columns and amount signs. Add the ID, display name, and observed `statement_credit_sign` (`positive` or `negative`) to `cards.json`. That sign recognizes explicit statement-credit rows; it does **not** determine benefit eligibility and may vary by export format. Check the guide against `prepare/benefits.py`, CSV/OFX parsing against `prepare/transactions.py`, merchant matching, and `runtime/calculations.py`. PDF import is **not implemented**.
3. Add synthetic import, credit/refund, and period tests, and an eval case. Run the checks in step 5. **A catalog entry alone does not make the card supported:** fix format or calculation gaps before collecting real data. Adjust the community skill's search scope if the card needs different public sources.

Prompt for the setup (replace the example card name):

> I want to add Chase Sapphire Reserve to PerkWatch. Generate a stable card ID using README step 2, check it does not exist in `src/perk_watch/cards.json`, and inspect a sample guide and CSV/OFX export that I provide. Verify columns and statement-credit sign, add the catalog entry, make only necessary parser/calculation changes, and add synthetic tests and an eval case. Run the local tests and guard. Do not collect real issuer or Reddit data until this setup passes; do not add credentials or account details to the catalog.

After setup passes, prompt for issuer collection and staging:

> Follow `.agents/skills/local-card-data-staging/SKILL.md` for `chase_sapphire_reserve` using my `PERKWATCH_DATA_DIR`. Help me capture current benefit terms and export transactions from January 1 through today as CSV/OFX. I will handle login, MFA, account selection, consent, and export. Stage the saved files using the skill, then report counts and missing terms without printing transaction rows or account details. Stop at a format you cannot parse; do not guess amounts.

Then explicitly start a **separate** community collection:

> Follow `.agents/skills/community-corpus-collection/SKILL.md` for `chase_sapphire_reserve` using its newly staged benefit terms and stable benefit IDs. Collect fresh public, unauthenticated Reddit sources into a new corpus version, review ideas against current terms, and report counts or access blockers. Do not reuse an older corpus as proof of a successful refresh.

Replace the example ID in both prompts with the ID you actually registered. Run step 3 afterward; inspect the new card's counts, unknowns, and source references before asking questions. An empty or wrong-sign result is a blocker.

### Existing card: refresh benefits, transactions, then community

Use the **existing** `amex_platinum` or `chase_sapphire_preferred` ID. The local-card-data skill stages files automatically: it copies them into `PERKWATCH_DATA_DIR/raw/<card>/` and records SHA-256 hashes and source IDs in `sources.json`. Repeated identical files are recognized; overlapping transaction exports are deduplicated during preparation. Do not include pending charges.

Prompt for the card data (replace the ID to refresh the other card):

> Follow `.agents/skills/local-card-data-staging/SKILL.md` for `amex_platinum` using my `PERKWATCH_DATA_DIR`. Help me capture current benefit terms and export transactions from January 1 through today as CSV/OFX. I will handle login, MFA, account selection, consent, and export. Stage the saved files with the skill, then report file counts and any missing terms without printing transaction rows or account details.

After the current terms are staged, prompt separately for community collection:

> Follow `.agents/skills/community-corpus-collection/SKILL.md` for `amex_platinum`. Use the newly staged terms and stable benefit IDs. Collect fresh public, unauthenticated Reddit sources into a **new** date-stamped corpus version, review ideas against current terms, and report counts or blockers. Do not claim an older corpus is refreshed.

Repeat for the other card if desired, then run step 3 and inspect `prepared/report.json` for skipped or unresolved records. The community skill never runs during preparation or while answering a question. A Reddit login wall is a blocker; an older local corpus may remain available, so do not claim a successful refresh in that case. Verify that changed benefit terms and their community checks were accepted before relying on suggestions.

### Manual fallback for files collected outside the skill

If you already have issuer files, stage them yourself from the repository root:

```sh
uv run python - <<'PY'
from perk_watch.staging.raw_data import import_benefit_guide, import_transactions

import_benefit_guide('/path/to/guide.json', card='amex_platinum', url='https://issuer.example/terms')
import_transactions('/path/to/export.csv', card='amex_platinum')
PY
```

Supported guide formats are `.json` and `.txt`; transaction formats are `.csv` and `.ofx`. Substitute the actual local paths and, if known, the real issuer source URL. Staging recognizes repeated content but does **not** parse, normalize, or embed it. The community skill writes its versioned corpus directly under `raw/<card>/community/`; do not pass it through the issuer-file staging functions.

## 3. Normalize and build the search indexes

After collection and staging for the card(s) you are refreshing (the command processes every configured card):

```sh
uv run python scripts/prepare_data.py --data-dir "$PERKWATCH_DATA_DIR"
python3 scripts/check_local_data_guard.py
```

`prepare/run.py` reads registered guides and exports, validates benefit extraction, normalizes and deduplicates transactions, matches merchants and explicit credits, and keeps only community ideas with a current, `no_known_conflict` terms check. It writes `prepared/perkwatch.sqlite` and `prepared/report.json`. Unknown or skipped fields are reported, not guessed.

With `OPENAI_API_KEY` set, the same preparation command builds **two** stored embedding indexes via `prepare/rag_search_index.py`: official benefit text and community ideas. Check the printed `embeddings`, `community_embeddings`, and `skipped` counts and the local report. Transactions remain in SQLite; they are never embedded. Re-run this command after changing raw files or an embedding provider/model. Missing or stale vectors are skipped at search time, not rebuilt during a question.

## 4. Ask through the read-only agent loop

```sh
uv run python scripts/ask.py "Which benefits still have value this month?"
uv run python scripts/show_benefits.py --data-root "$PERKWATCH_DATA_DIR" --as-of 2026-10-15
```

`runtime/app.py` opens the prepared SQLite database read-only. `runtime/agent.py` runs a bounded tool-selection loop (default: at most **6 tool calls**, **2 retries**). Its tools in `runtime/tools.py` search official terms, calculate benefit usage, find labeled community suggestions, and fetch only transactions referenced by a calculation. `runtime/retrieval/search.py` embeds the question and reads stored vectors; `runtime/calculations.py` computes amounts, refunds, and dates with code. The CLI does not collect, import, or index data. The optional community results are suggestions, never official rules.

`show_benefits.py` is a direct calculation path without the agent. Its `--as-of` date is illustrative above; use the date you want to inspect.

## 5. Test a feature change and run evaluations

```sh
uv run python -m unittest discover -s tests
python3 scripts/check_local_data_guard.py
uv run python evals/run.py > /tmp/perkwatch-eval.json
```

Unit tests and the guard are local checks. The eval runner rebuilds only the **synthetic** `evals/fixture.sqlite`; it never reads `PERKWATCH_DATA_DIR`. It requires `OPENAI_API_KEY` and incurs model calls for the live agent, query rewording, reranking, and answer-quality judge. Rewriting and reranking are **experiments**, not enabled in the runtime search path.

After a feature update, add or adjust a synthetic case in `evals/cases.json` and a focused test. Compare `fixture_check_failures` and `live_agent_failures` with the tool trace and selected answer in the JSON report. Factual checks verify structured amounts, dates, IDs, citations, and labels; the LLM judge scores answer quality **only**. Re-run the eval to check for unstable behavior before keeping a retrieval change. The fixture uses deterministic word-count vectors, so its search scores do not measure production embedding quality.

Earlier measured results and the limits of those measurements are recorded in the [Phase 5 evaluation ticket](docs/explanation/perk-watch-v2-phase-5-evaluation.md). Do not treat them as results of the current code until the evaluation is rerun.
