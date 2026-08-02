# Arc 4 real-embedding certification report

## Decision

Roadmap gate: **pass <!-- claim:roadmap_verdict=pass -->**.

The local candidate preserves the current exact float64 score definition and adds only deterministic descending-score, ascending-symbol-ID ordering. It attempts a vectorized float32 cosine pass with conservative intervals, exactly rescoring the uncertain boundary set. Memory-cap refusal, missing NumPy, allocation failure, interval violation, or excessive certification breadth selects the exact fallback.

This is a research candidate, not an upstream implementation. Current main still has no official Arc 4 certified scorer or explicit symbol-ID tie break. The result supports a local draft follow-up only.

## Canonical evidence

The canonical CSV contains 360 <!-- claim:row_count=360 --> rows, 79 <!-- claim:column_count=79 --> columns, and 120 <!-- claim:pair_count=120 --> three-mode pairs. Ordered-response parity holds for 360 <!-- claim:parity_count=360 --> rows.

| Corpus | Real vectors | Opportunities | Exact-tie participants | Near ties | Genuine disagreements | Total certified | Certified breadth |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| django | 45561 <!-- claim:django_vector_count=45561 --> | 182244 <!-- claim:django_candidate_denominator=182244 --> | 57085 <!-- claim:django_exact_tie_count=57085 --> | 290 <!-- claim:django_near_tie_count=290 --> | 0 <!-- claim:django_genuine_disagreement_count=0 --> | 290 <!-- claim:django_total_certified_count=290 --> | 0.1591% <!-- claim:django_total_certified_fraction=0.1591% --> |
| fastapi | 13405 <!-- claim:fastapi_vector_count=13405 --> | 53620 <!-- claim:fastapi_candidate_denominator=53620 --> | 25944 <!-- claim:fastapi_exact_tie_count=25944 --> | 97 <!-- claim:fastapi_near_tie_count=97 --> | 0 <!-- claim:fastapi_genuine_disagreement_count=0 --> | 97 <!-- claim:fastapi_total_certified_count=97 --> | 0.1809% <!-- claim:fastapi_total_certified_fraction=0.1809% --> |
| jcodemunch | 13960 <!-- claim:jcodemunch_vector_count=13960 --> | 55840 <!-- claim:jcodemunch_candidate_denominator=55840 --> | 7669 <!-- claim:jcodemunch_exact_tie_count=7669 --> | 150 <!-- claim:jcodemunch_near_tie_count=150 --> | 0 <!-- claim:jcodemunch_genuine_disagreement_count=0 --> | 150 <!-- claim:jcodemunch_total_certified_count=150 --> | 0.2686% <!-- claim:jcodemunch_total_certified_fraction=0.2686% --> |

Django is authoritative. Its aggregate certified breadth is below the roadmap pass threshold of 10.0000% <!-- claim:django_pass_threshold=10.0000% -->, and its genuine-disagreement fraction is below the fail threshold of 0.5000% <!-- claim:genuine_fail_threshold=0.5000% -->. FastAPI is a required transfer point. JCodeMunch is a control only and is not used as authority.

## Per-call breadth distribution

