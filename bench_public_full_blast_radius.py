"""End-to-end benchmark for every single-repo selective-hydration candidate.

The benchmark does not modify JCodeMunch source. In candidate mode it replaces
``IndexStore.load_index`` inside the process with an explicit component and row
selection prototype, then dispatches the real public tool through
``server.call_tool``. Baseline mode uses the production full loader.
"""

from __future__ import annotations

import asyncio
import csv
import gc
import hashlib
import json
import os
import posixpath
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


_SOURCE_ROOT_ENV = os.environ.get("JCM_BENCH_SOURCE_ROOT")
if not _SOURCE_ROOT_ENV:
    raise SystemExit(
        """JCM_BENCH_SOURCE_ROOT is not set.

This module measures whichever checkout it is pointed at. The driver harnesses
set it per worker subprocess from JCM_BASELINE_ROOT / JCM_CANDIDATE_ROOT, so
you normally do not set it by hand. To run this file directly:

  export JCM_BENCH_SOURCE_ROOT=/path/to/jcodemunch-mcp"""
    )
SOURCE_ROOT = Path(_SOURCE_ROOT_ENV)
if not (SOURCE_ROOT / "src" / "jcodemunch_mcp").is_dir():
    raise SystemExit(f"JCM_BENCH_SOURCE_ROOT={SOURCE_ROOT} is not a jcodemunch-mcp checkout")
sys.path.insert(0, str(SOURCE_ROOT / "src"))

import jcodemunch_mcp.config as config_module  # noqa: E402
from jcodemunch_mcp import __version__ as JCODEMUNCH_VERSION  # noqa: E402
from jcodemunch_mcp.server import call_tool  # noqa: E402
from jcodemunch_mcp.storage import result_cache_invalidate  # noqa: E402
from jcodemunch_mcp.storage.index_store import IndexStore  # noqa: E402
from jcodemunch_mcp.storage.sqlite_store import _cache_clear  # noqa: E402
from jcodemunch_mcp.tools.get_blast_radius import (  # noqa: E402
    _bfs_importers,
    _build_reverse_adjacency,
)


HERE = Path(__file__).resolve().parent
RAW_CSV = HERE / "public_full_blast_radius_raw_v2.csv"
PARITY_FAILURE = HERE / "public_full_blast_radius_parity_failure_v2.json"
TARGETS_PER_CASE = 5
REPETITIONS_PER_TARGET = 3
# Upstream repo -> LOCAL INDEX NAME. The suffixes below are index names from the
# machine that produced the shipped CSVs; jcodemunch derives them from the indexed
# path, so yours will differ. Override without editing this file:
#
#   export JCM_BENCH_REPOS='{"django/django":"django-<your-suffix>", ...}'
#
# Run list_repos to see your local names. For canonical response hashes to match
# the shipped rows, index these upstream commits:
#
#   django/django      274a1d494d11d87a1b767340d1f398f197810f93   45,561 symbols
#   fastapi/fastapi    95f8322ee1dcda7ceace7b1c4f6c9915b36d748f   13,405 symbols
#   gin-gonic/gin      34dac209ffb6ef85cc78c5d217bbb7ad001d68fd    1,834 symbols
#   expressjs/express  a3714473feb3d2908add734d340e7755fd85e0a3      471 symbols
_DEFAULT_REPOS = {
    "django/django": "django-3eb2e228",
    "expressjs/express": "express-080294c3",
    "fastapi/fastapi": "fastapi-c1d6b9c4",
    "gin-gonic/gin": "gin-87ab3d33",
}
REPOS = json.loads(os.environ["JCM_BENCH_REPOS"]) if os.environ.get("JCM_BENCH_REPOS") else dict(_DEFAULT_REPOS)
VOLATILE_KEYS = {
    "timing_ms",
    "total_tokens_saved",
    "turn_tokens_used",
    "turn_budget_remaining",
    "budget_warning",
}
BENCHMARK_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
JCODEMUNCH_SOURCE_SHA = subprocess.check_output(
    ["git", "-C", str(SOURCE_ROOT), "rev-parse", "HEAD"],
    text=True,
).strip()


@dataclass(frozen=True)
class Case:
    name: str
    tool: str
    profile: str


