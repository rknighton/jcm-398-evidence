"""Shared contracts and scoring logic for the Arc 4 certification harness."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = "arc4-real-embedding-certification-v1"
FLOAT32_UNIT_ROUNDOFF = 2.0**-24

CSV_COLUMNS = (
    "schema_version",
    "row_id",
    "run_id",
    "row_status",
    "superseded_run_id",
    "supersession_reason",
    "case_id",
    "pair_id",
    "repetition",
    "execution_order",
    "mode",
    "corpus",
    "corpus_role",
    "public_repo",
    "corpus_commit",
    "source_repo_id",
    "source_database_sha256",
    "working_database_sha256",
    "index_generation",
    "query_id",
    "query_kind",
    "tie_heavy_query",
    "serialized_args_json",
    "top_k",
    "semantic_weight",
    "cache_state",
    "cold_warm_state",
    "lane_selected",
    "fallback_reason",
    "candidate_count",
    "result_count",
    "result_boundary_score",
    "exact_tie_count",
    "near_tie_count",
    "genuine_disagreement_count",
    "other_certified_count",
    "total_certified_count",
    "exact_tie_fraction",
    "near_tie_fraction",
    "genuine_disagreement_fraction",
    "total_certified_fraction",
    "interval_violation_count",
    "wall_ns",
    "scoring_ns",
    "process_cpu_ns",
    "rss_before_bytes",
    "rss_after_bytes",
    "peak_rss_bytes",
    "baseline_response_hash",
    "candidate_response_hash",
    "canonical_parity",
    "ordered_result_id_hash",
    "baseline_version",
    "baseline_source_sha",
    "baseline_diff_sha256",
    "baseline_dirty_paths_json",
    "baseline_import_root",
    "candidate_version",
    "candidate_source_sha",
    "candidate_diff_sha256",
    "candidate_dirty_paths_json",
    "candidate_import_root",
    "candidate_classification",
    "harness_sha256",
    "config_sha256",
    "python_version",
    "numpy_version",
    "sqlite_version",
    "platform",
    "cpu_identity",
    "total_memory_bytes",
    "embedding_provider",
    "embedding_model",
    "embedding_dimension",
    "embedding_vector_count",
    "embedding_normalization",
    "embedding_generation_identity",
    "query_embedding_sha256",
    "diagnostic_json",
)


def canonical_json(value: Any) -> str:
    """Return deterministic compact JSON without lossy value rewriting."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def config_identity(path: Path) -> str:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    return sha256_bytes(canonical_json(parsed).encode("utf-8"))


def exact_cosine(query: Sequence[float], candidate: Sequence[float]) -> float:
    """Match the current pure-Python cosine operation order exactly."""
    if len(query) == 0 or len(candidate) == 0 or len(query) != len(candidate):
        return 0.0
    dot = sum(x * y for x, y in zip(query, candidate))
    norm_query = math.sqrt(sum(x * x for x in query))
    norm_candidate = math.sqrt(sum(y * y for y in candidate))
    if norm_query == 0.0 or norm_candidate == 0.0:
        return 0.0
    return dot / (norm_query * norm_candidate)


def deterministic_top(
    scores: Sequence[float], symbol_ids: Sequence[str], top_k: int
) -> list[int]:
    """Rank by descending score then ascending symbol ID."""
    ordered = sorted(
        range(len(scores)),
        key=lambda index: (-float(scores[index]), symbol_ids[index]),
    )
    return [index for index in ordered if float(scores[index]) > 0.0][:top_k]


def insertion_order_top(scores: Sequence[float], top_k: int) -> list[int]:
    """Historical stable-score ordering, retained only for non-vacuity tests."""
    ordered = sorted(range(len(scores)), key=lambda index: float(scores[index]), reverse=True)
    return [index for index in ordered if float(scores[index]) > 0.0][:top_k]


def tie_participants(scores: Sequence[float]) -> set[int]:
    groups: dict[float, list[int]] = {}
    for index, score in enumerate(scores):
        groups.setdefault(float(score), []).append(index)
    return {
        index
        for members in groups.values()
        if len(members) > 1
        for index in members
    }