| Corpus | Minimum | Median | p95 | Maximum | Pass-band calls | Design-band calls | Fail-band calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| django | 0.0900% <!-- claim:django_per_call_minimum=0.0900% --> | 0.1547% <!-- claim:django_per_call_median=0.1547% --> | 0.2298% <!-- claim:django_per_call_p95=0.2298% --> | 0.2370% <!-- claim:django_per_call_maximum=0.2370% --> | 4 <!-- claim:django_pass_band_calls=4 --> | 0 <!-- claim:django_design_band_calls=0 --> | 0 <!-- claim:django_fail_band_calls=0 --> |
| fastapi | 0.1194% <!-- claim:fastapi_per_call_minimum=0.1194% --> | 0.1790% <!-- claim:fastapi_per_call_median=0.1790% --> | 0.2383% <!-- claim:fastapi_per_call_p95=0.2383% --> | 0.2462% <!-- claim:fastapi_per_call_maximum=0.2462% --> | 4 <!-- claim:fastapi_pass_band_calls=4 --> | 0 <!-- claim:fastapi_design_band_calls=0 --> | 0 <!-- claim:fastapi_fail_band_calls=0 --> |
| jcodemunch | 0.1934% <!-- claim:jcodemunch_per_call_minimum=0.1934% --> | 0.2650% <!-- claim:jcodemunch_per_call_median=0.2650% --> | 0.3413% <!-- claim:jcodemunch_per_call_p95=0.3413% --> | 0.3510% <!-- claim:jcodemunch_per_call_maximum=0.3510% --> | 4 <!-- claim:jcodemunch_pass_band_calls=4 --> | 0 <!-- claim:jcodemunch_design_band_calls=0 --> | 0 <!-- claim:jcodemunch_fail_band_calls=0 --> |

The pass/design/fail breadth thresholds are 10.0000% <!-- claim:django_pass_threshold=10.0000% --> and 25.0000% <!-- claim:django_design_threshold=25.0000% -->. Exact ties are excluded before these bands are applied.

## Scoring performance

| Corpus | State | Exact baseline median | Float32 candidate median | Forced exact fallback median | Candidate speedup |
| --- | --- | ---: | ---: | ---: | ---: |
| django | cold_fresh_process | 1363.010 ms <!-- claim:django_cold_fresh_process_exact_tiebreak_baseline_median_ms=1363.010 ms --> | 45.260 ms <!-- claim:django_cold_fresh_process_float32_certified_candidate_median_ms=45.260 ms --> | 1361.100 ms <!-- claim:django_cold_fresh_process_bounded_exact_fallback_median_ms=1361.100 ms --> | 30.11x <!-- claim:django_cold_fresh_process_speedup=30.11x --> |
| django | generation_warm | 1379.218 ms <!-- claim:django_generation_warm_exact_tiebreak_baseline_median_ms=1379.218 ms --> | 45.144 ms <!-- claim:django_generation_warm_float32_certified_candidate_median_ms=45.144 ms --> | 1386.105 ms <!-- claim:django_generation_warm_bounded_exact_fallback_median_ms=1386.105 ms --> | 30.55x <!-- claim:django_generation_warm_speedup=30.55x --> |
| fastapi | cold_fresh_process | 396.905 ms <!-- claim:fastapi_cold_fresh_process_exact_tiebreak_baseline_median_ms=396.905 ms --> | 12.584 ms <!-- claim:fastapi_cold_fresh_process_float32_certified_candidate_median_ms=12.584 ms --> | 397.771 ms <!-- claim:fastapi_cold_fresh_process_bounded_exact_fallback_median_ms=397.771 ms --> | 31.54x <!-- claim:fastapi_cold_fresh_process_speedup=31.54x --> |
| fastapi | generation_warm | 396.693 ms <!-- claim:fastapi_generation_warm_exact_tiebreak_baseline_median_ms=396.693 ms --> | 10.451 ms <!-- claim:fastapi_generation_warm_float32_certified_candidate_median_ms=10.451 ms --> | 400.541 ms <!-- claim:fastapi_generation_warm_bounded_exact_fallback_median_ms=400.541 ms --> | 37.96x <!-- claim:fastapi_generation_warm_speedup=37.96x --> |
| jcodemunch | cold_fresh_process | 416.508 ms <!-- claim:jcodemunch_cold_fresh_process_exact_tiebreak_baseline_median_ms=416.508 ms --> | 13.742 ms <!-- claim:jcodemunch_cold_fresh_process_float32_certified_candidate_median_ms=13.742 ms --> | 417.639 ms <!-- claim:jcodemunch_cold_fresh_process_bounded_exact_fallback_median_ms=417.639 ms --> | 30.31x <!-- claim:jcodemunch_cold_fresh_process_speedup=30.31x --> |
| jcodemunch | generation_warm | 416.363 ms <!-- claim:jcodemunch_generation_warm_exact_tiebreak_baseline_median_ms=416.363 ms --> | 11.365 ms <!-- claim:jcodemunch_generation_warm_float32_certified_candidate_median_ms=11.365 ms --> | 415.809 ms <!-- claim:jcodemunch_generation_warm_bounded_exact_fallback_median_ms=415.809 ms --> | 36.64x <!-- claim:jcodemunch_generation_warm_speedup=36.64x --> |

