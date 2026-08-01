"""One-pass Django screen for every unbenchmarked read tool that loads an index."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import bench_generation_safe_hybrid_e2e as base


HERE = Path(__file__).resolve().parent
MANIFEST = HERE.parent / "manifests" / "index_hydration_blast_radius_v1.json"
RAW_CSV = HERE.parent / "source-runs" / "generation_safe_hybrid_expanded_surface_v1.csv"
FAILURE = HERE.parent / "logs" / "generation_safe_hybrid_expanded_surface_v1_failure.json"
REPO = "django/django"
REPO_NAME = "django-3eb2e228"
OTHER_REPO = "local/fastapi-c1d6b9c4"
TARGET_INDEX = 3
CLASS_ID = "django/db/models/base.py::Model#class"
CLASS_NAME = "Model"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _arguments(tool: str, fixture: dict[str, Any]) -> dict[str, Any]:
    target = fixture["target"]
    repo = f"local/{REPO_NAME}"
    symbol_id = target["symbol"]["id"]
    symbol_name = target["symbol"]["name"]
    file_path = target["file"]
    prefix = target["prefix"] or file_path
    source_root = fixture["source_root"]
    arguments: dict[str, dict[str, Any]] = {
        "assemble_task_context": {
            "repo": repo,
            "task": f"Understand {symbol_name}",
            "symbols": [symbol_id],
            "intent": "explore",
            "token_budget": 1000,
            "include": ["anchor"],
        },
        "audit_agent_config": {"repo": repo, "project_path": source_root},
        "check_delete_safe": {"repo": repo, "symbol": symbol_id},
        "check_edit_safe": {"repo": repo, "symbol": symbol_id},
        "check_rename_safe": {
            "repo": repo,
            "symbol_id": symbol_id,
            "new_name": f"{symbol_name}_renamed",
        },
        "digest": {"repo": repo, "since_sha": target["since_sha"]},
        "find_dead_code": {
            "repo": repo,
            "granularity": "file",
            "min_confidence": 1.0,
            "include_tests": False,
        },
        "find_implementations": {
            "repo": repo,
            "symbol": CLASS_NAME,
            "max_results": 10,
            "token_budget": 1000,
        },
        "find_similar_symbols": {
            "repo": repo,
            "threshold": 0.95,
            "max_clusters": 5,
            "include_tests": False,
            "scope": file_path,
            "token_budget": 1000,
        },
        "get_architecture_metrics": {"repo": repo, "top_n": 10},
        "get_call_hierarchy": {
            "repo": repo,
            "symbol_id": symbol_id,
            "direction": "callees",
            "depth": 1,
        },
        "get_class_hierarchy": {"repo": repo, "class_name": CLASS_NAME},
        "get_dead_code_v2": {
            "repo": repo,
            "min_confidence": 1.0,
            "include_tests": False,
            "max_results": 10,
        },
        "get_decorator_census": {
            "repo": repo,
            "include_sites": True,
            "max_decorators": 10,
            "max_sites_per": 1,
        },
        "get_endpoint_impact": {
            "repo": repo,
            "handler_symbol_id": symbol_id,
            "depth": 1,
            "call_depth": 1,
            "include_infra": False,
        },
        "get_extraction_candidates": {
            "repo": repo,
            "file_path": file_path,
            "min_complexity": 5,
            "min_callers": 1,
        },
        "get_group_contracts": {
            "repos": [repo, OTHER_REPO],
            "min_importers": 1,
            "max_contracts": 10,
            "token_budget": 1000,
        },
        "get_hotspots": {"repo": repo, "top_n": 10, "days": 90},
        "get_impact_preview": {
            "repo": repo,
            "symbol_id": symbol_id,
            "include_decisions": False,
        },
        "get_parity_map": {
            "source_repo": repo,
            "target_repo": repo,
            "source_path": file_path,
            "target_path": file_path,
            "rename": False,
            "include_port_plan": False,
        },
        "get_pr_risk_profile": {
            "repo": repo,
            "base_ref": target["since_sha"],
            "head_ref": target["until_sha"],
            "days": 90,
        },
        "get_project_intel": {"repo": repo, "category": "all", "scope_path": prefix},
        "get_ranked_context": {
            "repo": repo,
            "query": symbol_name,
            "token_budget": 1000,
            "strategy": "bm25",
            "fusion": False,
        },
        "get_related_symbols": {"repo": repo, "symbol_id": symbol_id, "max_results": 10},
        "get_repo_health": {"repo": repo, "days": 90},
        "get_repo_map": {
            "repo": repo,
            "token_budget": 1000,
            "scope": prefix,
            "max_per_file": 3,
        },
        "get_signal_chains": {
            "repo": repo,
            "symbol": symbol_name,
            "max_depth": 1,
            "include_tests": False,
            "include_flow_edges": False,
        },
        "get_symbol_diff": {"repo_a": repo, "repo_b": repo},
        "get_symbol_importance": {
            "repo": repo,
            "top_n": 10,
            "algorithm": "pagerank",
            "scope": prefix,
        },
        "get_tectonic_map": {"repo": repo, "days": 90, "min_plate_size": 5},
        "get_untested_symbols": {
            "repo": repo,
            "file_pattern": file_path,
            "min_confidence": 0.8,
            "max_results": 10,
        },
        "plan_refactoring": {
            "repo": repo,
            "symbol": symbol_id,
            "refactor_type": "rename",
            "new_name": f"{symbol_name}_renamed",
            "depth": 1,
        },
        "search_ast": {
            "repo": repo,
            "pattern": "lines:80+",
            "max_results": 10,
        },
        "search_columns": {"repo": repo, "query": "id", "max_results": 10},
        "search_symbols": {
            "repo": repo,
            "query": symbol_name,
            "max_results": 10,
            "detail_level": "compact",
            "fusion": False,
        },
        "suggest_corrections": {"repo": repo, "window_days": 30},
        "suggest_queries": {"repo": repo},
        "winnow_symbols": {
            "repo": repo,
            "criteria": [{"axis": "kind", "op": "eq", "value": "function"}],
            "rank_by": "name",
            "order": "asc",
            "max_results": 10,
        },
    }
    return arguments[tool]


def main() -> None:
    if not sys.flags.utf8_mode:
        raise RuntimeError("Run with Python UTF-8 mode enabled (-X utf8)")
    inventory = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tools = inventory["direct_tools_not_in_established_benchmark"]
    controller_sha = _sha256(Path(__file__))
    workers = {
        "baseline_full": base.Worker(base.BASELINE_ROOT, "baseline_full"),
        "generation_safe_hybrid": base.Worker(
            base.CANDIDATE_ROOT, "generation_safe_hybrid"
        ),
    }
    rows: list[dict[str, Any]] = []
    failures = []
    try:
        descriptions = {
            mode: worker.request({"command": "describe"})
            for mode, worker in workers.items()
        }
        for key in ("repos", "cases", "version", "source_sha"):
            if descriptions["baseline_full"][key] != descriptions[
                "generation_safe_hybrid"
            ][key]:
                raise AssertionError(f"Source trees disagree on {key}")
        fixture = workers["baseline_full"].request(
            {
                "command": "fixture",
                "repo_name": REPO_NAME,
                "target_index": TARGET_INDEX,
            }
        )

        for tool_number, tool in enumerate(tools, start=1):
            order = (
                ("baseline_full", "generation_safe_hybrid")
                if tool_number % 2
                else ("generation_safe_hybrid", "baseline_full")
            )
            pair = []
            arguments = _arguments(tool, fixture)
            for order_position, mode in enumerate(order, start=1):
                response = workers[mode].request(
                    {
                        "command": "measure",
                        "repo": REPO,
                        "repo_name": REPO_NAME,
                        "case": f"expanded_{tool}",
                        "tool": tool,
                        "profile": "expanded_direct_read_surface",
                        "arguments": arguments,
                        "target_index": TARGET_INDEX,
                        "repetition": 1,
                        "order_position": order_position,
                        "scope": "cold_generation_safe_hybrid_expanded_surface",
                        "controller_sha256": controller_sha,
                        "target_policy": "middle stride target with bounded tool-specific arguments",
                    }
                )
                pair.append(response["row"])
            if len({row["canonical_response_hash"] for row in pair}) != 1:
                failures.append({"tool": tool, "reason": "canonical_mismatch", "rows": pair})
                continue
            response_errors = [row["_response_error"] for row in pair if row["_response_error"]]
            if response_errors:
                failures.append(
                    {"tool": tool, "reason": "tool_error", "errors": response_errors}
                )
                continue
            for row in pair:
                row.pop("_canonical_response", None)
                row.pop("_response_error", None)
            rows.extend(pair)
            print(
                json.dumps(
                    {
                        "completed_tools": tool_number,
                        "total_tools": len(tools),
                        "tool": tool,
                        "baseline_wall_ms": next(
                            row["wall_ms"] for row in pair if row["mode"] == "baseline_full"
                        ),
                        "candidate_wall_ms": next(
                            row["wall_ms"]
                            for row in pair
                            if row["mode"] == "generation_safe_hybrid"
                        ),
                    }
                ),
                flush=True,
            )
    finally:
        for worker in workers.values():
            worker.close()

    if failures:
        FAILURE.parent.mkdir(parents=True, exist_ok=True)
        FAILURE.write_text(
            json.dumps(failures, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        raise AssertionError(f"Expanded surface had {len(failures)} invalid cases")

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
                "tools": len(tools),
                "rows": len(rows),
                "raw_csv": str(RAW_CSV),
                "sha256": _sha256(RAW_CSV),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