def disagreement_participants(exact_top: Sequence[int], approximate_top: Sequence[int]) -> set[int]:
    """Return members whose result-boundary membership or ordered rank differs."""
    exact_rank = {index: rank for rank, index in enumerate(exact_top)}
    approximate_rank = {index: rank for rank, index in enumerate(approximate_top)}
    members = set(exact_rank) | set(approximate_rank)
    return {
        index
        for index in members
        if exact_rank.get(index) != approximate_rank.get(index)
    }


def float32_scores_and_bounds(matrix: Any, query: Sequence[float]) -> tuple[Any, Any, Any]:
    """Compute float32 cosine estimates and conservative float64 reference bounds."""
    import numpy as np

    matrix32 = np.asarray(matrix, dtype=np.float32)
    query32 = np.asarray(query, dtype=np.float32)
    if matrix32.ndim != 2 or query32.ndim != 1 or matrix32.shape[1] != len(query32):
        raise ValueError("matrix and query dimensions do not match")
    if not np.all(np.isfinite(matrix32)) or not np.all(np.isfinite(query32)):
        raise ValueError("non-finite embedding value")

    dot32 = matrix32 @ query32
    candidate_norm32 = np.sqrt(np.sum(matrix32 * matrix32, axis=1, dtype=np.float32))
    query_norm32 = float(np.sqrt(np.sum(query32 * query32, dtype=np.float32)))
    denominator32 = candidate_norm32 * query_norm32
    estimates = np.zeros(len(matrix32), dtype=np.float32)
    nonzero = denominator32 > 0.0
    estimates[nonzero] = dot32[nonzero] / denominator32[nonzero]

    dimension = int(matrix32.shape[1])
    operations = 2 * dimension + 16
    gamma = (operations * FLOAT32_UNIT_ROUNDOFF) / (
        1.0 - operations * FLOAT32_UNIT_ROUNDOFF
    )
    # Cauchy-Schwarz bounds sum(abs(a_i * b_i)) / (||a|| * ||b||) by one.
    # Keeping that bound symbolic avoids a float64 copy of the corpus matrix and
    # the two full-matrix temporaries that such a copy would create.
    valid = nonzero
    error = gamma * (5.0 + np.abs(estimates.astype(np.float64)))
    error += 32.0 * np.finfo(np.float32).eps
    lower = estimates.astype(np.float64) - error
    upper = estimates.astype(np.float64) + error
    lower[~valid] = 0.0
    upper[~valid] = 0.0
    return estimates.astype(np.float64), lower, upper


