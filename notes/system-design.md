# PerkWatch System Design

Sep 28, 2026 · Vinod

## Overview

PerkWatch tracks every credit-card statement credit, every period, and marks it used, partly used, missed or at risk. It then uses an LLM to help plan how to use what is left before it expires.

**Design principle: deterministic where it counts, AI where it helps.** Whether a credit was used is decided by code: one regex per credit, matched against statement lines, from a hand-checked catalog. No model decides "used". The LLM only explains, plans and answers questions, and every dollar amount it writes is checked against the data.

**Scope:** 3 cards (Amex Platinum, Chase Sapphire Preferred, Chase Sapphire Reserve) and 20 tracked credits on the author's own data. It is a local, single-user app. Data collection (exports, logins, MFA) stays manual by design.

## Architecture

The system splits at SQLite. Everything above it runs offline as explicit, manual steps; everything below it only reads what those steps prepared.

```mermaid
flowchart TB
  subgraph Offline["Offline: manual, explicit steps"]
    A["Collect (manual)<br/>statement CSV/OFX exports<br/>benefit guides, public tips"] --> B["Stage<br/>file hash + source record"] --> C["Prepare<br/>normalize transactions<br/>embed terms + community tips"]
  end
  C --> D[("SQLite (prepared data)<br/>the only thing runtime reads")]
  subgraph Runtime["Runtime: reads prepared data only"]
    E["Tracker (no model)<br/>one regex per credit<br/>status for every period"]
    F["Retrieval (RAG)<br/>embedding search over<br/>terms + community tips"]
    G["Agent loop (gpt-4o-mini)<br/>5 tools, at most 4 calls<br/>every $ amount checked vs data"]
    E -->|"credit status + history as context"| G
    F --> G
  end
  D --> E
  D --> F
  E --> H["FastAPI + React UI<br/>tracker page, per-benefit chat, wallet Ask,<br/>weekly AI plan, Evals tab"]
  G --> H
```

The tracker is pure code and never calls a model. The model sits only in the agent loop, which gets tracker results as context and reaches retrieval through tools.

## Components

Only the agent loop, blurb generation and term extraction call a chat model; the tracker never does.

| Component | Code | Job | Model? |
| --- | --- | --- | --- |
| Staging | `staging/raw_data.py` | Copies user-supplied files into the data dir with a hash and a source record | No |
| Prepare | `prepare/run.py`, `scripts/prepare_data.py` | Normalizes transactions into SQLite, stores benefit terms and community tips, builds embeddings and cached blurbs | Embeddings, term extraction, blurbs |
| Catalog | `catalog.json`, `catalog.py` | Hand-checked public facts: each credit's amount, period and statement-line regex | No |
| Tracker | `runtime/tracker.py` | Walks every period of every credit and sets used / partial / missed / at risk from matched statement credits | No |
| Retrieval | `runtime/retrieval/search.py` | Cosine search over stored embeddings of official terms and community tips, narrowed to a card when the question names one | Query embedding only |
| Agent loop | `runtime/chat.py` | Per-benefit chat, wallet Ask and the weekly plan: a bounded tool-calling loop with a dollar-grounding check | gpt-4o-mini |
| API + UI | `api/app.py`, `web/` | FastAPI on :8000, React/Vite UI on :5173, including an Evals tab | No |
| Evals | `evals/run.py`, `evals/suites.py` | Tracker, retrieval and chat suites on a synthetic fixture, with an optional real-data run | Chat suite + LLM judge |

## Agent loop

One bounded tool-calling loop on `gpt-4o-mini` serves three features: the per-benefit chat, the wallet-wide Ask, and the weekly plan on the home page.

**What the model sees, in order:**

1. **System prompt:** rules. Dollar amounts, dates and days left must come from the context or a tool result; community tips are labelled "Community idea" with their source; urgent credits come first.
2. **Context, as JSON:** for a benefit chat, that credit's status, full period history, official terms and its community tips, preloaded because the benefit is already known. For wallet Ask and the weekly plan, the current period of every credit, sorted most urgent first.
3. **The conversation so far**, then the user's question.

**Tools (5):**

| Tool | What it does |
| --- | --- |
| `get_benefit_status` | Current period and history for one credit |
| `search_terms` | RAG search over official issuer terms |
| `search_community_tips` | RAG search over community tips and ideas |
| `get_community_tips` | Tips for one known benefit (used by the weekly plan) |
| `propose_mark` | Offers a one-tap "mark used" button for a manual credit; writes nothing |

