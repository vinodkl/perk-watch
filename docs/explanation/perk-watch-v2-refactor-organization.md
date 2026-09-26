---
type: explanation
status: original plan (partially implemented)
---

# PerkWatch V2 refactor organization plan

The implemented layout follows the later agreed names: `staging/raw_data.py`,
`prepare/rag_search_index.py`, and `runtime/retrieval/search.py`. This document
retains the original proposal for context. Storage migrations and per-benefit
community-term versioning remain proposed, not implemented.

Synthesis of three independent inspections (preparation pipeline, runtime
modular organization, evaluation). This is a **plan, not code**. It maps the
current module layout to a target layout, names the deep interfaces to keep or
create, and orders the work into verifiable phases. Every phase preserves the
project instructions in `AGENTS.md`: code under `src/perk_watch/`, entry points
under `scripts/`, cases under `evals/`, tests under `tests/`; runtime never
collects or writes; local data stays under `PERKWATCH_DATA_DIR` and out of git.

## What the three inspections agree on

- The code is already deep where it matters: the agent tool loop
  (`agent.py:answer_with_db`), the embedding seam (`EmbeddingProvider` with real
  + fake adapters), the PII redactor (`privacy.redact_pii`), merchant matching
  (`match_all`), and transaction parsing (`load_transactions`). These are not
  refactor targets.
- The wins are **structural, not architectural**: split `search.py` on the
  offline/online seam, extract a `tools.py` registry, add the missing staging
  module, harden `storage.py`, and trim `app.py` + `evals/run.py`.
- No repository/ORM, no API layer, no eval framework. The design doc already
  rejects "interfaces with only one implementation."

## Governing invariants (must survive every phase)

1. **Runtime never writes.** Runtime opens via `app.database()`
   (`sqlite3.connect`, no DDL); offline opens via `prepare.storage.connect()`
   (`CREATE TABLE IF NOT EXISTS` + migrations). Runtime never imports
   `storage.connect`.
2. **Outbound data is question-only at runtime.** After Phase 4, a runtime query
   sends only the redacted question to an embedder. Prepared benefit text and
   community ideas are embedded **at prepare time**, not query time.
3. **One outbound choke point.** Every outbound adapter routes through
   `privacy.redact_pii`. Merchant matching still sends only a cleaned
   description + fixed merchant list. No new outbound seams.
4. **Local data privacy.** Staging/prepare write only under
   `PERKWATCH_DATA_DIR/raw/` and `prepared/`. No real data, community sources,
   credentials, or generated stores in git.
5. **Content-addressed identity.** One `source_id` formula; one per-benefit terms
   hash; staging guarantees hash ↔ bytes agreement so foreign keys hold by
   construction rather than by luck.

## Current → target mapping

| Current | Target | Move |
|---|---|---|
| *(missing)* `perk_watch.raw_data` | `src/perk_watch/raw_data.py` | **New**: `import_benefit_guide`, `import_transactions`, `source_id`, `terms_hash` |
| `prepare/benefits.py` `source_id()` (bytes hash) | deleted; `load_benefits(..., source_id=)` | Consolidate identity into `raw_data`; benefits take `source_id` like transactions already do |
| `prepare/run.py` `_sources` / `_source_rows` / `_terms_version` | `_sources` uses `raw_data.source_id`; card-wide `_terms_version` → per-benefit `terms_hash` map | Identity + terms-validity single source of truth |
| `prepare/storage.py` `replace_card_data` (8 positional) + `connect()` (no migrations) | keyword-only/bundle args + `PRAGMA user_version` migrations | Locality fix: schema and delete-order/migration in lockstep |
| `prepare/community.py` card-wide terms filter | per-benefit terms filter (`terms_versions[benefit_id]`) | Invalidating one benefit's terms no longer drops unrelated ideas |
| `src/perk_watch/search.py` (runtime search + `build_*` + runtime re-embed) | `search.py` read-only, question-only embedding; `build_*` → `prepare/embeddings.py` | Make "search reads, prepare writes" structural |
| `src/perk_watch/agent.py` (loop + 4 tool impls + inline SQL + duplicated names) | `agent.py` loop only + `tools.py` registry/handlers/SQL | Tool names and SQL live in one place |
| `src/perk_watch/app.py` (5 funcs, 2 used) | `app.py` (`database`, `answer`) | Delete `benefit_status`/`find_benefits`; inline `show_benefits` into its script |
| `evals/run.py` (god-runner + patch seam) | `evals/harness.py` (`run_case` + pure helpers) + thin `run.py`; embedder injected | Tests and runner cross the same seam |
| `evals/fixture.py` (no embeddings built) | fixture builds `benefit_embeddings`/`community_embeddings` with `FixtureEmbedder` | Co-requisite of removing runtime re-embedding (see gaps) |
| `AGENTS.md` + staging SKILL (claim a staging module that writes sources) | reconciled docs | The staging seam must exist before the docs are true |

