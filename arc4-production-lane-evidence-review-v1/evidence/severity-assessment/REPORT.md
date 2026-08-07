# JCodeMunch v1.108.228 production-lane severity assessment

> **Superseded in part, 2026-08-07.** This assessment was written when only 33 of the
> 5,000 generated queries had been replayed through both shipped lanes. It states rates
> over the full 5,000 that the evidence at the time could not support, and the synthesis
> in `../../REPORT.md` withdrew that denominator. All 5,000 have since been replayed; see
> `../full-suite-replay/REPORT.md`. Read this document as the severity reasoning of that
> earlier state, retained because rejected and superseded work stays useful, and take
> every number in the table below from the replay instead. Specifically: "zero of 5,000
> provider-text cases" was a screening result, not a replay result; the 0.1% and 0.02%
> incidences were computed on a denominator only 33 of which had been tested; and "no
> measured provider-text case changed membership through top 100" is now false, since the
> complete replay found 29 top-100 membership changes and 4 inside the first five results.
> The rank-0 conclusion survives and is now stronger: 0 changes in 5,000.

## Verdict

This has **low demonstrated normal-use severity**. Meaningful user impact has not been established.

The adversarial packet proves a numerical equivalence defect exists. It does not prove that a legitimate user query is likely to encounter a rank-0 or membership failure. On current evidence, this is non-urgent correctness hardening, not a demonstrated user-facing incident.

## What changed relative to issue 398

The maintainer set the right test explicitly: pin v1.108.228, then report rank 0, ordered top-k, membership, and exact ties separately. The completed experiment does exactly that.

The issue record previously held two statements together:

1. Installation state must not silently select a different ranking.
2. The synthetic hazard had not been observed on practical real-embedding queries.

The first statement is confirmed only as a possibility under deliberately selected geometry. The second is not materially rebutted. Five ordinary local-ONNX queries over three real code corpora produced deep ordered public-path differences, but none changed rank 0, membership, or any measured downstream outcome.

Sources, with authors named because two of these three are the reporter's own words rather than the maintainer's:

- Maintainer, agreeing to the production-lane comparison and naming v1.108.228: [comment 5177953577](https://github.com/jgravelle/jcodemunch-mcp/issues/398#issuecomment-5177953577)
- Reporter, retracting the prior zero because it never exercised the NumPy-absent production lane: [comment 5175071271](https://github.com/jgravelle/jcodemunch-mcp/issues/398#issuecomment-5175071271)
- Maintainer, original disposition of the synthetic hazard: [comment 5172823848](https://github.com/jgravelle/jcodemunch-mcp/issues/398#issuecomment-5172823848)

## Severity by result dimension

| Dimension | Result | Severity meaning |
| --- | ---: | --- |
| Rank 0 | 3,211 of 10,002 adversarial geometric cases; zero of 5,000 provider-text cases | This is an adversarial capability result, not evidence of normal-use incidence. |
| Ordered top-k | Five of 5,000 provider-text queries; 11 of 35 hybrid cases | Normal inputs can expose numerical differences, but only deep adjacent swaps were observed. |
| Membership | Zero provider-text and zero hybrid changes | No observed result was added or removed at measured top-k boundaries. |
| Exact ties | Four of five provider-text findings are NumPy float32 ties that float64 distinguishes | Most practical findings are quantization-induced tie handling, not broad relevance changes. |
| Genuine inversion | One of 5,000 provider-text queries | At least one practical difference is a real score-order inversion rather than only tie resolution. |

The five provider-text differences are adjacent swaps. They first appear at ranks 38, 65, 65, 76, and 78. Each changes exactly two positions. Their suite incidence is 0.1%, and the genuine inversion incidence is 0.02%. These are test-suite incidences, not estimates of field prevalence.

## What normal use actually demonstrated

- No ordinary provider-text query changed rank 0.
- No measured provider-text or hybrid case changed membership through top 100.
- Practical differences were adjacent swaps deep in the result list.
- No experiment showed that a user or agent selected, read, or acted on a different symbol.
- No task-success, answer-quality, token-cost, or latency consequence was measured.
- No crash, corruption, security failure, or non-determinism within one fixed environment was observed.
- The rank-0 public counterexample is valid and stable, but adversarially constructed. The local provider was not shown to emit its exact query geometry.

The five provider-text differences prove only that the arithmetic difference is reachable with ordinary provider vectors. They do not prove a meaningful normal-use failure.

## What the adversarial proof establishes

- The public API can return different first results solely because NumPy imports successfully.
- The four-symbol rank-0 counterexample survives 50 fresh processes, five hash seeds, and all 24 insertion orders.
- One ordinary deep-rank finding is a genuine score-order inversion, so a deterministic tie-break alone cannot eliminate the arithmetic difference.

Those facts establish a reproducible contract violation under adversarial input. They do not assign practical severity by themselves.

## Recommended disposition

Track this as non-urgent correctness hardening unless a normal-use experiment demonstrates rank-0, membership, or downstream task impact. Do not use the 32.1% adversarial rank-0 rate in any practical-severity argument.

The fix should target cross-environment canonical ranking. It should not revive lane 3 merely because the old certification design exists. The maintainer already parked that lane because the exact warm scorer removed its performance premise. A suitable fix must cover both observed mechanisms: float32 ties that float64 distinguishes and genuine score-order inversion near a boundary.

Acceptance should include:

1. The retained four-symbol counterexample returns one canonical rank 0 in both installation states.
2. All five provider-text findings return identical ordered lists in both lanes.
3. Rank-0, ordered top-k, membership, and exact-tie outcomes remain separate in regression output.
4. NumPy absence remains supported and does not change canonical results.
5. Performance is remeasured independently so correctness remediation is not justified or rejected by assumption.

## Limits

The 5,000 text queries are broad, balanced, provider-reachable probes derived from indexed symbols. They are not a sample of production user traffic. No field incidence, task-success loss, or downstream agent outcome was measured. A defensible practical-severity verdict therefore remains low and provisional.

Everything remains local for user review.