CASES = (
    Case("symbol_source_single", "get_symbol_source", "target_symbols"),
    Case("symbol_source_batch", "get_symbol_source", "target_symbols"),
    Case("context_single", "get_context_bundle", "target_symbols"),
    Case("context_batch", "get_context_bundle", "target_symbols"),
    Case("context_single_callers", "get_context_bundle", "all_files_target_symbols"),
    Case("context_batch_callers", "get_context_bundle", "all_files_target_symbols"),
    Case("file_content", "get_file_content", "target_files"),
    Case("file_outline_single", "get_file_outline", "target_file_symbols"),
    Case("file_outline_batch", "get_file_outline", "target_file_symbols"),
    Case("symbol_complexity", "get_symbol_complexity", "target_symbols"),
    Case("churn_symbol", "get_churn_rate", "target_symbols"),
    Case("churn_file", "get_churn_rate", "metadata"),
    Case("symbol_provenance", "get_symbol_provenance", "target_symbols"),
    Case("references_single", "find_references", "all_files"),
    Case("references_batch", "find_references", "all_files"),
    Case("references_call_chain", "find_references", "reference_call_chain"),
    Case("importers_single", "find_importers", "all_files"),
    Case("importers_batch", "find_importers", "all_files"),
    Case("check_refs_single_imports", "check_references", "all_files_definitions"),
    Case("check_refs_batch_imports", "check_references", "all_files_definitions"),
    Case("check_refs_single_content", "check_references", "all_files_definitions"),
    Case("check_refs_batch_content", "check_references", "all_files_definitions"),
    Case("file_risk", "get_file_risk", "all_files_target_file_symbols"),
    Case("changed_symbols", "get_changed_symbols", "metadata"),
    Case("changed_symbols_blast", "get_changed_symbols", "all_files"),
    Case("blast_radius_default", "get_blast_radius", "all_files_target_symbols"),
    Case("blast_radius_source", "get_blast_radius", "blast_enrichment"),
    Case("delivery_metrics", "get_delivery_metrics", "metadata"),
    Case("list_workspaces", "list_workspaces", "metadata"),
    Case("search_text", "search_text", "all_files"),
    Case("coupling_metrics", "get_coupling_metrics", "all_files"),
    Case("dependency_cycles", "get_dependency_cycles", "all_files"),
    Case("dependency_graph", "get_dependency_graph", "all_files"),
    Case("cross_repo_map_filtered", "get_cross_repo_map", "all_files"),
    Case("layer_violations", "get_layer_violations", "all_files"),
    Case("file_tree_prefix", "get_file_tree", "prefix_files"),
)


_real_config_get = config_module.get


def _config_get(key: str, default: Any = None, repo: str | None = None) -> Any:
    if key == "turn_budget_tokens":
        return 0
    if key == "output_format":
        return "json"
    if key == "cross_repo_default":
        return False
    return _real_config_get(key, default, repo)


config_module.get = _config_get


