# PerkWatch V2 Phase 1

## Local-data preparation flow

```mermaid
flowchart LR
    A[Manual collection\nissuer login, MFA, exports] --> B[PERKWATCH_DATA_DIR/raw/<card>\nbenefits, CSV / OFX, community notes]
    B --> C[v2/scripts/prepare_data.py\nlocal-only preparation]
    C --> D[Validate and normalize\nbenefits, transactions, merchants]
    D --> E[(prepared/perkwatch.sqlite)]
    D --> F[prepared/report.json]
```

Issuer login, MFA, account selection, transaction export, and any consent are
manual. Preparation does not contact issuers or Reddit. Real inputs and
prepared outputs remain under `PERKWATCH_DATA_DIR`.

## SQLite structure

```mermaid
erDiagram
    cards ||--o{ benefits : has
    cards ||--o{ transactions : has
    sources ||--o{ benefits : references
    sources ||--o{ transactions : references
    transactions ||--o| merchant_matches : resolves
    transactions ||--o| credit_matches : confirms
    benefits ||--o{ credit_matches : identifies
    benefits ||--o{ community_ideas : supports

    cards {
        text card_id PK
        text display_name
    }
    sources {
        text source_id PK
        text card_id
        text kind
        text path
        text content_sha256
    }
    benefits {
        text benefit_id PK
        text card_id FK
        integer amount_minor
        text period
        text terms
        text source_id FK
    }
    transactions {
        text transaction_id PK
        text card_id FK
        text posted_date
        integer amount_minor
        text description
        text source_id FK
    }
    merchant_matches {
        text transaction_id PK
        text merchant
        text confidence
    }
    credit_matches {
        text transaction_id PK
        text benefit_id FK
        text confidence
    }
    community_ideas {
        text idea_id PK
        text benefit_id FK
        text terms_version
        text source_url
    }
```

`amount_minor` stores integer cents. Transaction IDs are stable hashes, so
overlapping exports do not create duplicate ledger rows. Unclear benefit fields
remain unknown, unresolved merchant matches are recorded rather than invented,
and only explicit unambiguous statement credits become credit matches.
