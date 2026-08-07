"""Deterministic helpers for the production-lane comparison."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

SCHEMA = "jcm-production-lane-v1"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def tie_groups(scores: list[dict[str, str]], top_k: int) -> dict[str, Any]:
    groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for rank, row in enumerate(scores):
        groups[row["final_hex"]].append((rank, row["id"]))
    tied = [items for items in groups.values() if len(items) > 1]
    relevant = []
    for items in tied:
        ranks = [rank for rank, _ in items]
        if any(rank < top_k for rank in ranks):
            relevant.append({"ranks": ranks, "ids": [sid for _, sid in items]})
    return {
        "group_count": len(tied),
        "participant_count": sum(len(items) for items in tied),
        "intersecting_top_k": relevant,
        "crossing_top_k_boundary": [g for g in relevant if min(g["ranks"]) < top_k <= max(g["ranks"])],
    }


def compare_case(numpy_evidence: dict[str, Any], python_evidence: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    nrows = numpy_evidence["scores"]
    prows = python_evidence["scores"]
    if [r["id"] for r in nrows] != [r["id"] for r in prows]:
        raise ValueError("candidate identity/order differs across lanes")
    top_k = case["top_k"]
    n_top = numpy_evidence["ordered_positive_ids"][:top_k]
    p_top = python_evidence["ordered_positive_ids"][:top_k]
    positions = [i for i, pair in enumerate(zip(n_top, p_top)) if pair[0] != pair[1]]
    n_only = sorted(set(n_top) - set(p_top))
    p_only = sorted(set(p_top) - set(n_top))
    cos_diffs = [abs(float.fromhex(n["cosine_hex"]) - float.fromhex(p["cosine_hex"])) for n, p in zip(nrows, prows)]
    final_diffs = [abs(float.fromhex(n["final_hex"]) - float.fromhex(p["final_hex"])) for n, p in zip(nrows, prows)]
    max_cos = max(cos_diffs, default=0.0)
    max_final = max(final_diffs, default=0.0)
    involved = set(n_top) ^ set(p_top)
    involved.update(n_top[i] for i in positions)
    involved.update(p_top[i] for i in positions)
    nties = tie_groups(numpy_evidence["ranked_scores"], top_k)
    pties = tie_groups(python_evidence["ranked_scores"], top_k)
    n_tied_ids = {sid for g in nties["intersecting_top_k"] for sid in g["ids"]}
    p_tied_ids = {sid for g in pties["intersecting_top_k"] for sid in g["ids"]}
    return {
        "schema_version": SCHEMA,
        "paired_case_id": case["paired_case_id"],
        "corpus": case["corpus"],
        "query_id": case["query_id"],
        "top_k": top_k,
        "rank_0": {"numpy": n_top[0], "python": p_top[0], "equal": n_top[0] == p_top[0]},
        "ordered_top_k": {
            "numpy": n_top, "python": p_top, "equal": n_top == p_top,
            "first_differing_rank": positions[0] if positions else None,
            "differing_positions": positions,
            "differing_position_count": len(positions),
        },
        "membership": {
            "equal": set(n_top) == set(p_top), "numpy_only": n_only, "python_only": p_only,
            "symmetric_difference_count": len(n_only) + len(p_only),
        },
        "exact_ties": {"numpy": nties, "python": pties},
        "disagreement_exact_tie_association": {
            "involved_ids": sorted(involved),
            "numpy_exact_tied_ids": sorted(involved & n_tied_ids),
            "python_exact_tied_ids": sorted(involved & p_tied_ids),
        },
        "numeric_diagnostics": {
            "max_abs_cosine_difference_hex": max_cos.hex(),
            "median_abs_cosine_difference_hex": median(cos_diffs).hex(),
            "max_abs_final_difference_hex": max_final.hex(),
            "median_abs_final_difference_hex": median(final_diffs).hex(),
            "max_cosine_ids": [nrows[i]["id"] for i, value in enumerate(cos_diffs) if value == max_cos],
            "max_final_ids": [nrows[i]["id"] for i, value in enumerate(final_diffs) if value == max_final],
        },
    }