def execute_mode(
    *,
    matrix: Any,
    query: Sequence[float],
    symbol_ids: Sequence[str],
    lexical_base: Sequence[float],
    semantic_weight: float,
    top_k: int,
    mode: str,
    max_rescore_fraction: float,
    matrix_max_bytes: int = 256 * 1024 * 1024,
) -> dict[str, Any]:
    """Execute only the requested production-shaped scoring lane."""
    required = min(top_k, len(symbol_ids))
    if mode in {"exact_tiebreak_baseline", "bounded_exact_fallback"}:
        exact_combined = [
            float(lexical_base[index])
            + semantic_weight * exact_cosine(query, matrix[index].tolist())
            for index in range(len(symbol_ids))
        ]
        top = deterministic_top(exact_combined, symbol_ids, top_k)
        return {
            "top": top,
            "scores": exact_combined,
            "lane_selected": mode,
            "fallback_reason": (
                "forced_exact_fallback_mode" if mode == "bounded_exact_fallback" else ""
            ),
            "rescored_count": len(symbol_ids),
        }

    if mode != "float32_certified_candidate":
        raise ValueError(f"unknown mode: {mode}")
    if int(getattr(matrix, "nbytes", 0)) > matrix_max_bytes:
        exact_combined = [
            float(lexical_base[index])
            + semantic_weight * exact_cosine(query, matrix[index].tolist())
            for index in range(len(symbol_ids))
        ]
        return {
            "top": deterministic_top(exact_combined, symbol_ids, top_k),
            "scores": exact_combined,
            "lane_selected": "bounded_exact_fallback",
            "fallback_reason": "memory_cap_refusal",
            "rescored_count": len(symbol_ids),
        }
    try:
        import numpy as np

        estimates, lower, upper = float32_scores_and_bounds(matrix, query)
    except ImportError:
        exact_combined = [
            float(lexical_base[index])
            + semantic_weight * exact_cosine(query, matrix[index].tolist())
            for index in range(len(symbol_ids))
        ]
        return {
            "top": deterministic_top(exact_combined, symbol_ids, top_k),
            "scores": exact_combined,
            "lane_selected": "bounded_exact_fallback",
            "fallback_reason": "numpy_unavailable",
            "rescored_count": len(symbol_ids),
        }
    except MemoryError:
        exact_combined = [
            float(lexical_base[index])
            + semantic_weight * exact_cosine(query, matrix[index].tolist())
            for index in range(len(symbol_ids))
        ]
        return {
            "top": deterministic_top(exact_combined, symbol_ids, top_k),
            "scores": exact_combined,
            "lane_selected": "bounded_exact_fallback",
            "fallback_reason": "allocation_failure",
            "rescored_count": len(symbol_ids),
        }
    lexical = np.asarray(lexical_base, dtype=np.float64)
    combined = lexical + semantic_weight * estimates
    combined_lower = lexical + semantic_weight * lower
    combined_upper = lexical + semantic_weight * upper
    if required:
        position = len(symbol_ids) - required
        kth_lower = float(np.partition(combined_lower, position)[position])
        uncertain = {int(index) for index in np.flatnonzero(combined_upper >= kth_lower)}
    else:
        uncertain = set()
    uncertain |= {
        int(index)
        for index in np.flatnonzero((combined_lower <= 0.0) & (combined_upper > 0.0))
    }
    limit = max(required, math.ceil(len(symbol_ids) * max_rescore_fraction))
    if len(uncertain) > limit:
        exact_combined = [
            float(lexical_base[index])
            + semantic_weight * exact_cosine(query, matrix[index].tolist())
            for index in range(len(symbol_ids))
        ]
        return {
            "top": deterministic_top(exact_combined, symbol_ids, top_k),
            "scores": exact_combined,
            "lane_selected": "bounded_exact_fallback",
            "fallback_reason": "certification_fraction_limit",
            "rescored_count": len(symbol_ids),
        }

    selected_scores = combined.tolist()
    for index in uncertain:
        selected_scores[index] = (
            float(lexical_base[index])
            + semantic_weight * exact_cosine(query, matrix[index].tolist())
        )
    return {
        "top": deterministic_top(selected_scores, symbol_ids, top_k),
        "scores": selected_scores,
        "lane_selected": mode,
        "fallback_reason": "",
        "rescored_count": len(uncertain),
    }


