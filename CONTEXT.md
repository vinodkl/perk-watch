# PerkWatch domain language

## Card

One card product/account scope, identified by a stable `card_id`. Benefits,
transactions, and community notes always belong to a card.

## Raw data

Manually collected, local-only source material for a card: issuer benefit
guides, transaction exports, and sanitized public-community notes. Raw data is
never read by the user-facing application.

## Prepared data

The linked, normalized local model built from raw data and read by PerkWatch.
It includes versioned benefit clauses, normalized transactions, reviewed
community ideas, and a preparation report.

## Benefit

An issuer-provided card entitlement with a stable `benefit_id`. Authoritative
eligibility, amounts, periods, and constraints come only from issuer terms.

## Community idea

A short, source-linked paraphrase of public community guidance associated with
a `benefit_id`. It is non-authoritative and can be served only after review
against the current benefit terms.

## Terms version

A deterministic identity for the complete set of current raw benefit sources.
A changed source creates a changed terms version and invalidates dependent
rules, citations, evaluations, conclusions, and community reviews.
