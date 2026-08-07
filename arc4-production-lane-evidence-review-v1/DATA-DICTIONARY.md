# Data dictionary

This package combines several experiments with different record formats. This dictionary explains the main review surfaces, their record grain, and the terms used in the report. The original experiment documentation beside each dataset remains authoritative for fields not summarized here.

## Shared terms

| Term | Plain-language meaning |
| --- | --- |
| Rank 0 | The first returned result. |
| Top k | The ordered set of results the caller asked to receive. The depth differs by surface and is never assumed: comparison-v2 returned 25 results for two query forms and 10 for the other two; the adversarial replays and the full-suite replay record the first 100. |
| Ordered top-k match | Both methods returned the same result IDs in the same order. |
| Top-k membership match | Both methods returned the same result IDs, even if their order differed. |
| Full-depth ranking | In comparison-v2, the ordering of every candidate whose score is greater than zero, sorted by descending score then ascending symbol ID. Candidates scoring zero or below are excluded by the metric definition in `harness/metrics.py`, and the on-disk schema is named `arc4.positive-ranking/v1` for that reason. Recomputing from `packet/raw/full-rankings/`, which stores every candidate including negatives, gives a different and larger divergence count. |
| First changed position | The first list position where the two methods returned different IDs. This package uses one-based positions everywhere except comparison-v2's `m12` histogram, whose keys are zero-based: `m12` key 1555 is the same place as one-based position 1,556. |
| Exact tie | Two or more candidates received exactly the same score within one method. |
| Screen nomination | A query selected by a preliminary numerical filter for complete two-method replay. It is not itself a confirmed ranking change. |
| Screen rejection | A query not selected by that filter. It is not a confirmed negative because the filter's miss rate was not measured. |
| Ranking problem | One unique corpus and query-form comparison. Repetitions of the same problem test stability, not breadth. |
| Provider-reachable | Generated text was converted to a vector through the same provider route used by the tested software. This makes the query mechanically plausible, not representative of production traffic. |

## Adversarial falsification data

### `artifacts/queries/provider-text.jsonl`

Record grain: one mechanically generated text query. There are 5,000 records.

| Field | Type | Meaning |
| --- | --- | --- |
| `query_id` | text | Stable identity for the generated query. |
| `corpus_seed` | text | Corpus family used to construct the query. |
| `symbol_id` | text | Source symbol used as a generation seed. |
| `text` | text | Generated query text sent through the embedding provider. |
| `vector` | float array | Provider-produced query vector used by the screen. |
| `vector_sha256` | SHA-256 | Content identity for the vector. |

### `artifacts/screens/provider-text-screen.json`

Record grain: one screen run over the 5,000 generated queries.

| Field | Type | Meaning |
| --- | --- | --- |
| `status` | text | Explicitly labels the artifact as screening, not proof. |
| `coverage` | object | Query counts and quota coverage. |
| `hits` | array | The 33 queries nominated for complete replay. |
| `closest_rank0_margins` | array | Diagnostic list of the smallest observed rank-0 margins. |
| `top_k_boundaries` | array | Diagnostic values near returned-result boundaries. |

The 4,967 queries outside `hits` were screen rejections. They must not be counted as complete two-method negative results.

### `artifacts/findings/provider-actual-findings.json`

Record grain: one query whose complete replay through the actual NumPy and pure-Python methods confirmed an ordering difference. There are five records.

| Field | Type | Meaning |
| --- | --- | --- |
| `query_id` | text | Identity joining the finding to the generated query. |
| `query_text` | text | Text used for the replay. |
| `corpus` | text | Indexed code corpus used for scoring. |
| `dimensions` | object | Per-boundary comparison outcomes, keyed by top-k boundary (`1`, `5`, `10`, `25`, `50`, `100`), each holding `rank0`, `ordered` and `membership` booleans. It is not the embedding width, which is 384 for every record here. |
| `numpy` | object | NumPy-lane metadata, ordered top 100, and exact score encodings. |
| `python` | object | Pure-Python-lane metadata, ordered top 100, and exact score encodings. |

The first changed positions are 38, 65, 65, 76, and 78. All five retain the same first result, first 25 ordered results, and top-100 membership.

### `artifacts/queries/geometric.jsonl`

Record grain: one deliberately sensitive numerical boundary case.

| Field | Type | Meaning |
| --- | --- | --- |
| `case_id` | text | Stable case identity. |
| `family` | text | Construction family used for the case. |
| `query` | float array | Synthetic query vector. |
| `candidates` | array | Synthetic candidate IDs and vectors for the ranking test. |

These cases were constructed to expose numerical sensitivity. They are not estimates of normal-user frequency.

### Other adversarial artifacts

| Path | Meaning |
| --- | --- |
| `artifacts/attempts/` | Failed, superseded, and diagnostic attempts. They preserve the research trail but do not support positive claims unless another document explicitly says so. |
| `artifacts/JOURNAL.jsonl` | Chronological machine-readable research journal. One record is one recorded event. |
| `artifacts/summary.json` | Compact experiment counts used by the package verifier. |
| `artifacts/coverage.json` | Coverage accounting. |
| `artifacts/provenance.json` | Source, environment, and execution provenance. |

## Complete replay data

### `evidence/full-suite-replay/raw/{lane}-{corpus}.jsonl`

