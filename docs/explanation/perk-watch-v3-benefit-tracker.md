---
type: explanation
---

# PerkWatch V3: benefit tracker redesign

PerkWatch V3 turns the V2 question-answering assistant into a benefit tracker: every credit, every period, used / partial / missed / at risk, with a per-benefit chat and a community-ideas blurb.

## In short

V2 has most of the building blocks, but it is shaped as a Q&A bot, and on real data it cannot give a single benefit a status. V3 keeps staging, SQLite, the React shell, and the eval harness, and replaces the middle:

1. A **hand-checked benefit catalog** (about 20 trackable credits) replaces LLM term extraction.
2. **Description patterns on issuer credit lines** replace merchant matching.
3. A **period tracker** that walks every period from January to today replaces the current-period calculator.
4. A **per-benefit chat that writes real answers** replaces the evidence-index agent.

Estimated effort: about **4 to 5 focused days**.

## Target: what MaxRewards shows

Observed on `maxrewards.com/my/benefits` (logged in, Amex Platinum, 2026-09-26):

- **Grouping:** by card, then by period: Monthly, Quarterly, Semi-annual, Annual, then Manually tracked. Each group shows "Resets in N days".
- **Card header:** "$1,371 left of $1,567" plus a progress bar.
- **Benefit tile:** title, `$used / $amount` for the current period, and a progress bar. Annual tiles show days left ("96d").
- **Period dots:** one dot per past period. Green check = fully used, yellow = partially used (Digital Entertainment Jan to May, $22.99 of $25), grey X = missed (Walmart+ Jan to Sep, Uber Cash Jan to Jul), ring = current, empty = future.
- **Tracking type:** "Autotracked" (statement credit detected) or "Manually tracked" (Uber Cash, paid in-app, with a "Mark as used" button). 24 benefits are hidden as untracked perks (lounges, insurance).
- **Filters:** Category, Tracking (all / auto / manual), Favorites, Needs Enrollment. Sort: Expiring soon.
- **Detail modal:** month strip, "Used $0 of $15", "5 days remaining" in red, and the full terms under "About".
- **Redeemed Benefits page:** a ledger of benefit, period, amount saved, and "N matched purchases".

**We add** what MaxRewards lacks: an explicit **missed $ this year**, an **Ask about this benefit** chat on at-risk tiles, and a **community blurb** per benefit.

## Where V2 is today (measured)

- **Every real benefit is `unknown`.** `calculate_all` on `data/real` returns `unknown` for **63 of 63** benefits. After re-preparing with the uncommitted `mechanism` change it is still 63 of 63: 34 "not verifiable from statements", 20 "amount unknown", 7 "statement coverage incomplete", 2 "period unknown".
- **One unmatched charge blocks a whole benefit.** On the merchant path (`runtime/calculations.py:96-98`), any transaction with no merchant in the period makes the benefit `unknown`. **1,337 of 1,362** real transactions have no merchant, because `prepare/merchants.py:10` knows only 7 merchant names.
- **The coverage check blanks the current period.** `calculations.py:74-76` requires statements that reach today's date. Real exports end on 09-19, so every credit fails on 09-26.
- **Only the current period is computed.** There is no period history, so "missed" cannot exist: unused Q1 and Q2 Uber credits in the demo data are silently forgotten. "Act soon" is only "deadline within 14 days" (`runtime/briefing.py:28-31`).
- **Amounts are per-year or per-period, inconsistently.** "$300 Digital Entertainment" is stored as 2500 monthly. "$200 Uber Cash" is stored as 20000 yearly, but it is really $15 a month plus $20 extra in December.
- **Credit ties are dropped.** `prepare/credits.py:17-33` matches credits by title-word overlap. The March "Platinum Resy Credit" ties across 3 Resy benefits and is dropped.
- **The agent cannot chat.** Its prompt forbids prose (`runtime/agent.py:86`) and it returns JSON evidence blocks (`agent.py:51-66`). A "how should I use this?" chat contradicts that design.
- **The period logic is duplicated.** `api/app.py:171-185` repeats it without half-year or account-year handling.
- **Tests are green but prove nothing on real data.** 64 of 64 pass (`uv run --with pytest pytest -q`; pytest is not a declared dependency).

