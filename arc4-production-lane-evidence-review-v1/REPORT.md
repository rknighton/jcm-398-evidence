# Arc 4 evidence review

## Key Judgment

Small numerical differences between the NumPy and pure-Python scoring methods were already known and expected. The testing confirmed that those differences can change a ranking, but it did not find evidence that they create a practically significant problem in the completed semi-realistic or fixed real-codebase comparisons. The evidence also cannot establish a production failure rate or prove perfect safety. On balance, the faster method appears more likely than not safe enough to be worth using, especially when uncertain boundaries are checked with the exact method. This is a working engineering judgment, not a mathematical proof or production-rate measurement.

## Working Hypothesis

The research question was never whether the methods are perfectly identical. Different numerical precision made exact identity an unreasonable expectation, and the maintainer had already [reported a synthetic rank-0 disagreement](https://github.com/jgravelle/jcodemunch-mcp/issues/398#issuecomment-5172823848).

The working hypothesis was that these expected differences would usually be too small or too deep in the ranking to matter in normal use, making the faster method worth retaining if uncertain cases could be checked exactly. The experiments tried to disprove that hypothesis using deliberately sensitive synthetic cases, semi-realistic generated searches, fixed real-codebase comparisons, and a guarded research candidate.

## Evidence That Survived Adversarial Review

| Evidence | What it shows | What it does not show |
| --- | --- | --- |
| [Synthetic boundary tests](evidence/adversarial-falsification/REPORT.md) | A four-symbol fixture produced a stable rank-0 change across 24 insertion orders and 50 fresh-process replays. A larger geometric stress test produced 3,211 rank-0 changes among 10,002 deliberately sensitive cases. The expected numerical difference can reach a public result. | These are constructed sensitivity tests, not normal-use samples. They establish neither production frequency nor which result is better. |
| [Generated-text study](evidence/adversarial-falsification/REPORT.md) | A preliminary filter examined 5,000 mechanically generated searches and nominated 33 for complete replay through both actual methods. Five produced adjacent two-position swaps, first at positions 38, 65, 65, 76, and 78. The top 25, rank 0, and top-100 membership were unchanged in all five. | The filter was not validated against the 4,967 rejected searches, so the 5,000 total cannot support a disagreement rate or safety probability. |
| [Official-package fixed comparison](evidence/comparison-v2/RESEARCH-REPORT.md) | All 12 fixed ranking problems matched on rank 0, ordered returned results, and membership. Numerical differences appeared only deeper in the complete rankings. | Twelve fixed problems are too narrow to establish general behavior or production incidence. Repetitions improve confidence in those cases, not breadth. |
| [Guarded research candidate](../arc4-real-embedding-certification-v1/REPORT.md) | Exact boundary rescore and fallback preserved the ordered outputs across its 12 frozen problems. This supports exact checking as a plausible risk control. | It was not an official released implementation, does not prove universal parity, and is not used here as product-performance evidence. |

The generated-suite gap is closable, but the current package does not present it as turnkey. The package includes [all 5,000 frozen queries](evidence/adversarial-falsification/artifacts/queries/provider-text.jsonl) and the [actual-lane replay implementation](evidence/adversarial-falsification/harness/real_replay.py). Replaying all 5,000 requires adapting that implementation to consume the complete query file and supplying equivalent local indexes. [The bounded follow-up specification](FOLLOW-UP-5000.md) defines the required output. It would establish the disagreement rate within this generated suite and reveal filter misses, but it would still not establish a production-user rate.

The 5,000 generated-text queries, 10,002 executed geometric cases, preserved failed attempts, and complete comparison rankings are unpacked parts of this report. [The dataset inventory](DATASET-INVENTORY.md) links directly to them and explains the lossless compression of the single oversized paired JSONL file.

## Overall Judgment

Under a strict requirement that installation state must never change a result, the two methods do not meet the standard. That was already expected and is now independently reproducible.

Under the practical question that matters here, whether the difference is likely to cause enough meaningful harm to outweigh the faster method's value, the evidence supports continued use more than rejection. The completed semi-realistic replays found only deep adjacent swaps, the fixed official-package suite found no returned-result changes, and no experiment demonstrated a worse answer or downstream task failure. Exact checking or fallback remains the prudent control for uncertain boundaries.

## Adversarial Position

The strongest case against this judgment is the absence of representative field evidence, not demonstrated user harm.

- **The production rate is unknown.** No experiment sampled representative multi-user traffic, and the generated-text filter's miss rate is unknown.

- **A rank-0 change is not evidence of a worse answer.** Every confirmed rank-0 change was synthetic and had no independent relevance labels. Either result could be better, worse, or effectively equivalent. Testing that direction is not immediately feasible without substantially more data and realistic rank-0 examples.

- **The strongest controlled comparison is narrow.** The official-package study covered only 12 fixed ranking problems. Its repeated runs establish stability for those problems, not generality.

- **Formal acceptance has a ceiling.** The comparison-v2 findings were directly reconciled, but literal completion of every design requirement was not achieved: the final mutation campaign stopped at 53 of 93 tests, and the final refined verifier has no canonical success receipt. This limits formal acceptance claims without erasing the retained observations.

## Recommendation

1. **Continue treating the faster method as a reasonable engineering choice.** The available evidence makes practical acceptability more likely than not, while stopping short of a safety proof.

2. **Use exact boundary rescore or fallback where uncertainty can affect returned results.** This directly addresses the demonstrated consistency risk without assuming every difference is harmful.

3. **Keep the sensitive examples as regression cases.** Label the synthetic rank-0 cases and deep generated-text swaps as consistency tests, not demonstrated quality failures.

4. **Prioritize representative monitoring if stronger assurance becomes necessary.** A full replay of the 5,000 generated queries is useful supplemental evidence, but production observation is required to estimate real incidence and downstream effect.

5. **Keep claims conservative.** Do not claim perfect equivalence, a production failure rate, or answer degradation from the available data.

Detailed provenance, limitations, and verification status remain in the [source map](SOURCE-MAP.md), [claim ledger](CLAIM-LEDGER.csv), and [source notes](SOURCE-NOTES.md).
