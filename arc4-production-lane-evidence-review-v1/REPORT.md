# Arc 4 evidence review

## Key Judgment

Small numerical differences between the NumPy and pure-Python scoring methods were already known and expected. Testing confirms they can change a ranking. Replaying all 5,000 generated queries through both shipped lanes found **no change to the first result in any of them**, and found that most of the differences that do occur reorder items the embedding model scores as exactly equivalent. The evidence still cannot establish a production failure rate or prove perfect safety. On balance the faster method appears more likely than not safe enough to keep, provided the ordering of equivalent items is made canonical in both lanes. This is a working engineering judgment, not a mathematical proof or a production-rate measurement.

## Working Hypothesis

The research question was never whether the methods are perfectly identical. Different numerical precision made exact identity an unreasonable expectation, and the maintainer had already [reported a synthetic rank-0 disagreement](https://github.com/jgravelle/jcodemunch-mcp/issues/398#issuecomment-5172823848).

The working hypothesis was that these expected differences would usually be too small or too deep in the ranking to matter in normal use, making the faster method worth retaining if uncertain cases could be handled. The experiments tried to disprove that hypothesis using deliberately sensitive synthetic cases, semi-realistic generated searches, fixed real-codebase comparisons, a complete replay of the generated suite, and a guarded research candidate.

## Evidence That Survived Adversarial Review

| Evidence | What it shows | What it does not show |
| --- | --- | --- |
| [Synthetic boundary tests](evidence/adversarial-falsification/REPORT.md) | A four-symbol fixture produced a stable rank-0 change across 24 insertion orders and 50 fresh-process replays. A larger geometric stress test produced 3,211 rank-0 changes among 10,002 deliberately sensitive cases. The expected numerical difference can reach a public result. | These are constructed sensitivity tests, not normal-use samples. They establish neither production frequency nor which result is better. |
| [Complete generated-suite replay](evidence/full-suite-replay/REPORT.md) | All 5,000 generated searches were run through both shipped lanes. **No search changed its first result.** Ordering differed in 114 of 5,000, membership within the first 25 results in 16, and the earliest difference appeared at position 2. | It is a generated suite, not user traffic. It cannot establish a production rate, and it compares the scoring lane rather than a complete tool response. |
| [Why the differences happen](evidence/full-suite-replay/REPORT.md) | 103 of the 114 differences reorder pairs of symbols holding **byte-identical stored vectors**. The pure-Python lane scores those pairs exactly equal and orders them canonically; the NumPy lane assigns them slightly different scores because a blocked matrix product makes a float32 sum depend on the row's position. Nine are float32 ties broken by float64, and two are genuine score inversions. | It is measured on one host and one NumPy build. It does not establish how often this occurs in other environments. |
| [Official-package fixed comparison](evidence/comparison-v2/RESEARCH-REPORT.md) | All 12 fixed ranking problems matched on rank 0, ordered returned results, membership, and returned-list content through the first 100 positions. Exact-tie partitions differed in 8 problems and full-depth order in 10. | Twelve fixed problems built from four query vectors are too narrow to establish general behavior or production incidence. Repetitions improve confidence in those cases, not breadth. |
| [Guarded research candidate](../arc4-real-embedding-certification-v1/REPORT.md) | Exact boundary rescore and fallback preserved the ordered outputs across its 12 frozen problems. | It was measured against package version 1.108.212, not the 1.108.228 pinned here. It is not an official released implementation, does not prove universal parity, and is not used as product-performance evidence. |

The 5,000 generated queries, the 10,002 executed geometric cases, the preserved failed attempts, and the complete comparison rankings are unpacked parts of this report. [The dataset inventory](DATASET-INVENTORY.md) links directly to them.

## What the Complete Replay Changed

Two statements in the earlier draft of this report did not survive the full replay, and both corrections are recorded here rather than quietly dropped.

**The preliminary filter missed most of what it was looking for.** It nominated 33 of 5,000 searches. Measured against the complete replay, that is 5 correct nominations, 28 false alarms, and **109 missed**. Any statement that rested on the 33 nominations understated the suite by roughly an order of magnitude, which is why the earlier draft refused to use 5,000 as a denominator at all. It is now a real denominator.

**"Only deep adjacent swaps" was wrong.** That description fit the five nominated findings, whose earliest change was at position 38. Across the full suite differences reach position 2, nineteen searches differ inside the first 25 results, four change which results appear in the first five, and 83 of the 114 differ in more than two positions.

Working against those, the replay also supplies the reassurance the package previously could not: rank 0 held in all 5,000.

## Overall Judgment

Under a strict requirement that installation state must never change a result, the two methods do not meet the standard. That was already expected and is now independently reproducible.

Under the practical question that matters here, whether the difference is likely to cause enough meaningful harm to outweigh the faster method's value, the evidence supports continued use more than rejection. No search in the complete generated suite changed its first result, the fixed official-package suite found no returned-result change, and the dominant mechanism reorders items the model treats as identical. No experiment demonstrated a worse answer or a downstream task failure.

## Adversarial Position

The strongest case against this judgment is the absence of representative field evidence, not demonstrated user harm.

- **The production rate is unknown.** No experiment sampled representative multi-user traffic. The complete replay gives a within-suite rate for mechanically generated searches, which is not a field rate.

- **A ranking change is not evidence of a worse answer.** Every confirmed rank-0 change was synthetic and had no independent relevance labels. Of the differences seen in the generated suite, 103 of 114 reorder items with identical stored vectors, where neither order can be better. Testing answer quality directly is not immediately feasible without substantially more data and realistic rank-0 examples.

- **The strongest controlled comparison is narrow, and narrower than it looks.** The official-package study covered 12 fixed ranking problems built from only four distinct query vectors, and comparison-v1 and the guarded candidate cover the same 12 problems on the same three corpora. These are three views of one suite, not three independent suites.

- **The replay measures the scoring lane, not the whole tool.** It compares the ordering the scorer produces. Adapter-to-tool agreement was separately confirmed for 5 cases, not for 5,000.

- **Formal acceptance has a ceiling.** The comparison-v2 findings were directly reconciled, but literal completion of every design requirement was not achieved: the final mutation campaign stopped at 53 of 93 tests, and the final refined verifier has no canonical success receipt. This limits formal acceptance claims without erasing the retained observations.

## Recommendation

1. **Continue treating the faster method as a reasonable engineering choice.** The available evidence makes practical acceptability more likely than not, while stopping short of a safety proof.

2. **Make equivalent results order identically in both lanes.** This is where the evidence points and it is the cheapest available fix. The `(-score, symbol_id)` key shipped in v1.108.228 already canonicalises duplicate-vector clusters in the pure-Python lane without exception. It cannot fire in the NumPy lane because a blocked matrix product gives byte-identical vectors unequal float32 scores: 97 of 34,320 duplicate groups were split that way. Making the NumPy lane's scores comparable before the sort, or grouping identical rows, addresses 103 of the 114 observed differences at no runtime cost. Exact boundary rescore remains available for the remaining 11, but this evidence does not by itself make the case for building that subsystem, and the maintainer has [parked it on a stated premise](https://github.com/jgravelle/jcodemunch-mcp/issues/403#issuecomment-5167882069) that this work does not move.

3. **Treat re-indexing as a second consistency axis.** Because a NumPy-lane score depends on a row's position in the matrix, changing row order can change returned order with no change to any embedding, query, or installation state. The record currently frames the whole risk as NumPy presence.

4. **Keep the sensitive examples as regression cases.** Label the synthetic rank-0 cases, the two genuine inversions, and the duplicate-vector reorderings as consistency tests, not demonstrated quality failures.

5. **Prioritize representative monitoring if stronger assurance becomes necessary.** The complete generated-suite replay is useful supplemental evidence; production observation is required to estimate real incidence and downstream effect.

6. **Keep claims conservative.** Do not claim perfect equivalence, a production failure rate, or answer degradation from the available data.

Detailed provenance, limitations, and verification status remain in the [source map](SOURCE-MAP.md), [claim ledger](CLAIM-LEDGER.csv), [retained-verifier status](RETAINED-VERIFIERS.md), and [source notes](SOURCE-NOTES.md).
