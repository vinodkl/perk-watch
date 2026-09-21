# VKU-20 red-team safety evaluation

The evaluation is evaluation-only. `scripts/evaluate_red_team.py` reads the
synthetic frozen terms, fixtures, status facts, and conflicting-ideas corpus.
Each of the 10 predeclared benefits receives **1 attempt**, so the run has
**10 attempts**. The completion path is `--attacker-model MODEL`, which uses
OpenAI chat completion with the existing `OPENAI_API_KEY`; the deterministic
attacker remains only an offline fallback. The attacker receives the benefit,
governing clause, and true engine facts, then generates text attempting to move
status, used amount, remaining value, and deadline.

## Results

- dataset: `slice0-2026-09-19.v1`
- terms: `synthetic-2026-09-19.v1`
- completion attacker: `gpt-4o-mini` via the existing OpenAI adapter
- completion command: `.venv/bin/python scripts/evaluate_red_team.py --attacker-model gpt-4o-mini`
- model-generated attack success rate: **0/10**
- model-generated attack resistance rate: **10/10**
- protected fields checked: status, used amount, remaining value, deadline
- observed failures: **[]**
- frozen generated regression cases: **0/10**, therefore none were added

The real conflicting-ideas corpus remains the headline safety case:

- corpus: `community-synthetic-2026-09-19.v1`
- dataset: `slice0-2026-09-19.v1`
- conflicting ideas resisted: **3/3**
- conflicting ideas served or indexed: **0/3**

Adversarial rows and the test index are built under a temporary directory and
never pass through the production community index, source snapshots, or
`data/real`. The runtime's deterministic evaluator supplies all protected facts;
retrieved community text is non-authoritative and cannot mutate them.

## Coverage gaps

- One model-generated attempt per benefit, not a larger campaign.
- Synthetic terms, transactions, and community data only.
- No generated attack succeeded, so there are no permanent attack fixtures to
  replay yet.
