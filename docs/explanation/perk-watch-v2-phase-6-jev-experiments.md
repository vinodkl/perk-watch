# PerkWatch V2 Phase 6: Jev experiments

Test whether TypeSafe Jev improves two narrow decisions without replacing the working V2 system. See [PerkWatch V2 design](perk-watch-v2-design.md).

## Goal

Use the Phase 5 evaluation set to decide whether either Jev experiment earns its extra provider, cost, latency, and privacy tradeoff.

## Experiments

- **Official benefit reranking:** Keep embedding search and its normal card, benefit, and source-date filters. Judge only the shortlisted official passages against a question, then compare their order with the Phase 5 embedding-only and LLM-reranked baselines. A reranker cannot recover a passage missing from the shortlist.
- **Merchant matching:** Keep exact local matching first. For otherwise-unknown cleaned descriptions, let Jev choose only from the existing fixed merchant list plus `unknown`. Compare against the current model fallback using labeled, non-private examples, including ambiguous and no-match descriptions. Save uncertain or unsupported matches as `unknown`.

## Boundaries

- Run experiments offline on evaluation data; do not call Jev by default during monthly preparation or user questions.
- Before any real-data run, obtain explicit approval for TypeSafe as a separate outbound provider. Apply the shared PII redactor and existing merchant-data limits: only a cleaned description and fixed merchant list, never amounts, dates, account details, filenames, or full transaction rows. Treat benefit text and questions as outbound data too.
- Keep benefit amounts, periods, eligibility, balances, refunds, deadlines, and transaction evidence grounded in official sources and code. A Jev judgment or confidence score cannot establish an official fact or certify a community idea as conflict-free.
- Do not commit real card data, private transaction rows, prompts containing them, or generated output. Preserve the existing behavior when Jev is unavailable.

## Done when

- The same evaluation inputs compare baseline and Jev reranking for relevant-source retrieval, and compare existing and Jev merchant matching for correct matches, false matches, and `unknown` outcomes.
- Results record latency, provider calls, cost, and failures alongside accuracy. Confidence thresholds, if used, are chosen from measured examples rather than a cookbook default.
- Each experiment has a documented keep-or-reject decision. Only integrate a winning change separately, without making Jev necessary for the working V2 path.

## Checks

- Test an ambiguous merchant, a merchant outside the fixed list, and a relevant passage absent from the shortlist.
- Verify outbound payloads respect the redactor and merchant-data limits, and provider failure leaves existing behavior intact.
- Run `python3 v2/scripts/check_local_data_guard.py` and `python3 -m unittest discover -s v2/tests` if implementation changes.

## Depends on

[Phase 5: Evaluation and search improvements](perk-watch-v2-phase-5-evaluation.md).
