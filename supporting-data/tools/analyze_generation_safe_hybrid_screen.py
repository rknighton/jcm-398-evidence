"""Validate and summarize the generation-safe hybrid end-to-end screen."""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "source-runs" / "generation_safe_hybrid_e2e_screen_v1.csv"
OUTPUT = HERE.parent / "manifests" / "generation_safe_hybrid_e2e_screen_v1_summary.json"
BASELINE = "baseline_full"
CANDIDATE = "generation_safe_hybrid"
PAIR_FIELDS = ("repo", "case", "target_index", "repetition")


def _number(row: dict[str, str], field: str) -> float:
    return float(row[field])


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _geomean(values: list[float]) -> float:
    return math.exp(statistics.fmean(math.log(value) for value in values))


def _summary(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_wall = sum(pair["baseline_wall_ms"] for pair in pairs)
    candidate_wall = sum(pair["candidate_wall_ms"] for pair in pairs)
    baseline_cpu = sum(pair["baseline_cpu_ms"] for pair in pairs)
    candidate_cpu = sum(pair["candidate_cpu_ms"] for pair in pairs)
    return {
        "pair_count": len(pairs),
        "candidate_faster_count": sum(pair["saved_ms"] > 0 for pair in pairs),
        "candidate_slower_count": sum(pair["saved_ms"] < 0 for pair in pairs),
        "candidate_equal_count": sum(pair["saved_ms"] == 0 for pair in pairs),
        "meaningful_win_count": sum(
            pair["saved_ms"] >= 10 and pair["reduction_pct"] >= 10
            for pair in pairs
        ),
        "negligible_or_mixed_count": sum(
            pair["saved_ms"] < 10 or pair["reduction_pct"] < 10
            for pair in pairs
        ),
        "baseline_wall_ms_sum": baseline_wall,
        "candidate_wall_ms_sum": candidate_wall,
        "wall_ms_saved_sum": baseline_wall - candidate_wall,
        "suite_speedup_x": baseline_wall / candidate_wall,
        "suite_reduction_pct": (baseline_wall - candidate_wall) / baseline_wall * 100,
        "median_pair_speedup_x": _median([pair["speedup_x"] for pair in pairs]),
        "geomean_pair_speedup_x": _geomean([pair["speedup_x"] for pair in pairs]),
        "median_pair_reduction_pct": _median(
            [pair["reduction_pct"] for pair in pairs]
        ),
        "baseline_cpu_ms_sum": baseline_cpu,
        "candidate_cpu_ms_sum": candidate_cpu,
        "cpu_ms_saved_sum": baseline_cpu - candidate_cpu,
        "cpu_reduction_pct": (
            (baseline_cpu - candidate_cpu) / baseline_cpu * 100
            if baseline_cpu
            else 0.0
        ),
    }


def main() -> None:
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 288:
        raise AssertionError(f"Expected 288 rows, found {len(rows)}")

    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row[field] for field in PAIR_FIELDS)].append(row)

    pairs: list[dict[str, Any]] = []
    for key, pair_rows in grouped.items():
        by_mode = {row["mode"]: row for row in pair_rows}
        if set(by_mode) != {BASELINE, CANDIDATE} or len(pair_rows) != 2:
            raise AssertionError(f"Invalid pair {key}: {sorted(by_mode)}")
        baseline = by_mode[BASELINE]
        candidate = by_mode[CANDIDATE]
        if baseline["canonical_response_hash"] != candidate["canonical_response_hash"]:
            raise AssertionError(f"Canonical response mismatch in pair {key}")
        if baseline["target_value"] != candidate["target_value"]:
            raise AssertionError(f"Target mismatch in pair {key}")
        baseline_wall = _number(baseline, "wall_ms")
        candidate_wall = _number(candidate, "wall_ms")
        baseline_cpu = float(json.loads(baseline["parity_debug_json"])["process_cpu_ms"])
        candidate_cpu = float(json.loads(candidate["parity_debug_json"])["process_cpu_ms"])
        pairs.append(
            {
                "repo": baseline["repo"],
                "case": baseline["case"],
                "tool": baseline["tool"],
                "symbol_count": int(baseline["symbol_count"]),
                "baseline_wall_ms": baseline_wall,
                "candidate_wall_ms": candidate_wall,
                "saved_ms": baseline_wall - candidate_wall,
                "speedup_x": baseline_wall / candidate_wall,
                "reduction_pct": (baseline_wall - candidate_wall) / baseline_wall * 100,
                "baseline_load_ms": _number(baseline, "load_phase_ms"),
                "candidate_load_ms": _number(candidate, "load_phase_ms"),
                "baseline_cpu_ms": baseline_cpu,
                "candidate_cpu_ms": candidate_cpu,
            }
        )

    if len(pairs) != 144:
        raise AssertionError(f"Expected 144 pairs, found {len(pairs)}")

    by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pair in pairs:
        by_repo[pair["repo"]].append(pair)
        by_tool[pair["tool"]].append(pair)

    result = {
        "schema": "jcodemunch.generation_safe_hybrid_screen_summary/v1",
        "source": SOURCE.name,
        "validation": {
            "row_count": len(rows),
            "pair_count": len(pairs),
            "canonical_parity_pairs": sum(
                1
                for pair_rows in grouped.values()
                if len({row["canonical_response_hash"] for row in pair_rows}) == 1
            ),
            "repos": sorted(by_repo),
            "tools": sorted(by_tool),
            "cases": sorted({pair["case"] for pair in pairs}),
            "source_versions": sorted({row["jcodemunch_version"] for row in rows}),
            "source_shas": sorted({row["jcodemunch_source_sha"] for row in rows}),
        },
        "overall": _summary(pairs),
        "by_repo": {repo: _summary(items) for repo, items in sorted(by_repo.items())},
        "by_tool": {tool: _summary(items) for tool, items in sorted(by_tool.items())},
        "largest_absolute_wins": sorted(
            pairs, key=lambda pair: pair["saved_ms"], reverse=True
        )[:15],
        "largest_regressions": sorted(pairs, key=lambda pair: pair["saved_ms"])[:15],
        "largest_speedups": sorted(
            pairs, key=lambda pair: pair["speedup_x"], reverse=True
        )[:15],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
