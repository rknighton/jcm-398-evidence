# Column reference

The source-run CSVs use several experiment-specific schemas, at 18, 23, 33 and 34
columns. The unified master CSV normalizes them into one fixed 57-column schema. Do not
assume a single header when writing an importer: `INDEX.json` carries the exact column
count, provenance column, row grain, modes, repos, and hashes for every file, and the
columns below are the union rather than a guaranteed-present set.

## Identity: which run is this row

| Column | Meaning |
| --- | --- |
| `repo` | Upstream repository, for example `django/django`. |
| `repo_name` | Local jcodemunch index name. The hash suffix is derived from the indexed path, so it will differ on your machine. |
| `repo_git_head` | Commit of the indexed corpus. Pinned values are in `INDEX.json` under `corpora`. |
| `case` | Named scenario within a run. |
| `tool` | The jcodemunch tool being called. |
| `target_value` | The exact arguments passed, as JSON. Recorded verbatim, so for the handful of tools that take a `project_path` this includes the absolute corpus path on the machine that ran the benchmark. Left as measured rather than rewritten, because these rows are content-addressed and editing an input after the fact would make the hashes in `INDEX.json` attest to something that was never executed. |
| `repetition` | 1-based repeat counter. **Check this before treating rows as independent cases.** |
| `order_position` | Position within the A/B pair, for order balancing. |

## Mode: which side of the A/B

`mode` names the implementation under test. Pair a `baseline_*` row with the
`candidate`/`generation_safe_hybrid` row that shares `repo_name`, `tool`, `case`, and
`repetition`.

| Value | Meaning |
| --- | --- |
| `baseline_full` | Unmodified jcodemunch at `c2201a55`, full hydration. |
| `generation_safe_hybrid` | Candidate prototype. |
| `baseline_full_warm_probe` / `generation_safe_hybrid_warm_probe` | Same pair, warm-cache probe. |
| `generation_unsafe_global_*` | A rejected variant, retained so the rejection is auditable. Not a candidate. |

## Timing and memory

| Column | Meaning |
| --- | --- |
| `wall_ms` | End-to-end wall time for the tool call. **This is the timing column to use.** |
| `load_phase_ms` | Time inside index loading specifically. |
| `load_phase_pct` | `load_phase_ms` as a percentage of `wall_ms`. Shows how much of a call is hydration. |
| `load_calls` | Number of index-load calls the request made. |
| `rss_before_bytes` / `rss_after_bytes` / `peak_rss_bytes` | Real process RSS, not tracemalloc. |
| `response_bytes` | Serialized response size. |

## Correctness

| Column | Meaning |
| --- | --- |
| `canonical_response_hash` | SHA-256 of the response after removing documented volatile fields (timings, cumulative counters). **Baseline and candidate hashes must match; that is the parity claim.** |
| `symbol_dict_equal` / `source_equal` | Structural equality checks where applicable. |
| `parity_debug_json` | Per-row diagnostic blob. Also carries `runtime_distribution_version` and cache/WAL observations. |

## Provenance

| Column | Meaning |
| --- | --- |
| `jcodemunch_source_sha` | **Authoritative code identity.** Filter on this before aggregating. The 18-column boundary run carries the same value under `source_sha` instead, so an importer must accept both names. `INDEX.json` records which column each file uses. |
| `jcodemunch_version` | Ambient installed distribution string. `1.108.199` here even though the source is `c2201a55` (v1.108.207); stale metadata, not a revision mismatch. |
| `benchmark_sha256` | Hash of the harness file that produced the row. |
| `source_diff_sha256` | Hash of the working-tree diff. `e3b0c442...` is the SHA-256 of the empty string, meaning a clean tree. Baseline rows carry it; a dirty baseline is therefore detectable rather than assumed. |
| `source_dirty_paths` | Which files differed, for candidate rows. |
| `source_root_basename` | Which worktree produced the row. |

## Recomputing the published figures

`verify.py` does all of this and prints claimed against recomputed. The two recipes
worth knowing by hand:

**Aggregate throughput** is summed baseline wall time over summed candidate wall time.
It is not the mean of per-case ratios, and on the 38-case Django suite the two differ a
lot: 3.22x aggregate against a 1.23x median, because two tools carry 62.5% of the
baseline time.

**Per-case separation** needs `repetition`. Group by `repo_name` + `tool` + `case`,
compare the median of baseline repetitions to the median of candidate repetitions, and
treat a case as resolved only when the two ranges do not overlap. On calls of a few
milliseconds, individual repetition pairs swing far enough to invert the ordering, so a
single pair is not evidence of a regression.
