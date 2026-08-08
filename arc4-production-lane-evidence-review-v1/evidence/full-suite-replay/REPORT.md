# Full-suite production-lane replay: all 5,000 generated queries

## What this is

The bounded follow-up specified in [FOLLOW-UP-5000.md](../../FOLLOW-UP-5000.md), executed. Every one of the 5,000 frozen provider-text queries was run through both shipped scoring lanes of JCodeMunch v1.108.228 against the same three frozen real-embedding corpora. The earlier adversarial packet fully replayed only the 33 queries a preliminary filter nominated.

**This is supplemental, not the requested deliverable.** The comparison the maintainer agreed to in [issue 398 comment 5177953577](https://github.com/jgravelle/jcodemunch-mcp/issues/398#issuecomment-5177953577) is the fixed production-lane study in [../comparison-v2/RESEARCH-REPORT.md](../comparison-v2/RESEARCH-REPORT.md), which measures complete tool responses on 12 frozen ranking problems. This replay is broader in query count and narrower in scope: it compares the scoring lane across mechanically generated query vectors. It is offered as an additional stress on that conclusion, and it uses the same four reported dimensions so the two can be read together.

## Result

| Dimension | Result |
| --- | --- |
| **Rank 0** | **0 differences in 5,000 queries** |
| Ordered top-k, at k = 1 / 5 / 10 / 25 / 50 / 100 | 0 / 5 / 11 / 19 / 51 / 114 |
| Top-k membership, at k = 1 / 5 / 10 / 25 / 50 / 100 | 0 / 4 / 10 / 16 / 33 / 29 |
| Exact-tie partition, within the returned top 100 | differs in 130 queries: django 6, fastapi 117, jcodemunch 7 |

| Supporting measure | Result |
| --- | --- |
| Any ordered difference inside the top 100 | 114 queries, 2.28% |
| Full-depth ordering hash differs | 4,971 queries, 99.4% |
| Shallowest first changed position | 2 |
| Positions changed inside the top 100 | exactly 2 in 31 queries, more than 2 in 83, maximum 97 |
| Per corpus, ordered top-100 differences | django 3 of 1,667; fastapi 103 of 1,667; jcodemunch 8 of 1,666 |

## What each result licenses

**Rank 0 held across the whole suite.** Every one of 5,000 provider-reachable queries returned the same first result in both lanes. That is the strongest available statement about the practical reach of the known float32 and float64 difference on these corpora, and it is a statement the 33-query replay could not make.

**"Only deep adjacent swaps" does not survive.** Differences reach position 2, nineteen queries differ inside the first 25 results, four change membership inside the first five, and 83 of the 114 differ in more than two positions. The five nominated findings were the shallow tail of the suite, not its shape.

**The screen was the binding limitation, and its miss rate is now measured.** 33 nominations produced 5 true positives, 28 false alarms and **109 misses**: precision 15%, sensitivity 4.4%. [`text_screen.py`](../adversarial-falsification/harness/text_screen.py) emulates both lanes inside NumPy rather than running them, and that emulation is a poor proxy in both directions. Any statement resting on the 33 nominations understates the suite by roughly an order of magnitude.

**Still not a production rate.** Mechanically generated queries seeded from indexed symbols, three fixed corpora, one host, one release. This measures the disagreement rate *within this generated suite* and the screen's miss rate against it. It says nothing about representative user traffic, and nothing about which ordering is better.

## Why the lanes disagree

**What the shipped bytes establish.** `compare_lanes.py` classifies the score relationship of the **first differing pair** in each disagreeing query, from the top-100 score encodings, with full-depth scores where the pair is not visible in both lists:

| First-pair class | Count |
| --- | ---: |
| Tied by the pure-Python lane, separated by the NumPy lane | 103 |
| Tied by the NumPy lane, separated by float64 | 9 |
| Strict inequality in both lanes, opposite directions | 2 |

That is a first-pair result. 83 of the 114 disagreements change more than two top-100 positions, up to 97, so it locates where the lanes part company and does not characterise the whole permutation.

**What is attested but not gated.** The rest of this section is derived from the three frozen corpus databases, which are outside the publication boundary. `mechanism-census.json` records it, `harness/mechanism_census.py` reproduces it given `JCM398_INDEX_ROOT`, and `verify_package.py` does not check it. Read what follows as a hypothesis for the maintainer to accept or reject on his own measurement.

Nothing in `../../REPORT.md` or `../../CLAIM-LEDGER.csv` rests on it, and neither recommends acting on it. An earlier revision did: it made "investigate canonical ordering" a numbered recommendation and gave the hypothesis a paragraph in the proposed public reply, while simultaneously asserting that no decision depended on it. Both were withdrawn, because a numbered recommendation is a decision no matter what the surrounding prose calls it. This section is the only place the material argues for anything, and what it argues for is a measurement someone else would have to make.

For django query `text-00750`, `ProfileForm.Meta#class` and `LogEntry.Meta#class` hold byte-identical stored blobs, and after normalisation `numpy.array_equal` on their two matrix rows is `True`. Scored one row at a time, `matrix[i].dot(qv)` returns `0x1.56a7fc0p-1` for both. Scored the way the shipped path scores, `matrix.dot(qv)` returns `0x1.56a7fe0p-1` for row 34172 and `0x1.56a7fc0p-1` for row 2407.

Identical inputs, different outputs, from row position alone. A blocked BLAS matrix-vector product vectorises the reduction, and float32 addition is not associative, so the summation order depends on where a row sits. It is deterministic rather than flaky: two fresh processes produce byte-identical score sets.

Prevalence across all 5,000 top-100 lists:

| Measure | Value |
| --- | ---: |
| Duplicate-stored-vector groups appearing in a NumPy-lane top 100 | 34,320 |
| Split into unequal scores by the NumPy lane | 97, or 0.28% |
| Split by the pure-Python lane | 0 |

If that reading is right, the `(-score, symbol_id)` key is correct and is simply denied the equality it needs in one lane, and the NumPy lane would not be row-order independent, which is a wider axis than installation state. Neither of those is established here. What is measured is the census above and the single inspected example; no canonicalisation was implemented, so no coverage or cost figure follows, and the claim that these 103 reorder equivalent items rests on the first pair rather than the full permutation.

## Control

The five findings published in [`provider-actual-findings.json`](../adversarial-falsification/artifacts/findings/provider-actual-findings.json) are re-derived from this run and compared. All five reproduce with byte-identical top-100 lists in both lanes and identical first-changed positions of 38, 65, 65, 76 and 78. `compare_lanes.py` exits non-zero if any of them fails to reproduce.

## Provenance

| Item | Value |
| --- | --- |
| Package under test | jcodemunch-mcp 1.108.228, the release the maintainer named |
| Wheel | SHA-256 `81af0f0308cdbed7e4884fc272b589a6691e8119828858ed6b99b2aa09132af9`, matching `../adversarial-falsification/artifacts/provenance.json` |
| Corpora | the three frozen databases whose SHA-256 digests are recorded in that same provenance file; the harness verifies each before scoring |
| Lanes | two isolated environments on Python 3.13.7, NumPy 2.4.4 present in one and absent in the other |
| Ordering | `(-score, symbol_id)`, matching `retrieval/signal_fusion.py` in the installed wheel |
| Runtime | NumPy lane 51 s for all three corpora; pure-Python lane 886 s, 264 s and 278 s, run in parallel |

The corpus databases themselves stay outside the publication boundary, unchanged from the earlier packets. `full_replay.py` refuses to run without `JCM398_INDEX_ROOT` rather than guessing.

## Scope, stated before it is asked

- **Scorer level, not tool level.** This compares `EmbeddingMatrix.score_all` output ordered by the shipped key. It is the same method the five published findings used, and the ordering convention matches `signal_fusion.py`, but it is not the full tool path: no hybrid weighting, no filters, no `top_k` truncation. The adversarial packet verified adapter-to-tool parity for 5 cases, not for 5,000. **"Rank 0 never changed" is a claim about the semantic scoring lane, not about `search_symbols` responses.**
- **Exact tie is depth-bounded.** The 130-query tie result covers ties inside the returned top 100, the depth captured for every query. Comparison-v2's `m4` covers its full positive ranking. The two are not interchangeable.
- **The BLAS result is host-bound.** NumPy 2.4.4 on one Windows host with the BLAS in that wheel. Deterministic there; not tested on another BLAS, thread count or platform.
- **Row order.** `full_replay.py` reads rows with `ORDER BY symbol_id`, inherited from the retained `real_replay.py`, while production reads through `EmbeddingStore.iter_raw()`. Row order changes no per-row score and the final sort is deterministic, so the reported results are unaffected. Because the NumPy lane is row-order sensitive at the BLAS level, a different row order could split a different set of duplicate groups: the count of 97 is specific to this ordering, the mechanism is not.

## Reproducing it

Comparison alone, no corpus databases and no jcodemunch install, standard library only:

```bash
py -3 -B harness/compare_lanes.py
```

The full replay, which does need the corpora and both environments:

```bash
export JCM398_INDEX_ROOT=/path/to/frozen/indexes
for corpus in django fastapi jcodemunch; do
  "$NUMPY_ENV/python"  -B harness/full_replay.py --lane numpy  --corpus "$corpus" --output "raw/numpy-$corpus.jsonl"
  "$PYTHON_ENV/python" -B harness/full_replay.py --lane python --corpus "$corpus" --output "raw/python-$corpus.jsonl"
done
py -3 -B harness/compare_lanes.py
```

`deep_scores.py` captures full-depth scores for the 29 queries whose first swap leaves both top-100 lists. Without it `compare_lanes.py` reports those 29 as unclassifiable and exits non-zero, which is the intended behaviour: an unclassified case is a failure, not a footnote.

## Files

| Path | Contents |
| --- | --- |
| `results-summary.json` | every number above, machine-readable |
| `raw/{numpy,python}-{corpus}.jsonl` | per-lane header plus, for each query, the ordered top 100, its exact score encodings, and a SHA-256 over the complete ordering |
| `raw/deep-{lane}-{corpus}.jsonl` | full-depth scores for the 29 queries needing them |
| `raw/disagreements.jsonl` | 114 records, both lanes' full top-100 lists and scores |
| `harness/` | the three scripts above |
| `logs/` | per-corpus progress logs from the pure-Python lane |
