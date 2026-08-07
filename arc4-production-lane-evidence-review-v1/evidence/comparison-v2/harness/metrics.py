from __future__ import annotations

import math
import statistics
import struct
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping, Sequence

from .common import canonical_json_bytes, ensure_finite_scores, require, sha256_bytes


def float_bits(value: float) -> bytes:
    return struct.pack(">d", float(value))


def ranking(scores: Mapping[str, float]) -> list[str]:
    ensure_finite_scores(scores)
    return sorted((symbol_id for symbol_id, score in scores.items() if score > 0.0), key=lambda symbol_id: (-float(scores[symbol_id]), symbol_id))


def ordering_sha256(scores: Mapping[str, float]) -> str:
    lines = [canonical_json_bytes({"schema": "arc4.positive-ranking/v1"})]
    for symbol_id in ranking(scores):
        lines.append(canonical_json_bytes({"symbol_id": symbol_id, "score_hex": float(scores[symbol_id]).hex()}))
    return sha256_bytes(b"".join(lines))


def tie_groups(scores: Mapping[str, float]) -> tuple[tuple[str, ...], ...]:
    groups: dict[bytes, list[str]] = defaultdict(list)
    for symbol_id in ranking(scores):
        groups[float_bits(scores[symbol_id])].append(symbol_id)
    return tuple(sorted((tuple(sorted(group)) for group in groups.values() if len(group) > 1)))


def tie_evidence(scores: Mapping[str, float], top_k: int) -> dict[str, Any]:
    ordered = ranking(scores)
    groups = tie_groups(scores)
    top = set(ordered[:top_k])
    boundary_left = set(ordered[:top_k])
    boundary_right = set(ordered[top_k:])
    intersecting = tuple(group for group in groups if set(group) & top)
    crossing = tuple(group for group in groups if set(group) & boundary_left and set(group) & boundary_right)
    participants = sorted({item for group in groups for item in group})
    encoded = canonical_json_bytes([list(group) for group in groups])
    return {
        "tie_partition_sha256": sha256_bytes(encoded),
        "groups": [list(group) for group in groups],
        "participants": participants,
        "groups_intersecting_top_k": [list(group) for group in intersecting],
        "groups_crossing_top_k_boundary": [list(group) for group in crossing],
    }


class _Fenwick:
    def __init__(self, size: int) -> None:
        self.values = [0] * (size + 1)

    def add(self, index: int) -> None:
        index += 1
        while index < len(self.values):
            self.values[index] += 1
            index += index & -index

    def prefix(self, end_exclusive: int) -> int:
        result = 0
        index = end_exclusive
        while index:
            result += self.values[index]
            index -= index & -index
        return result


def inversion_count(left: Mapping[str, float], right: Mapping[str, float], ids: Iterable[str]) -> int:
    selected = list(ids)
    require(all(item in left and item in right for item in selected), "score_id_set", "comparison ID absent from a score vector")
    right_values = sorted({float(right[item]) for item in selected})
    coordinates = {value: index for index, value in enumerate(right_values)}
    ordered = sorted(selected, key=lambda item: -float(left[item]))
    tree = _Fenwick(len(right_values))
    result = 0
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        value = float(left[ordered[cursor]])
        while end < len(ordered) and float(left[ordered[end]]) == value:
            end += 1
        for item in ordered[cursor:end]:
            result += tree.prefix(coordinates[float(right[item])])
        for item in ordered[cursor:end]:
            tree.add(coordinates[float(right[item])])
        cursor = end
    return result


