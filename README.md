# PerkWatch

PerkWatch tracks your card credits period by period (used, partly used, missed, at risk) from your own statement exports, and lets you ask an LLM how to use a credit before it expires, with source-linked community tips. Issuer and community collection are **explicit offline actions**; the app never collects data, and its only write is "mark used" for credits your statement can't show. See the [V3 tracker design](docs/explanation/perk-watch-v3-benefit-tracker.md).

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

## 4. Track credits and ask questions

```sh
uv run python scripts/show_tracker.py --data-root "$PERKWATCH_DATA_DIR" --as-of 2026-10-15
uv run python scripts/ask.py "Which credits should I use this week?"
uv run --extra ui python scripts/serve.py   # API on http://127.0.0.1:8000 for the web UI
```

`runtime/app.py` opens the prepared SQLite database read-only. `runtime/tracker.py` matches issuer credit lines to the hand-checked catalog (`catalog.json`) and reports each credit's periods, status, and yearly captured/missed totals. `runtime/chat.py` answers per-benefit and wallet questions with a small tool loop grounded in tracker status, official terms, and community tips, and flags dollar amounts it cannot find in that context. "Mark used" for manually tracked credits is the only runtime write, to `PERKWATCH_DATA_DIR/user/profile.json`. Community tips are suggestions, never official rules. The `--as-of` date is illustrative above.

## 5. Test a feature change and run evaluations

```sh
uv run --extra ui python -m unittest discover -s tests
python3 scripts/check_local_data_guard.py
uv run python evals/run.py --suite tracker           # synthetic, no model calls
uv run python evals/run.py --suite all --real        # adds real data, retrieval and chat (about 20 OpenAI calls)
```

The eval runner has three suites:

- **tracker:** period status and amounts, with no LLM. It checks a synthetic in-memory fixture (`evals/fixture.py`, `evals/cases.json`), and with `--real` also a local answer key transcribed from a commercial tracker (`$PERKWATCH_DATA_DIR/eval/maxrewards_answer_key.json`, never committed).
- **retrieval:** recall@3 of the right benefit for plain-language questions, using real embeddings.
- **chat:** per-benefit and wallet answers. Code checks cover the remaining amount, the deadline, no unverified dollar amounts, labelled community tips, and the expected tool. An LLM judge scores usefulness from 1 to 5, and **only** usefulness.

Suites that need a key or real data are skipped with a note. After a feature change, add a synthetic case to `evals/cases.json` and a focused test.

Last full run (2026-09-26, real data): tracker 31/31, retrieval recall@3 8/8, chat 5/5 checks with judge mean 4.2. See the [V3 tracker design](docs/explanation/perk-watch-v3-benefit-tracker.md) for how these were measured.

## 6. Run the web app

```sh
uv run --extra ui python scripts/serve.py   # API on http://127.0.0.1:8000
cd web && npm run dev                       # UI on http://localhost:5173
```
