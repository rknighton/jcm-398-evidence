# Data dictionary

Row grain: one requested scoring mode for one corpus, frozen query, cache state, and repetition. The authoritative file contains five repetitions of every cell. `pair_id` joins the three modes for the same logical call and repetition.

Certification denominator: `candidate_count` per logical call. Aggregate corpus fractions use one generation-warm candidate row per frozen query at repetition 1, so repeated timing observations do not multiply the classification denominator. Exact equal-score participants are reported separately and excluded from certified breadth. The three certified buckets are disjoint and must sum to `total_certified_count`.

Nullability: only `superseded_run_id`, `supersession_reason`, and `fallback_reason` may be blank. `fallback_reason` is blank unless a fallback is selected.

| Column | Type/unit | Definition |
| --- | --- | --- |
| `schema_version` | text | Fixed CSV contract identifier. |
| `row_id` | text | Deterministic unique identity for this measurement row. |
| `run_id` | text | Identity of the screen or authoritative controller run. |
| `row_status` | text | Retention state. Canonical rows must be retained. |
| `superseded_run_id` | text or blank | Prior run identity when a row is superseded. Blank in this packet. |
| `supersession_reason` | text or blank | Reason for supersession. Blank in this packet. |
| `case_id` | text | Corpus, query, and cache-state logical case identity. |
| `pair_id` | text | Case plus repetition identity shared by the three modes. |
| `repetition` | integer | One-based authoritative repetition number. |
| `execution_order` | integer | One-based position of a mode within its rotated three-mode block. |
| `mode` | text | Requested exact baseline, float32 candidate, or forced exact fallback mode. |
| `corpus` | text | Short corpus name. |
| `corpus_role` | text | Authoritative, required second point, or control-only role. |
| `public_repo` | text | Public owner/repository identity of the corpus. |
| `corpus_commit` | text | Exact corpus Git commit pinned for the run. |
| `source_repo_id` | text | Canonical JCodeMunch index identity used as the source. |
| `source_database_sha256` | SHA-256 | Hash of the unmodified source index database. |
| `working_database_sha256` | SHA-256 | Hash of the isolated real-embedding database copy. |
| `index_generation` | timestamp | Recorded source index generation timestamp. |
| `query_id` | text | Frozen query-suite identity. |
| `query_kind` | text | Semantic-only or hybrid query class. |
| `tie_heavy_query` | boolean text | Whether the query was predeclared as tie-heavy. |
| `serialized_args_json` | JSON text | Verbatim canonical public query arguments. |
| `top_k` | integer | Requested result count. |
| `semantic_weight` | float | Semantic channel weight in the combined score. |
| `cache_state` | text | Fresh-process cold or generation-warm measurement state. |
| `cold_warm_state` | text | Explicit duplicate of the cache-state contract for auditability. |
| `lane_selected` | text | Scoring lane actually executed after safety checks. |
| `fallback_reason` | text or blank | Exact reason for fallback. Blank when no fallback occurred. |
| `candidate_count` | integer | Number of scored symbols in the corpus. |
| `result_count` | integer | Number of ordered result IDs returned. |
| `result_boundary_score` | float64 | Exact baseline combined score at the top-k boundary. |
| `exact_tie_count` | integer | Candidates participating in exact equal-score groups. Excluded from certification breadth. |
| `near_tie_count` | integer | Certified uncertain candidates without an exact tie or genuine top-k disagreement. |
| `genuine_disagreement_count` | integer | Certified participants in a float32-versus-exact top-k membership disagreement after exact ties are excluded. |
| `other_certified_count` | integer | Certified candidates caused by interval violations or a fail-closed fallback, excluding other buckets. |
| `total_certified_count` | integer | Disjoint union of near-tie, genuine-disagreement, and other-certified candidates. |
| `exact_tie_fraction` | float | The matching count divided by candidate_count for this row. |
| `near_tie_fraction` | float | The matching count divided by candidate_count for this row. |
| `genuine_disagreement_fraction` | float | The matching count divided by candidate_count for this row. |
| `total_certified_fraction` | float | The matching count divided by candidate_count for this row. |
| `interval_violation_count` | integer | Exact cosine scores outside the conservative float32 interval. |
| `wall_ns` | integer nanoseconds | End-to-end worker wall time for the declared cache state. |
| `scoring_ns` | integer nanoseconds | Wall time for the selected scoring lane only. |
| `process_cpu_ns` | integer nanoseconds | Process CPU time consumed during the measured worker interval. |
| `rss_before_bytes` | integer bytes | Resident memory immediately before the measured interval. |
| `rss_after_bytes` | integer bytes | Resident memory immediately after the measured interval. |
| `peak_rss_bytes` | integer bytes | Highest polled resident memory during the measured interval. |
| `baseline_response_hash` | SHA-256 | Hash of exact deterministic ordered result IDs. |
| `candidate_response_hash` | SHA-256 | Hash of selected-lane ordered result IDs. |
| `canonical_parity` | boolean text | Whether ordered selected IDs exactly match the deterministic baseline. |
| `ordered_result_id_hash` | SHA-256 | Independent hash of the selected ordered result-ID list. |
| `baseline_version` | text | Recorded baseline package version. |
| `baseline_source_sha` | Git SHA | Recorded baseline source commit. |
| `baseline_diff_sha256` | SHA-256 | Hash of the baseline uncommitted diff. |
| `baseline_dirty_paths_json` | JSON text | Dirty path list for the baseline source tree. |
| `baseline_import_root` | path | Resolved Python import root for the baseline implementation. |
| `candidate_version` | text | Recorded candidate package version. |
| `candidate_source_sha` | Git SHA | Recorded candidate source commit. |
| `candidate_diff_sha256` | SHA-256 | Hash of the candidate uncommitted diff. |
| `candidate_dirty_paths_json` | JSON text | Dirty path list for the candidate source tree. |
| `candidate_import_root` | path | Resolved Python import root for the candidate implementation. |
| `candidate_classification` | text | Authority status of the tested candidate. This packet uses a local minimal candidate. |
| `harness_sha256` | SHA-256 | Combined identity of harness source files. |
| `config_sha256` | SHA-256 | Canonical identity of research_config.json. |
| `python_version` | text | Recorded python package version. |
| `numpy_version` | text | Recorded numpy package version. |
| `sqlite_version` | text | Recorded sqlite package version. |
| `platform` | text | Recorded execution platform. |
| `cpu_identity` | text | Recorded execution cpu identity. |
| `total_memory_bytes` | integer bytes | Host physical memory reported to the worker. |
| `embedding_provider` | text | Embedding provider identity. |
| `embedding_model` | text | Embedding model identity. |
| `embedding_dimension` | integer | Embedding vector dimension. |
| `embedding_vector_count` | integer | Real vectors aligned to corpus symbols. |
| `embedding_normalization` | text | Declared embedding normalization contract. |
| `embedding_generation_identity` | SHA-256 | Content identity over ordered symbol IDs and stored vectors. |
| `query_embedding_sha256` | SHA-256 | Identity of the frozen real query vector. |
| `diagnostic_json` | JSON text | Bounded diagnostic counts and result IDs retained for audit. |
