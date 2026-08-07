# JCodeMunch v1.108.228 production-lane comparison

## Result

No disagreement was observed in this fixed 12-case suite.

Rank 0 equality: 12/12 paired cases.
Ordered top-k equality: 12/12 paired cases.
Top-k membership equality: 12/12 paired cases.
Cases with exact ties: NumPy 12/12; Python 12/12.

Exact ties are bit-exact final-score equality, with no epsilon. Across full positive-score rankings, NumPy had 12972 groups and 61458 participants; Python had 12946 groups and 61422 participants. Groups intersecting returned top-k were NumPy 16 and Python 16; groups crossing the top-k boundary were NumPy 4 and Python 4. Relevant tie-group IDs and ascending symbol-ID order are retained per case in `artifacts/comparisons.jsonl`.

### Per corpus

| Corpus | Cases | Rank 0 equal | Ordered equal | Membership equal |
| --- | ---: | ---: | ---: | ---: |
| django | 4 | 4 | 4 | 4 |
| fastapi | 4 | 4 | 4 | 4 |
| jcodemunch | 4 | 4 | 4 | 4 |

### Per query

| Query | Cases | Rank 0 equal | Ordered equal | Membership equal |
| --- | ---: | ---: | ---: | ---: |
| `semantic_input_validation` | 3 | 3 | 3 | 3 |
| `semantic_transaction_persistence` | 3 | 3 | 3 | 3 |
| `hybrid_authentication_middleware` | 3 | 3 | 3 | 3 |
| `hybrid_test_client_response` | 3 | 3 | 3 | 3 |

## Scope and identities

This is a new production-lane comparison of the shipped NumPy float32 and NumPy-absent pure-Python float64 lanes in v1.108.228 at `8bed872e9436093be9f89d35fb84e0cb58a293af`. v1.108.228 includes the deterministic `(-score, symbol_id)` tie-break, but not the earlier certified scorer candidate.
The same locally built wheel (`81af0f0308cdbed7e4884fc272b589a6691e8119828858ed6b99b2aa09132af9`) was installed in both isolated Python 3.13 environments. NumPy was 2.4.4 in one lane and absent in the other.

The fixed, purposive suite contains Django, FastAPI, and JCodeMunch corpora with four frozen real query embeddings each. It is not a random sample, and these 12 cases do not support a population prevalence claim. The second repetitions are determinism checks, not additional cases.

## Controls and reproducibility

The positive control demonstrated an actual production-scorer ordering divergence. The exact-tie control ordered reversed insertion input by ascending symbol ID in both lanes. The negative control reported no difference for identical evidence. All 48 fresh-process trials had tool/adapter parity and identical within-lane repetitions.

Reproduce locally from this directory with:

```powershell
py -3 harness\controller.py all
py -3 verify.py --self-test --write-receipt
```

## Limitations

The corpora and queries are fixed and purposive. Numeric diagnostics describe this suite only. No timing or performance conclusion is made. The JCodeMunch control database contains private-source-derived indexed text and remains local.

## Local hold

Nothing was pushed, released, posted, or submitted. The only next action is user review and a publication decision.
## Artifact inventory

`artifacts/manifest.json` is the exact SHA-256 inventory of every retained packet file. The primary created surfaces are `harness/`, `config.json`, `artifacts/preflight.json`, `artifacts/controls/`, 48 immutable trial records plus two full score-evidence repetitions for each lane/case under `artifacts/raw/`, `artifacts/comparisons.jsonl`, `artifacts/summary.json`, `REPORT.md`, `verify.py`, and `verification.txt`.

Disposable local state is under `working/`: the clean detached source, one built wheel, build and lane environments, trial-local database copies, and the preserved first incomplete run that exposed uncontrolled Python hash randomization. None is listed as public-safe export material.

