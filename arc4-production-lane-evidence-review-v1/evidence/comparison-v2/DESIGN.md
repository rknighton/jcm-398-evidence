# Arc 4 production-lane comparison v2: experiment design

Status: **design only. Nothing measured, nothing published, nothing modified under test.**
Target: JCodeMunch v1.108.228 at `8bed872e9436093be9f89d35fb84e0cb58a293af`.
Prepared: 2026-08-04. Awaiting authorisation to execute.

Question: **at v1.108.228, with the `(-score, symbol_id)` tie-break shipped, do the two
production semantic-scoring lanes (NumPy float32 matmul, NumPy-absent Python float64
accumulation over float32-normalized rows)
produce different rankings on real embedding corpora?**

---

## 1. Executive design verdict

### 1.1 The matrix

```text
THE MATRIX (all reported figures come from here)
  3 corpora x 4 lane-reaching query forms x 2 cache states x 5 repetitions x 2 lanes
  = 240 measured rows, 120 paired comparisons

Preflight contract check (ancillary, never a finding)
  3 corpora x 2 verbatim hybrid forms x 2 cache states x 1 repetition x 2 lanes
  = 24 rows, 12 pairs
```

The headline denominator is **120 paired comparisons over 12 ranking problems and 4 query
vectors**.

**The study size is 240 rows and 120 paired comparisons.** The 24-row preflight contract check
does not exercise the semantic scorer, produces no finding, and is never added to the matrix
total or reported in the same table (6.2). It exists only to establish two code-path facts as
measurements rather than as claims.

The row count is derived, not assumed. The original packet's 360 rows are **120 case
executions crossed with 3 research-candidate scoring modes**, and `mode` has no counterpart in
v1.108.228, so it collapses and `lane` replaces it. Section 7 gives four independent routes to
120.

### 1.2 The design principle that governs everything below

**The evidence must be equally strong whether it finds zero differences or many.**

A design that can only produce a compelling result in one direction is not evidence, it is an
argument. Three commitments make this true here, and they shape most of what follows:

- **Every result is a measurement, never an absence.** The two lanes compute different
  arithmetic, so their scores will differ by roughly 1e-7 whether or not ordering changes. The
  study therefore always reports *how much* the scores differed, *how much headroom* the
  ordering had, and *at what rank* the orderings first diverged at full depth. A "no top-k
  difference" outcome arrives as a quantified safety margin, not as a null. See M10, M11, M12.
- **Detector sensitivity is proven, not assumed.** Controls demonstrate that the comparison
  code catches a planted ordering change of one unit in the last place, far below the roughly
  1e-7 effect under study (C19). A zero cannot be attributed to a blind detector.
- **The claim ceiling for both outcomes is fixed before execution.** Section 13.5 and 13.6
  pre-specify what a zero establishes and what a finding establishes. Neither can be inflated
  after the fact.

### 1.3 What makes each attack surface closed

| Attack | Closed by |
| --- | --- |
| "You didn't run the real code path" | Public `search_symbols` on every row, plus adapter parity on every row (C8) |
| "Your arguments didn't reach the scorer" | Both argument forms executed as separate arms; no argument choice is load-bearing (6.2) |
| "You picked cases likely to disagree" | Full census of the frozen suite; zero selection; pre-registered (14.3) |
| "You stopped when you liked the answer" | Pre-registration hash committed before the first row; no early stop in either direction (14) |
| "Your harness caused or hid the difference" | Scoring, sorting, candidate selection and result construction are never substituted; exactly one fresh-process provider-boundary substitution is proven by C7; byte-diff of installed package per trial (9.3) |
| "Your inputs drifted" | Content-addressed inputs, hashed before and after every row (9.1, C3) |
| "The lanes weren't really different" | Lane observed from `EmbeddingMatrix.vectorised` and `cache_stats()`, before and after the call (C5, C6) |
| "Everything else wasn't really the same" | Canonical logical environment-manifest diff must be empty except NumPy; path-bearing receipts remain separate (C16) |
| "Your detector is blind" | One-ULP ordering-change sensitivity control plus per-class known-positive fixtures (C18, C19) |
| "Your detector hallucinates differences" | Known-zero control plus within-lane repetition pairs as a production-scale negative control (C17, M7) |
| "Only top 10, you missed deeper flips" | Full-depth ordering hash and full exact score vectors retained on every matrix row; first-divergence rank reported (M12) |
| "12 problems is too small to mean anything" | Correct, and the design neither disputes it nor computes around it: this is a census of a fixed suite, so it reports counts and margins and draws no inference at all (13.3, 13.8) |
| "You're overclaiming prevalence" | Claim ceiling pre-specified for both outcomes; denominators always carry their independence level (13) |
| "It isn't reproducible" | Wheel rebuilt from clean detached source and hash-matched; hash-seed sweep; BLAS pinned and recorded; bounds of reproduction stated (18.4) |
| "You changed the design mid-flight" | `run_id`, superseded-run discipline, append-only journals (14.3) |
| "Coverage was short and you reported anyway" | `verdict: incomplete` is mandatory below full coverage (14.8) |

---

## 2. Verified interpretation of the original 360 rows

Established by direct recomputation from
`<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\measurements.csv`.

| Property | Value |
| --- | --- |
| SHA-256 | `f50451015e4b56522fdbca84eddd677ecf3da77724e054a75c1e2e69005da303` (matches `manifest.json`) |
| Rows / columns | 360 / 79 |
| Unique `row_id` | 360 |
| Unique `case_id` (`corpus:query:cache_state`) | 24, 1:1 verified |
| Unique `pair_id` (`case_id:rNN`) | 120, 1:1 verified |
| Rows per `pair_id` | exactly 3 (the three modes) |
| Rows per `case_id` | exactly 15 (5 repetitions x 3 modes) |
| `run_id` / `row_status` | 1 run, all `retained`, nothing superseded |
| Cartesian coverage | 360 of 360 cells, zero missing, zero extra |

The 360 rows are **multiple research modes applied to the same 120 case executions**, which
are themselves a full crossing of corpora, queries, cache states, and repetitions. One axis,
`mode`, does not transfer to a two-production-lane comparison.

Two properties of the original packet are load-bearing inputs to this design rather than
observations about it:

- Its harness required NumPy unconditionally, so all 360 rows record `numpy_version=2.4.4`.
  The NumPy-absent lane has no prior measurement, which is why this study exists.
- Its harness scored through internal imports rather than `search_symbols`, so the recorded
  `serialized_args_json` values are a statement of intent that has never been executed through
  the public API. Section 6.2 handles that by executing both forms rather than choosing one.

One property transfers exactly: `arc4lib.deterministic_top` sorts by `(-score, symbol_id)` and
drops `score <= 0.0`, which is `search_symbols.py:1462` plus the filter at `:1439`. The
ordering contract is identical.

---

## 3. Original matrix decomposition

### 3.1 Structure

```text
3 corpora x 4 queries x 2 cache_states = 24 case_id
24 case_id x 5 repetitions             = 120 pair_id
120 pair_id x 3 modes                  = 360 rows
```

Fully crossed, fully balanced, no holes.

### 3.2 Factors

| Dimension | Levels | Values |
| --- | --- | --- |
| `corpus` | 3 | django (authoritative), fastapi (required_second_point), jcodemunch (control_only) |
| `query_id` | 4 | `semantic_input_validation`, `semantic_transaction_persistence`, `hybrid_authentication_middleware`, `hybrid_test_client_response` |
| `cache_state` | 2 | `cold_fresh_process`, `generation_warm` (`cold_warm_state` is an identical duplicate) |
| `repetition` | 5 | 1..5 |
| `mode` | 3 | `exact_tiebreak_baseline`, `float32_certified_candidate`, `bounded_exact_fallback` |
| `execution_order` | 3 | rotated by `(repetition - 1) % 3`, giving a 2/2/1 imbalance across 5 repetitions |

### 3.3 Nested query attributes (do not multiply)

| `query_id` | `query_kind` | `top_k` | `semantic_weight` | `tie_heavy` | rows |
| --- | --- | ---: | ---: | --- | ---: |
| `semantic_input_validation` | semantic_only | 10 | 1.0 | false | 90 |
| `semantic_transaction_persistence` | semantic_only | 25 | 1.0 | false | 90 |
| `hybrid_authentication_middleware` | hybrid | 10 | 0.5 | false | 90 |
| `hybrid_test_client_response` | hybrid | 25 | 0.5 | **true** | 90 |

`top_k` and `semantic_weight` each have 2 distinct values but are confounded with the query and
with each other. There are 4 query cells, not 16. Likewise `corpus_role`, `public_repo`,
`corpus_commit`, `source_repo_id`, the corpus hashes, `embedding_vector_count` and
`candidate_count` are 3-valued functions of `corpus`; `query_embedding_sha256` and
`serialized_args_json` are 4-valued functions of `query_id`.

### 3.4 Corpus identities

| Corpus | Role | Commit | Symbols = embeddings | Working DB SHA-256 |
| --- | --- | --- | ---: | --- |
| django | authoritative | `274a1d494d11d87a1b767340d1f398f197810f93` | 45,561 | `21767e35...3740529` |
| fastapi | required_second_point | `95f8322ee1dcda7ceace7b1c4f6c9915b36d748f` | 13,405 | `fb0f933f...760e61e` |
| jcodemunch | control_only | `c78392cac0d50570d5cf86558d8d3674c0bea068` | 13,960 | `9b6a007e...93cdc58` |

Verified by read-only immutable SQLite probe: `symbols` and `symbol_embeddings` row counts are
**equal** in all three corpora. The production path's embed-and-write-back branch therefore has
nothing to do, which C11 asserts rather than assumes.

### 3.5 Outcome columns

All 360 rows: `canonical_parity=true`, `interval_violation_count=0`,
`genuine_disagreement_count=0`, `lane_selected == mode`. `exact_tie_count` ranges 1,915 to
14,310. `result_count` is 10 or 25.

---

## 4. Experimental unit and independence structure

The row is not the unit of evidence. Five nested levels, kept apart in the design and in every
reported denominator.

| Level | n (matrix) | What it is | Independent? |
| --- | ---: | --- | --- |
| Unique query vector | **4** | frozen 384-d real embeddings | The query-diversity ceiling of the whole study |
| Ranking problem (`corpus` x `query form`) | **12** | a distinct corpus-and-query scoring problem | The closest thing to an independent unit |
| Case identity (`+ cache_state`) | **24** | adds a nuisance factor expected to be null for ordering | Not independent of the 12 |
| Case execution (`+ repetition`) | **120** | the pairing key | Replicates, not new cases |
| Measured row (`+ lane`) | **240** | one lane execution | Two rows per paired comparison |

The study has 4 query vectors and 12 ranking problems. It does not have 240, 120, or 24
queries. Repetitions add determinism evidence and zero query diversity. Cache states add
robustness evidence and zero query diversity. Lane is the treatment.

The 12 are not 12 independent draws either: each query vector appears in 3 of them and each
corpus in 4. Every statement at the 12 level carries that caveat.

Preflight contract check: 6 ranking problems, 12 case identities, 12 case executions, 24 rows.
Reported in its own subsection of `REPORT.md`, never in a findings table, and never summed with
the matrix.

---

## 5. Transferability decision for every original dimension

Codes: **U** unchanged, **L** maps to the lane factor, **C** becomes a control,
**N** does not apply to shipped production lanes, **A** justified adaptation.