## Key finding: statement credits already are the answer

The Amex export has **14 issuer credit lines** in 2026: Digital Entertainment ×9 (monthly), lululemon ×3 (Mar, Jun, Sep), Resy ×1 (Mar), Uber One ×1 (Feb). MaxRewards' Redeemed page lists **exactly these 14** auto-tracked 2026 redemptions, same months and amounts. Its only other 2026 entry is Uber Cash, which is manual.

So a regex per benefit over `description` (for example `PLATINUM DIGITAL ENTERTAINMENT CREDIT`) reproduces MaxRewards' auto-tracking on this data. No merchant matching, LLM matching, or embedding is needed to decide "used".

## V3 design, layer by layer

### 1. Fetch (staging): keep

- **Keep** manual CSV export plus `staging/raw_data.py` hashing. It works and respects the "no automated login" boundary.
- **Keep** `sources.json`, and add each export's `data_through` date: the last posted date, or the statement end date if known. The tracker needs it to tell "no credit yet" apart from "no data yet".
- **Drop from the monthly routine:** refreshing benefit guides every month. The catalog (below) is edited only when issuer terms change.

### 2. Normalize (prepare): simplify hard

**Benefit catalog, hand-checked, one JSON per card.** This replaces `prepare/extractor.py` (LLM extraction) and the regex backfill in `prepare/benefits.py:93-115`. MaxRewards curates its catalog too; for about 20 credits, correctness beats automatic extraction.

```json
{
  "benefit_id": "amex_platinum_digital_entertainment",
  "card_id": "amex_platinum",
  "title": "$300 Digital Entertainment Credit",
  "category": "entertainment",
  "period": "monthly",
  "amount_minor": 2500,
  "schedule_overrides": {},
  "reset": "calendar",
  "tracking": "auto",
  "credit_patterns": ["PLATINUM DIGITAL ENTERTAINMENT CREDIT"],
  "spend_patterns": ["DISNEY", "HULU", "PEACOCK", "NYTIMES", "YOUTUBE"],
  "enrollment_required": true,
  "terms": "Up to $25 in statement credits each month for eligible ...",
  "source_url": "https://www.americanexpress.com/..."
}
```

- `amount_minor` is always **per period**. `schedule_overrides` handles uneven periods, for example Uber Cash `{"12": 3500}`.
- `period` is one of `monthly | quarterly | semiannual | annual | multi_year`. `reset` is `calendar | anniversary`.
- `tracking` is `auto` (credit patterns), `manual` (user marks it, for example Uber Cash), or `none` (perks and protections: listed, never tracked).
- `spend_patterns` is optional. It is evidence only, used for "matched purchases" in the detail view, and never decides status.

**Matching:** a credit line matches a benefit when its description matches one of that benefit's `credit_patterns` and it has the card's credit sign from `cards.json`. First match wins. A test asserts that no two benefits share a pattern, so ties cannot happen.

**Delete:** `prepare/merchants.py` (LLM merchant matching), `prepare/credits.py` (word overlap), `prepare/extractor.py` (keep only as an optional offline "draft a catalog entry" helper if wanted).

**Keep:** `prepare/transactions.py` (CSV/OFX parse and dedupe), `prepare/storage.py`.

### 3. Tracker: new deterministic core (replaces `calculations.py` and `briefing.py`)

One module, `runtime/tracker.py`, about 150 lines. For each benefit where `tracking != none`, it enumerates **every period** from the later of January 1 or the card open date, through the period containing `as_of`. For each period it computes:

| Field | Rule |
|---|---|
| `used_minor` | sum of matched credits posted in the period, plus manual marks, capped at the amount |
| `status` (closed period) | `used` if used ≥ amount; `partial` if 0 < used < amount; `missed` if used = 0 |
| `status` (open period) | `at_risk` if remaining > 0 and days left ≤ window; otherwise `open` (or `used`) |
| `pending` | a closed period whose end + 10 days is after `data_through`: shown as "waiting for statement", never `missed` |