def _canonical(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _canonical(value.model_dump())
    if isinstance(value, dict):
        if value.get("type") == "text" and isinstance(value.get("text"), str):
            try:
                parsed_text = json.loads(value["text"])
            except json.JSONDecodeError:
                parsed_text = re.sub(
                    r"(?P<key>(?:_meta\.)?(?:timing_ms|total_tokens_saved|"
                    r"turn_tokens_used|turn_budget_remaining|budget_warning)=)"
                    r"(?:\"(?:[^\"\\]|\\.)*\"|[^\s|]+)",
                    r"\g<key><volatile>",
                    value["text"],
                )
                parsed_text = re.sub(
                    r"(?P<key>(?:\"\"|\")?(?:timing_ms|total_tokens_saved|"
                    r"turn_tokens_used|turn_budget_remaining|budget_warning)"
                    r"(?:\"\"|\")?:)"
                    r"(?:\"(?:[^\"\\]|\\.)*\"|-?[0-9]+(?:\.[0-9]+)?|true|false|null)",
                    r"\g<key>\"<volatile>\"",
                    parsed_text,
                )
            value = {**value, "text": parsed_text}
        return {
            key: _canonical(item)
            for key, item in sorted(value.items())
            if key not in VOLATILE_KEYS and not key.startswith("cost_avoided")
        }
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stride_positions(length: int, count: int) -> list[int]:
    if length < count:
        raise RuntimeError(f"Need {count} targets, found only {length}")
    if count == 1:
        return [length // 2]
    return [round(i * (length - 1) / (count - 1)) for i in range(count)]


def _batch_at(values: list[dict[str, str]], position: int) -> list[dict[str, str]]:
    return [values[(position + offset) % len(values)] for offset in range(3)]


@lru_cache(maxsize=None)
def _repo_fixture(repo_name: str) -> dict[str, Any]:
    store = IndexStore()
    db_path = store._sqlite._db_path("local", repo_name)
    conn = store._sqlite._connect(db_path)
    try:
        meta = store._sqlite._read_meta(conn)
        symbols = [
            {"id": str(row[0]), "name": str(row[1]), "file": str(row[2])}
            for row in conn.execute(
                "SELECT id, name, file FROM symbols ORDER BY rowid"
            ).fetchall()
            if row[0] and row[1] and row[2]
        ]
        files = [
            {"file": str(row[0])}
            for row in conn.execute("SELECT path FROM files ORDER BY rowid").fetchall()
            if row[0]
        ]
        symbol_count = int(conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0])
        file_count = int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
    finally:
        conn.close()

    source_root = str(meta.get("source_root", ""))
    commits = subprocess.check_output(
        ["git", "-C", source_root, "rev-list", "--max-count=6", "HEAD"],
        text=True,
    ).splitlines()
    if not commits:
        raise RuntimeError(f"No git commit found for {repo_name}")
    # The public benchmark checkouts are shallow snapshots. Repeating HEAD keeps
    # the change-analysis request deterministic and still exercises its index
    # hydration, git validation, parser setup, and optional import-graph setup.
    commits.extend([commits[-1]] * (6 - len(commits)))

    symbol_positions = _stride_positions(len(symbols), TARGETS_PER_CASE)
    file_positions = _stride_positions(len(files), TARGETS_PER_CASE)
    return {
        "meta": meta,
        "symbols": symbols,
        "files": files,
        "symbol_positions": symbol_positions,
        "file_positions": file_positions,
        "commits": commits,
        "symbol_count": symbol_count,
        "file_count": file_count,
    }


def _target(repo_name: str, target_index: int) -> dict[str, Any]:
    fixture = _repo_fixture(repo_name)
    symbol_pos = fixture["symbol_positions"][target_index - 1]
    file_pos = fixture["file_positions"][target_index - 1]
    symbol = fixture["symbols"][symbol_pos]
    file_entry = fixture["files"][file_pos]
    symbol_batch = _batch_at(fixture["symbols"], symbol_pos)
    file_batch = _batch_at(fixture["files"], file_pos)
    prefix = file_entry["file"].split("/", 1)[0]
    if "/" not in file_entry["file"]:
        prefix = ""
    return {
        "symbol": symbol,
        "file": file_entry["file"],
        "symbol_batch": symbol_batch,
        "file_batch": file_batch,
        "prefix": prefix,
        "since_sha": fixture["commits"][target_index],
        "until_sha": fixture["commits"][target_index - 1],
        "symbol_count": fixture["symbol_count"],
        "file_count": fixture["file_count"],
        "repo_git_head": str(fixture["meta"].get("git_head", "")),
        "repo_indexed_at": str(fixture["meta"].get("indexed_at", "")),
    }


def _arguments(case: Case, repo_name: str, target: dict[str, Any]) -> dict[str, Any]:
    args: dict[str, Any] = {"repo": f"local/{repo_name}"}
    symbol = target["symbol"]
    symbol_ids = [entry["id"] for entry in target["symbol_batch"]]
    names = [entry["name"] for entry in target["symbol_batch"]]
    files = [entry["file"] for entry in target["file_batch"]]

    if case.name in {"symbol_source_single", "context_single", "context_single_callers"}:
        args["symbol_id"] = symbol["id"]
    elif case.name in {"symbol_source_batch", "context_batch", "context_batch_callers"}:
        args["symbol_ids"] = symbol_ids
    elif case.name == "file_content":
        args["file_path"] = target["file"]
    elif case.name == "file_outline_single":
        args["file_path"] = target["file"]
    elif case.name == "file_outline_batch":
        args["file_paths"] = files
    elif case.name == "symbol_complexity":
        args["symbol_id"] = symbol["id"]
    elif case.name == "churn_symbol":
        args.update({"target": symbol["id"], "days": 30})
    elif case.name == "churn_file":
        args.update({"target": target["file"], "days": 30})
    elif case.name == "symbol_provenance":
        args.update({"symbol": symbol["id"], "max_commits": 3})
    elif case.name in {"references_single", "references_call_chain"}:
        args["identifier"] = symbol["name"]
    elif case.name == "references_batch":
        args["identifiers"] = names
    elif case.name == "importers_single":
        args.update({"file_path": target["file"], "cross_repo": False})
    elif case.name == "importers_batch":
        args.update({"file_paths": files, "cross_repo": False})
    elif case.name.startswith("check_refs_single"):
        args["identifier"] = symbol["name"]
    elif case.name.startswith("check_refs_batch"):
        args["identifiers"] = names
    elif case.name == "file_risk":
        args["file_path"] = target["file"]
    elif case.name.startswith("changed_symbols"):
        args.update(
            {
                "since_sha": target["since_sha"],
                "until_sha": target["until_sha"],
                "include_blast_radius": case.name.endswith("blast"),
            }
        )
    elif case.name.startswith("blast_radius"):
        args.update({"symbol": symbol["id"], "cross_repo": False})
    elif case.name == "delivery_metrics":
        args.update({"window_days": (30, 60, 90, 180, 365)[target["target_index"] - 1]})
    elif case.name == "search_text":
        args.update({"query": symbol["name"], "max_results": 20})
    elif case.name == "coupling_metrics":
        args["module_path"] = target["file"]
    elif case.name == "dependency_graph":
        args.update(
            {"file": target["file"], "direction": "both", "depth": 3, "cross_repo": False}
        )
    elif case.name == "cross_repo_map_filtered":
        args["repo"] = f"local/{repo_name}"
    elif case.name == "layer_violations":
        args["rules"] = [{"name": "all", "paths": ["**/*"], "may_not_import": []}]
    elif case.name == "file_tree_prefix":
        args.update({"path_prefix": target["prefix"], "include_summaries": True})

    if case.name.endswith("_callers"):
        args["include_callers"] = True
    if case.name == "references_call_chain":
        args["include_call_chain"] = True
    if case.name.endswith("_imports"):
        args["search_content"] = False
    if case.name.endswith("_content"):
        args.update({"search_content": True, "max_content_results": 20})
    if case.name == "blast_radius_source":
        args.update({"include_source": True, "source_budget": 1000})
    return args


def _where_in(column: str, values: list[str]) -> tuple[str, tuple[str, ...]]:
    if not values:
        return "1 = 0", ()
    placeholders = ",".join("?" for _ in values)
    return f"{column} IN ({placeholders})", tuple(values)


def _requested_symbol_ids(args: dict[str, Any]) -> list[str]:
    if args.get("symbol_id"):
        return [str(args["symbol_id"])]
    if args.get("symbol_ids"):
        return [str(value) for value in args["symbol_ids"]]
    if args.get("symbol") and "::" in str(args["symbol"]):
        return [str(args["symbol"])]
    if args.get("target") and "::" in str(args["target"]):
        return [str(args["target"])]
    return []


def _requested_files(args: dict[str, Any]) -> list[str]:
    values: list[str] = []
    if args.get("file_path"):
        values.append(str(args["file_path"]))
    if args.get("file_paths"):
        values.extend(str(value) for value in args["file_paths"])
    return values


def _requested_identifiers(args: dict[str, Any]) -> list[str]:
    values: list[str] = []
    if args.get("identifier"):
        values.append(str(args["identifier"]))
    if args.get("identifiers"):
        values.extend(str(value) for value in args["identifiers"])
    return values


def _reference_files(file_rows: list[Any], identifiers: list[str], limit: int) -> list[str]:
    wanted = {value.lower() for value in identifiers}
    found: set[str] = set()
    for row in file_rows:
        if not row["imports"]:
            continue
        try:
            imports = json.loads(row["imports"])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for imp in imports:
            names = {str(value).lower() for value in imp.get("names", [])}
            stem = posixpath.splitext(posixpath.basename(imp.get("specifier", "")))[0].lower()
            if names.intersection(wanted) or stem in wanted:
                found.add(str(row["path"]))
                break
    return sorted(found)[:limit]


def _selective_load(
    store: IndexStore,
    owner: str,
    name: str,
    case: Case,
    args: dict[str, Any],
):
    db_path = store._sqlite._db_path(owner, name)
    conn = store._sqlite._connect(db_path)
    try:
        conn.execute("BEGIN")
        meta = store._sqlite._read_meta(conn)
        symbol_rows: list[Any] = []
        file_rows: list[Any] = []

        if case.profile in {
            "all_files",
            "all_files_target_symbols",
            "all_files_target_file_symbols",
            "all_files_definitions",
            "reference_call_chain",
            "blast_enrichment",
        }:
            file_rows = conn.execute("SELECT * FROM files").fetchall()
        elif case.profile == "prefix_files":
            prefix = str(args.get("path_prefix", ""))
            file_rows = conn.execute(
                "SELECT * FROM files WHERE path LIKE ? ESCAPE '\\'",
                (prefix.replace("%", "\\%").replace("_", "\\_") + "%",),
            ).fetchall()

        ids = _requested_symbol_ids(args)
        if case.profile in {"target_symbols", "all_files_target_symbols", "blast_enrichment"}:
            where, params = _where_in("id", ids)
            symbol_rows = conn.execute(f"SELECT * FROM symbols WHERE {where}", params).fetchall()
        elif case.profile in {"target_file_symbols", "all_files_target_file_symbols"}:
            target_files = _requested_files(args)
            where, params = _where_in("file", target_files)
            symbol_rows = conn.execute(f"SELECT * FROM symbols WHERE {where}", params).fetchall()
        elif case.profile == "all_files_definitions":
            identifiers = [value.lower() for value in _requested_identifiers(args)]
            where, params = _where_in("lower(name)", identifiers)
            symbol_rows = conn.execute(f"SELECT * FROM symbols WHERE {where}", params).fetchall()
        elif case.profile == "reference_call_chain":
            identifiers = _requested_identifiers(args)
            reference_files = _reference_files(file_rows, identifiers, int(args.get("max_results", 50)))
            where, params = _where_in("file", reference_files)
            symbol_rows = conn.execute(f"SELECT * FROM symbols WHERE {where}", params).fetchall()
        elif case.profile == "prefix_files":
            prefix_files = [str(row["path"]) for row in file_rows]
            where, params = _where_in("file", prefix_files)
            symbol_rows = conn.execute(f"SELECT * FROM symbols WHERE {where}", params).fetchall()

        if case.profile in {"target_symbols", "target_file_symbols", "target_files"}:
            target_files = _requested_files(args)
            if symbol_rows:
                target_files.extend(str(row["file"]) for row in symbol_rows if row["file"])
            target_files = sorted(set(target_files))
            where, params = _where_in("path", target_files)
            file_rows = conn.execute(f"SELECT * FROM files WHERE {where}", params).fetchall()

        if case.profile == "blast_enrichment" and symbol_rows:
            preliminary = store._sqlite._build_index_from_rows(
                meta, symbol_rows, file_rows, owner, name
            )
            focal_file = str(symbol_rows[0]["file"])
            source_files = frozenset(preliminary.source_files)
            reverse = _build_reverse_adjacency(
                preliminary.imports or {},
                source_files,
                preliminary.alias_map,
                getattr(preliminary, "psr4_map", None),
            )
            importer_files, _ = _bfs_importers(
                focal_file, reverse, int(args.get("depth", 1))
            )
            where, params = _where_in("file", sorted(importer_files))
            enrichment_rows = conn.execute(
                f"SELECT * FROM symbols WHERE {where}", params
            ).fetchall()
            by_id = {str(row["id"]): row for row in [*symbol_rows, *enrichment_rows]}
            symbol_rows = list(by_id.values())

        return store._sqlite._build_index_from_rows(
            meta, symbol_rows, file_rows, owner, name
        )
    finally:
        conn.close()


def _measure(
    task: tuple[str, str, Case, str, int, int, int]
) -> dict[str, Any]:
    repo, repo_name, case, mode, target_index, repetition, order_position = task
    target = _target(repo_name, target_index)
    target["target_index"] = target_index
    arguments = _arguments(case, repo_name, target)
    original_load = IndexStore.load_index
    load_calls = 0
    load_ms = 0.0

    result_cache_invalidate()
    asyncio.run(call_tool(case.tool, arguments))
    result_cache_invalidate()
    _cache_clear()
    gc.collect()

    def measured_load(self: IndexStore, owner: str, name: str, *args: Any, **kwargs: Any):
        nonlocal load_calls, load_ms
        load_calls += 1
        started = time.perf_counter_ns()
        if mode == "candidate":
            value = _selective_load(self, owner, name, case, arguments)
        else:
            value = original_load(self, owner, name, *args, **kwargs)
            if mode == "promoted" and value is not None:
                len(value.symbols)
        load_ms += (time.perf_counter_ns() - started) / 1_000_000
        return value

    IndexStore.load_index = measured_load
    try:
        result_cache_invalidate()
        started = time.perf_counter_ns()
        result = asyncio.run(call_tool(case.tool, arguments))
        wall_ms = (time.perf_counter_ns() - started) / 1_000_000
    finally:
        IndexStore.load_index = original_load

    canonical = _canonical(result)
    serialized = json.dumps(result, sort_keys=True, ensure_ascii=False, default=str)
    return {
        "repo": repo,
        "repo_name": repo_name,
        "case": case.name,
        "tool": case.tool,
        "profile": case.profile,
        "mode": mode,
        "target_index": target_index,
        "target_value": json.dumps(arguments, sort_keys=True, ensure_ascii=False),
        "repetition": repetition,
        "order_position": order_position,
        "symbol_count": target["symbol_count"],
        "file_count": target["file_count"],
        "repo_git_head": target["repo_git_head"],
        "repo_indexed_at": target["repo_indexed_at"],
        "wall_ms": wall_ms,
        "load_phase_ms": load_ms,
        "load_phase_pct": (load_ms / wall_ms) * 100 if wall_ms else 0.0,
        "load_calls": load_calls,
        "response_bytes": len(serialized.encode("utf-8")),
        "canonical_response_hash": _hash(canonical),
        "_canonical_response": canonical,
        "jcodemunch_version": JCODEMUNCH_VERSION,
        "jcodemunch_source_sha": JCODEMUNCH_SOURCE_SHA,
        "benchmark_sha256": BENCHMARK_SHA256,
        "python_utf8_mode": int(sys.flags.utf8_mode),
    }


def main() -> None:
    if not sys.flags.utf8_mode:
        raise RuntimeError("Run this benchmark with Python UTF-8 mode enabled (-X utf8)")
    tasks: list[tuple[str, str, Case, str, int, int, int]] = []
    for repetition in range(1, REPETITIONS_PER_TARGET + 1):
        modes = ("baseline", "candidate") if repetition % 2 else (
            "candidate",
            "baseline",
        )
        for repo, repo_name in REPOS.items():
            for case in CASES:
                for target_index in range(1, TARGETS_PER_CASE + 1):
                    for order_position, mode in enumerate(modes, start=1):
                        tasks.append(
                            (
                                repo,
                                repo_name,
                                case,
                                mode,
                                target_index,
                                repetition,
                                order_position,
                            )
                        )

    rows: list[dict[str, Any]] = []
    for task_number, task in enumerate(tasks, start=1):
        rows.append(_measure(task))
        if task_number % 50 == 0:
            print(json.dumps({"completed": task_number, "total": len(tasks)}), flush=True)

    for repo in REPOS:
        for case in CASES:
            case_rows = [
                row for row in rows if row["repo"] == repo and row["case"] == case.name
            ]
            for target_index in range(1, TARGETS_PER_CASE + 1):
                target_rows = [
                    row for row in case_rows if row["target_index"] == target_index
                ]
                if len({row["canonical_response_hash"] for row in target_rows}) == 1:
                    continue
                examples = {}
                for mode in ("baseline", "candidate"):
                    examples[mode] = next(
                        row["_canonical_response"]
                        for row in target_rows
                        if row["mode"] == mode
                    )
                PARITY_FAILURE.write_text(
                    json.dumps(
                        {
                            "repo": repo,
                            "case": case.name,
                            "target_index": target_index,
                            "examples": examples,
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                raise AssertionError(
                    f"Response parity failed for {repo} {case.name} target {target_index}"
                )
    if any(row["load_calls"] != 1 for row in rows):
        bad = [row for row in rows if row["load_calls"] != 1][:5]
        raise AssertionError(f"Unexpected load count: {bad}")

    with RAW_CSV.open("w", newline="", encoding="utf-8") as stream:
        output_rows = [
            {key: value for key, value in row.items() if key != "_canonical_response"}
            for row in rows
        ]
        writer = csv.DictWriter(stream, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)

    print(json.dumps({"status": "ok", "rows": len(rows), "raw_csv": str(RAW_CSV)}))


if __name__ == "__main__":
    main()