| # | Dimension | Class | Decision |
| --- | --- | --- | --- |
| 1 | `corpus` (3) | **U** | All three retained including `control_only`. Multiplies by 3 |
| 2 | `corpus_role`, `public_repo`, `corpus_commit`, `source_repo_id` | **U** | Provenance labels. Do not multiply |
| 3 | `source_database_sha256`, `working_database_sha256` | **C** | Frozen-input control C3. The **working** copies are the measured inputs |
| 4 | `index_generation`, `embedding_generation_identity` | **C** | Recorded per row, asserted equal across lanes |
| 5 | `query_id` (4) | **U** | All four retained verbatim. Nothing invented, reworded, added, or removed. Multiplies by 4 |
| 6 | `query_kind` (2) | **U** | Query attribute. Reporting stratum. Does not multiply |
| 7 | `tie_heavy_query` | **U** | Query attribute. `hybrid_test_client_response` remains the predeclared tie-heavy case. Dropping it would bias toward parity |
| 8 | `top_k` (10, 25) | **U** | Query attribute, not crossed. Does not multiply. Reported per row |
| 9 | `semantic_weight` (1.0, 0.5) | **U**, pinned at execution | Query attribute. Pinned against the tuning override by C15 (6.3) |
| 10 | `serialized_args_json` (4) | **A**, both forms | The semantic-enabled form is measured in the matrix; the recorded form runs once per corpus per cache state as the ancillary preflight contract check (6.2) |
| 11 | `query_embedding_sha256` (4) | **C** | Frozen query-vector control C4. All four hashes verified to match `prepared-inputs.json` exactly |
| 12 | `cache_state` (2) | **A**, retained | Meaning re-specified against the shipped `storage.embedding_matrix` process cache (5.1). Multiplies by 2 |
| 13 | `cold_warm_state` | **U** | Duplicate, retained for auditability |
| 14 | `repetition` (5) | **U** as replicate | All 5 retained. Reclassified from timing replicate to within-lane determinism replicate. Multiplies rows by 5, adds zero cases |
| 15 | **`mode` (3)** | **N**, replaced by **L** | Does not transfer (5.2). Replaced by `lane` (2) |
| 16 | `execution_order` (3) | **A** | Becomes lane-invocation order (2), rebalanced to exactly 60/60 (10.3) |
| 17 | `lane_selected` (3) | **A** | Redefined as the shipped lane actually taken, observed not requested. Controls C5, C6 |
| 18 | `fallback_reason` | **N** | No fallback concept on this path. Retained, always blank, reason recorded |
| 19 | `candidate_count` | **A** | Production drops `score <= 0.0` at `:1439`, so the scored-and-kept count is lane-observable and is recorded per row, never assumed equal |
| 20 | `exact_tie_count` | **U** | Retained, reported in its own category (M4) |
| 21 | `near_tie_count`, `genuine_disagreement_count`, `other_certified_count`, `total_certified_count`, `interval_violation_count`, all `*_fraction`, `result_boundary_score`, `max_rescore_fraction` | **N** | Certification-machinery outputs. v1.108.228 ships no certification, intervals, or rescore budget (5.3) |
| 22 | `wall_ns`, `scoring_ns`, `process_cpu_ns`, `rss_*`, `peak_rss_bytes` | **C** | Recorded, never a result. No timing or memory claim is made. The verifier fails if any timing figure reaches the summary or report (19.4) |
| 23 | `baseline_response_hash`, `candidate_response_hash`, `canonical_parity`, `ordered_result_id_hash` | **A** | Re-anchored to NumPy-lane vs Python-lane. Semantics preserved, names changed |
| 24 | `baseline_*` / `candidate_*` identity columns | **A** | Collapse to one target identity plus a per-lane environment identity |
| 25 | `candidate_classification` | **N** | Replaced by `target_classification = shipped_release_wheel` |
| 26 | `harness_sha256`, `config_sha256` | **U** | New values, control C13 |
| 27 | `python_version`, `sqlite_version`, `platform`, `cpu_identity`, `total_memory_bytes` | **C** | Asserted identical across lanes |
| 28 | `numpy_version` | **L** | The treatment. `2.4.4` in one lane, absent in the other |
| 29 | `embedding_provider/model/dimension/normalization/vector_count` | **C** | Asserted identical. Provider bypassed for the query vector (9.3) |
| 30 | `row_id`, `run_id`, `row_status`, `superseded_run_id`, `supersession_reason` | **U** | Retention and supersession discipline carried over |
| 31 | `diagnostic_json` | **A** | Re-specified to carry ordered IDs, top-k scores as hex float64, full-depth ordering hash, and tie-group evidence |

### 5.1 `cache_state`: retained, meaning re-specified

Production meaning in v1.108.228: `storage.embedding_matrix.get_matrix()` decodes and
L2-normalises the whole matrix once per `(db_path, size+mtime stamp of .db/-wal/-shm)` and
caches it per process, capped at `_MAX_CACHED_REPOS = 2`.

- `cold_fresh_process`: fresh process; the measured call is the first `search_symbols` call;
  `_build()` runs inside it.
- `generation_warm`: fresh process; one untimed `search_symbols` call with the same frozen
  query and identical arguments first, then the measured call; `_build()` does not rerun.

Same-query warm-up is safe on the lane-reaching forms because `search_symbols.py:698` sets
`_cacheable = not debug and not semantic and not semantic_only and _get_cache_max() > 0`, so
the process-local result LRU is disabled on the semantic path. This was checked specifically,
because a result-cache hit would manufacture false parity.

On the preflight contract check the BM25 path **is** cacheable, so its warm rows are served
from the LRU. That is a correct and expected property of that path, is recorded per row as
`served_from_result_cache`, and is one of the two facts the check exists to establish.

Ordering is expected to be cache-invariant. This is the only axis in the frozen design that can
falsify that, which is why it is kept even though a null is the likely outcome.

### 5.2 Why `mode` does not transfer

v1.108.228 selects between exactly two implementations on exactly one condition:

- `storage/embedding_matrix.py:196` calls `_numpy()` inside `_build()`.
- NumPy importable: `_build` returns an `EmbeddingMatrix` with a float32 `_matrix`, and
  `score_all` dispatches to `_scores_numpy` (`:155-162`).
- Not importable: `_build` returns one with `array.array('f')` rows, and `score_all` dispatches
  to `_scores_python` (`:164-175`).

There is no third lane, no mode parameter, no fallback trigger, and no certification. The three
original modes are `arc4lib.execute_mode` branches: a float64 reference, a float32 candidate
with Cauchy-Schwarz interval bounds and a rescore budget, and a forced variant of the same
candidate. None exists in the wheel.

**Information lost:** the certification-breadth question against the ROADMAP thresholds.
**Breadth effect:** none for the question asked. The maintainer scoped it explicitly:
"agreed the certified scorer is not in `.228`, so please don't let its absence get read as a
gap in the result"
(`https://github.com/jgravelle/jcodemunch-mcp/issues/398#issuecomment-5177953577`).
**Faithful alternative?** No. The honest representation is to record the retirement and its
reason, which `TRANSFER-DECISIONS.json` does per column.
**Row-count effect:** divides the naive 360-cases reading by 3, giving 120 case executions.

### 5.3 Why the certification columns are excluded

They are outputs of `arc4lib.float32_scores_and_bounds` and `arc4lib.score_case`, which compute
gamma-scaled float32 error intervals and classify candidates into disjoint buckets against a
`max_rescore_fraction`. v1.108.228 contains none of it. Recomputing them in the harness would
be measuring the retired research candidate under a new name; emitting them blank would be
honest but useless. `exact_tie_count` is the exception and is retained, because exact ties are
a property of the shipped scorer's output and were requested separately.

---

## 6. Exact proposed production-lane matrix

### 6.1 Query forms

Six query-form cells. The `arg_form` factor is **nested**, not crossed: it has two levels only
where the two levels differ.

| # | `form_id` | `query_id` | `semantic` | `semantic_only` | `semantic_weight` | `top_k` | Reaches scorer | Arm |
| --- | --- | --- | --- | --- | ---: | ---: | --- | --- |
| 1 | `sem_input_validation` | `semantic_input_validation` | true | true | 1.0 | 10 | yes | headline |
| 2 | `sem_transaction_persistence` | `semantic_transaction_persistence` | true | true | 1.0 | 25 | yes | headline |
| 3 | `hyb_auth_middleware__semantic` | `hybrid_authentication_middleware` | **true** | false | 0.5 | 10 | yes | headline |
| 4 | `hyb_test_client__semantic` | `hybrid_test_client_response` | **true** | false | 0.5 | 25 | yes | headline |
| 5 | `hyb_auth_middleware__verbatim` | `hybrid_authentication_middleware` | false | false | 0.5 | 10 | no | preflight |
| 6 | `hyb_test_client__verbatim` | `hybrid_test_client_response` | false | false | 0.5 | 25 | no | preflight |

Forms 1 and 2 have a single level because for a `semantic_only` call, passing `semantic: true`
is a verified no-op: line 797 does `if semantic or semantic_only: semantic = True`; line 698's
`_cacheable` is already false via `semantic_only`; and line 683's tuning trigger requires
`semantic_weight == 0.5`, which is 1.0 here. Running them twice would inflate n with
byte-identical calls, which is itself an attack surface.

### 6.2 Why both hybrid forms are executed

`search_symbols` has a `semantic: bool = False` parameter distinct from `semantic_only`
(signature at `:572-593`). Line 797 makes `semantic_only` imply `semantic`; `semantic_weight`
does not. Line 858 gates the semantic path on `semantic`. The recorded hybrid arguments carry
`semantic_only: false` and `semantic_weight: 0.5` and no `semantic` key.

Rather than choose which form is "the" hybrid case and make that choice load-bearing, both run:

- Forms 3 and 4 execute the recorded intent (`query_kind: hybrid`, `semantic_weight: 0.5`) and
  belong to the matrix.
- Forms 5 and 6 execute the recorded arguments byte-for-byte and belong to the
  **preflight contract check**, which records which code path they reach as a measured fact
  rather than a claim read off the source.

No result in the matrix can be attributed to an argument choice made by me, because the
alternative form was executed rather than argued about. The contract check is ancillary: one
repetition, both cache states, both lanes, 24 rows. It establishes exactly two facts, that the
recorded arguments take the BM25 path without loading the embedding matrix, and that this path
is result-cached. It produces no lane finding, because a path that never calls `score_all`
cannot distinguish the lanes. Its rows are never summed with the matrix and never appear in a
findings table.

### 6.3 Pinning `semantic_weight`

`search_symbols.py:683-687`: when `semantic or fusion` is true **and** `semantic_weight ==
0.5`, the caller's value is discarded and replaced by
`retrieval.tuning.get_semantic_weight(...)`, which reads
`<storage_path or ~/.code-index>/tuning.jsonc` and can return anything in `[0.1, 0.8]`. Forms 3
and 4 sit exactly on that trigger. Forms 5 and 6 do not reach it, because line 683 evaluates
before line 797 and sees `semantic=False`.

Resolution, which is production default behaviour on a clean install and changes no scorer
code: guarantee no `tuning.jsonc` exists under the trial-local `storage_path` or
`~/.code-index`, assert its absence per trial, assert the effective weight at scoring time
equals the frozen value, and record the effective weight on every row (C15). A silent per-repo
override would make the three corpora incomparable, so this is asserted rather than trusted.

### 6.4 Factors

| Factor | Levels | Multiplies? |
| --- | ---: | --- |
| `lane` | 2 (`numpy_present`, `numpy_absent`) | yes, treatment |
| `corpus` | 3 | yes |
| `form_id` | 4 in the matrix / 2 in the preflight check | yes, within arm |
| `cache_state` | 2 | yes |
| `repetition` | 5 in the matrix / 1 in the preflight check | yes, as replicates |
| `query_kind`, `top_k`, `semantic_weight`, `tie_heavy_query` | nested in `form_id` | no |
| `lane_invocation_order` | 2, balanced 60/60 in the matrix and 6/6 in the preflight check | no |

### 6.5 Identity keys

