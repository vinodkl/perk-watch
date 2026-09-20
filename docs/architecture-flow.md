# PerkWatch architecture flow

PerkWatch separates data preparation from the user-facing runtime:

1. **Offline preparation** imports and versions local data, builds registries
   and indexes, and performs no end-user query handling.
2. **Online user flow** reads those prepared artifacts to produce a direct
   briefing or a conversational, evidence-backed plan.
3. **Evaluation** measures the system outside the product request path.

No user query fetches issuer pages or Reddit, parses PDFs, imports statements,
or changes the rule registry or indexes.

Ticket status symbols reflect the current Linear plan:

- ✅ Done
- ⏳ Backlog / remaining floor work
- ◇ Below-the-line optional work
- 👤 Manual user action

## Offline preparation flow

These jobs run manually or during an explicit import/refresh. Their outputs are
versioned, local artifacts consumed read-only by the online flow.

```mermaid
flowchart TB
    OP([User / operator])

    OP -->|"Manual account login and check"| V24["👤 VKU-24<br/>Verify account benefits"]
    V24 --> V25["⏳ VKU-25<br/>Expand benefit coverage"]
    V25 --> V26["⏳ VKU-26<br/>Refresh guides and report invalidations"]

    OP -->|"Benefit guides, CSV / OFX"| S22["✅ VKU-22<br/>Local-only data staging"]
    S22 --> T15["✅ VKU-15<br/>Normalize transactions<br/>Resolve merchants"]
    T15 --> P29["⏳ VKU-29<br/>Persist ledger and merchant decisions"]
    P29 --> LEDGER[("SQLite transaction ledger")]

    V26 --> CORPUS[("Versioned official-clause corpus")]
    CORPUS --> R17["⏳ VKU-17<br/>Extractor + Verifier"]
    R17 --> REG[("SQLite rule registry")]
    CORPUS --> O13["⏳ VKU-13<br/>Build official-clause index"]
    O13 --> OINDEX[("Official-clause search index")]

    S22 --> C23["✅ VKU-23<br/>Real offline Reddit collection"]
    C23 --> COMM[("Served + conflicting<br/>community corpora")]
    COMM --> O28["◇ VKU-28<br/>Build optional community index<br/>and measure reranking"]
    O28 --> CINDEX[("Optional community search index")]

    C12["✅ VKU-12<br/>Synthetic fixtures, corpus schema,<br/>and frozen evaluation set"]

    classDef done fill:#dcfce7,stroke:#15803d,color:#14532d;
    classDef pending fill:#fef3c7,stroke:#b45309,color:#78350f;
    classDef optional fill:#f3e8ff,stroke:#7e22ce,color:#581c87;
    class S22,T15,C23,C12 done;
    class V24,V25,V26,P29,R17,O13 pending;
    class O28 optional;
```

## Online user flow

The online path performs no source collection or ingestion. It reads the
prepared SQLite stores and search indexes.

```mermaid
flowchart TB
    U([User]) --> CHOICE{"What does the user need?"}
    CHOICE -->|"Show all benefits"| BRIEF["Core benefit briefing"]
    CHOICE -->|"Ask a question"| REACT

    subgraph DET["Deterministic tools — authoritative facts"]
        direction TB
        REG[("SQLite rule registry<br/>from VKU-17")]
        LEDGER[("SQLite transaction ledger<br/>from VKU-29")]
        ENGINE["✅ VKU-16<br/>Deterministic evaluator"]
        STATUS["Statuses, used value,<br/>remaining value, deadlines,<br/>reason codes and evidence"]
        FACTS["Verified deterministic facts"]
        CHECK["Deterministic plan<br/>feasibility check"]

        REG --> ENGINE
        LEDGER --> ENGINE
        ENGINE --> STATUS
        ENGINE --> FACTS
    end

    subgraph RAG["RAG — evidence retrieval only"]
        direction TB
        OINDEX[("Official-clause index")]
        RETRIEVE["⏳ VKU-13<br/>Official-clause retrieval"]
        CLAUSES["Version-correct clauses<br/>and citations"]

        CINDEX[("Optional community index")]
        CRETRIEVE["◇ VKU-28<br/>Community retrieval"]
        IDEAS["Non-authoritative ideas<br/>with source URLs"]

        OINDEX --> RETRIEVE --> CLAUSES
        CINDEX -.-> CRETRIEVE -.-> IDEAS
    end

    subgraph LOOP["ReAct loop and planning"]
        direction TB
        REACT["⏳ VKU-14<br/>Hand-rolled ReAct loop"]
        MULTI{"Several expiring benefits?"}
        PLAN["⏳ VKU-19<br/>Parallel researchers + Planner"]
        ANSWER["Ranked, evidence-backed answer"]

        REACT --> MULTI
        MULTI -->|"No"| ANSWER
        MULTI -->|"Yes"| PLAN
    end

    BRIEF --> ENGINE
    STATUS --> U

    REACT -->|"Evaluate benefits"| ENGINE
    FACTS -->|"Tool result"| REACT

    REACT -->|"Retrieve governing terms"| RETRIEVE
    CLAUSES -->|"Evidence"| REACT

    REACT -.->|"Optional ideas"| CRETRIEVE
    IDEAS -.->|"Unverified evidence"| REACT

    PLAN --> CHECK
    CHECK --> ANSWER
    ANSWER --> U

    classDef done fill:#dcfce7,stroke:#15803d,color:#14532d;
    classDef pending fill:#fef3c7,stroke:#b45309,color:#78350f;
    classDef optional fill:#f3e8ff,stroke:#7e22ce,color:#581c87;
    class ENGINE done;
    class REACT,RETRIEVE,PLAN pending;
    class CRETRIEVE optional;
```