def _split_pairs(tied: Mapping[str, float], other: Mapping[str, float], ids: set[str]) -> int:
    groups: dict[bytes, list[str]] = defaultdict(list)
    for item in ids:
        groups[float_bits(tied[item])].append(item)
    total = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        all_pairs = len(group) * (len(group) - 1) // 2
        same_other = Counter(float_bits(other[item]) for item in group)
        total += all_pairs - sum(count * (count - 1) // 2 for count in same_other.values())
    return total


def genuine_disagreement_count(left: Mapping[str, float], right: Mapping[str, float], ids: set[str]) -> int:
    return _split_pairs(left, right, ids) + _split_pairs(right, left, ids)


def first_divergence(left: Sequence[str], right: Sequence[str]) -> int | None:
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    return None if len(left) == len(right) else min(len(left), len(right))


def numeric_summary(values: Sequence[float]) -> dict[str, Any]:
    require(bool(values), "no_finite_values", "numeric summary requires at least one value")
    ordered = sorted(float(value) for value in values)
    require(all(math.isfinite(value) for value in ordered), "summary_nonfinite", "non-finite aggregate input")
    p99_index = max(0, min(len(ordered) - 1, math.ceil(0.99 * len(ordered)) - 1))
    return {"minimum": ordered[0], "median": statistics.median(ordered), "p99_nearest_rank": ordered[p99_index], "maximum": ordered[-1], "count": len(ordered)}


def score_delta_summary(left: Mapping[str, float], right: Mapping[str, float]) -> dict[str, Any]:
    require(set(left) == set(right) and bool(left), "score_vector_ids", "score-vector ID sets must be equal and nonempty")
    deltas = [abs(float(left[item]) - float(right[item])) for item in left]
    summary = numeric_summary(deltas)
    return {"max": summary["maximum"], "median": summary["median"], "p99_nearest_rank": summary["p99_nearest_rank"], "bit_identical": sum(float_bits(left[item]) == float_bits(right[item]) for item in left), "candidate_count": len(left)}


def _ratio(gap: float, denominator: float) -> float | str:
    if denominator == 0.0:
        return "+inf" if gap > 0.0 else "exact_tie"
    if gap == 0.0:
        return 0.0
    return gap / denominator


def _margin_for_order(order_scores: Mapping[str, float], other_scores: Mapping[str, float], top_k: int) -> dict[str, Any]:
    order = ranking(order_scores)
    max_delta = max(abs(float(other_scores[item]) - float(order_scores[item])) for item in order_scores)
    def one(a: str, b: str) -> dict[str, Any]:
        gap = float(order_scores[a]) - float(order_scores[b])
        other_gap = float(other_scores[a]) - float(other_scores[b])
        observed_denominator = abs(gap - other_gap)
        conservative_denominator = 2.0 * max_delta
        return {
            "symbols": [a, b],
            "gap": gap,
            "observed_denominator": observed_denominator,
            "conservative_denominator": conservative_denominator,
            "observed": _ratio(gap, observed_denominator),
            "conservative": _ratio(gap, conservative_denominator),
        }
    boundary: dict[str, Any] | str = "insufficient_ranking"
    if len(order) >= top_k + 1:
        boundary = one(order[top_k - 1], order[top_k])
    internal: dict[str, Any] | str = "insufficient_ranking"
    if len(order) >= 2 and min(top_k, len(order)) >= 2:
        limit = min(top_k, len(order))
        pairs = [one(order[index], order[index + 1]) for index in range(limit - 1)]
        internal = min(pairs, key=lambda value: value["gap"])
    return {"boundary": boundary, "minimum_internal": internal}


def compare_pair(
    numpy_scores: Mapping[str, float], python_scores: Mapping[str, float], top_k: int,
    *, numpy_raw_cosine: Mapping[str, float] | None = None, python_raw_cosine: Mapping[str, float] | None = None,
    include_hybrid_final: bool = False,
) -> dict[str, Any]:
    ensure_finite_scores(numpy_scores)
    ensure_finite_scores(python_scores)
    require(set(numpy_scores) == set(python_scores), "score_vector_ids", "lane ID sets differ")
    require(isinstance(top_k, int) and top_k > 0, "top_k", "top_k must be positive")
    n_order = ranking(numpy_scores)
    p_order = ranking(python_scores)
    n_top, p_top = n_order[:top_k], p_order[:top_k]
    n_ties, p_ties = tie_evidence(numpy_scores, top_k), tie_evidence(python_scores, top_k)
    union_top = set(n_top) | set(p_top)
    positive_union = set(n_order) | set(p_order)
    raw_left = numpy_scores if numpy_raw_cosine is None else numpy_raw_cosine
    raw_right = python_scores if python_raw_cosine is None else python_raw_cosine
    ensure_finite_scores(raw_left)
    ensure_finite_scores(raw_right)
    require(set(raw_left) == set(raw_right) == set(numpy_scores), "raw_score_vector_ids", "raw cosine ID sets differ")
    result = {
        "m1_rank0_difference": None if not n_order or not p_order else n_order[0] != p_order[0],
        "m1_status": "no_results" if not n_order or not p_order else "eligible",
        "m2_ordered_top_k_difference": n_top != p_top,
        "m3_membership_top_k_difference": set(n_top) != set(p_top),
        "m4_exact_tie_difference": n_ties["tie_partition_sha256"] != p_ties["tie_partition_sha256"],
        "m4_numpy": n_ties,
        "m4_python": p_ties,
        "m4_participant_symmetric_difference": sorted(set(n_ties["participants"]) ^ set(p_ties["participants"])),
        "m5_top_k_inversion_count": inversion_count(numpy_scores, python_scores, union_top),
        "m5_full_inversion_count": inversion_count(numpy_scores, python_scores, positive_union),
        "m6_top_k_genuine_disagreement_count": genuine_disagreement_count(numpy_scores, python_scores, union_top),
        "m6_full_genuine_disagreement_count": genuine_disagreement_count(numpy_scores, python_scores, positive_union),
        "m10_raw_cosine": score_delta_summary(raw_left, raw_right),
        "m11_numpy_order": _margin_for_order(numpy_scores, python_scores, top_k),
        "m11_python_order": _margin_for_order(python_scores, numpy_scores, top_k),
        "m12_first_divergence_rank": first_divergence(n_order, p_order),
        "numpy_ordering_sha256": ordering_sha256(numpy_scores),
        "python_ordering_sha256": ordering_sha256(python_scores),
    }
    if include_hybrid_final:
        result["m10_hybrid_final"] = score_delta_summary(numpy_scores, python_scores)
    return result