## Deep interfaces and composition

### Keep (already deep, two real adapters — no change)

- `EmbeddingProvider` Protocol (`model` + `embed(texts)`) — `OpenAIEmbeddingProvider` / `FixtureEmbedder` / `FakeEmbedder`.
- `privacy.redact_pii` — single outbound choke point with three call sites; correct locality.
- `prepare/merchants.py:match_all(descriptions, chooser)` — exact-substring built-in + `OpenAIMerchantChooser`. This is the slot a future `JevMerchantChooser` drops into.
- `prepare/transactions.py:load_transactions(card_id, path, source)` — CSV + two OFX adapters behind one interface.
- `prepare/benefits.py:load_benefits(card_id, path, extractor=)` — extractor seam (OpenAI / local / test lambdas).
- `answer_with_db` as the agent loop seam — keep the loop, shrink the body.

### Create (new deep modules)

```text
raw_data.py
  import_benefit_guide(guide_path, *, card, url) -> dict   # writes raw/<card>/benefits/, appends sources.json
  import_transactions(export_path, *, card) -> dict        # same for raw/<card>/transactions/
  source_id(card_id, kind, content_sha256) -> str          # the single identity formula
  terms_hash(benefit_id, terms) -> str                     # per-benefit terms version
```
Depth behind it: SHA-256 content addressing, stable `source_id`, relative-path
recording, idempotency (skip already-stored content), and the "never write
outside `PERKWATCH_DATA_DIR`" invariant. One call per artifact for both staging
skills and the monthly update. It comes with a test asserting idempotency and
that writes never leave the data root.

```text
tools.py
  TOOLS: dict[str, ToolSpec]           # name -> (schema, description, handler)
  dispatch(db, state, name, args, *, embedder) -> list[dict]
```
Depth behind it: owns all four tool handlers (`search_benefits`,
`evaluate_benefits`, `search_community_ideas`, `get_transaction_evidence`),
the guard state (searched/evaluated ID sets), and the one transaction-row SQL
query. `agent.py` keeps only the loop, `_ground_selection`, and `_render`.

```text
prepare/embeddings.py
  build_benefit_embeddings(db, embedder, card_id=None) -> int
  build_community_embeddings(db, embedder, card_id=None) -> int
```
Moved verbatim out of `search.py`; imports change only in `prepare/run.py` and
`tests/test_phase2.py` / `test_phase4.py`.

```text
evals/harness.py
  run_case(db, case, *, client, embedder, judge_model, usage) -> dict
```
Pure, side-effect-free helpers (`_contains`, `factual_checks`, `tool_plan`,
`FixtureEmbedder`, `PlannedAgentClient`, `request/reword/rerank/judge`) plus one
result dict (planned + live, factual failures, search experiments, judge scores).
`evals/run.py` only loads cases, opens the fixture, loops `run_case`, prints.

### Shrink

- `agent.py`: loop only — no SQL, no tool implementations, tool names referenced
  once via `tools.TOOLS`.
- `app.py`: `database()` (root→connection seam) + `answer()` (composition root).
  `show_benefits` inlines into `scripts/show_benefits.py` as
  `calculate_all(database(root), …)`.
