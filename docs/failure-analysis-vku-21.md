# VKU-21 failure analysis

## Synthetic frozen benchmark

Dataset `slice0-2026-09-19.v1`, terms `synthetic-2026-09-19.v1`, **36 cases**. The deterministic tool path was **36/36** status, **36/36** remaining value, and **36/36** deadline accuracy. It covered fully used 11, indeterminate 11, partially used 6, and unused 8 cases. The retrieval baseline was **20/36** status, **20/36** remaining value, and **28/36** deadline accuracy. Its false-unused rate was **0/4**, indeterminate precision **11/26**, and indeterminate coverage **11/11**.

Retrieval failures were cases `case-03, case-04, case-05, case-06, case-07, case-10, case-11, case-12, case-14, case-15, case-16, case-17, case-18, case-21, case-22, case-24, case-25, case-26, case-29, case-30, case-31, case-35, case-36`. They are retrieval-context failures: the baseline put incomplete or wrong transaction evidence in one vector store, so it could not reliably handle enrollment, portal gating, near-miss descriptors, period boundaries, or exact arithmetic. The selected architecture fixes this by keeping transaction filtering and arithmetic in deterministic tools.

The arithmetic-only ablation uses the same 36 cases after deterministic transaction selection. Its exact error numerator/denominator is recorded in the generated final report. It does not measure merchant resolution or eligibility.

## Local real-data integration, separate result set

Dataset `local-real-data-integration-vku-27` is real staged issuer guides, real local transactions, and real public community inputs. It is **not a human-labelled accuracy benchmark**: accuracy, false-unused, precision, recall, remaining-value accuracy, and deadline accuracy are unavailable (`null`), not zero. The run had 82 mapped benefit rows, 15 supported active benefits, 12 indeterminate mappings, and 55 known-untrackable benefits; 51 active rules were loaded. The prepared ledger contained 1,375 transactions and 563 merchant decisions, of which 375 were resolved and **188 remained unresolved**.

The demo applies the explicit fallback that all 188 unresolved descriptors are outside the active benefit groups. This can create false-unused results. Unknown enrollment, portal state, current selection, and availability are also recorded account-state assumptions. No local count is substituted with a synthetic count.

## Safety and retrieval

The real conflicting-ideas corpus `community-synthetic-2026-09-19.v1` resisted **3/3** attacks and served/indexed **0/3**. The generated red-team run resisted **10/10** attempts with **0/10** generated attack successes; it is secondary to the real conflict corpus. Community retrieval served **10/10** current ideas. Baseline and exact-index Recall@5 were **10/10**; baseline and reranked MRR were **10.0/10**. The simpler unranked path was retained and the index/reranker cut.

## Qualitative and operational gaps

The fixed qualitative rubric is helpfulness, clarity, evidence traceability, and authority-boundary disclosure. A human-scored calibration sample was not collected in this run, so no qualitative score is claimed. The rubric is never used for status correctness or recommendation validity; the latter is checked separately against governing clauses and the deterministic feasibility check. Prior runs did not persist live token-usage metadata, so token cost is reported as unavailable rather than invented. Offline comparison latency is measured by the final report harness; live latency and token cost require a future usage-instrumented run.
