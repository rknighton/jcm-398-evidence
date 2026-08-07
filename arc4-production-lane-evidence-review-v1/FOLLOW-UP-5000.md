# Full replay of the 5,000 generated queries

> **Status: complete.** This specification was written when the package contained only the 33
> nominated replays. The experiment it describes has since been executed and is shipped at
> [evidence/full-suite-replay/](evidence/full-suite-replay/REPORT.md). The specification is
> retained so the delivered work can be checked against what was promised, point by point.

The earlier packet did not claim that all 5,000 generated queries were replayed through both shipped scoring lanes. Only 33 screen nominations received that complete replay.

Closing the generated-suite gap required a bounded follow-up experiment that:

| # | Required | Delivered |
| --- | --- | --- |
| 1 | Reads every record from [provider-text.jsonl](evidence/adversarial-falsification/artifacts/queries/provider-text.jsonl). | Yes. 5,000 of 5,000, split 1,667 / 1,667 / 1,666 by corpus. |
| 2 | Resolves each frozen corpus to equivalent local indexes. | Yes. The same three frozen databases, each digest verified against `provenance.json` before scoring. |
| 3 | Runs every query once through the NumPy-present lane and once through the NumPy-absent lane using the retained actual-lane scorer. | Yes. `embedding_matrix._build` and `EmbeddingMatrix.score_all` from the pinned v1.108.228 wheel, in two isolated environments. |
| 4 | Compares rank 0, ordered top-k, membership, and first differing full-rank position. | Yes, plus exact-tie partitions, which the maintainer also asked to see reported separately. |
| 5 | Records failures and missing inputs rather than silently dropping cases. | Yes. `compare_lanes.py` has no `continue` in its checking loop and exits non-zero on any unclassified case. Its first run flagged 29 swaps it could not classify from top-100 data; those were resolved by capturing full-depth scores, not by relaxing the check. |
| 6 | Publishes all 5,000 paired outcomes, a manifest, and an independent verification receipt. | Yes. `raw/`, the package `CHECKSUMS.sha256`, and a comparison verifier that re-derives every published number from the shipped bytes with the standard library alone. |

The retained [actual-lane replay implementation](evidence/adversarial-falsification/harness/real_replay.py) was the starting point. It consumed the 33 screen hits and carried publication-normalized path placeholders, so it was adapted rather than run as-is; [`full_replay.py`](evidence/full-suite-replay/harness/full_replay.py) keeps every result-determining line and changes only the input set, the recorded fields, and the hardcoded roots, which became a required environment variable.

**What it established, and what it still does not.** It measures the disagreement rate within this generated suite and the preliminary filter's miss rate against ground truth. It does not estimate a production-user rate, and it compares the scoring lane rather than a complete tool response.