- `search.py`: `BenefitSearch` / `CommunitySearch` only; question-only embedding;
  no `build_*`, no runtime re-embedding.

## Migration order

Each phase is independently verifiable and leaves the system working. Phases 1–3
are offline, 4–6 runtime, 7 evaluation. Phases marked *(parallel)* touch disjoint
files and can be done concurrently; the linear order is for a single developer.

### Phase 1 — Staging seam and source identity *(offline)*

Add `src/perk_watch/raw_data.py` with `import_benefit_guide`,
`import_transactions`, `source_id`, `terms_hash`. Delete `prepare/benefits.py`
`source_id()`; change `load_benefits` to accept an explicit `source_id` (symmetric
with `load_transactions`), computed by `prepare/run.py` from the sources record
via `raw_data.source_id`. Update `run._sources` to use the single formula. Add a
test asserting idempotency and data-root confinement. Reconcile `AGENTS.md` and
`local-card-data-staging/SKILL.md` to say: staging writes raw files + `sources.json`
(content-addressed, idempotent); `prepare_data.py` builds SQLite + embeddings.

- **Why first:** it is the one real correctness defect (the documented staging
  module does not exist), and it provides the shared identity/terms helpers the
  later offline phases need.
- **Deps:** none.
- **Checks:** `.venv/bin/python -m unittest discover -s tests` (new
  `test_raw_data.py`), `python3 scripts/check_local_data_guard.py`.
- **Risk:** must reproduce the existing `sources.json` shape — relative `path`,
  `content_sha256`, optional `source_id`, and both observed kinds (`benefits`,
  `benefits_reference`) — or a real `data/real` rebuild fails. Preserve both
  kinds.

### Phase 2 — Storage governance *(offline, parallel with Phase 1)*

Add `PRAGMA user_version` migrations to `prepare/storage.py:connect()` (a small
versioned migration runner; move the bespoke `ALTER` for `source_date` into it).
Convert `replace_card_data` from 8 positional params to keyword-only args or a
`CardRows` bundle. Keep the hand-ordered DELETE cascade but co-locate it with the
schema and add a comment tying both to `user_version` (any new table bumps the
version and adds a DELETE step).

- **Why:** Phase 6 adds tables; migrations must exist before more land. The
  positional tuple breaks at the next table.
- **Deps:** none.
- **Checks:** `.venv/bin/python -m unittest discover -s tests`
  (`test_phase1.py` prepare/rebuild tests), plus a fresh-db and an
  already-migrated-db open.

### Phase 3 — Per-benefit community validity *(offline, depends on Phase 1)*

Replace card-wide `_terms_version` with a `terms_versions: dict[benefit_id, str]`
map from `raw_data.terms_hash`. `prepare/community.py` filters
`row["terms_version"] == terms_versions[row["benefit_id"]]`. Update the
community-collection skill to stamp each idea's `terms_version` with the
per-benefit hash (computed from the newly collected guide) instead of one
card-wide value.

- **Why:** editing one benefit's terms should not invalidate every community idea
  on the card.
- **Deps:** Phase 1 (`terms_hash`).
- **Checks:** `.venv/bin/python -m unittest discover -s tests` (update
  `test_phase1.py` community fixtures to per-benefit hashes).
- **Risk:** one-time local re-staging of community ideas; existing prepared
  `terms_version` values won't match per-benefit hashes. Low blast radius.

### Phase 4 — Read-only search split *(runtime)*

Move `build_benefit_embeddings` / `build_community_embeddings` from `search.py`
into new `prepare/embeddings.py`; update imports in `prepare/run.py` and
`test_phase2.py` / `test_phase4.py`. In `BenefitSearch.search` and
`CommunitySearch.search`, **stop the runtime re-embedding path**: skip candidates
whose stored vector is missing, model-mismatched, or stale instead of calling
`provider.embed` on prepared text. Runtime outbound becomes question-only
(redacted). **Co-requisite:** `evals/fixture.py` must build
`benefit_embeddings`/`community_embeddings` with `FixtureEmbedder` (today it
builds none, and evals silently depend on runtime re-embedding).

