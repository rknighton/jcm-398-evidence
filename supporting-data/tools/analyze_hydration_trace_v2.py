"""Deterministically classify runtime hydration behavior from traced screens."""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
SOURCE_RUNS = HERE.parent / "source-runs"
SOURCES = (
    SOURCE_RUNS / "generation_safe_hybrid_hydration_trace_screen_v2.csv",
    SOURCE_RUNS / "generation_safe_hybrid_hydration_trace_expanded_v2.csv",
)
OUTPUT = HERE.parent / "manifests" / "generation_safe_hybrid_hydration_trace_v2.json"
SPARSE_KEYS = (
    "sparse_by_id_calls",
    "sparse_by_file_calls",
    "sparse_by_name_calls",
    "sparse_by_files_calls",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _median(values: list[float]) -> float:
    return statistics.median(values)


def _trace(row: dict[str, str]) -> dict[str, Any]:
    debug = json.loads(row["parity_debug_json"])
    trace = debug.get("hydration_trace")
    if not isinstance(trace, dict):
        raise ValueError(f"Missing hydration_trace in {row['case']} {row['mode']}")
    return trace


def _classify(trace: dict[str, Any]) -> str:
    requested = {
        item.get("requested_hydration", "auto")
        for item in trace.get("load_results", [])
    }
    explicit_full = "full" in requested
    lazy_full = int(trace.get("lazy_full_materializations", 0)) > 0
    sparse = sum(int(trace.get(key, 0)) for key in SPARSE_KEYS) > 0
    if explicit_full and sparse:
        return "explicit_full_plus_sparse"
    if explicit_full:
        return "explicit_full"
    if lazy_full and sparse:
        return "lazy_full_plus_sparse"
    if lazy_full:
        return "lazy_full"
    if sparse:
        return "sparse_only"
    return "metadata_or_file_state_only"


def main() -> None:
    missing = [str(path) for path in SOURCES if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing traced source files: {missing}")

    rows: list[dict[str, str]] = []
    for source in SOURCES:
        with source.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row["_source_file"] = source.name
                rows.append(row)

    candidate = [row for row in rows if row["mode"] == "generation_safe_hybrid"]
    baseline = [row for row in rows if row["mode"] == "baseline_full"]
    if len(candidate) != len(baseline):
        raise AssertionError("Baseline and candidate row counts differ")

    pair_hashes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        pair_hashes[(row["repo"], row["case"])].add(row["canonical_response_hash"])
    mismatches = [
        {"repo": key[0], "case": key[1], "hashes": sorted(hashes)}
        for key, hashes in pair_hashes.items()
        if len(hashes) != 1
    ]
    if mismatches:
        raise AssertionError(f"Canonical response mismatches: {mismatches}")

    by_tool: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_case: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in candidate:
        by_tool[row["tool"]].append(row)
        by_case[(row["repo"], row["case"])].append(row)

    tool_results: dict[str, Any] = {}
    for tool, tool_rows in sorted(by_tool.items()):
        observations = []
        classifications = set()
        for row in tool_rows:
            trace = _trace(row)
            classification = _classify(trace)
            classifications.add(classification)
            observations.append(
                {
                    "repo": row["repo"],
                    "case": row["case"],
                    "classification": classification,
                    "load_calls": int(row["load_calls"]),
                    "requested_hydration": sorted(
                        {
                            str(item.get("requested_hydration", "auto"))
                            for item in trace.get("load_results", [])
                        }
                    ),
                    "symbol_collection_types": sorted(
                        {
                            str(item.get("symbol_collection_type"))
                            for item in trace.get("load_results", [])
                        }
                    ),
                    "lazy_full_materializations": int(
                        trace.get("lazy_full_materializations", 0)
                    ),
                    "sparse_calls": {
                        key: int(trace.get(key, 0)) for key in SPARSE_KEYS
                    },
                }
            )
        tool_results[tool] = {
            "classifications": sorted(classifications),
            "stable_across_observations": len(classifications) == 1,
            "observations": observations,
        }

    paired_timings = []
    baseline_by_key = {
        (row["repo"], row["case"]): row
        for row in baseline
    }
    for row in candidate:
        key = (row["repo"], row["case"])
        before = baseline_by_key[key]
        baseline_ms = float(before["wall_ms"])
        candidate_ms = float(row["wall_ms"])
        paired_timings.append(
            {
                "repo": row["repo"],
                "case": row["case"],
                "tool": row["tool"],
                "classification": _classify(_trace(row)),
                "baseline_wall_ms": baseline_ms,
                "candidate_wall_ms": candidate_ms,
                "saved_ms": baseline_ms - candidate_ms,
                "speedup_x": baseline_ms / candidate_ms if candidate_ms else None,
            }
        )

    class_timings: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in paired_timings:
        class_timings[item["classification"]].append(item)
    timing_summary = {}
    for classification, items in sorted(class_timings.items()):
        timing_summary[classification] = {
            "pairs": len(items),
            "median_saved_ms": _median([item["saved_ms"] for item in items]),
            "median_speedup_x": _median([item["speedup_x"] for item in items]),
            "total_baseline_ms": sum(item["baseline_wall_ms"] for item in items),
            "total_candidate_ms": sum(item["candidate_wall_ms"] for item in items),
        }

    result = {
        "schema": "jcodemunch.hydration_trace/v2",
        "method": (
            "One cold measured call per case and repository after an unmeasured warm-up. "
            "The worker traced load_index hydration requests plus LazySymbolList full and "
            "sparse access methods. Classification describes the exercised argument path, "
            "not every possible argument path in the tool."
        ),
        "source_files": [
            {"name": path.name, "sha256": _sha256(path)} for path in SOURCES
        ],
        "analysis_script_sha256": _sha256(Path(__file__)),
        "counts": {
            "rows": len(rows),
            "candidate_observations": len(candidate),
            "tools": len(by_tool),
            "cases": len(by_case),
            "canonical_mismatches": len(mismatches),
            "unstable_tool_classifications": sum(
                not item["stable_across_observations"]
                for item in tool_results.values()
            ),
        },
        "timing_summary_by_classification": timing_summary,
        "tools": tool_results,
        "paired_timings": paired_timings,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["counts"], sort_keys=True))
    print(json.dumps(timing_summary, indent=2, sort_keys=True))
    print(str(OUTPUT))


if __name__ == "__main__":
    main()