The roadmap asks the warm path to retain roughly 5.00x <!-- claim:warm_speed_rationale=5.00x --> rationale. The Django generation-warm scorer exceeds that mark. Cold end-to-end wall time and generation-warm state remain separate columns in the CSV; the table compares scorer time only.

## Method and provenance

- The query suite was frozen before any real-embedding result was inspected. It contains 4 <!-- claim:query_count=4 --> queries across 3 <!-- claim:corpus_count=3 --> corpora.
- The authoritative run used 5 <!-- claim:repetitions=5 --> repetitions with rotated mode order.
- After measurement, consolidation was hardened to serialize count fractions as exact decimals after the verifier rejected binary-float strings. The retained scoring and timing fragments were unchanged. The manifest records separate measured and final packet harness identities.
- Real 384 <!-- claim:embedding_dimension=384 -->-dimensional normalized float32 embeddings were generated locally with `local_onnx` and `all-MiniLM-L6-v2 <!-- claim:embedding_model=all-MiniLM-L6-v2 -->`. Source databases were copied with SQLite backup before embedding.
- The measured source was clean JCodeMunch 1.108.212 <!-- claim:measured_version=1.108.212 --> at `c78392cac0d50570d5cf86558d8d3674c0bea068 <!-- claim:measured_source_sha=c78392cac0d50570d5cf86558d8d3674c0bea068 -->`. A last-minute upstream recheck found 1.108.213 <!-- claim:current_version=1.108.213 --> and main `16e66052fb0f8ed5b0ba6e3ebfae7a4e98bc9dde <!-- claim:current_source_sha=16e66052fb0f8ed5b0ba6e3ebfae7a4e98bc9dde -->`; only counter, version, documentation, benchmark metadata, and related tests changed. Semantic search, embedding, scoring, and Arc 4 roadmap blob `68e5c627be61884bb17000eafccf5d802010c68e <!-- claim:roadmap_blob_sha=68e5c627be61884bb17000eafccf5d802010c68e -->` were unchanged.
- Django commit: `274a1d494d11d87a1b767340d1f398f197810f93 <!-- claim:django_corpus_commit=274a1d494d11d87a1b767340d1f398f197810f93 -->`. FastAPI commit: `95f8322ee1dcda7ceace7b1c4f6c9915b36d748f <!-- claim:fastapi_corpus_commit=95f8322ee1dcda7ceace7b1c4f6c9915b36d748f -->`.

## Validation and limitations

The no-dependency verifier checks the fixed schema, row identities, complete cell matrix, five-repetition coverage, order balance, response parity, bucket reconciliation, exact fractions, public artifact hashes, claim markers, release manifest, and a deliberate tamper self-test. JDataMunch independently validated the canonical source file and reproduced the gate metrics.

Limitations: the frozen suite is intentionally small; it establishes the roadmap gate on named public corpora, not universal ranking quality. The conservative interval is a mathematical safety envelope, not an empirically minimized error model. Timing reflects this Windows host and local storage. The Windows process CPU clock quantized some shortest candidate cells to zero; these are valid non-negative measurements below its resolution, while wall and scorer clocks remain positive. Because upstream has not selected an official Arc 4 implementation, adoption remains provisional even though the evidence verdict is pass.

The evidence repository and its Arc 4 GitHub release are published. The focused
upstream follow-up issue remains a local draft outside the public evidence tree and
has not been submitted. No upstream issue comment, pull request, or issue submission
was made as part of this evidence publication.
