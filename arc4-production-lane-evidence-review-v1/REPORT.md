# Arc 4 evidence review

## Key Judgment

Small numerical differences between the NumPy and pure-Python scoring methods were already known and expected. Testing confirms they can change a ranking. The requested fixed-suite comparison at the pinned release found the returned results identical on all 12 ranking problems, differing only in exact-tie partitions and in ordering far below the returned depth. A supplemental replay of all 5,000 generated queries through both scorers found **no change to the first result in any of them**, while ordering and membership did differ inside returned depths. The evidence cannot establish a production failure rate or prove perfect safety. On balance the faster method appears more likely than not safe enough to keep. This is a working engineering judgment, not a mathematical proof or a production-rate measurement.

## Working Hypothesis

The research question was never whether the methods are perfectly identical. Different numerical precision made exact identity an unreasonable expectation, and the maintainer had already [reported a synthetic rank-0 disagreement](https://github.com/jgravelle/jcodemunch-mcp/issues/398#issuecomment-5172823848).

The working hypothesis was that these expected differences would usually be too small or too deep in the ranking to matter in normal use, making the faster method worth retaining if uncertain cases could be handled. The experiments tried to disprove that hypothesis using deliberately sensitive synthetic cases, semi-realistic generated searches, fixed real-codebase comparisons, a complete replay of the generated suite, and a guarded research candidate.

## Evidence That Survived Adversarial Review

The evidence is ordered by what it answers, not by size. The first row is the comparison the maintainer requested; everything below it is supplemental.

| Evidence | What it shows | What it does not show |
| --- | --- | --- |
| **[Official-package production-lane comparison](evidence/comparison-v2/RESEARCH-REPORT.md)**, the requested deliverable | On 12 fixed ranking problems at the pinned v1.108.228: rank 0, ordered top-k and membership identical in 12 of 12; exact-tie partitions differed in 8 of 12. The earliest full-depth divergence in any of the 120 pairs was position 1,556, so the first 100 positions matched everywhere. | Twelve problems built from four query vectors are a purposive census, not a prevalence estimate. Repetitions establish stability, not breadth. |
| [Synthetic boundary tests](evidence/adversarial-falsification/REPORT.md) | A four-symbol fixture produced a stable rank-0 change across 24 insertion orders and 50 fresh-process replays. A larger geometric stress test produced 3,211 rank-0 changes among 10,002 deliberately sensitive cases. The expected numerical difference can reach a public result. | These are constructed sensitivity tests, not normal-use samples. They establish neither production frequency nor which result is better. |
| [Complete generated-suite replay](evidence/full-suite-replay/REPORT.md), supplemental | All 5,000 mechanically generated queries were scored through both shipped lanes. **No query changed its first result.** Ordering differed in 114 of 5,000, membership within the first 25 results in 16, and the earliest difference appeared at position 2. | It is a generated suite, not user traffic, and it compares the scoring lane rather than a complete tool response. It cannot establish a production rate. |
| [First-swap classification](evidence/full-suite-replay/REPORT.md), supplemental | In 103 of the 114 disagreeing queries the first differing pair was scored exactly equal by the pure-Python lane and unequal by the NumPy lane. Nine were the reverse, and two were strict inversions in both lanes. | It classifies the first differing pair only, and 83 of the 114 change more than two positions, so it does not characterise whole permutations. The stored-vector explanation for those 103 is an inspected example plus an attested census, not a gated result. |
| [Guarded research candidate](../arc4-real-embedding-certification-v1/REPORT.md) | Exact boundary rescore and fallback preserved the ordered outputs across its 12 frozen problems. | It was measured against package version 1.108.212, not the 1.108.228 pinned here. It is not an official released implementation, does not prove universal parity, and is not used as product-performance evidence. |

The 5,000 generated queries, the 10,002 executed geometric cases, the preserved failed attempts, and the complete comparison rankings are unpacked parts of this report. [The dataset inventory](DATASET-INVENTORY.md) links directly to them.

## What the Complete Replay Changed

Two statements in the earlier draft of this report did not survive the full replay, and both corrections are recorded here rather than quietly dropped.

**The preliminary filter missed most of what it was looking for.** It nominated 33 of 5,000 searches. Measured against the complete replay, that is 5 correct nominations, 28 false alarms, and **109 missed**. Any statement that rested on the 33 nominations understated the suite by roughly an order of magnitude, which is why the earlier draft refused to use 5,000 as a denominator at all. It is now a real denominator.

**"Only deep adjacent swaps" was wrong.** That description fit the five nominated findings, whose earliest change was at position 38. Across the full suite differences reach position 2, nineteen searches differ inside the first 25 results, four change which results appear in the first five, and 83 of the 114 differ in more than two positions.

Working against those, the replay also supplies the reassurance the package previously could not: rank 0 held in all 5,000.

## Overall Judgment

Under a strict requirement that installation state must never change a result, the two methods do not meet the standard. That was already expected and is now independently reproducible.

Under the practical question that matters here, whether the difference is likely to cause enough meaningful harm to outweigh the faster method's value, the evidence supports continued use more than rejection. The fixed official-package suite found no returned-result change, and no query in the supplemental generated suite changed its first result. No experiment demonstrated a worse answer or a downstream task failure.

## Adversarial Position

The strongest case against this judgment is the absence of representative field evidence, not demonstrated user harm.

- **The production rate is unknown.** No experiment sampled representative multi-user traffic. The complete replay gives a within-suite rate for mechanically generated searches, which is not a field rate.

- **A ranking change is not evidence of a worse answer.** Every confirmed rank-0 change was synthetic and had no independent relevance labels, and no experiment here compares answer quality in either direction. Testing that directly is not immediately feasible without substantially more data and realistic rank-0 examples.

- **The strongest controlled comparison is narrow, and narrower than it looks.** The official-package study covered 12 fixed ranking problems built from only four distinct query vectors, and comparison-v1 and the guarded candidate cover the same 12 problems on the same three corpora. These are three views of one suite, not three independent suites.

- **The replay measures the scoring lane, not the whole tool.** It compares the ordering the scorer produces. Adapter-to-tool agreement was separately confirmed for 5 cases, not for 5,000. The requested comparison, by contrast, measured complete tool responses.

- **The mechanism account is the least mature thing here.** It classifies the first differing pair, and its stored-vector explanation rests on an inspected example plus a census derived from databases this package does not ship. It is offered as a hypothesis, and nothing in the recommendation depends on it.

- **Formal acceptance has a ceiling.** The comparison-v2 findings were directly reconciled, but literal completion of every design requirement was not achieved: the final mutation campaign stopped at 53 of 93 tests, and the final refined verifier has no canonical success receipt. This limits formal acceptance claims without erasing the retained observations.

## Recommendation

1. **Continue treating the faster method as a reasonable engineering choice.** The available evidence makes practical acceptability more likely than not, while stopping short of a safety proof.

2. **Investigate canonical ordering of equivalent results, as a hypothesis worth testing.** In 103 of the 114 disagreeing queries the first differing pair was tied by the pure-Python lane and separated by the NumPy lane, so `(-score, symbol_id)` had nothing to act on in one lane. An inspected Django example shows two symbols with byte-identical stored vectors whose NumPy scores still differ by one float32 step, which would make a blocked reduction row-order sensitive. Neither the coverage of a canonicalisation nor its cost has been measured here, so this is a follow-up to scope rather than a change to make. It does not move the premise on which the maintainer [parked lane 3](https://github.com/jgravelle/jcodemunch-mcp/issues/403#issuecomment-5167882069), and it is not a request to unpark it.

3. **Keep the sensitive examples as regression cases.** Label the synthetic rank-0 cases, the two genuine inversions, and the deep reorderings as consistency tests, not demonstrated quality failures.

4. **Prioritize representative monitoring if stronger assurance becomes necessary.** The complete generated-suite replay is useful supplemental evidence; production observation is required to estimate real incidence and downstream effect.

5. **Keep claims conservative.** Do not claim perfect equivalence, a production failure rate, or answer degradation from the available data.

Detailed provenance, limitations, and verification status remain in the [source map](SOURCE-MAP.md), [claim ledger](CLAIM-LEDGER.csv), [retained-verifier status](RETAINED-VERIFIERS.md), and [source notes](SOURCE-NOTES.md).