The first line is a header record describing the run: lane, corpus, the corpus SHA-256 actually read, candidate count, embedding width, the count of rows skipped for mismatched width, whether the vectorised path was taken, the NumPy and Python versions, and the installed package version. Every later line is one query.

| Field | Type | Meaning |
| --- | --- | --- |
| `query_id` | text | Joins to `provider-text.jsonl`. |
| `vector_sha256` | SHA-256 | The query vector actually used, so both lanes can be proved to have scored the same input. |
| `ordered_top_100` | text array | The first 100 symbol IDs, descending score then ascending symbol ID. |
| `score_hex` | object | Exact hexadecimal float encoding for each of those 100, so ties and inversions can be checked rather than inferred. |
| `full_ordering_sha256` | SHA-256 | Digest over every candidate ID in ranked order. Unlike comparison-v2's similarly named field, this covers IDs only and no scores, so comparing it between lanes does test whether the complete orderings match. |

### `evidence/full-suite-replay/raw/deep-{lane}-{corpus}.jsonl`

One record per query needing full-depth classification, holding `scores_hex` for every candidate. Present only for the 29 queries whose first swap involves a symbol outside the other lane's top 100.

### `evidence/full-suite-replay/raw/disagreements.jsonl`

One record per query whose lanes disagreed anywhere in the top 100. `first_swap_classification` is one of `python_exact_tie_separated_by_numpy`, `numpy_exact_tie_separated_by_python`, or `genuine_score_order_inversion`. The comparison exits non-zero rather than emitting any other value.

## Comparison v1 data

### `artifacts/comparisons.jsonl`

Record grain: one precursor corpus/query comparison. There are 12 records.

Important objects are `rank_0`, `ordered_top_k`, `membership`, `exact_ties`, and `numeric_diagnostics`. Each records a different comparison property. The raw files under `artifacts/raw/` and controls under `artifacts/controls/` support those compact rows. V1 is supplemental because the later v2 packet is the authoritative official-package comparison.

## Comparison v2 data

### `packet/raw/rows.jsonl`

Record grain: one measured lane execution for one ranking problem, cache state, and repetition. The two `arm` values form a paired comparison. `pair_id` joins those two lane rows. `problem_id` groups repetitions of the same ranking problem.

The most important fields for review are:

| Field | Type/unit | Meaning |
| --- | --- | --- |
| `row_id` | text | Unique measurement-row identity. |
| `problem_id` | text | Identity of the underlying ranking problem. |
| `pair_id` | text | Identity shared by the two compared lane executions. |
| `arm` | text | Which part of the study the row belongs to, `matrix` or `preflight`. The 240 matrix rows over 12 problems carry the findings; the 24 preflight rows over 6 verbatim-form problems are a contract check and are excluded from every findings denominator, which is why `rows.jsonl` holds 18 distinct `problem_id` values while the headline count is 12. The lane is in `lane`, not here. |
| `lane` | text | Scoring lane actually observed. |
| `corpus` | text | Indexed corpus identity. |
| `query_id` | text | Frozen query identity. |
| `cache_state` | text | Declared cache condition. |
| `repetition` | integer | Repeated execution number for the same problem. |
| `candidate_count` | integer | Number of scored candidates. |
| `public_result_ids` | text array | Ordered IDs returned to the caller. |
| `full_depth_ordering_sha256` | SHA-256 | Identity of the positive-score ordering **and every candidate's exact score**. Because scores always differ slightly between lanes, this digest differs for all 120 matrix pairs. It cannot be used to test whether the orderings match; `m12` in `packet/SUMMARY.json` reports that, and finds 100 of 120. |
| `full_ranking_evidence` | object | Reference and integrity metadata for full-depth ranking files. |
| `wall_ns` | integer nanoseconds | Observed end-to-end wall time. It is retained as raw evidence but is not quoted in this report. |
| `process_cpu_ns` | integer nanoseconds | Observed process CPU time. It is retained as raw evidence but is not quoted in this report. |
| `controls` | object | Per-row control results. |

### Remaining v2 surfaces

| Path | Meaning |
| --- | --- |
| `packet/raw/full-rankings/` | Complete per-candidate score vectors in candidate order, not ranked order; the ranking is obtained by sorting. There are 360 files holding 36 distinct contents, because each of the 10 repetitions of a problem produced byte-identical output. |
| `packet/raw/warmups.jsonl` | One warmup record per paired execution. |
| `packet/invocations/` | Captured invocation records supporting execution provenance. |
| `packet/controls/` | Independent control outputs. |
| `packet/SUMMARY.json` | Authoritative compact comparison counts and the explicit descriptive-only claim ceiling. |
| `packet/paired.jsonl.gz` | Deterministic gzip representation of the single oversized paired JSONL file. It is not a bundle of files. |
| `packet/paired.jsonl.gz.json` | Original and compressed sizes, hashes, and original line count used to verify lossless reconstruction. |

## Integrity and authority

`CHECKSUMS.sha256` covers the public package. `SOURCE-HASHES.sha256` records the frozen source identities before publication normalization. `PROVENANCE-ANNOTATION.md` explains which files are exact copies, which received publication-only normalization, and why the one oversized JSONL file is stored as gzip.

For decision claims, use this order: `REPORT.md`, `CLAIM-LEDGER.csv`, `SOURCE-MAP.md`, then the experiment-specific reports and raw artifacts. Raw measurements outrank a narrative if a conflict is ever found. The package verifier independently recomputes the headline counts and fails on disagreement.