**Budget:** at most 4 tool calls per turn. After the fourth, tools are withdrawn and the model must answer with what it has.

**Grounding check:** after generation, code compares every dollar amount in the answer with the context and tool results. The UI shows the check ("N amounts found in your data") and flags any amount it cannot find.

**Transparency:** every answer shows its tool trace (tool, query, one-line result), so a user can see how it got there.

**Memory:** the browser keeps each chat and resends the whole conversation with every question. The server is stateless and stores no chat history.

## Retrieval (RAG)

Retrieval is a tool the agent chooses to call, not a step that runs on every question. When the benefit is already known, its terms and tips are simply loaded into context instead.

- **What is embedded:** official benefit terms, and community tips and ideas (paraphrased, each with a public source link). Transactions are never embedded.
- **When:** at prepare time, offline, with `text-embedding-3-small`. Each vector stores its model and a content hash, so stale vectors are skipped instead of served. At runtime only the question is embedded.
- **Search:** cosine similarity over the stored vectors, a minimum score of 0.2, top 3 results. When a question names a card, the search is narrowed to that card first.
- **Two separate searches:** `search_terms` returns official rules; `search_community_tips` returns ideas labelled as community, never as rules. Keeping them apart stops a forum tip being presented as an issuer policy.
- **Why a tool, not always-on retrieval:** most wallet questions are about amounts and deadlines already in context. Retrieving on every turn would add tokens and noise; the agent calls a search only when the question is about coverage or ideas.

## Privacy and safety boundaries

The model never sees raw financial records, and nothing at runtime logs in, scrapes or writes on the user's behalf.

- **What the model may see:** a credit's terms, tips, amounts, dates and statuses.
- **What it never sees:** transaction descriptions, account details, filenames or complete transaction rows. `redact_pii` runs before any text is embedded or sent to a model.
- **Manual by design:** login, MFA, CAPTCHA, account selection and consent. There are no bank APIs, no credential storage and no automated scraping.
- **One runtime write:** "mark used" for credits a statement can't show (for example a credit paid inside a partner app). The agent can only *propose* it with `propose_mark`; the user's tap writes it to `user/profile.json`.
- **No live lookups while answering:** the app makes no web requests except model calls. Community tips are collected offline from public pages, paraphrased, and stored with their source link.
- **What stays out of git:** statements, exports, databases, community sources and generated output live in a local data directory. Only the hand-checked catalog of public issuer facts is committed, and a guard script checks this before each commit.

## Tech stack, cost and latency

| Layer | Choice |
| --- | --- |
| Language | Python (backend, prep, evals), TypeScript (UI) |
| Storage | SQLite, one local file of prepared data |
| API | FastAPI + Uvicorn |
| UI | React + Vite |
| Chat model | OpenAI `gpt-4o-mini` |
| Embeddings | OpenAI `text-embedding-3-small` |
| Tests | `unittest` (95 tests), plus a local-data guard script |

**Cost and latency:** preparing a card costs about 10 small OpenAI calls (blurbs and embeddings, cached between runs). A chat or weekly-plan reply costs 1 to 5 calls and returns in a few seconds. A full real-data eval run used 21 chat calls and 11 embedding calls.

## Known limitations and next steps

- **Credits that never reach a statement** (for example a DoorDash credit spent inside the app) can't be detected by regex. They are tracked manually with a user-confirmed mark.
- **Term extraction drift:** re-running prepare re-extracts some benefit terms with a model, which can shift embeddings. The latest real-data run missed one retrieval case (the CLEAR+ credit for "airport security fast lanes"). Next step: cache extracted terms by source hash so re-runs are stable.
- **Community label consistency:** after the community RAG change, 2 of 8 real-data chat cases linked a community source without the "Community idea" label. Next step: tighten the benefit-chat prompt and keep the label check as a gate.
- **Self-grading judge:** the LLM judge is the same model that answers. A different judge model would remove self-grading bias.
- **Retrieval evals cover official terms only.** Next step: add community-tip cases to the retrieval suite.
- **Single user, local only:** no auth, no multi-user storage, and card coverage is limited to the 3 cards in the catalog.
