# ADR: PerkWatch authority boundary

**Status:** accepted for the capstone. **Date:** 2026-09-21.

## Decision

Merchant resolution is **model-authoritative and measured** at transaction ingest. The resolver may map a sanitized statement descriptor to a canonical merchant group, persist that decision, or return `indeterminate`.

Everything that can change a benefit conclusion is deterministic and reads the prepared rule registry and transaction ledger: transaction occurrence/filtering, eligibility matching, period arithmetic, amounts, remaining value, deadlines, and status. The ReAct model selects tools and explains returned evidence. It cannot write rules, ledger rows, status, amounts, deadlines, or eligibility.

Official retrieval supplies version-correct citations. Community ideas are reviewed, source-linked, non-authoritative evidence. They may suggest usage tactics but cannot change deterministic facts. The planner is proposal plus deterministic feasibility check; an invalid action is dropped, not argued back into the answer.

## Boundary of reality

**Real and served:** staged issuer guides, local transaction exports, offline preparation, model merchant resolution, SQLite registry/ledger, offline public Reddit collection, reviewed community ideas, official citations, ReAct selection, and multi-benefit planning.

**Simulated/reproducible:** frozen terms, transactions, cases, merchant labels, and conflicting ideas under `evals/data/frozen/`; offline retrieval comparison; generated red-team test copy. These counts never mix with local counts.

**Deferred:** query-time Reddit lookup, live account connectivity, email streams, notifications/scheduling, enrollment automation, non-observable-benefit data sources, and cards outside the two-card scope. VKU-27's explicit fallback treats **188 unresolved merchant descriptors** as outside active benefit groups for the demo. It can produce false-unused results. Human-labelled local accuracy remains unavailable.

## Scope decisions

- **Keep served community retrieval:** it is useful as labelled, non-authoritative context. Cut the embedding index and LLM reranker because both tied the simpler per-benefit baseline: Recall@5 10/10 either way and MRR 10.0/10 either way.
- **Keep the red-team agent as evaluation-only:** it is useful regression evidence, but the real conflicting-ideas corpus remains the headline safety result.
- **Cut an MCP wrapper:** no external protocol improves this local, bounded demo; direct Python dispatch keeps the boundary inspectable.
- **Cut a QLoRA merchant model:** no labelled local merchant set exists; the measured OpenAI resolver plus persisted decisions is sufficient.
- **Cut vision PDF extraction:** captured guides are already structured locally; adding OCR would expand failure surface without an evaluated need.
- **Keep minimal conversational polish:** the three-minute path needs one question, citations, community labelling, and a planner result, not a chat product.

## Multi-agent shape

Extractor/Verifier qualifies because two independent bounded contexts are used and only structured proposal plus clause reach verification. Researchers/Planner qualifies because each researcher receives one benefit's facts and clauses in an isolated fan-out, then a planner reconciles candidates and applies deterministic checks. The fixed community collector is a deterministic preparation pipeline, not an agent: it has no open-ended goal, delegation, or runtime decision loop.

No graph or supervisor runtime is used. The flows have fixed steps, bounded retries, typed tool arguments, and a deterministic final authority. A framework would add generic registration, memory, and orchestration overhead without adding safety or capability here.