**At-risk windows:** monthly **7 days**, quarterly **14**, semiannual **30**, annual **45**. The 7-day monthly window matches competitor reminders.

**Output**, feeding the API and UI directly:

```json
{
  "benefit_id": "...",
  "current": {"used_minor": 0, "amount_minor": 1500, "days_left": 5, "status": "at_risk"},
  "periods": [{"label": "Jan", "status": "missed", "used_minor": 0}],
  "ytd": {"captured_minor": 0, "missed_minor": 10500}
}
```

Card and page totals: **$ captured YTD, $ missed YTD, $ at risk now**.

**Manual marks and anniversary** live in one small local file, `PERKWATCH_DATA_DIR/user/profile.json`: `{card_id: {"open_date": ..., "marks": [{benefit_id, period_start, amount_minor}]}}`. This is the only runtime write, it is explicit, and it is user-initiated. It relaxes V2's "runtime is read-only" rule, so call that out in `AGENTS.md`.

**Credits posted after the period ends:** attribute by posted date (MaxRewards does the same: the June lululemon credit shows under June). The `pending` rule covers credits that post late.

### 4. RAG: one small index, used where it earns its place

With about 20 catalog benefits, the tracker and per-benefit chat **do not need vector search**: the benefit is known by ID, so its terms, status, and tips are inserted into the prompt directly.

- **Keep one index** of `chunks(chunk_id, benefit_id, kind: terms|tip, text, vector)` built at prepare time, replacing the two separate indexes. It is used for:
  - the **global Ask box** ("which credit covers my Equinox membership?");
  - a `search_terms` **tool** inside the chat, for cross-benefit questions ("can I stack Resy with Digital Entertainment?").
- **Drop** the reword and rerank experiments (Phase 5 showed no gain) and `as_of` source-date filtering.
- **Keep** the content-hash staleness check (`retrieval/search.py:79`). It is cheap and correct.

### 5. Agent: per-benefit chat that writes answers

Replace the "select evidence indexes, never write prose" loop with a normal tool-using chat. Keep the existing OpenAI client and `gpt-4o-mini`.

- **Endpoint:** `POST /api/benefits/{id}/chat` with `{messages}`.
- **Context block (no retrieval needed):** benefit terms, current period status (`$0 of $15, 5 days left`), period history, enrollment flag, and that benefit's community tips.
- **Tools** (max 4 calls per turn): `get_benefit_status(benefit_id)`, `search_terms(query)`, `get_community_tips(benefit_id)`, `list_matched_transactions(benefit_id)`.
- **System rules:**
  - Dollar amounts and dates come only from the context or tools.
  - Label community tips as "community idea, not official".
  - Say "check the issuer terms" when unsure.
  - Keep answers to 3 to 6 short suggestions.
- **Guard (code, after generation):** every `$` amount in the answer must appear in the context or tool results. Otherwise, retry once with a note, then fall back. The same check is an eval metric.
- **Keep** the global Ask using the same loop, without a fixed benefit.
- **Reuse** from V2: pydantic tool input validation, the call limit, the repeated-call guard (`agent.py:92-156`). **Drop** `_ground_selection` and `_render`.

### 6. Community ideas: static tips plus a generated blurb

- **Tips:** `community/<card_id>.json` holds 3 to 5 tips per benefit: `{benefit_id, tip, source_url, source_date, last_verified}`. Seed them from the existing 12 reviewed ideas plus manual picks from r/amex, r/churning, Frequent Miler, and TPG. Tips expire (airline gift cards stopped working in 2025, TSA and award-tax charges stopped in July 2026), so the UI shows `last_verified`.
- **Blurb:** at prepare time, one LLM call per benefit turns its tips into a 1 to 2 sentence "What people do" blurb with source links, stored in SQLite. It is never generated per request.
- **Drop:** the versioned Reddit corpus, the model-judgment files, and the card-wide `terms_version` gate (`prepare/community.py:48-57`). That gate drops every idea on a card when any one benefit's text changes.