- **Why:** makes "search reads, prepare writes" structural, and closes the only
  runtime leak of prepared text to OpenAI.
- **Deps:** none (do before Phase 5 so tool handlers call read-only search).
- **Checks:** `.venv/bin/python -m unittest discover -s tests`,
  `.venv/bin/python evals/run.py` (fixture now embedded), and
  `scripts/prepare_data.py` against a synthetic data root.
- **Risk:** missing vectors become a prepare-time defect surfaced by `build_*`
  counts, not a query-time repair. The fixture change is mandatory or evals
  break.

### Phase 5 — Tool registry and injectable embedder *(runtime)*

Create `src/perk_watch/tools.py` with the `TOOLS` registry and `dispatch()`.
Move the four handlers, guard state, and the `get_transaction_evidence` SQL out
of `agent.py`; `agent.py` keeps only the loop, `_ground_selection`, `_render`.
Add `embedder=None` to `answer_with_db` and thread it through `dispatch` into
`search_benefits` / `search_community_ideas` (they already accept `embedder`).
Delete the two `patch("perk_watch.agent.search_*")` blocks in `evals/run.py`;
pass `FixtureEmbedder()` through the real interface.

- **Why:** fixes tool-name quadruplication, moves SQL out of the agent, and
  replaces the fragile patch seam with the existing dependency seam.
- **Deps:** Phase 4 (handlers call read-only search).
- **Checks:** `.venv/bin/python -m unittest discover -s tests`
  (`test_phase3.py`, `test_phase4.py`, `test_eval_runner.py` keep their canned
  patches; eval crosses the real seam), `.venv/bin/python evals/run.py`.

### Phase 6 — Trim `app.py` facade *(runtime, parallel with Phase 5)*

Keep `database()` and `answer()`. Delete `benefit_status` and `find_benefits`
(zero callers). Inline `show_benefits` into `scripts/show_benefits.py`.

- **Why:** removes speculative API surface the design doc says not to build.
- **Deps:** none.
- **Checks:** `.venv/bin/python -m unittest discover -s tests`,
  `python3 scripts/show_benefits.py --data-root <synthetic root>`.

### Phase 7 — Evaluation harness and integration *(evaluation)*

Create `evals/harness.py`; move pure helpers verbatim and add
`run_case(db, case, *, client, embedder, judge_model, usage) -> dict`. Thin
`evals/run.py` to orchestrate. Update `tests/test_eval_runner.py` to import from
`harness`. Add one deterministic end-to-end case test that runs a fixture case
through `run_case` with `PlannedAgentClient` and asserts no
`fixture_check_failures`.

- **Why:** concentrates pass/fail logic in one module behind one function, and
  closes the gap where checks are tested only in isolation.
- **Deps:** Phases 4–5 (embedded fixture + injectable embedder).
- **Checks:** `.venv/bin/python -m unittest discover -s tests`,
  `.venv/bin/python evals/run.py` (behavior identical).
- **Ticket-gated only:** one prep→runtime end-to-end eval case that reuses
  `prepare(root, extractor=, merchant_chooser=, embedder=)` with deterministic
  adapters. Do not build it speculatively; `test_phase1.py` already covers prep.

## Checks (every phase)

```sh
.venv/bin/python -m unittest discover -s tests      # 48 tests; use .venv/bin/python
python3 scripts/check_local_data_guard.py            # after any data/real or staging change
.venv/bin/python evals/run.py                        # after Phases 4–7
PYTHONPATH=src .venv/bin/python scripts/prepare_data.py --data-dir <synthetic root>   # offline phases
```

Note: system `python3` (3.13) lacks `pydantic`, so the bare
`python3 -m unittest discover -s tests` in `AGENTS.md` errors on
`test_phase3`/`test_phase4`. Use `.venv/bin/python` (pydantic 2.13.5), which
passes all 48 tests.