| Key | Grain | n (matrix) | n (preflight) |
| --- | --- | ---: | ---: |
| `problem_id` | `{corpus}__{form_id}` | 12 | 6 |
| `case_id` | `{corpus}:{form_id}:{cache_state}` | 24 | 12 |
| `pair_id` | `{case_id}:r{NN}` | 120 | 12 |
| `row_id` | `sha256({run_id},{pair_id},{lane})[:24]` | 240 | 24 |

`pair_id` is the pairing key. Exactly two rows share it, one per lane.

### 6.6 Deliberately absent

No new queries, no symbol-derived or agent-generated or adversarial vectors, no case selected
for likelihood of disagreement, no corpus or query or cache state or repetition removed for
cost, and no top-k sweep beyond the two frozen values. Depth beyond `top_k` is obtained from
retained full-depth evidence at zero extra execution (M12, 15.2), not by adding cases.

---

## 7. Exact row-count derivation

### 7.1 The matrix

```text
corpora                            3
lane-reaching query forms        x 4
cache states                     x 2
repetitions                      x 5
                                ----
frozen case executions           120     (= pair_id)
production lanes                 x 2
                                ----
measured rows                    240
paired lane comparisons          120
```

`rows = |corpus| x |form| x |cache_state| x |repetition| x |lane| = 3*4*2*5*2 = 240`.

### 7.2 Preflight contract check (ancillary, not part of the study size)

```text
3 corpora x 2 verbatim forms x 2 cache states x 1 repetition x 2 lanes = 24 rows, 12 pairs
```

### 7.3 Four routes to 120 case executions

1. Factor product: `3 * 4 * 2 * 5 = 120`.
2. Original packet grain: `360 rows / 3 modes = 120`.
3. Observed cardinality: `measurements.csv` has exactly 120 distinct `pair_id` values.
4. Observed structure: 24 `case_id` x 5 repetitions = 120, with 15 rows per `case_id` verified.

### 7.4 Counts that are wrong, and why

- **720.** Requires 360 frozen applicable cases. There are 120. The extra factor of 3 is
  `mode`, which is a scorer-implementation dimension whose three levels do not exist in
  v1.108.228. Crossing it with lane would mean executing three scorers that are not in the
  wheel against two lanes that are.
- **264 as a single study size.** The 24 preflight rows do not exercise the semantic scorer and
  cannot produce a lane finding. Adding them to 240 would merge a lane comparison with a
  code-path contract check and inflate the apparent scale of the study. The study size is 240
  rows and 120 paired comparisons.
- **48.** 24 case identities x 2 lanes discards all 5 repetitions and with them the within-lane
  determinism evidence that the negative control depends on.

---

## 8. Environment isolation contract

The only intended treatment difference is NumPy availability and the resulting shipped scorer
path.

### 8.1 Two environments

| Property | `numpy_present` | `numpy_absent` |
| --- | --- | --- |
| Python | 3.13.7 exactly | same |
| Wheel | official PyPI `jcodemunch_mcp-1.108.228-py3-none-any.whl`, SHA-256 `ff74b6344430053c6fad9064892d6a3904ffba6265823e3fba4dfde78f9a0488` | same file, same hash |
| NumPy | 2.4.4 importable | not importable by any means |
| Every other installed distribution | identical set and versions | identical set and versions |
| `PYTHONHASHSEED` | pinned, recorded | same value |
| `PYTHONNOUSERSITE` | `1` | `1` |
| `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS` | `1` | `1` |
| `JCODEMUNCH_EMBED_MATRIX_CACHE` | unset (production default) | unset |
| `storage_path`, `~/.code-index` | trial-local, no `tuning.jsonc` | same |
| Trial config | `share_savings=false`, `perf_telemetry_enabled=false`, identical non-executed `embed_model` sentinel | same |
| Network-defense environment | `JCODEMUNCH_SHARE_SAVINGS=0`; no embedding API credentials | same |
| Locale, TZ, CWD | pinned identical | pinned identical |

C16 compares a canonical logical manifest whose path-bearing fields are normalized. Its only
permitted semantic difference is NumPy. Raw provenance receipts retain the distinct interpreter,
venv and trial-root paths and are not expected to be byte-identical.

The canonical manifest schema is closed, versioned as
`arc4.environment-lock/v1`, and rejects missing keys, unknown keys and wrong types. Its required
keys are: schema string; lane string; Python implementation, version and cache tag strings;
platform, machine, processor, locale, time zone, SQLite and OpenSSL strings; a sorted distribution
array of objects containing normalized project name, version and retained wheel SHA-256; the exact
official treatment-wheel SHA-256; pip version; NumPy state object; CPU and BLAS identity objects;
the seven named environment variables below; the three effective configuration values
`share_savings`, `perf_telemetry_enabled` and `embed_model`; and `python_executable`,
`storage_path` and `cwd` strings. The only path rewrites are exact-prefix replacements:
the lane venv root becomes `<LANE_VENV>`, the trial root becomes `<TRIAL_ROOT>`, and this packet
root becomes `<PACKET_ROOT>`, with `/` as the canonical separator. A path that is not wholly
under its declared root is rejected rather than generalized. After these rewrites, the manifests
must be structurally identical except that `lane` is `numpy_present` versus `numpy_absent`, and
the NumPy state is respectively `{present:true,version:"2.4.4",artifact_sha256:<pinned>}` versus
`{present:false,version:null,artifact_sha256:null}`. The distribution arrays are compared after
removing that one declared NumPy entry; no other distribution difference is permitted.

The CPU object has exactly four keys: `architecture`, `machine` and `processor` as strings, and
`logical_cpu_count` as a positive integer. The BLAS object is a shared, preregistration-time
baseline copied byte-identically into both canonical manifests; it has exactly
`source_lane:"numpy_present"`, `numpy_version:"2.4.4"`, `config_json_sha256` as 64 lowercase
hexadecimal characters, and `raw_receipt_sha256` as 64 lowercase hexadecimal characters. It
describes the NumPy treatment's recorded BLAS configuration, not a claim that the fallback lane
loads BLAS. The environment-variable object has exactly `PYTHONHASHSEED`, `PYTHONNOUSERSITE`,
`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`,
`JCODEMUNCH_EMBED_MATRIX_CACHE`, and `JCODEMUNCH_SHARE_SAVINGS`. Values are JSON strings when
set and JSON null when intentionally unset; an omitted key is invalid.

### 8.2 Enforcing NumPy absence structurally

`_numpy()` at `storage/embedding_matrix.py:60-72` catches any exception and deliberately does
not cache the failure, so absence must be structural rather than patched:

- Build the fallback venv with pinned `--no-deps` installs and never install `numpy` or
  anything that pulls it transitively, notably `onnxruntime` (see the module docstring at
  `:25-27`).
- `PYTHONNOUSERSITE=1` so a user-site NumPy cannot leak in.
- In-process preflight: `import numpy` raises `ModuleNotFoundError`, **and**
  `importlib.util.find_spec("numpy") is None`, **and** `embedding_matrix._numpy() is None`.
- The same three assertions run **again after** the measured call. Because `_numpy()` does not
  cache failure, a process that gained NumPy mid-life would silently switch behaviour on the
  next `_build`; this closes that.
- Symmetric assertions in the NumPy lane: `numpy.__version__ == "2.4.4"`,
  `_numpy() is not None`, `matrix.vectorised is True`.

### 8.3 Lane is a process property

`_build()` reads `_numpy()` once and bakes the result into the returned `EmbeddingMatrix`
(`:201` vs `:230`), and `get_matrix()` caches that object per `(db_path, stamp)`. A process
that changed NumPy availability mid-life would keep scoring through whichever lane built the
cached matrix. Lane therefore cannot be a per-call flag. Every row is a fresh process in a
fresh interpreter from the correct venv. 264 processes, 240 of them in the matrix.

### 8.4 Shared, frozen, read-only

The two environments share only the wheel, the frozen database copies, the frozen query
vectors, the serialized argument set, and the harness source. All are content-addressed and
verified by hash at the start of every trial.

### 8.5 Dependency, configuration and network isolation

Before preregistration, `ENVIRONMENT-LOCK.json` pins Python 3.13.7, pip, every installed
distribution and artifact hash. Both venvs are built from that local wheelhouse with `--no-deps`;
the NumPy-present lock adds only NumPy 2.4.4. The verifier compares the canonical locks before
any row and rejects an undeclared distribution.

Each trial uses an explicit trial-local configuration with `share_savings=false` and
`perf_telemetry_enabled=false`, plus `JCODEMUNCH_SHARE_SAVINGS=0`. No embedding API credential
is inherited. A process-local outbound-socket tripwire records and rejects any connection
attempt. This tripwire does not alter scoring; it proves the local-only boundary. A tripwire
event is an infrastructure failure and no lane result is retained from that attempt.

Worker startup calls `jcodemunch_mcp.config.load_config(storage_path=trial_root)` before importing
or calling the search tool, then asserts through `jcodemunch_mcp.config.get` that
`share_savings is False`, `perf_telemetry_enabled is False`, and the non-executed `embed_model`
sentinel is exact. It also asserts `JCODEMUNCH_SHARE_SAVINGS == "0"`. The outbound-socket
tripwire is installed before configuration load and remains active until process exit.

---

## 9. Input-freezing contract

### 9.1 Corpora

