"""Probe whether database-file churn prevents safe cross-request cache reuse."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import bench_generation_safe_hybrid_e2e as base


HERE = Path(__file__).resolve().parent
RAW_CSV = HERE.parent / "source-runs" / "cache_generation_churn_probe_v7.csv"
REPO = "django/django"
REPO_NAME = "django-3eb2e228"
TARGET_INDEX = 3


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if not sys.flags.utf8_mode:
        raise RuntimeError("Run with Python UTF-8 mode enabled (-X utf8)")
    controller_sha = _sha256(Path(__file__))
    roots = {
        "baseline_full_warm_probe": base.BASELINE_ROOT,
        "generation_safe_hybrid_warm_probe": base.CANDIDATE_ROOT,
        "generation_unsafe_global_partial_warm_probe": base.CANDIDATE_ROOT,
    }
    workers = {mode: base.Worker(root, mode) for mode, root in roots.items()}
    rows = []
    try:
        fixture = workers["baseline_full_warm_probe"].request(
            {"command": "fixture", "repo_name": REPO_NAME, "target_index": TARGET_INDEX}
        )
        symbol = fixture["target"]["symbol"]
        cases = (
            (
                "symbol_source_warm_probe",
                "get_symbol_source",
                {"repo": f"local/{REPO_NAME}", "symbol_id": symbol["id"]},
            ),
            (
                "search_symbols_warm_probe",
                "search_symbols",
                {
                    "repo": f"local/{REPO_NAME}",
                    "query": symbol["name"],
                    "max_results": 10,
                    "detail_level": "compact",
                    "fusion": False,
                },
            ),
        )
        for case, tool, arguments in cases:
            group = []
            for order_position, (mode, worker) in enumerate(workers.items(), start=1):
                response = worker.request(
                    {
                        "command": "measure",
                        "repo": REPO,
                        "repo_name": REPO_NAME,
                        "case": case,
                        "tool": tool,
                        "profile": "cache_generation_probe",
                        "arguments": arguments,
                        "target_index": TARGET_INDEX,
                        "repetition": 1,
                        "order_position": order_position,
                        "cache_policy": "warm_index",
                        "scope": "cache_generation_churn_probe",
                        "controller_sha256": controller_sha,
                        "target_policy": "same request repeated with tool result cache disabled",
                    }
                )
                group.append(response["row"])
            if len({row["canonical_response_hash"] for row in group}) != 1:
                raise AssertionError(f"Canonical mismatch for {case}")
            for row in group:
                if row["_response_error"]:
                    raise AssertionError(f"Tool error for {case}: {row['_response_error']}")
                row.pop("_canonical_response", None)
                row.pop("_response_error", None)
            rows.extend(group)
            print(
                json.dumps(
                    {"case": case, "timings_ms": {r["mode"]: r["wall_ms"] for r in group}}
                ),
                flush=True,
            )
    finally:
        for worker in workers.values():
            worker.close()

    temporary = RAW_CSV.with_suffix(".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(RAW_CSV)
    print(
        json.dumps(
            {
                "status": "ok",
                "rows": len(rows),
                "raw_csv": str(RAW_CSV),
                "sha256": _sha256(RAW_CSV),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