## Explicit non-goals

- No repository/ORM over SQLite — three read-only query sites don't justify a
  new interface; centralize SQL only where it's already duplicated
  (`get_transaction_evidence`).
- No API layer — delete `benefit_status`/`find_benefits`; do not build ahead of
  the API.
- No `CaseRunner` class, plugin registry, schema versioning for evals, or generic
  "eval framework" — `cases.json` + `harness.py` + thin `run.py` is enough.
- No frozen fixture directory until there is a tracked-fixture need; the
  `evals/data/frozen` exemption in `check_local_data_guard.py` stays dormant or is
  deleted.
- No widening `app.answer` beyond what eval needs — the seam fix belongs on
  `answer_with_db`.
- No new outbound seams — Phase 6 Jev adapters (rerank, merchant match, new
  embedder) must route through `privacy.redact_pii` and the merchant limits.
- No automated login, credential storage, bank/card APIs, cookie extraction, or
  live lookup at runtime; no committing real data or community sources.
- Do not refactor `transactions.py`, `match_all`, `embeddings.py`, or
  `privacy.py` — they are already deep and correct.

## Discrepancies and missing coverage (flagged)

1. **Staging doc/code mismatch (highest priority).** `AGENTS.md`
   ("imports run through `scripts/prepare_data.py`, so hashes and source records
   are written") and the staging SKILL (`from perk_watch.raw_data import …`) both
   describe a module that does not exist. `prepare/run.py` only **reads**
   `sources.json`. Phase 1 resolves this by building `raw_data.py` and fixing the
   docs. The Phase-1 "foreign-key integrity" completion evidence passed only
   because the manually-staged records happen to be correct.

2. **Cross-finding gap: removing runtime re-embedding breaks the eval fixture.**
   `evals/fixture.py` builds **no** `benefit_embeddings`/`community_embeddings`
   rows; `run.py` currently relies on the query-time re-embedding path to compute
   vectors with `FixtureEmbedder`. The runtime finding ("stop re-embedding") and
   the evals finding (embedder injection) were written independently and neither
   connected the two. Phase 4 must make the fixture build stored vectors, or
   `evals/run.py` returns empty search results.

3. **Per-benefit `terms_version` has an unstated skill dependency.** The
   community-collection skill records one card-wide terms version. The prepare
   finding recommends per-benefit hashing but only notes "one-time local
   re-staging." Per-benefit validity also requires the **skill** (an offline
   agent procedure) to stamp each idea with the per-benefit `terms_hash` using
   the same shared helper. Phase 3 covers this; it is not a code-only change.

4. **`source_id` consolidation is larger than "delete `benefits.source_id`".**
   `load_benefits` currently computes its own source_id from bytes. Consolidating
   means `load_benefits` must accept an explicit `source_id` (symmetry with
   `load_transactions`) — a signature change that ripples to `prepare/run.py` and
   `test_phase1.py` callers. The prepare finding understates this blast radius.

5. **`sources.json` kind vocabulary.** Real `data/real` observes both `benefits`
   and `benefits_reference` kinds. The staging module must reproduce/accept both,
   or a real rebuild fails (promoted from the prepare finding's migration-risk
   note to a plan requirement in Phase 1).

6. **Interpreter mismatch in the documented check command.** `AGENTS.md` says
   `python3 -m unittest discover -s tests`; system `python3` lacks `pydantic` and
   errors. The project's `.venv/bin/python` has `pydantic 2.13.5` and passes all
   48 tests. Checks above use `.venv/bin/python`; `AGENTS.md` should be updated
   alongside Phase 1.

7. **Minor, accepted as-is (no action in this plan).** In-memory transaction
   dedup (`run.py`) loses deterministic ordering across runs (dict preserves
   last-occurrence order depending on `sources.json` enumeration) — accept unless
   a deterministic-ordering ticket appears. PII redaction is called independently
   in `merchants.py`, `extractor.py`, and `embeddings.py` — accepted as
   defense-in-depth behind the single `redact_pii` function.
