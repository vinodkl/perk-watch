# VKU-17 rule registry

`perk_watch.rule_registry` is the offline Extractor/Verifier boundary. The
Extractor returns only structured fields. The Verifier is called with exactly
the source clause and that proposal, and returns `supported`,
`partial_support`, or `disagreement`. Only `supported` rows enter
`prepared/rules/registry.sqlite3`; every decision is retained in
`rule_decisions` for audit.

The persisted `active_rules` table is the sole source for calculation rules.
It stores clause/source IDs, effective dates, terms version, period and value
fields, and structured eligibility. `benefits.evaluate_persisted_benefits`
loads only this table, so reopening SQLite reproduces the same evaluator input.
A changed prepared clause is reprocessed, unchanged clauses are skipped, and
removed clauses cannot remain active.

Independent Extractor and Verifier roles qualify as multi-agent because the
Verifier has an explicit information boundary and can reject the proposal.
The fixed community collector is a deterministic data-preparation pipeline,
not an independent judgment of a rule, and is therefore not multi-agent rule
verification.