Source of truth:
`<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\working\indexes\`

Present and hash-verified today:

| File | SHA-256 | Bytes |
| --- | --- | ---: |
| `local-django-3eb2e228.db` | `21767e35f79cf051c346389c90562126317fff9871ee9c7e4b33280fe3740529` | 137,502,720 |
| `local-fastapi-c1d6b9c4.db` | `fb0f933f2fff75684a26872b86bc8f7b7301b7d08c54a079630c05ede760e61e` | 43,274,240 |
| `local-arc4-research-v1-upstream-6f37f3de.db` | `9b6a007e9554a7afdb98936180d0abebce8b86693d842841122c72e9093cdc58` | 42,561,536 |

All three match `manifest.json`'s `working_database_sha256`.

The frozen originals are never opened by the production path. `sqlite_store._connect` applies
WAL pragmas on every connect, creating or touching `-wal`/`-shm` and bumping the exact stamp
`embedding_matrix._stamp()` reads. Protocol:

1. Copy `.db` (and `-wal`, `-shm` when present) into a **trial-local** directory, fresh per row.
2. Open the trial copy through the production store, then record a pre-call baseline for the
   main database and WAL, plus a logical digest and row count of `symbol_embeddings`. The SHM
   file is recorded as diagnostic state because reader locks may change it without changing
   database content.
3. Verify the main database and WAL are byte-identical to that baseline after the measured call,
   or that an absent WAL remains absent or contains no frames. Recompute the logical embedding
   digest and row count. Any content change fails the row even if the main `.db` hash did not
   change because a write remained in WAL.
4. Re-hash the frozen originals at run start and run end; they must be unchanged.

The logical embedding digest is `SHA-256` over one unambiguous byte stream. Execute
`SELECT symbol_id, embedding FROM symbol_embeddings ORDER BY symbol_id COLLATE BINARY` through
the same sidecar-aware read-only connection used by the tagged product. Reject a NULL or duplicate
ID, a non-text ID, or a non-BLOB embedding. Begin with ASCII
`arc4.symbol-embeddings/v1\n`. For every row append an unsigned 64-bit big-endian ID byte length,
the exact UTF-8 ID bytes, an unsigned 64-bit big-endian BLOB length, and the exact BLOB bytes.
The separate row count is the number of encoded rows. No decoded-float or host-native encoding
participates in this digest.

All design-phase inspection used `file:...?mode=ro&immutable=1`, which creates no sidecars, and
the three hashes were confirmed unchanged afterward.

### 9.2 Query vectors

Source of truth:
`<PUBLIC_EVIDENCE_ROOT>\arc4-real-embedding-certification-v1\prepared-inputs.json`

All four vectors are 384-dimensional and their recorded hashes match `query_embedding_sha256`
in `measurements.csv` exactly:

| `query_id` | vector SHA-256 |
| --- | --- |
| `semantic_input_validation` | `4993f06e82012359a98d6c00b285bba5e5f3ebc58a33719c1d9fee6abb9b4898` |
| `semantic_transaction_persistence` | `e3b2663419c7dd78b0ee5f4255fe1d318accb7273d0eb73e3d045853d141e867` |
| `hybrid_authentication_middleware` | `5312460bf00d3b9bedb7c99c52aebae23f458d9d487e4e5cc9093acbbd353f58` |
| `hybrid_test_client_response` | `7b66a6300e3925f0ea9f71e84536709129c413827229a6286fb307fb0f3fa135` |

Recomputed per trial and asserted before the call.

### 9.3 Query-provider injection: exact location and proof of scope

Regeneration is not acceptable. The query vector is an **input**, and this study's premise is
that both lanes receive byte-identical inputs so that any output difference is attributable to
the scorer alone. Invoking an embedding provider at measurement time would introduce
uncontrolled variation (provider version, runtime library, kernel selection, hardware) into the
one thing that must be held fixed, and it would break comparability with the frozen vectors the
original packet measured. The vectors are therefore supplied from `prepared-inputs.json`,
hash-verified per trial, and the provider is never invoked.

**The single injection point** is `search_symbols.py:1337`:

```python
query_vec = embed_texts([query], provider, model, task_type=query_task_type)[0]
```

`_search_symbols_semantic` performs a function-local import from
`jcodemunch_mcp.tools.embed_repo` on each call. The harness therefore substitutes
`embed_repo.embed_texts` in the fresh worker process. It does not patch the
`search_symbols` module.

Before that import, `_detect_provider()` must return a provider identity. Both lanes receive
the same trial-local `embed_model` sentinel, which causes detection to return
`("sentence_transformers", <sentinel>)` without importing or executing that backend. The
sentinel is a runtime gate identity only. `SOURCE-INVENTORY.json` separately records that the
frozen vectors were generated by `local_onnx`; the two identities are never conflated.

Proof obligations, all enforced as control C7:

- Called exactly once per measured `search_symbols` call, with `texts` equal to the frozen
  query string. Call count and arguments asserted, not merely logged.
- Returns the frozen vector for that `query_id`, byte-identical, hash re-verified inside the
  call.
- Changes only `query_vec`. `EmbeddingMatrix.score_all`, `_scores_numpy`, `_scores_python`,
  `_build`, `get_matrix`, the `score <= 0.0` filter at `:1439`, the `(-score, symbol_id)` sort
  at `:1462`, `_bm25_score_no_identity`, `_identity_score`, and result construction all run
  untouched.
- The second `embed_texts` call site at `:1359` must not execute. The substitute sets a
  persistent tripwire flag and raises on any call whose text is not the frozen query. Because
  `search_symbols` catches that exception in its top-up branch, the worker checks the flag
  after the public call and fails the row. C11 also requires unchanged embedding content.
- Byte-level diff of the installed package before and after each trial confirms no source under
  test was modified.

This is a **narrowly scoped process-local dependency substitution** at one imported provider
boundary, not a scorer patch. The worker invokes exactly one public tool call and exits, so no
unrelated call can observe the substitution. Scoring, sorting, candidate selection and result
construction are untouched, which C7 proves per trial by byte-diffing the installed package.

### 9.4 Serialized arguments

Both lanes receive byte-identical argument dictionaries per `form_id`, hashed per row. The four
recorded `serialized_args_json` values are identical across `research_config.json`,
`measurements.csv`, and `prepared-inputs.json` (verified). Forms 3 and 4 add exactly one key,
`"semantic": true`, and that delta is recorded explicitly per row as `arg_delta_from_recorded`.

### 9.5 Target-source provenance

The treatment artifact is the official PyPI wheel, downloaded from the 1.108.228 release and
hash-verified as
`ff74b6344430053c6fad9064892d6a3904ffba6265823e3fba4dfde78f9a0488`.
The release tag resolves to commit
`8bed872e9436093be9f89d35fb84e0cb58a293af`, which is now present as an object in the local
clone. The main checkout remains clean at `3e7f18fa4...` and is not used as target source.

The previously prepared local wheel, SHA-256
`81af0f0308cdbed7e4884fc272b589a6691e8119828858ed6b99b2aa09132af9`, is retained only as a
provenance comparison. It is not the treatment artifact. Against the PyPI wheel it has the
same 267 members; 58 Python members differ only by CRLF versus LF bytes and `RECORD` differs
accordingly. No normalized member-content difference was observed. This comparison is recorded
but does not substitute for P0.

An exact clean rebuild was attempted before preregistration and disproved byte reproducibility
under the recorded local build environment. From clean detached commit
`8bed872e9436093be9f89d35fb84e0cb58a293af`, Python 3.13.7 and an isolated PEP 517 build using
Hatchling 1.31.0 produced SHA-256
`c7fdf3bf2b666a6c9850c4485b2715500df569f315d8a986dc1d9be30fb92939`, not the official hash.
Both wheels contain 267 members. There are 203 raw differing members: 201 Python files and the
license differ only by line endings, and `RECORD` necessarily differs. After the normalization
defined below, there are zero substantive payload differences. This failed exact-hash attempt is
retained in `FAILURE-JOURNAL.jsonl`; the study makes no bit-reproducible-build claim.

**Mandatory preflight gate P0, before the first measured row:** independently repeat a normalized
payload-equivalence comparison between the official wheel and a clean rebuild from the tagged
commit. Reject a directory entry, an absolute or traversal path, a backslash path, or any duplicate
ZIP member path before constructing the path set. Require identical file-member path sets. The
one excluded comparison member is exactly
`jcodemunch_mcp-1.108.228.dist-info/RECORD`; no other suffix or basename match is excluded. For
every other member, compare exact bytes unless both byte streams are valid UTF-8 text with no NUL,
in which case normalize only CRLF and bare CR to LF and compare the resulting bytes. No whitespace,
Unicode, metadata, archive timestamp or other normalization is permitted.

Parse the official `RECORD` with Python's strict CSV reader and require exactly three fields per
row: archive path, hash and size. Paths must use the same safe canonical spelling as ZIP members,
must be unique, and must name every archive member exactly once. The `RECORD` row itself must have
empty hash and size fields. Every other row must use `sha256=<digest>`, where `<digest>` is an
unpadded URL-safe Base64 value that decodes to exactly 32 bytes and equals the member's SHA-256;
its size must be canonical unsigned decimal with no sign and no leading zero except `0`, and must
equal the exact byte length. No other empty field is permitted. Record the exact rebuild hash,
official hash, raw member differences, normalized member differences, build environment and
comparison-tool hash in `SOURCE-INVENTORY.json`. P0 passes only with zero missing or extra members,
zero normalized payload differences, and internally valid official `RECORD`; otherwise the run
does not start.

P0 supports the narrower statement that the retained official treatment wheel's payload is
equivalent to the tagged source under explicit newline normalization. It does not establish byte
reproducibility, the original publisher's build environment, or end-to-end supply-chain
authenticity. No result is produced unless this narrower provenance gate passes.

---

## 10. Execution-order and cache-state protocol

### 10.1 Process isolation

One fresh OS process per measured row, from the correct venv. No process executes two lanes,
two corpora, two forms, two cache states, or two repetitions.

### 10.2 Cache-state protocol

- `cold_fresh_process`: fresh process, fresh trial-local DB copy, measured call is the first
  `search_symbols` call. Assert `embedding_matrix.cache_stats()["repos"] == 0` immediately
  before it.
- `generation_warm`: fresh process, fresh copy, one untimed identical call first, then the
  measured call. Assert `cache_stats()["repos"] == 1` and the stamp unchanged between calls.
  Warm-up count is 1, matching the original `measurement.warmups`.
- The warm-up call's own result is retained as evidence, not discarded, so a warm-up that
  itself diverged is visible rather than invisible.

### 10.3 Lane-invocation order

Order cannot confound a deterministic ordering outcome across two processes in two venvs, but
it is balanced anyway so the question cannot be raised:

```text
numpy_first  if (case_ordinal + repetition) % 2 == 0  else python_first
```

Over 24 cases x 5 repetitions this yields exactly **60 / 60** in the matrix, and 6 / 6 over the
12 preflight case executions. Recorded per row and asserted by C10.

### 10.4 Hash-seed rules

- `PYTHONHASHSEED` pinned to a single recorded value for all 264 rows, identical in both lanes.
- A separate seed-sensitivity control (C9) re-runs a fixed, predeclared subset at seeds
  `{0, 1, 2, 3, 4}` plus one run with `PYTHONHASHSEED` unset. Seed 0 disables randomization in
  CPython, the four fixed values probe distinct randomizations, and the unset run probes the
  default production condition. Those rows carry `is_control=true`, are excluded from the
  matrix and from every headline count, and the verifier fails if any leaks in.
- Seed-dependent ordering, if found, is a finding about the product and is reported in its own
  section rather than folded into the paired comparison.

### 10.5 Warm-up rules

None for cold rows by definition, exactly one for warm rows. No cross-row, cross-process, or
filesystem-level warm-up, and no OS page-cache pre-warming, since no timing claim is made.

### 10.6 Failure and retry

- A trial that raises, times out, or fails any precondition is written to the failure journal
  with full context and is **not** written as a measured row.
- A failed `pair_id` stays failed until repaired and rerun under the same frozen identity: same
  corpus hash, query-vector hash, arguments, lane, repetition, cache state.
- Retries carry `attempt_n` and a reason. Nothing is silently re-attempted.
- Infrastructure failures (copy, disk, venv, timeout) and product-lane failures
  (`search_symbols` returns `error`, a lane assertion fails) are classified into separate
  buckets and reported separately (M9). An infrastructure failure is never reported as a lane
  result.

---

## 11. Metric definitions

Each paired comparison is `(numpy_row, python_row)` sharing a `pair_id`. `N` and `P` are the
ordered result-ID lists, `S_N` and `S_P` the full positive-score rankings, `k = top_k`.

**M1. Rank-0 difference.** `N[0] != P[0]`, symbol IDs compared as strings. Recorded as
`no_results` and excluded from the rank-0 denominator, with the exclusion stated, if either
list is empty.

**M2. Ordered top-k difference.** `N[:k] != P[:k]` as **sequences**. Order matters. Identical
membership in a different order is an M2 difference and is never collapsed into M3.

**M3. Top-k membership difference.** `set(N[:k]) != set(P[:k])`. M3 implies M2; M2 does not
imply M3. Both counts are always published together with the containment direction stated, so
neither reads as the other.

**M4. Exact-tie difference.** Exact tie means bit-identical final score, no epsilon, compared
as float64 bit patterns.

The comparison is over **tie-group identity, not counts.** Equal counts do not imply equal
structure: the partitions `{a,b},{c,d}` and `{a,c},{b,d}` have identical group and participant
counts and are different partitions. Each lane's tie structure is canonicalised as a sorted
tuple of sorted symbol-ID tuples and hashed. The pair metric is, in order:

1. `tie_partition_sha256` differs between the lanes (the primary signal).
2. Symmetric difference of the participant sets.
3. Symmetric difference of the set of groups intersecting the returned top-k.
4. Symmetric difference of the set of groups crossing the top-k boundary.

`tie_groups`, `tie_participants`, `groups_intersecting_top_k` and
`groups_crossing_the_top_k_boundary` are retained per lane as **summaries only** and are never
the basis of the equality decision.

**Exact ties are never excluded before being reported.** They appear in their own category
first, and only then may they be excluded from M6.

**M5. Score-order inversion.** A symbol pair `(a, b)` with `score_N(a) > score_N(b)` and
`score_P(a) < score_P(b)`, both strict. Equalities are not inversions. Counted over symbols in
either top-k, and separately over the full positive-score ranking.

**M6. Genuine disagreement: float32 tie where float64 distinguishes.** A symbol pair with
`score_N(a) == score_N(b)` exactly and `score_P(a) != score_P(b)`, or vice versa. This is the
tie-resolution asymmetry expected from float32 versus float64 accumulation. **A float32 tie is
never labelled an inversion.** M5 and M6 are disjoint by construction and appear as separate
rows in the summary. M6 is the only metric from which exact ties may be excluded, and only
after M4 has published them.

**M7. Within-lane determinism, and the pipeline negative control.** For a given `case_id` and
lane, the 5 repetitions must produce identical ordered result-ID lists, identical full-depth
ordering hashes, and identical top-k score vectors. Any difference is a determinism failure
attributed to that lane and reported before any cross-lane metric; the affected pairs are
marked `indeterminate` rather than `equal`. These same-lane repetition pairs run through the
identical comparison code as the cross-lane pairs, so they double as a production-scale
negative control: the pipeline must report zero on M1-M6 for them.

**M8. Public-tool versus reconstruction-adapter parity.** For every matrix row the adapter calls
the shipped `get_matrix` and `EmbeddingMatrix.score_all`, then reconstructs the exact final
ranking. Semantic-only forms set `final = cosine`. Hybrid forms execute the shipped `_tokenize`,
`_compute_bm25`, `_compute_centrality`, `_bm25_score_no_identity` and `_identity_score` helpers
over exactly the filtered production candidate domain. In pass 1 they collect `(lex, identity,
cosine)` for every candidate and compute `max_lex`, `max_identity` and, diagnostically,
`max_cosine` on that same domain. In pass 2:

```text
lex_norm      = lex / max_lex           if max_lex > 0 else 0
identity_norm = identity / max_identity if max_identity > 0 else 0
lexical_channel = max(lex_norm, identity_norm)
final = (1 - semantic_weight) * lexical_channel + semantic_weight * cosine
```

There is no cosine normalization and no reciprocal-rank fusion in this production path. The
adapter uses the effective `semantic_weight` asserted at call time, discards `final <= 0.0`, and
orders the remainder by `(-final, symbol_id)`. It rejects duplicate candidate IDs and any
non-finite component or final score. For semantic-only, it skips lexical and identity work and
applies the same positive-score filter and total order to cosine.

The public call must reproduce the adapter's ordered top-k IDs exactly on every matrix row. With
`debug=true`, exposed public scores are rounded to four decimal places, so the control compares
those exposed values to `round(adapter_final, 4)` and does not misdescribe them as bit-exact.
Raw semantic-ranking parity and final hybrid-result parity are recorded separately and never
conflated. The adapter exists because the public response does not expose unrounded full-depth
score vectors, which M4-M6 and M10-M12 require. Consequently full-depth numeric conclusions rely
on a reconstruction that reuses named shipped helpers plus the frozen equation above; they are
not independent black-box confirmation of an unobservable production vector. This limitation is
reported. A top-k parity failure is a harness defect and blocks the row.

**M9. Error, fallback, or lane-selection mismatch.** Any of: `search_symbols` returned an
`error` key; the observed lane does not match the intended lane; the fallback branch fired; the
embed-write tripwire fired; a precondition assertion failed. Reported as counts by category,
never merged into M1-M6.

**M10. Score-difference magnitude.** Per candidate, `|score_N(id) - score_P(id)|`. Computed
over the **full `score_all` output**, meaning every embedded symbol in the corpus, not only the
positive-score ranking and not only the top-k. Reported per pair as max, median, 99th
percentile, and the count of candidates whose scores are bit-identical across lanes. This is
the measurement that makes a null outcome quantitative: it establishes whether the two lanes
computed different arithmetic, and by how much. It is reported for all 120 matrix pairs. The
12 unique ranking problems contain 291,704 candidate identities; across 2 cache states and 5
repetitions the executed and retained matrix contains 2,917,040 candidate score comparisons
(13.8). Those comparisons are strongly dependent, so the count states completeness, not
statistical power, and no inference is drawn from its size.

M10's primary score is the raw cosine returned by `score_all`. For hybrid rows, the same four
summaries are also reported separately for the reconstructed final hybrid score and are labelled
`hybrid_final`, never merged with raw cosine. M4-M6 and M11 use final ranking scores because
those scores determine ordering. Any non-finite raw or final score fails the row.

For all numeric summaries, median is the ordinary middle value or the arithmetic mean of the
two middle values after sorting. The 99th percentile uses the nearest-rank rule at zero-based
index `ceil(0.99 * n) - 1`, clamped to `[0, n - 1]`. An empty eligible set emits
`no_finite_values`; it never fabricates zero.

**M11. Ordering margin (flip headroom).** What decides whether an adjacent pair `(a, b)`
flips is not the per-candidate score difference but the **change in their gap**. Writing
`delta_x = score_P(x) - score_N(x)`:

```text
gap_P(a,b) = gap_N(a,b) + (delta_a - delta_b)
```

With `a` ranked above `b` in lane N, so `gap_N(a,b) > 0`, a flip means `gap_P(a,b) < 0`, which
rearranges to

```text
gap_N(a,b) < (delta_b - delta_a)
```

Note the direction: the flip condition is `delta_b - delta_a`, not `delta_a - delta_b`. The
magnitude `|delta_b - delta_a|` reaches **2 x max|delta|** when the two candidates move in
opposite directions. Dividing a gap by `max|delta|` alone would overstate the safety margin by
up to a factor of two, so that form is not used.

For computation under either lane's own ordering, let `L` be the ordering lane, `O` the other
lane, and `gap_L(a,b) = score_L(a) - score_L(b)`. Two margins are reported per pair, both
computable because every matrix row's full score vector is retained:

- **Observed margin (primary):** `gap_L(a,b) / |gap_L(a,b) - gap_O(a,b)|`, using the directly
  measured gap change. Exact, and needs no bound.
- **Conservative a priori margin:** `gap_L(a,b) / (2 * max|delta|)`, the worst case over any
  pair, where `delta_x = score_P(x) - score_N(x)` regardless of which lane supplies the
  ordering.

Both are computed for the top-k boundary pair (`score[k-1] - score[k]`) and for the minimum
adjacent-pair gap inside the top-k, and **both are computed under each lane's own ordering**,
because the boundary pair is not necessarily the same pair in the two lanes.

**Zero-denominator semantics, pre-registered.** Both ratios are undefined when their denominator
is zero, so the value emitted is fixed in advance rather than decided at analysis time:

| `gap_L` | denominator | Emitted value | Meaning |
| --- | --- | --- | --- |
| `> 0` | `0` | `+inf` | The lanes moved this pair's gap by exactly zero. Maximally safe |
| `= 0` | `0` | `exact_tie` | Both lanes tie this pair. Belongs to M4, not to a margin |
| `= 0` | `> 0` | `0.0` | Tied in one lane, split in the other. Cross-referenced to M6 |
| `> 0` | `> 0` | finite positive | The ordinary case |

The conservative margin's denominator is zero only when `max|delta| = 0`, meaning the two lanes
produced bit-identical scores across the entire corpus. A positive `gap_L` then emits `+inf`; a
zero `gap_L` remains `exact_tie`. Both are flagged as notable outcomes.

**Aggregation rule.** Numeric aggregates (minimum, median, percentiles) are computed over
**finite values only, including every `0.0`**. Counts of `+inf`, `exact_tie` and `0.0` are
reported beside the aggregates, but only `+inf` and `exact_tie` are excluded. The headline
figure is the **minimum finite margin**, which is the tightest observed case, not the mean,
which `+inf` values would distort.


A ratio far above 1 means the ordering had headroom to spare; a ratio near or below 1 means it
survived by a margin comparable to the perturbation. This converts "no flips observed" into
"no flips, with a measured margin of X on this suite". It describes the frozen suite and is
not extrapolated beyond it (13.8).

**M12. First divergence rank at full depth.** The smallest rank at which `S_N` and `S_P`
disagree over the entire positive-score ranking, or `none` if the full orderings and their
lengths are identical. If one ordering is a strict prefix of the other, the first divergence is
the zero-based length of the shorter ordering. Answers "you only looked at top 10" from
retained evidence at zero extra execution cost.

### 11.1 Reporting rules

- M1, M2, M3 and M4 are the four requested by name and each gets its own table and count.
- No single merged "disagreement" figure is reported anywhere.
- Every result carries planned, observed and eligible denominators. The planned matrix is
  `n = 120 paired comparisons over 12 ranking problems and 4 query vectors`.
- M1 marks a pair `no_results` and removes it only from the M1 eligible denominator if either
  list is empty. M2 and M3 compare the possibly short sequences and sets directly. M11 emits
  `insufficient_ranking` for a boundary requiring rank `k` when fewer than `k + 1` positive
  results exist, and for an internal adjacent gap when fewer than 2 results exist. Those
  sentinels are counted and excluded from margin aggregates. No short ranking is silently
  treated as equal or dropped.
- Score evidence is retained as hex float64 (`float.hex()`) so it round-trips exactly.
- Matrix figures and preflight contract figures never share a table, and the preflight rows
  are never added to any matrix denominator.

---

## 12. Controls

| ID | Control | Passes when |
| --- | --- | --- |
| C1 | Target wheel identity | Installed official PyPI wheel SHA-256 is `ff74b634...9a0488` and `__version__` is `1.108.228`, in **both** lanes |
| C2 | Target source identity | Preflight gate P0 (9.5): commit `8bed872e...` checked out clean and detached with line-ending conversion disabled; clean rebuild and official wheel have identical member paths, zero normalized payload differences, and the official `RECORD` validates internally |
| C3 | Frozen database identity | Trial-local main DB and WAL baseline, logical embedding digest and row count remain unchanged across every measured call; frozen originals unchanged at run start and end |
| C4 | Frozen query-vector hashes | Recomputed per trial, matches 9.2 |
| C5 | Lane selection, NumPy lane | `_numpy() is not None`, `matrix.vectorised is True`, `cache_stats()["numpy"] is True`, `numpy.__version__ == "2.4.4"` |
| C6 | NumPy absence, fallback lane | `import numpy` raises, `find_spec("numpy") is None`, `_numpy() is None`, `matrix.vectorised is False`, asserted before **and after** the measured call |
| C7 | Injection scope | Process-local `embed_repo.embed_texts` substitute called exactly once with the frozen text, returns the hash-verified frozen vector, no tripwire call occurred, installed package bytes unchanged |
| C8 | Tool/adapter parity | M8 holds on all 240 matrix rows; on the 24 preflight rows the adapter reproduces the BM25 ordering |
| C9 | Determinism and hash-seed | M7 holds on all case/lane groups, plus the separate seed sweep (10.4) |
| C10 | Order balance | `lane_invocation_order` exactly 60/60 in the matrix and 6/6 in the preflight check |
| C11 | Embed-write tripwire | The `:1359` top-up tripwire flag is false; main DB and WAL baseline, `symbol_embeddings` row count and logical content digest are unchanged |
| C12 | Preflight contract observation | Forms 5 and 6 record which code path they reached, that `get_matrix` was **not** called, and `served_from_result_cache` |
| C13 | Manifest integrity and mutation self-test | Verifier recomputes all manifest-listed hashes and the detached manifest root; all mutation self-tests fail closed (16.4). This detects accidental or uncoordinated mutation, not an adversary rewriting the whole packet |
| C14 | Cache-state validation | Cold: `cache_stats()["repos"] == 0` before the measured call. Warm: `== 1`, stamp unchanged between calls |
| C15 | Semantic-weight pinning | No `tuning.jsonc` under `storage_path` or `~/.code-index`; effective weight at scoring time equals the frozen value; recorded per row |
| C16 | Environment parity | Canonical logical-manifest diff is limited to the lane label and the declared NumPy state/distribution entry; after removing those declarations the diff is empty; raw path-bearing receipts are retained separately |
| C17 | **Known-zero** | Two byte-identical result sets are fed to the comparison code, which reports zero on every one of M1-M6 and `none` on M12 |
| C18 | **Known-positive, per class and sentinel** | Frozen hex-float fixtures produce the preregistered metric vectors in 12.1, including required overlaps, M11 `exact_tie`, `0.0`, `+inf`, and finite-zero aggregate inclusion |
| C19 | **Sensitivity floor (1 ULP per candidate)** | Two adjacent candidates start one ULP apart and each moves one ULP in the opposite direction, guaranteeing an order crossing. The expected metric vector is frozen in 12.1. This establishes detector sensitivity; it does not claim that moving one endpoint by one ULP always crosses |
| C20 | Full-depth evidence integrity | Every matrix row retains raw cosine and final score evidence as applicable; the verifier recomputes the full-depth ordering hash and M10-M12 from all 240 retained row vectors |
| C21 | Local-only network isolation | Explicit telemetry config and environment disable sharing, no embedding credential is inherited, and the worker's outbound-socket tripwire records zero attempts |

### 12.1 Fixture policy for the positive controls

C18 and C19 use **harness-local synthetic fixtures constructed inside this packet** from
literals: result-list and score-vector pairs built by the harness to exercise each branch of
the comparison code. They never touch a shipped scorer, never read an external corpus, and
never produce a matrix row.

The score literals and expected metric overlaps are frozen here. Candidate order in each cell
is the positive full ranking after the `(-score, id)` tie-break. Metrics not named in the
expected column are false unless the column explicitly states a sentinel or denominator rule.

| Fixture | `k` | Lane N scores | Lane P scores | Required result |
| --- | ---: | --- | --- | --- |
| `known_zero` | 2 | `a=0x1.0p+0,b=0x1.0p-1` | identical | M1-M6 false; M12 `none` |
| `rank0_swap` | 2 | `a=0x1.0p+0,b=0x1.0p-1` | `b=0x1.0p+0,a=0x1.0p-1` | M1, M2, M5; M3 false; M12 rank 0 |
| `ordered_only` | 3 | `a=0x1.0p+0,b=0x1.8p-1,c=0x1.0p-1` | `a=0x1.0p+0,c=0x1.8p-1,b=0x1.0p-1` | M2, M5; M1 and M3 false; M12 rank 1 |
| `membership_boundary` | 2 | `a=0x1.0p+0,b=0x1.8p-1,c=0x1.0p-1` | `a=0x1.0p+0,c=0x1.8p-1,b=0x1.0p-1` | M2, M3, M5; M1 false; M12 rank 1 |
| `tie_split` | 2 | `a=0x1.0p-1,b=0x1.0p-1` | `a=0x1.8p-1,b=0x1.0p-1` | M4 and M6; N-order observed margin `0.0`; M12 `none` |
| `same_tie` | 2 | `a=0x1.0p-1,b=0x1.0p-1` | identical | M1-M6 false; both lane-order margins `exact_tie`; M12 `none` |
| `unchanged_positive_gap` | 2 | `a=0x1.0p+0,b=0x1.0p-1` | `a=0x1.2p+0,b=0x1.4p-1` | M1-M6 false; observed margin `+inf`; M12 `none` |
| `deep_rank_only` | 2 | `a=0x1.0p+0,b=0x1.8p-1,c=0x1.0p-1,d=0x1.0p-2` | `a=0x1.0p+0,b=0x1.8p-1,d=0x1.0p-1,c=0x1.0p-2` | M1-M3 false; full-depth M5; M12 rank 2 |
| `one_ulp_cross` | 2 | `a=0x1.0000000000002p+0,b=0x1.0000000000001p+0` | `b=0x1.0000000000002p+0,a=0x1.0000000000001p+0` | M1, M2, M5; M3 false; M12 rank 0 |

The aggregation primitive also receives the literal sequence
`[0x0.0p+0, 0x1.0p+1, +inf, exact_tie]`. Its eligible finite set must be `[0.0, 2.0]`, with
minimum `0.0`, median `1.0`, nearest-rank p99 `2.0`, one `+inf`, one `exact_tie`, and one finite
zero. Excluding the zero fails C18.

- Every control row carries `is_control=true` and a `control_id`.
- Control rows are excluded from every headline count, and the verifier fails if one leaks in
  (16.3).
- No fixture, corpus, query, vector, result, or severity judgement originates outside this
  packet's own declared inputs, which are exactly the frozen corpora (9.1) and the frozen
  query vectors (9.2).

This makes detector sensitivity provable without importing anything from outside the frozen
suite.

---

## 13. Statistical interpretation

### 13.1 What this design is

A **census of a fixed, purposive, predetermined suite**. It is not a random sample of
production traffic, and no sampling frame over user queries exists.

### 13.2 Permitted claims

- **Descriptive incidence within the frozen suite.** "X of 120 paired comparisons differed at
  rank 0", always accompanied by "over 12 ranking problems and 4 query vectors". Exact counts,
  per corpus and per query form.
- **Quantitative arithmetic divergence.** M10 and M11 are exhaustive direct measurements over
  the frozen suite. They are reported as measurements of these corpora and these vectors, and
  are **not** extrapolated to other queries, corpora, or inputs.
- **Observed same-host repeatability.** Within-lane agreement across the five recorded
  repetitions, two cache states, pinned hash seeds and exact local environments is a property
  observed for this frozen suite on this host. It is not an implementation-wide determinism or
  cross-host reproducibility claim.
- **Capability.** A single genuine difference establishes that the shipped lanes *can* diverge
  on real embeddings at v1.108.228.
- **Ordinary-use reachability.** Only for the specific frozen queries executed, which are four
  researcher-authored strings.

### 13.3 No inferential statistics are reported

**No p-value, no confidence interval, and no hypothesis test appears anywhere in this study's
outputs.** This is a design decision, not an omission, and the verifier enforces it (16.3).

Two candidate procedures were considered and both are rejected:

- **Exact McNemar.** McNemar tests marginal homogeneity across discordant paired outcomes. Here
  each ranking problem yields a single lane-equality indicator rather than a pair of
  per-treatment binary outcomes, so there are no discordant cells to test. The procedure does
  not apply to this outcome shape.
- **Clopper-Pearson intervals.** These assume independent, identically distributed Bernoulli
  trials drawn from a population. The 12 ranking problems are purposive rather than random and
  share 4 query vectors across 3 corpora, so they are dependent. An interval computed under
  that model would be arithmetically valid and substantively meaningless, and once printed it
  would be quotable out of context.

### 13.4 What is reported instead

Descriptive counts with explicit denominators, and nothing else. **The two denominators take
distinct numerators**, because one differing problem contributes all 10 of its paired
comparisons:

- `rank-0 differences: X_problem / 12 ranking problems; X_pair / 120 paired comparisons`
- the same form for M2, M3 and M4
- per-corpus and per-query-form breakdowns as raw counts

**Aggregation rule from pairs to problems, pre-registered.** Each ranking problem contributes
10 paired comparisons (2 cache states x 5 repetitions). The problem-level outcome is the
logical OR over those 10: the problem counts as differing if any of its pairs differs.

**Unanimity is required and checked.** Under M7 determinism the 5 repetitions within a cache
state must agree, and ordering is expected to be cache-invariant (5.1), so all 10 pairs of a
problem should be unanimous. A problem whose 10 pairs are **not** unanimous is flagged
`heterogeneous_within_problem` and reported explicitly in its own line, because non-unanimity is
either a determinism failure (M7) or a cache-state dependence, and both are findings in their
own right rather than something to average away. The verifier fails if a heterogeneous problem
is aggregated without the flag.

Every count carries its independence level inline. No count is converted into a rate, a
proportion with an interval, or a probability.

### 13.5 What a zero finding establishes, pre-specified

**Establishes:** across these 12 ranking problems, on these 3 real corpora, with these 4 real
query vectors, at v1.108.228 with `(-score, symbol_id)` ordering, the two shipped lanes
produced identical rank-0, identical ordered top-k, and identical membership, repeatably on the
recorded host and environments across 5 repetitions and both cache states, with lane selection proven rather than assumed and
with a detector demonstrated to resolve a one-ULP ordering change (C19). Accompanied by M10 and M11, it further
establishes *how far* the scores diverged and *how much headroom* the ordering had, which
converts the zero from an absence into a measured margin.

**Does not establish:** that the lanes cannot diverge; any rate (13.4); anything about queries,
corpora, top-k values, or weights outside the frozen set; anything about production prevalence
or user harm.

### 13.6 What one or more findings establishes, pre-specified

**Establishes:** that divergence between the shipped lanes survives the `(-score, symbol_id)`
tie-break shipped in v1.108.228, and that it is reachable from a real embedding corpus and a
real query vector. The source under test states at `search_symbols.py:1448-1461` that the two
lanes' scores differ by about 1e-7 and that a rank-0 disagreement was observed on a deliberately
near-tied synthetic corpus; a finding here would show the same effect on real embeddings, which
that comment explicitly does not claim. Same-host repeatability is observed through the 5
repetitions, both cache states, and the seed sweep. The packet enables a later independent
reproduction attempt but does not prove cross-host or cross-BLAS reproducibility. Attribution
to the lane rather than the harness is supported by C7, C8 and C16 within the stated process
substitution boundary.

**Does not establish:** how often this happens for real users. A difference found in a purposive
suite is a capability demonstration with a real-input existence proof, not a rate. The report
states this in the same paragraph as the count, not in a limitations section further down.

### 13.7 Forbidden in every outcome

No p-values, confidence intervals, or hypothesis tests of any kind (13.3). No production
prevalence or field incidence. No "N% of queries" derived from 12, 120, 240, or from any
candidate-level count. No description of candidate scores or adjacent pairs as independent
observations. No extrapolation of an M10 or M11 measurement beyond the frozen suite.
No treating repetitions as query diversity or rows as independent queries. No extrapolation
from 4 query vectors to any real query distribution. No timing or memory conclusion.

### 13.8 Why "sample size" is the wrong frame

The natural objection is that 12 ranking problems cannot support a statistical claim. That is
correct, and this design does not make one. The resolution is not a larger n or a cleverer
statistic; it is that **this is a census, not a sample**, and a census has no sampling error
and no generalization.

**What is enumerated, exhaustively.**

| Quantity | Unit | Count in the matrix |
| --- | --- | ---: |
| Ranking problems | corpus x query form | **12** |
| Matrix lane pairs | ranking problem x cache state x repetition | **120** |
| Unique candidate identities across 12 problems | one candidate identity in one problem | **291,704** |
| Executed candidate score comparisons | one candidate, both lanes, one matrix pair | **2,917,040** |
| Executed adjacent-pair comparisons | one adjacent pair, both lanes, one matrix pair | up to **2,916,920** |

Per corpus: django 45,561 x 4 forms = 182,244; fastapi 13,405 x 4 = 53,620; jcodemunch
13,960 x 4 = 55,840.

**These counts are completeness, not power.** The 2,917,040 executed score comparisons repeat
291,704 candidate identities across cache states and repetitions. They share 4 query vectors, 3
corpora, one BLAS build per lane and one accumulation pattern, and their magnitudes are strongly
dependent. The adjacent pairs additionally overlap because consecutive pairs share a candidate.
**None is an independent observation, and none is treated as one.** The counts state that
nothing in the frozen matrix was sampled, subsetted or skipped. They are never used to justify
an inference, confidence statement or extrapolation.

**What this buys, given no inference is drawn.** Three things, all descriptive:

1. **Completeness.** Every candidate in every corpus, at every frozen query form, in both
   lanes, is compared. There is no selection step anywhere, so there is no selection to argue
   about.
2. **Resolution.** M10 and M11 report how far the scores moved and how much gap the ordering
   had, so an outcome of "no flips" arrives with the margin attached rather than as a bare
   zero. That is a property of the frozen suite, stated as such.
3. **Falsifiability.** A margin near 1 would be a warning that a flip is close, on this suite,
   even where none occurred. A count alone can never produce that.

**What this explicitly does not buy.** It does not license any statement about queries,
corpora, weights, or top-k values outside the frozen set. The mechanism is arithmetic and the
same rounding behaviour plausibly applies elsewhere, but plausibility is not measurement, and
this study reports only what it enumerated. Section 13.7 forbids the rest.

**Why the query set is not enlarged.** Two reasons, both of higher authority than any
convenience argument. The brief governing this work forbids inventing, expanding, or replacing
the original query set. And the maintainer scoped the request to this comparison over "the same
real-embedding corpora" with "identical queries", so an enlarged suite would answer a question
nobody asked and would no longer be comparable to the packet it succeeds. A breadth study over
many queries is a legitimate and different experiment, with its own sampling frame, its own
pre-registration, and its own report. It is not this one, and this design neither depends on
one nor borrows from one.

**What a genuine prevalence claim would require**, if one were ever wanted: a sampling frame
over real production queries, which does not exist for this tool, since the query text reaching
`search_symbols` is model-generated rather than user-typed. That is a different experiment with
a different design, and this one does not pretend to be it.

---

## 14. Stopping and blocker rules (pre-registered)

Frozen before any lane result is inspected. No lane result is inspected before this design is
approved and `PREREGISTRATION.md` is hashed and committed.

1. **No early stop on the first disagreement.** All 240 matrix rows execute.
2. **No early stop on observed parity.** All 240 matrix rows execute.
3. **No post-result design changes.** Queries, corpora, forms, top-k values, weights, cache
   states, repetitions, metric definitions and the pairing key are frozen at approval. Any
   change after results are seen voids the run, which restarts under a new `run_id` with the
   prior run retained and marked superseded with a reason.
4. **A failed case stays failed** until repaired and rerun under the same frozen identity
   (10.6). Never dropped, never substituted, never quietly excluded from a denominator.
5. **No weakening substitutions.** No smaller corpus, no reduced top-k, no fewer repetitions,
   no different embedding provider, no regenerated query vectors, no alternative scorer.
6. **Infrastructure and product-lane failures are separate** (M9) and never merged.
7. **Three-strikes blocker rule.** If the same genuine blocker survives three materially
   different repair attempts, **stop without a verdict** and report all three attempts with
   full methodology and evidence, the most likely cause, and the exact unblocker required.
   Three variations of one approach are not three attempts.
8. **Partial execution cannot produce the final verdict.** Coverage must be 240/240 matrix rows
   and 120/120 matrix pairs, plus 24/24 preflight rows, verifier-confirmed, or the report states
   `verdict: incomplete` and publishes the coverage shortfall as the headline. All controls
   passing with 239 matrix rows is `incomplete`.

---

## 15. Evidence packet specification

Root: `<LOCAL_RESEARCH_ROOT>\arc4-production-lane-comparison-v2\`

### 15.1 Artifacts

| Artifact | Contents |
| --- | --- |
| `PLAN.md` | This design, as approved |
| `PREREGISTRATION.md` | Sections 11, 13 and 14 frozen, UTC timestamp, config hash, committed before the first measured row |
| `PROVENANCE.json` | Design hash lineage, issue and comment authorization, official and excluded local wheel identities, Munch runtime identities, immutable top-level task IDs, commands, retrieval times and evidence annotations |
| `SOURCE-INVENTORY.json` | Official wheel hash and PyPI URL, P0 rebuild result, member-level comparison, source commit, per-corpus identities and hashes, query-vector hashes, both canonical and raw environment manifests, BLAS identity, unreproducible elements |
| `ENVIRONMENT-LOCK.json` | Python, pip and exact wheelhouse artifact identities; two lane locks whose only distribution difference is NumPy 2.4.4 |
| `inputs/jcodemunch_mcp-1.108.228-py3-none-any.whl` | Exact official PyPI treatment wheel, retained locally and manifest-bound |
| `ORIGINAL-MATRIX-DECOMPOSITION.json` | Section 3, machine-readable, recomputed by the verifier from the original CSV rather than transcribed |
| `TRANSFER-DECISIONS.json` | One record per original dimension and column: classification, justification, information lost, breadth effect, row-count effect |
| `frozen-cases.json` | All 132 case executions and 264 planned rows (120 + 240 matrix, 12 + 24 preflight) with `row_id`, `pair_id`, `case_id`, `problem_id`, arm, lane, args hash, corpus hash, query-vector hash, `lane_invocation_order`. Written and hashed **before** execution |
| `env/numpy-present.json`, `env/numpy-absent.json` | Canonical logical environment manifests used by C16 |
| `env/raw-numpy-present.json`, `env/raw-numpy-absent.json` | Full path-bearing provenance receipts, retained without byte-parity expectations |
| `raw/rows.jsonl` | 264 immutable row records, arm-tagged (15.2) |
| `raw/full-rankings/` | Full exact score vectors for all 240 matrix rows (15.2) |
| `raw/warmups.jsonl` | The 66 warm-up call results (60 matrix, 6 preflight), retained not discarded |
| `paired.jsonl` | 132 paired comparisons, arm-tagged. M1-M9 on all; M10-M12 on the 120 matrix pairs only, since the preflight path produces no semantic score vector |
| `controls/` | One record per control C1-C21 with its own pass/fail and evidence |
| `FAILURE-JOURNAL.jsonl` | Every failed pilot, setup, verification and trial attempt with methodology, evidence, classification and repair. Append-only, retained even when superseded by a success |
| `METHODOLOGY-JOURNAL.jsonl` | Chronological record of every execution-time decision, including decisions not to change something |
| `SUMMARY.json` | All headline counts, each with denominator and independence level, arm-separated |
| `REPORT.md` | Sections 11 and 13 as prose, four separate tables for M1-M4, M10-M12 margins, limitations, local-hold statement |
| `MANIFEST.json`, `MANIFEST.sha256` | SHA-256 inventory of all immutable packet files except the manifest, detached root and generated verifier receipt; detached SHA-256 of the canonical manifest |
| `verify.py`, `verification.txt` | Independent verifier and its receipt |

### 15.2 Full-depth evidence, and why it is bounded this way

- **Every matrix row** records a `full_depth_ordering_sha256` over the complete positive-score ranking
  using the exact encoding below. Cheap, and it makes M7 determinism a full-depth check rather
  than a top-k check.
- **Every one of the 240 matrix rows** retains its complete score vector. Semantic-only rows
  retain raw cosine once because it is also the final score. Hybrid rows retain both raw cosine
  and reconstructed final score. The preflight arm produces no semantic score vector. At the
  prior measured encoding density this is estimated at roughly **385 MB**, about 7.5 times the
  former 51 MB repetition-1-only plan. This is an estimate, not a measurement, and actual file
  sizes are reported.
- M10-M12 are recomputed for all 120 matrix pairs from those retained vectors. C20 checks every
  vector rehashes to the ordering hash recorded in its row. A missing vector is a coverage
  failure, not an eligible exclusion.

Raw sample-level results are preserved in full. Aggregates are always rederivable from
`raw/`, never the only surviving form.

The score-vector file encoding is closed and versioned. One UTF-8 JSON Lines file with no BOM and
LF endings represents each score kind. Its first line is exactly
`{"schema":"arc4.full-score-vector/v1"}` serialized with compact separators. Each following
line has exactly the keys `symbol_id` and `score_hex`, in that order; `symbol_id` is a JSON string
and `score_hex` is Python `float.hex()` for a finite binary64 value. Rows are sorted by
`symbol_id` using Unicode code-point order. Duplicate IDs, a missing or extra ID relative to the
frozen matrix `id_set`, a non-finite value, an unknown key or a noncanonical JSON spelling fail
the row. The file SHA-256 binds the complete vector used by M10.

The full-depth ordering hash uses a separate canonical UTF-8 JSON Lines stream whose first line
is exactly `{"schema":"arc4.positive-ranking/v1"}`. It contains only candidates whose final
score is strictly greater than zero, ordered by `(-score, symbol_id)`, with the same exact
two-key row encoding and LF termination. Zero and negative scores remain in the complete vector
but not in this positive-ranking stream. Its SHA-256 is `full_depth_ordering_sha256`. The
verifier reconstructs both streams byte for byte rather than trusting recorded hashes.

All canonical JSON lines in these two streams are produced by Python `json.dumps` with
`ensure_ascii=False`, `allow_nan=False`, `separators=(",", ":")`, and `sort_keys=False`, followed
by exactly one `\n`. Dictionaries are constructed in the fixed key order stated above. Encoding
is UTF-8 without BOM. Any alternative escaping, spacing, key order or final-line termination is
noncanonical even when a generic JSON parser would accept it.

---

## 16. Independent verifier specification

`verify.py`. Standard library only, no dependencies, no checkout required. Its packet root is
`Path(__file__).resolve().parent`. Run it as `py -3 verify.py`; success is exit 0. Exit 2 means
the packet was rejected, 64 means invalid CLI use, and 70 means an internal verifier exception.
Optional `py -3 verify.py --self-test` runs mutation tests without writing a file; optional
`py -3 verify.py --write-receipt` writes `verification.txt`, and the two flags may be combined.
No invocation writes outside the packet root.

Stdout is one canonical compact JSON object using the same JSON settings above, with keys in this
exact order: `schema`, `status`, `verifier_sha256`, `manifest_sha256`,
`matrix_rows_observed`, `matrix_rows_expected`, `matrix_pairs_observed`,
`matrix_pairs_expected`, `preflight_rows_observed`, `preflight_rows_expected`,
`controls_passed`, `controls_expected`, `manifest_files_verified`, `self_tests_passed`,
`self_tests_expected`, `verdict`, `error_codes`. The schema is
`arc4.verification-receipt/v1`; count fields are nonnegative integers or JSON null when the stage
did not run; `error_codes` is a sorted unique string array. `status` is `verified`, `rejected`,
`usage_error`, or `internal_error` and agrees with the exit code. Human prose goes to stderr and
cannot alter the receipt schema.

### 16.1 Order of operations

1. **Hash self-check first.** Recompute `MANIFEST.sha256`, then every file hash listed in
   `MANIFEST.json`, before computing a single figure. `MANIFEST.json`, `MANIFEST.sha256` and the
   generated `verification.txt` are deliberately excluded from the inventory to avoid circular
   self-hashes. Abort on mismatch. This is an internal-consistency and accidental-mutation
   control, not proof against coordinated rewriting of the entire local packet.
2. Recompute the original-matrix decomposition directly from the original `measurements.csv`
   and assert 360 rows, 24 `case_id`, 120 `pair_id`, 3 modes, full Cartesian coverage. This
   makes the row-count derivation itself checkable rather than asserted.
3. Recompute every headline count in `SUMMARY.json` and `REPORT.md` from `raw/rows.jsonl` and
   `raw/full-rankings/`.
4. Print claimed against recomputed for every figure.

### 16.2 Rejection tests

Fails on mutation of: lane identity, case identity, `pair_id` pairing, query-vector hash,
corpus hash, ordered result IDs, top-k membership, rank 0, exact-tie classification, full-depth
ordering hash, coverage counts, arm assignment, control pass/fail, and the summary verdict.

### 16.3 Anti-skip requirements

- **No `continue` and no early `return` inside any checking loop.** A row it cannot classify is
  a **failure**, never a skip. Unknown schema, missing field, unparseable value: fail.
- Every row must be **positively classified**; the verifier proves it recognised each row
  rather than assuming it did.
- **Every summary line is computed from the loop's results**, never from arithmetic over the
  file list. No `len(files) - len(exceptions)` constructions.
- Coverage asserted as 240 matrix rows / 120 matrix pairs and 24 preflight rows / 12 preflight
  pairs, each pair having exactly one row per lane. Two rows in the same lane for one `pair_id`
  is a failure.
- **The verifier fails if any p-value, confidence interval, or hypothesis-test result appears in
  `SUMMARY.json` or `REPORT.md`** (13.3), and if any preflight row is summed into a matrix
  denominator.
- Problem-level and pair-level counts are recomputed **separately** from raw rows and must not
  share a numerator (13.4). The verifier recomputes the pairs-to-problems OR aggregation itself,
  and **fails if a problem whose 10 pairs are non-unanimous was aggregated without the
  `heterogeneous_within_problem` flag**.
- M11 sentinel values (`+inf`, `exact_tie`, `insufficient_ranking`) and finite zeros are
  recounted from raw rows. The verifier fails if a numeric aggregate includes a non-finite value,
  excludes an eligible finite zero, or includes an `insufficient_ranking` sentinel.
- Control rows are excluded from headline counts and the verifier fails if any leaked in.
- Matrix and preflight counts are computed separately; a merged figure anywhere is a failure.

### 16.4 Self-tests

`--self-test` mutates an in-memory copy of the packet in each way listed in 16.2 and asserts
the verifier **fails** on every one. A self-test that passes when it should fail is itself a
failure. Results appear in the stdout receipt; `verification.txt` is written only when
`--write-receipt` is also present.

### 16.5 Stated non-coverage, in the receipt itself

- It does not re-execute the scorers, so it cannot detect a harness that measured the wrong
  thing consistently. C8 is the guard there; the verifier only checks C8 was recorded passing.
- It verifies P0's normalized payload-equivalence result and retained member comparison, but it
  does not rebuild the wheel and cannot elevate that result into a reproducible-build or
  supply-chain-authenticity claim.
- It cannot reproduce the NumPy lane's float32 results on a different BLAS build (18.4).

---

## 17. Acceptance criteria

**Design** (this document):

- [x] The original 360 rows decomposed exactly, Cartesian structure shown and verified complete.
- [x] Row count derived by four independent routes, not assumed.
- [x] Every original dimension and column carries an explicit transfer decision.
- [x] No query or case invented, reworded, or removed.
- [x] Both lanes receive the same frozen case executions.
- [x] Independence and repetition described correctly (4 / 12 / 24 / 120 / 240 hierarchy).
- [x] M1 rank-0, M2 ordered, M3 membership, M4 exact ties, M5 inversion and M6 float32-tie are
      six distinct metrics with no collapsing.
- [x] Statistical claims bounded to a fixed purposive suite, with zero and non-zero outcomes
      both pre-specified.
- [x] Positive controls use harness-local synthetic fixtures only; no input, result, or
      severity judgement is imported from outside the frozen suite.
- [x] Evidence packet and verifier detect incomplete or contaminated execution.
- [x] Every design decision resolved (section 19); no open choice remains.
- [x] No experiment executed, nothing left this machine.

**Run**, when authorised: coverage 240/240 matrix rows, 120/120 matrix pairs, 24/24 preflight
rows and 12/12 preflight pairs, matching the verifier contract in 16.3; P0 provenance gate
passed; C1 to C21 all
pass; verifier passes including self-tests; no unrepaired failed `pair_id`; M1 to M4 reported
separately; M10 to M12 reported alongside so the outcome is quantitative in either direction.

---

## 18. Known limitations

These are properties of the question and the inputs, not defects in the protocol. They are
stated here and repeated in `REPORT.md` beside the figures they qualify.

**18.1 Four query vectors.** The whole study rests on 4 researcher-authored query strings.
This is the original frozen suite and must not be expanded without becoming a different
experiment. It is the binding constraint on every incidence claim, though not on M10 and M11,
which are direct measurements.

**18.2 Twelve ranking problems, not independent.** Query vectors are reused across corpora and
corpora across query forms.

**18.3 Corpora frozen at their original commits** (Django `274a1d49`, FastAPI `95f8322e`,
JCodeMunch `c78392ca`) with embeddings at the original `local_onnx` / `all-MiniLM-L6-v2`
generation. Comparability with the original packet requires this; currency does not follow from
it.

**18.4 NumPy-lane results are BLAS-dependent.** `_scores_numpy` is `self._matrix.dot(qv)` on
float32 operands; accumulation order and any internal extended precision are
implementation-defined. `numpy.show_config()`, BLAS vendor and version, thread counts (pinned
to 1) and CPU identity are recorded. Same-host repetition agreement is measured for this NumPy
build; results are **not** guaranteed bit-identical on another reviewer's machine. The Python lane
has no such dependency: `sum(x * y for x, y in zip(row, q))` has a language-defined float64
accumulation order. This is a property of the thing under test, not of the harness, and no
protocol change can remove it.

**18.5 Cache-state is expected to be null for ordering.** If it is, those extra paired
comparisons add robustness evidence and no query diversity. That is the honest expected value
of retaining the axis; it is retained because a non-null result would be important and this is
the only axis that can produce one.

**18.6 No timing or memory conclusion**, despite timing columns being recorded.

**18.7 The JCodeMunch control corpus contains private-source-derived indexed text** and remains
local. Any later publication decision must exclude it or handle it explicitly, as the original
packet's `release_coverage` did. This constrains export, not validity.

**18.8 The original packet's `execution_order` was imbalanced 2/2/1** because 5 repetitions do
not divide by 3 modes. Recorded because it qualifies the original's timing figures; this design
is balanced 60/60 and does not inherit it.

**18.9 Two byte-differing copies of the original measurements exist.** The certification
packet's `measurements.csv` (`f5045101...`) and the release-asset copy at
`<PUBLIC_EVIDENCE_ROOT>\arc4-real-embedding-certification-v1\measurements.csv`
(`b480db69...`). Verified row-for-row identical in all 79 columns except `baseline_import_root`
and `candidate_import_root`, which are path-redacted in the release copy. The design pins the
certification-packet copy as authoritative and the verifier rejects the other by hash.

**18.10 Packet integrity is locally anchored, not adversary-proof.** `MANIFEST.sha256` and the
local preregistration commit detect accidental and uncoordinated mutation. They do not prevent a
party with write access from replacing the entire packet, manifest and local Git history. No
stronger tamper-resistance claim is made.

---

## 19. Resolved design decisions

Every decision that could have been left open is closed here, with the resolution and the
reason it is the one that cannot be attacked from either side.

**19.1 Hybrid argument form: both, as separate arms.** Rather than choose between the recorded
arguments and the semantic-enabled arguments and make that choice load-bearing, both execute
(6.2). The matrix carries forms 3 and 4. Forms 5 and 6 run as an ancillary preflight contract
check at one repetition, 24 rows, cheap because the BM25 path skips the matrix decode entirely.
Its rows are never summed with the matrix and never appear in a findings table, because a path
that never calls `score_all` cannot distinguish the lanes. Benefit is that the argument choice
is settled by measurement rather than by my judgement.

**19.2 `semantic_weight` tuning override: pinned and asserted.** No `tuning.jsonc` under
`storage_path` or `~/.code-index`, absence asserted per trial, effective weight asserted equal
to the frozen value at scoring time, and recorded per row (C15). This is clean-install
production default behaviour, so nothing about the scorer changes (6.3).

**19.3 Wheel-to-commit provenance: official wheel plus normalized payload gate P0.** The
treatment artifact is the official PyPI wheel at `ff74b634...9a0488`. A clean rebuild from
`8bed872e...` did not reproduce the wheel byte hash and is retained as a failed exact-build
attempt. Before the first measured row, P0 instead requires identical member paths, zero
substantive payload differences after newline-only text normalization, and a valid internal
`RECORD` for the official wheel. The result supports payload equivalence under that declared
normalization, not a reproducible-build or supply-chain-authenticity claim (9.5).

**19.4 Timing columns: recorded, and structurally barred from claims.** Kept for
diagnosability of anomalous rows and to avoid blocking a future timing question. The verifier
fails if any timing figure appears in `SUMMARY.json` or `REPORT.md` (16.2, table row 22 of
section 5).

**19.5 Detector fixtures: harness-local synthetic only.** C18 and C19 construct their fixtures
inside this packet from literals. Nothing outside the frozen corpora and the frozen query
vectors enters this study as an input, a result, or a severity judgement (12.1).

**19.6 The `jcodemunch` control-only corpus: kept in.** Dropping it would shrink the frozen
applicable set for convenience. It is retained in the matrix and flagged as export-constrained
(18.7). Publication scope is a later, separate decision and is not gated on this design.

**19.7 Depth beyond `top_k`: from retained evidence, not new cases.** Full-depth ordering hashes
and score vectors on every matrix row give M12 first-divergence rank and M10-M11 measurements
for all 120 pairs without adding a case or touching the frozen top-k values (15.2).

**19.8 Repetitions: all 5 retained, and reclassified.** They carry no query diversity and are
never counted as cases, but they supply the within-lane determinism evidence that doubles as
the pipeline negative control (M7), which is what allows a cross-lane zero to mean anything.

---

## 20. Authorisation checklist

The provenance work listed as completed below occurred before preregistration and is retained as
part of the design lineage. The measurement campaign has not started.

| State | Item | Detail |
| --- | --- | --- |
| Completed provenance | Network | Read-only retrieval of the official PyPI wheel, remote release-tag verification, and read-only GitHub issue/comment retrieval. No push, publication, post, submission or other external mutation |
| Completed provenance | Local checkout/build | Clean detached checkout of `8bed872e...`, one exact-rebuild attempt, and member-level comparison against the official wheel. The exact hash failed and the newline-normalized payload comparison passed; both outcomes are retained |
| Completed provenance | Local writes | Official and rebuilt wheels, detached worktree, comparison outputs, journals, design revisions, and local JDocMunch/JCodeMunch indexes. These are setup and evidence artifacts, not measured study rows |
| Pending preflight | P0 | A harness-owned independent replay of the narrowed payload-equivalence and `RECORD` contract, recorded in `SOURCE-INVENTORY.json` with the comparison-tool hash |
| Pending build | Environments | Two isolated venvs from the preregistered wheelhouse and their closed canonical/raw manifests |
| Pending measurement | Disk | Trial-local database copies (peak roughly 140 MB at a time) plus an estimated 385 MB of retained full-ranking evidence (15.2) |
| Pending measurement | Runtime | Estimated 3 to 5 hours over 264 rows, dominated by the NumPy-absent lane. The estimate comes from operation counts, not a measured campaign, and pilot rows replace it |
| All stages | Write boundary | Writes stay within the packet directory, trial-local scratch, the detached scratch checkout and local tool indexes. Frozen corpus originals and the main source checkout are never written |

Issue 398 comment 5177953577 provides the governing execution boundary described in 2.1. It does
not authorize external publication or mutation.

---

## Current local state before preregistration

No measured row has executed and no outcome data exists. Local provenance work has executed and
modified only the completed surfaces enumerated in section 20. The three frozen corpus databases
were inspected with `mode=ro&immutable=1`; their SHA-256 values were confirmed unchanged
afterward, and no sidecar was created beside an original. The main JCodeMunch checkout remains
clean and is not the detached source used for P0. Network activity was limited to the three
read-only retrieval classes listed in section 20. Nothing was pushed, published, posted,
submitted, or otherwise mutated externally.
