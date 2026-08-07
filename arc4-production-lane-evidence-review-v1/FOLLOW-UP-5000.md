# Optional full replay of the 5,000 generated queries

The current packet does not claim that all 5,000 generated queries were replayed through both shipped scoring lanes. Only 33 screen nominations received that complete replay.

Closing this generated-suite gap requires a bounded follow-up experiment that:

1. Reads every record from [provider-text.jsonl](evidence/adversarial-falsification/artifacts/queries/provider-text.jsonl).
2. Resolves each frozen corpus to equivalent local indexes.
3. Runs every query once through the NumPy-present lane and once through the NumPy-absent lane using the retained actual-lane scorer.
4. Compares rank 0, ordered top-k, membership, and first differing full-rank position.
5. Records failures and missing inputs rather than silently dropping cases.
6. Publishes all 5,000 paired outcomes, a manifest, and an independent verification receipt.

The retained [actual-lane replay implementation](evidence/adversarial-falsification/harness/real_replay.py) is the starting point, but it currently consumes the 33 screen hits and contains publication-normalized path placeholders. It must be adapted before this follow-up is runnable. Completing it would estimate disagreement within this generated suite. It still would not estimate a production-user rate.