## Evaluation and submission flow

Evaluation consumes the same prepared artifacts and runtime outputs, but it is
not part of an end-user request.

```mermaid
flowchart LR
    FROZEN["✅ VKU-12<br/>Frozen synthetic set"] --> COMPARE["⏳ VKU-18<br/>Retrieval baseline vs<br/>tool-based architecture"]
    RUNTIME["Online runtime outputs"] --> COMPARE

    LOCAL["Local registry + ledger"] --> REAL["⏳ VKU-27<br/>Local real-data validation"]
    CONFLICTS["✅ VKU-23<br/>Conflicting-ideas corpus"] --> SAFETY["Required authority-boundary<br/>safety evaluation"]

    COMMUNITY["◇ VKU-28<br/>Test-copy community index"] -.-> RED["◇ VKU-20<br/>Optional red-team agent"]
    RUNTIME -.-> RED

    COMPARE --> FINAL["⏳ VKU-21<br/>Ablation, ADR, failure analysis,<br/>metrics, docs and demo"]
    REAL --> FINAL
    SAFETY --> FINAL
    RED -.-> FINAL

    classDef done fill:#dcfce7,stroke:#15803d,color:#14532d;
    classDef pending fill:#fef3c7,stroke:#b45309,color:#78350f;
    classDef optional fill:#f3e8ff,stroke:#7e22ce,color:#581c87;
    class FROZEN,CONFLICTS done;
    class COMPARE,REAL,FINAL pending;
    class COMMUNITY,RED optional;
```

## Ticket-to-user-outcome map

| Ticket | Flow | Architectural role | User relevance |
|---|---|---|---|
| **VKU-12 ✅** | Offline + evaluation | Clause schema, fixtures, frozen set | Supplies reproducible test evidence, not runtime data |
| **VKU-22 ✅** | Offline | Local-only staging boundary | Safely receives manually supplied guides and exports |
| **VKU-15 ✅** | Offline | Transaction normalization and merchant resolution | Converts exports into structured evidence before queries |
| **VKU-23 ✅** | Offline + evaluation | Real offline community collection | Produces source-linked ideas and the safety corpus |
| **VKU-16 ✅** | Online | Deterministic authority | Returns exact statuses, values, periods, and deadlines |
| **VKU-24 👤** | Offline/manual | Account verification | Ensures prepared benefits match the actual account |
| **VKU-25 ⏳** | Offline | Benefit-scope expansion | Covers every benefit across both cards |
| **VKU-26 ⏳** | Offline | Guide refresh and invalidation | Prevents stale terms from reaching runtime |
| **VKU-29 ⏳** | Offline storage | SQLite ledger and merchant persistence | Makes runtime restart-safe and model-independent |
| **VKU-17 ⏳** | Offline storage | Extractor/Verifier and SQLite registry | Produces the only rules the online evaluator may use |
| **VKU-13 ⏳** | Offline build + online read | Official-clause index and retrieval | Supplies version-correct citations during a query |
| **VKU-14 ⏳** | Online | ReAct loop | Handles natural-language questions and explanations |
| **VKU-19 ⏳** | Online | Researchers and Planner | Produces one feasible multi-benefit action plan |
| **VKU-27 ⏳** | Evaluation | Local real-data validation | Measures account-accurate behavior outside runtime |
| **VKU-18 ⏳** | Evaluation | A-vs-B comparison | Measures deterministic tools against vanilla RAG |
| **VKU-21 ⏳** | Evaluation/submission | Final analysis and documentation | Consolidates evidence, failures, ADR, docs, and demo |
| **VKU-28 ◇** | Offline build + online read | Optional community index/retrieval | Adds ranked, non-authoritative usage suggestions |
| **VKU-20 ◇** | Evaluation | Optional generated adversary | Adds prompt-injection regression coverage |

## Authority boundary

### Deterministic authority

VKU-16, VKU-17, and VKU-29 own transaction occurrence, eligibility,
periods, amounts, remaining value, deadlines, and status. Model output cannot
change those facts.

### Model-authoritative merchant resolution

VKU-15 resolves a raw statement descriptor to a canonical merchant during
transaction ingest. VKU-29 persists that decision so the runtime briefing does
not need a model call. Missing or unresolved decisions produce an
`indeterminate` result rather than a guess.

### Model-assistive interaction

VKU-13, VKU-14, VKU-19, and optional VKU-28 retrieve evidence, explain verified
facts, and propose plans. The deterministic feasibility check rejects plan
items that exceed remaining value, miss a deadline, or violate known
constraints.

## Execution dependency map

```text
VKU-24 → VKU-25 → VKU-26 → VKU-13 ┐
                            → VKU-17 ├→ VKU-14 → VKU-19 → VKU-18 → VKU-21
VKU-15 + VKU-16 + VKU-22 → VKU-29 ┘             │
                                  VKU-17 + VKU-29 → VKU-27 → VKU-21

Optional:
VKU-13 + VKU-23 → VKU-28 → VKU-20
```

The immediate unblocked work is VKU-24 and VKU-29. VKU-24 requires manual
login, MFA, account selection, and consent; these steps must not be automated.
