# JCodeMunch v1.108.228 adversarial production-lane falsification

## Verdict

Rank-0 equivalence is falsified.

A valid four-symbol JCodeMunch repository, valid float32 stored embeddings, and a valid 384-dimensional query vector produce different first results through the untouched public `search_symbols` path:

- NumPy 2.4.4 lane: `counterexample.py::omega_boundary_candidate#function` (`symbol-00046`)
- NumPy-absent lane: `counterexample.py::gamma_boundary_candidate#function` (`symbol-03962`)

Both tool responses exactly equal independent adapter rankings. The failure survives all 24 insertion orders and 50 fresh-process replays across Python hash seeds 0, 1, 2, 11, and 101.

## Breadth

- 10,000 independently generated boundary cases plus the full and minimized known fixtures were executed through both shipped scorers.
- 3,211 geometric cases flipped rank 0.
- 5,000 production-provider text queries were frozen before screening: 1,667 Django, 1,667 FastAPI, and 1,666 JCodeMunch.
- 33 provider-text screens were replayed against full real corpora through both actual shipped scorers.
- Five ordinary text queries produced actual ordered top-k differences. One appears by top 50 and all five by top 100. None changed membership or rank 0.
- Those five findings reproduced through public `search_symbols` with tool/adapter parity.
- Seven hybrid weights over those five queries produced 35 public-path cases and 11 ordered differences, with no membership or rank-0 change.
- Top-k boundaries 1, 5, 10, 25, 50, and 100 were classified.
- All 5,000 frozen provider vectors reproduced byte-for-byte under the recorded ONNX Runtime 1.24.4 generation runtime. A deliberate 1.28.0 replay changed all 5,000 hashes and is preserved as a failed attempt and reproducibility warning.

## Why the four-row case matters

The initial 4,000-row seed-11 corpus flipped rank 0. An assumed two-row minimization failed: both lanes selected the fallback winner. Width sweeping then found that four rows are sufficient. With four rows, NumPy scores `symbol-00046` as `0x1.0000040000000p+0` and selects it first; the fallback selects `symbol-03962` with `0x1.0000008548b89p+0`.

This is not malformed input or monkeypatching the scorer. The corpus is indexed normally, embeddings are written through JCodeMunch's embedding store, the query vector satisfies the production dimensional contract, and both lanes run their shipped matrix construction, scoring, and ranking code. Query-provider injection only supplies the frozen vector, exactly as a provider would.

## Methodology and failed attempts

The complete process, mathematical targeting, tools, and evidence hierarchy are in `METHODOLOGY.md`. The chronological machine-readable record is `artifacts/JOURNAL.jsonl`. Failed attempts are retained under `artifacts/attempts/`, including the invalid two-candidate minimization and the first text generator that accidentally allocated all queries to Django.

`artifacts/provenance.json` binds the findings to the clean v1.108.228 source commit, wheel digest, three frozen corpus digests, provider reproduction control, and independently passing original comparison packet.

## Limits

The four-row rank-0 counterexample is geometric. It proves the shipped tool can produce environment-dependent first results for theoretically valid production inputs, but does not show that the local text provider emits that exact vector. The 5,000 provider-reachable text queries found real ordered differences but no rank-0 or membership change. Search coverage is broad and adversarial, not exhaustive.

## Local hold

Nothing was pushed, released, posted, or submitted. The next action is user review.