### 7. Evals: three small suites

| Suite | What it checks | Data | LLM? |
|---|---|---|---|
| **E1 tracker** | period status and $ per benefit per period | synthetic fixture (committed) + real answer key (local only) | no |
| **E2 retrieval** | recall@3 of the right `benefit_id` for about 20 questions | synthetic chunks | embeddings only |
| **E3 chat** | 10 to 15 at-risk scenarios: correct remaining $ and deadline, no invented $, tips labeled; judge scores usefulness 1 to 5 | synthetic fixture | yes |

- **E1 real answer key:** transcribe MaxRewards' Redeemed list (19 rows) and the current dots into `PERKWATCH_DATA_DIR/eval/answer_key.json`. It is never committed, per `AGENTS.md`. Report period-level accuracy and the $ captured difference. The expected result is 14 of 14 auto credits. This is the strongest capstone evidence: "matches a commercial tracker on my real data."
- **E1 synthetic edge cases:** partial month, missed quarter, a December Uber override, an anniversary reset, a credit posted after period end (pending), a refunded purchase, and the Chase positive credit sign.
- **Reuse** `evals/harness.py` structure. **Drop** the reword and rerank experiment branches.

### 8. API and UI

- **API:** `GET /api/benefits` returns tracker output grouped by card and period. It replaces `/api/briefing` and the duplicate `_evidence_bounds`. Also:
  - `GET /api/benefits/{id}` (detail, matched transactions, blurb);
  - `POST /api/benefits/{id}/mark`;
  - `POST /api/benefits/{id}/chat`;
  - `GET /api/redeemed`.
- **UI:** reuse the React shell in `web/src/main.tsx`:
  - the MaxRewards-style **grid of tiles with period dots**;
  - a top strip showing **captured / missed / at risk**;
  - a sort by "Expiring soon";
  - a detail drawer with terms, dots, matched transactions, the community blurb, and an **Ask** chat panel, open by default when the tile is at risk.

## What to cut or park

- **Phase 6** (Jev experiments), **Phase 7** (tracing), **Phase 9** (admin UI): mark as out of scope. For observability, append each chat turn's tool calls to one JSONL file. That is about 10 lines.
- **V2 constraint "two cards only":** keep it for the capstone. The catalog format makes adding a card a JSON file plus its credit patterns.
- **Uncommitted `mechanism` work:** its idea becomes `tracking: auto|manual|none` in the catalog. Do not finish slice 8.5 as specified.

## Build order

1. **Catalog + pattern matching (half a day).** Write `amex_platinum.json` and `chase_sapphire_preferred.json`. Add the pattern-uniqueness test. Re-prepare real data and confirm 14 matched credits.
2. **Tracker + E1 (1 day).** Build `tracker.py` with synthetic edge-case tests and the real answer-key comparison.
3. **API + UI tiles (1 to 1.5 days).** Build `/api/benefits`, tiles, dots, and totals. Delete `briefing.py` and `calculations.py`.
4. **Community tips + blurbs (half a day).**
5. **Chat + single RAG index (1 day).** Build the chat endpoint, tools, the $ guard, and the drawer panel.
6. **E2/E3 evals + docs (half to 1 day).**

## Risks

- **Credits not on the statement** (Uber Cash, DoorDash, Walmart+ if paid through the Walmart app) can only be manual. Show them in a Manually tracked group, as MaxRewards does.
- **Statement lag:** exports end before today, so recent periods show "waiting for statement" instead of missed. This is honest, but tell the user their `data_through` date on the page.
- **Pattern drift:** issuers can rename credit lines. The prepare report should list **unmatched lines containing "CREDIT"** so new names are caught in one glance.
- **Catalog is committed public issuer data.** This changes the `AGENTS.md` rule "keep real benefits out of git", which was written for raw guides. Decide explicitly.
