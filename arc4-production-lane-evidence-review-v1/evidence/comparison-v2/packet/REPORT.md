# Arc 4 production-lane comparison v2 report

Verdict: **complete**.

This is a census of a fixed purposive suite: 12 ranking problems over 4 frozen query vectors. It is not a random sample. No p-values, confidence intervals, hypothesis tests, prevalence rates, timing conclusions, or memory conclusions are reported.

The paired denominator is 120 replicated lane comparisons. The problem denominator is 12 non-independent ranking problems. Repetitions and cache states add repeatability evidence, not query diversity.

## M1 rank-0 difference

| Unit | Numerator | Denominator | Independence |
| --- | ---: | ---: | --- |
| Paired comparisons | 0 | 120 | replicated pair |
| Ranking problems | 0 | 12 | not independent draws |

Heterogeneous within problem: none.

Excluded no-results pairs: 0.

## M2 ordered top-k difference

| Unit | Numerator | Denominator | Independence |
| --- | ---: | ---: | --- |
| Paired comparisons | 0 | 120 | replicated pair |
| Ranking problems | 0 | 12 | not independent draws |

Heterogeneous within problem: none.

## M3 top-k membership difference

| Unit | Numerator | Denominator | Independence |
| --- | ---: | ---: | --- |
| Paired comparisons | 0 | 120 | replicated pair |
| Ranking problems | 0 | 12 | not independent draws |

Heterogeneous within problem: none.

## M4 exact-tie partition difference

| Unit | Numerator | Denominator | Independence |
| --- | ---: | ---: | --- |
| Paired comparisons | 80 | 120 | replicated pair |
| Ranking problems | 8 | 12 | not independent draws |

Heterogeneous within problem: none.

## M9 failures and lane-selection mismatches

Public-tool errors: 0; lane mismatches: 0; fallback firings: 0; embed-write tripwire firings: 0; failed preconditions: 12; infrastructure failures: 0; total failed attempts: 12; explicit-repair failures: 4; successful repair pairs: 2; repair declarations: 6; rowless failures: 5.

Attempt-number accounting: `{"1":132,"2":2,"3":2,"4":1,"5":1}`.

## M10 score-difference magnitude

Raw cosine: all 120 matrix pairs, 2917040 candidate comparisons, maximum absolute delta `0x1.ba0b9e0800000p-24`, and 0 bit-identical scores.

Hybrid final: 60 hybrid matrix pairs, 1458520 candidate comparisons, maximum absolute delta `0x1.ba0b9e1000000p-25`, and 0 bit-identical scores.

## M11 ordering margins

Observed and conservative margins were computed at each lane's top-k boundary and minimum internal top-k gap. Finite zero remains eligible; `+inf`, `exact_tie`, and `insufficient_ranking` are counted separately in SUMMARY.json.

## M12 first divergence at full depth

No full-depth divergence: 20 of 120 pairs. First-divergence histogram: `{"1555":10,"1852":10,"1888":10,"2377":10,"3065":10,"3624":10,"4744":10,"4916":10,"5189":10,"7904":10}`.

## Claim ceiling

A zero establishes only observed parity and measured score/margin behavior on this frozen suite. One or more findings establish only that the shipped lanes can diverge on these retained real inputs. Neither outcome establishes production incidence or behavior outside the frozen suite.

Provenance claim ceiling: newline-normalized payload equivalence only. This does not establish a reproducible build, the publisher build environment, or end-to-end supply-chain authenticity.

## Limitations

Four researcher-authored query vectors are reused across three corpora. NumPy-lane results are BLAS-dependent. Full-depth hybrid numeric evidence relies on a reconstruction adapter whose public top-k parity is checked on every matrix row. The private-source-derived control corpus remains local.