def score_case(
    *,
    matrix: Any,
    query: Sequence[float],
    symbol_ids: Sequence[str],
    lexical_base: Sequence[float],
    semantic_weight: float,
    top_k: int,
    mode: str,
    max_rescore_fraction: float,
) -> dict[str, Any]:
    """Execute one scoring mode and independently classify it against exact math."""
    import numpy as np

    if len(symbol_ids) != len(matrix) or len(lexical_base) != len(symbol_ids):
        raise ValueError("candidate arrays have inconsistent lengths")
    exact_cosines = [exact_cosine(query, row.tolist()) for row in matrix]
    exact_combined = [
        float(lexical_base[index]) + semantic_weight * exact_cosines[index]
        for index in range(len(symbol_ids))
    ]
    exact_top = deterministic_top(exact_combined, symbol_ids, top_k)
    exact_ties = tie_participants(exact_combined)

    estimates, lower, upper = float32_scores_and_bounds(matrix, query)
    approximate_combined = np.asarray(lexical_base, dtype=np.float64) + semantic_weight * estimates
    combined_lower = np.asarray(lexical_base, dtype=np.float64) + semantic_weight * lower
    combined_upper = np.asarray(lexical_base, dtype=np.float64) + semantic_weight * upper
    approximate_top = deterministic_top(approximate_combined.tolist(), symbol_ids, top_k)
    genuine = disagreement_participants(exact_top, approximate_top) - exact_ties

    interval_violations = {
        index
        for index, score in enumerate(exact_cosines)
        if not (float(lower[index]) <= score <= float(upper[index]))
    }
    required = min(top_k, len(symbol_ids))
    if required:
        position = len(symbol_ids) - required
        kth_lower = float(np.partition(combined_lower, position)[position])
        uncertain = {int(index) for index in np.flatnonzero(combined_upper >= kth_lower)}
    else:
        uncertain = set()
    sign_ambiguous = {
        int(index)
        for index in np.flatnonzero((combined_lower <= 0.0) & (combined_upper > 0.0))
    }
    uncertain |= sign_ambiguous

    execution = execute_mode(
        matrix=matrix,
        query=query,
        symbol_ids=symbol_ids,
        lexical_base=lexical_base,
        semantic_weight=semantic_weight,
        top_k=top_k,
        mode=mode,
        max_rescore_fraction=max_rescore_fraction,
    )
    selected_top = execution["top"]
    lane_selected = execution["lane_selected"]
    fallback_reason = execution["fallback_reason"]
    if interval_violations and mode == "float32_certified_candidate":
        selected_top = exact_top
        lane_selected = "bounded_exact_fallback"
        fallback_reason = "interval_violation"
    parity = selected_top == exact_top
    exact_ids = [symbol_ids[index] for index in exact_top]
    selected_ids = [symbol_ids[index] for index in selected_top]
    baseline_hash = sha256_bytes(canonical_json({"ids": exact_ids}).encode("utf-8"))
    candidate_hash = sha256_bytes(canonical_json({"ids": selected_ids}).encode("utf-8"))

    certified = uncertain - exact_ties
    genuine_certified = genuine & certified
    near_ties = certified - genuine_certified
    other_certified = interval_violations
    if lane_selected == "bounded_exact_fallback" and fallback_reason:
        other_certified = set(range(len(symbol_ids))) - exact_ties - near_ties - genuine_certified
    total_certified = near_ties | genuine_certified | other_certified
    boundary = exact_combined[exact_top[-1]] if exact_top else 0.0

    return {
        "candidate_count": len(symbol_ids),
        "result_count": len(selected_top),
        "result_boundary_score": float(boundary),
        "exact_tie_count": len(exact_ties),
        "near_tie_count": len(near_ties),
        "genuine_disagreement_count": len(genuine_certified),
        "other_certified_count": len(other_certified),
        "total_certified_count": len(total_certified),
        "interval_violation_count": len(interval_violations),
        "baseline_response_hash": baseline_hash,
        "candidate_response_hash": candidate_hash,
        "canonical_parity": parity,
        "ordered_result_id_hash": sha256_bytes(canonical_json(selected_ids).encode("utf-8")),
        "lane_selected": lane_selected,
        "fallback_reason": fallback_reason,
        "diagnostic": {
            "uncertain_count": len(uncertain),
            "float32_top_disagreement_participants": len(genuine),
            "exact_top_ids": exact_ids,
            "selected_top_ids": selected_ids,
        },
    }


def fractions(counts: dict[str, int], denominator: int) -> dict[str, str]:
    keys = (
        "exact_tie_count",
        "near_tie_count",
        "genuine_disagreement_count",
        "total_certified_count",
    )
    if denominator <= 0:
        return {key.replace("_count", "_fraction"): "" for key in keys}
    return {
        key.replace("_count", "_fraction"): format(counts[key] / denominator, ".17g")
        for key in keys
    }


def assert_fixed_schema(row: dict[str, Any]) -> None:
    missing = set(CSV_COLUMNS) - set(row)
    unknown = set(row) - set(CSV_COLUMNS)
    if missing or unknown:
        raise ValueError(f"fixed schema mismatch missing={sorted(missing)} unknown={sorted(unknown)}")


def stable_row_id(parts: Iterable[str]) -> str:
    return sha256_bytes("\x1f".join(parts).encode("utf-8"))[:24]
