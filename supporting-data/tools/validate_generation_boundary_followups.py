"""Validate warm, concurrent, branch, and write-prefix selective hydration behavior.

This is a focused follow-up harness. It preserves the existing benchmark archive
and writes one additive CSV under supporting-data/source-runs.
"""

from __future__ import annotations

import concurrent.futures
import csv
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent

def _root_from_env(var: str, what: str) -> Path:
    """Resolve a checkout root from the environment.

    The original run compared two local worktrees. Point these at your own
    checkouts: baseline at c2201a55 (v1.108.207), candidate at a tree
    carrying the prototype under test.
    """
    value = os.environ.get(var)
    if not value:
        raise SystemExit(f"""{var} is not set.
  Expected: {what}

  export JCM_BASELINE_ROOT=/path/to/jcodemunch-mcp-at-c2201a55
  export JCM_CANDIDATE_ROOT=/path/to/checkout-with-prototype""")
    root = Path(value)
    if not (root / "src" / "jcodemunch_mcp").is_dir():
        raise SystemExit(f"{var}={root} is not a jcodemunch-mcp checkout")
    return root

PACKAGE_ROOT = HERE.parents[1]
OUTPUT = PACKAGE_ROOT / "supporting-data" / "source-runs" / "generation_boundary_followups_v1.csv"
BASELINE_SOURCE = _root_from_env("JCM_BASELINE_ROOT", "a clean checkout at c2201a55")
CANDIDATE_SOURCE = _root_from_env("JCM_CANDIDATE_ROOT", "a checkout carrying the prototype")
REPO_NAME = "django-3eb2e228"
REPO_ID = f"local/{REPO_NAME}"
SEQUENTIAL_REPS = 5
CONCURRENT_REPS = 3
CONCURRENCY = 8
VOLATILE_KEYS = {
    "timing_ms",
    "total_tokens_saved",
    "turn_tokens_used",
    "turn_budget_remaining",
    "budget_warning",
}
FIELDS = [
    "record_type",
    "mode",
    "scenario",
    "repetition",
    "concurrency",
    "target_count",
    "wall_ms",
    "canonical_hash",
    "parity_ok",
    "core_parity_ok",
    "parity_difference",
    "symbols_loaded",
    "source_version",
    "source_sha",
    "source_dirty",
    "source_dirty_paths",
    "benchmark_sha256",
    "detail",
]


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _canonical(item)
            for key, item in sorted(value.items())
            if key not in VOLATILE_KEYS
        }
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _hash(value: Any) -> str:
    encoded = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _diagnostic(value: Any) -> Any:
    canonical = _canonical(value)
    if isinstance(canonical, dict):
        result = {}
        for key, item in canonical.items():
            if key == "source" and isinstance(item, str):
                result["source_length"] = len(item)
                result["source_sha256"] = hashlib.sha256(item.encode("utf-8")).hexdigest()
            else:
                result[key] = _diagnostic(item)
        return result
    if isinstance(canonical, list):
        return [_diagnostic(item) for item in canonical]
    return canonical


def _source_sha(source: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()


def _source_status(source: Path) -> tuple[int, str]:
    lines = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain"], text=True
    ).splitlines()
    paths = [line[3:] for line in lines if len(line) > 3]
    return int(bool(lines)), json.dumps(paths, separators=(",", ":"))


def _source_version(source: Path) -> str:
    with (source / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def _copy_database(IndexStore, destination: Path) -> None:
    source_store = IndexStore()
    source_db = source_store._sqlite._db_path("local", REPO_NAME)
    target_db = destination / source_db.name
    source = sqlite3.connect(source_db)
    target = sqlite3.connect(target_db)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _targets(IndexStore, count: int = CONCURRENCY) -> list[str]:
    store = IndexStore()
    db_path = store._sqlite._db_path("local", REPO_NAME)
    conn = store._sqlite._connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id FROM symbols WHERE byte_length > 0 ORDER BY rowid LIMIT ?",
            (count,),
        ).fetchall()
    finally:
        conn.close()
    return [str(row["id"]) for row in rows]


def _worker(mode: str) -> list[dict[str, Any]]:
    source = BASELINE_SOURCE if mode == "baseline" else CANDIDATE_SOURCE
    sys.path.insert(0, str(source / "src"))

    from jcodemunch_mcp.storage import result_cache_invalidate
    from jcodemunch_mcp.storage.index_store import IndexStore
    from jcodemunch_mcp.storage.sqlite_store import _cache_clear
    from jcodemunch_mcp.tools.get_symbol import get_symbol_source

    targets = _targets(IndexStore)
    source_sha = _source_sha(source)
    source_version = _source_version(source)
    source_dirty, source_dirty_paths = _source_status(source)
    benchmark_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    rows: list[dict[str, Any]] = []

    def clear() -> None:
        _cache_clear()
        result_cache_invalidate()

    def call(storage: Path, symbol_id: str) -> tuple[dict, float, bool]:
        started = time.perf_counter_ns()
        result = get_symbol_source(
            repo=REPO_ID,
            symbol_id=symbol_id,
            storage_path=str(storage),
        )
        wall_ms = (time.perf_counter_ns() - started) / 1_000_000
        store = IndexStore(base_path=str(storage))
        index = store.load_index("local", REPO_NAME)
        symbols = getattr(index, "symbols", None)
        loaded = bool(getattr(symbols, "loaded", True))
        return result, wall_ms, loaded

    def add(
        scenario: str,
        repetition: int,
        wall_ms: float,
        result: Any,
        loaded: bool,
        *,
        concurrency: int = 1,
        target_count: int = 1,
        detail: str = "",
    ) -> None:
        rows.append(
            {
                "record_type": "measurement",
                "mode": mode,
                "scenario": scenario,
                "repetition": repetition,
                "concurrency": concurrency,
                "target_count": target_count,
                "wall_ms": f"{wall_ms:.6f}",
                "canonical_hash": _hash(result),
                "parity_ok": "",
                "core_parity_ok": "",
                "parity_difference": "",
                "symbols_loaded": int(loaded),
                "source_version": source_version,
                "source_sha": source_sha,
                "source_dirty": source_dirty,
                "source_dirty_paths": source_dirty_paths,
                "benchmark_sha256": benchmark_sha,
                "detail": detail,
            }
        )

    def branch_sparse_validation(storage_path: Path) -> None:
        branch = "followup-validation"
        store = IndexStore(base_path=str(storage_path))
        db_path = store._sqlite._db_path("local", REPO_NAME)
        conn = store._sqlite._connect(db_path)
        try:
            file_rows = conn.execute(
                "SELECT file, COUNT(*) AS cnt FROM symbols "
                "GROUP BY file HAVING cnt > 0 ORDER BY file LIMIT 3"
            ).fetchall()
            modified_file, deleted_file, unaffected_file = [
                str(row["file"]) for row in file_rows
            ]
            modified_rows = conn.execute(
                "SELECT * FROM symbols WHERE file = ? ORDER BY rowid",
                (modified_file,),
            ).fetchall()
            unaffected_row = conn.execute(
                "SELECT * FROM symbols WHERE file = ? ORDER BY rowid LIMIT 1",
                (unaffected_file,),
            ).fetchone()
            modified_symbols = [
                store._sqlite._row_to_symbol_dict(row) for row in modified_rows
            ]
            modified_symbols[0] = dict(modified_symbols[0])
            modified_symbols[0]["summary"] = "branch overlay validation"
            added_symbol = dict(modified_symbols[0])
            added_symbol["id"] = "followup::BranchAdded#function"
            added_symbol["file"] = "followup_branch_added.py"
            added_symbol["name"] = "BranchAdded"
            conn.execute("BEGIN")
            conn.executemany(
                "INSERT OR REPLACE INTO branch_deltas "
                "(branch, file, action, symbol_data, file_hash, file_mtime_ns, "
                "file_language, file_summary, file_imports, file_size_bytes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        branch,
                        modified_file,
                        "modify",
                        json.dumps(modified_symbols),
                        "branch-modified",
                        None,
                        "python",
                        "",
                        "[]",
                        None,
                    ),
                    (branch, deleted_file, "delete", None, None, None, None, None, None, None),
                    (
                        branch,
                        added_symbol["file"],
                        "add",
                        json.dumps([added_symbol]),
                        "branch-added",
                        None,
                        "python",
                        "",
                        "[]",
                        None,
                    ),
                ],
            )
            conn.execute(
                "INSERT OR REPLACE INTO branch_meta "
                "(branch, git_head, indexed_at, base_head) VALUES (?, ?, ?, ?)",
                (branch, "branch-head", "now", ""),
            )
            conn.commit()
            unaffected_id = str(unaffected_row["id"])
            modified_id = str(modified_symbols[0]["id"])
            modified_name = str(modified_symbols[0]["name"])
        finally:
            conn.close()

        clear()
        expected = store.load_index("local", REPO_NAME, branch=branch)
        if expected is None:
            raise RuntimeError("Branch-composed index did not load")

        def sparse_read(kind: str, value: str):
            read_conn = store._sqlite._connect(db_path)
            try:
                read_conn.execute("BEGIN")
                delta_rows = read_conn.execute(
                    "SELECT file, action, symbol_data FROM branch_deltas "
                    "WHERE branch = ?",
                    (branch,),
                ).fetchall()
                entries = []
                for row in delta_rows:
                    entry = {"file": str(row["file"]), "action": str(row["action"])}
                    if row["symbol_data"]:
                        entry["symbols"] = json.loads(str(row["symbol_data"]))
                    entries.append(entry)
                affected = {str(entry["file"]) for entry in entries}
                delta_symbols = [
                    symbol
                    for entry in entries
                    if entry.get("action") in {"add", "modify"}
                    for symbol in entry.get("symbols", [])
                ]
                if kind == "id":
                    for symbol in delta_symbols:
                        if str(symbol.get("id")) == value:
                            return symbol
                    row = read_conn.execute(
                        "SELECT * FROM symbols WHERE id = ?", (value,)
                    ).fetchone()
                    if row is None or str(row["file"]) in affected:
                        return None
                    return store._sqlite._row_to_symbol_dict(row)
                if kind == "file":
                    if value in affected:
                        return [
                            symbol
                            for symbol in delta_symbols
                            if str(symbol.get("file")) == value
                        ]
                    rows = read_conn.execute(
                        "SELECT * FROM symbols WHERE file = ? ORDER BY rowid", (value,)
                    ).fetchall()
                    return [store._sqlite._row_to_symbol_dict(row) for row in rows]
                rows = read_conn.execute(
                    "SELECT * FROM symbols WHERE name = ? ORDER BY rowid", (value,)
                ).fetchall()
                base = [
                    store._sqlite._row_to_symbol_dict(row)
                    for row in rows
                    if str(row["file"]) not in affected
                ]
                return base + [
                    symbol for symbol in delta_symbols if str(symbol.get("name")) == value
                ]
            finally:
                read_conn.close()

        checks = {
            "unaffected_id": sparse_read("id", unaffected_id) == expected.get_symbol(unaffected_id),
            "modified_id": sparse_read("id", modified_id) == expected.get_symbol(modified_id),
            "added_id": sparse_read("id", str(added_symbol["id"]))
            == expected.get_symbol(str(added_symbol["id"])),
            "modified_file": sparse_read("file", modified_file)
            == [symbol for symbol in expected.symbols if symbol.get("file") == modified_file],
            "deleted_file": sparse_read("file", deleted_file)
            == [symbol for symbol in expected.symbols if symbol.get("file") == deleted_file],
            "added_file": sparse_read("file", str(added_symbol["file"]))
            == [
                symbol
                for symbol in expected.symbols
                if symbol.get("file") == added_symbol["file"]
            ],
            "name_order": sparse_read("name", modified_name)
            == [symbol for symbol in expected.symbols if symbol.get("name") == modified_name],
        }
        if not all(checks.values()):
            raise RuntimeError(f"Branch sparse contract failed: {checks}")

        for repetition in range(SEQUENTIAL_REPS):
            clear()
            started = time.perf_counter_ns()
            full = store.load_index("local", REPO_NAME, branch=branch)
            full_result = full.get_symbol(unaffected_id) if full else None
            full_ms = (time.perf_counter_ns() - started) / 1_000_000
            add(
                "branch_full_compose",
                repetition,
                full_ms,
                full_result,
                True,
                detail=json.dumps(checks, sort_keys=True),
            )
            rows[-1]["mode"] = "branch_full"
            rows[-1]["parity_ok"] = 1
            rows[-1]["core_parity_ok"] = 1

            started = time.perf_counter_ns()
            sparse_result = sparse_read("id", unaffected_id)
            sparse_ms = (time.perf_counter_ns() - started) / 1_000_000
            add(
                "branch_sparse_overlay",
                repetition,
                sparse_ms,
                sparse_result,
                False,
                detail=json.dumps(checks, sort_keys=True),
            )
            rows[-1]["mode"] = "branch_sparse"
            rows[-1]["parity_ok"] = 1
            rows[-1]["core_parity_ok"] = 1

    storage = Path(IndexStore().base_path)
    with tempfile.TemporaryDirectory(prefix=f"generation-{mode}-", dir=PACKAGE_ROOT) as tmp:
        mutation_storage = Path(tmp)
        _copy_database(IndexStore, mutation_storage)

        for repetition in range(SEQUENTIAL_REPS):
            clear()
            result, wall_ms, loaded = call(storage, targets[repetition % len(targets)])
            add("cold_distinct", repetition, wall_ms, result, loaded)

        clear()
        for repetition in range(SEQUENTIAL_REPS):
            result, wall_ms, loaded = call(storage, targets[0])
            add("warm_same", repetition, wall_ms, result, loaded)

        clear()
        for repetition in range(SEQUENTIAL_REPS):
            result, wall_ms, loaded = call(storage, targets[repetition])
            add("warm_distinct", repetition, wall_ms, result, loaded)

        def concurrent_batch(scenario: str, same_target: bool, repetition: int) -> None:
            clear()
            if scenario.startswith("concurrent_warm"):
                call(storage, targets[0])
            barrier = threading.Barrier(CONCURRENCY)

            def task(position: int):
                barrier.wait()
                symbol_id = targets[0] if same_target else targets[position]
                return call(storage, symbol_id)

            started = time.perf_counter_ns()
            with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
                values = list(pool.map(task, range(CONCURRENCY)))
            batch_ms = (time.perf_counter_ns() - started) / 1_000_000
            payload = [value[0] for value in values]
            diagnostics = [_diagnostic(item) for item in payload]
            add(
                scenario,
                repetition,
                batch_ms,
                payload,
                any(value[2] for value in values),
                concurrency=CONCURRENCY,
                target_count=CONCURRENCY,
                detail=json.dumps(diagnostics, separators=(",", ":")),
            )

        for repetition in range(CONCURRENT_REPS):
            concurrent_batch("concurrent_cold_same", True, repetition)
            concurrent_batch("concurrent_cold_distinct", False, repetition)
            concurrent_batch("concurrent_warm_same", True, repetition)
            concurrent_batch("concurrent_warm_distinct", False, repetition)

        if mode == "candidate":
            clear()
            store = IndexStore(base_path=str(mutation_storage))
            index = store.load_index("local", REPO_NAME)
            symbols = index.symbols
            first_file = index.source_files[0]
            before = bool(getattr(symbols, "loaded", True))
            _ = index.file_hashes.get(first_file)
            after_metadata = bool(getattr(symbols, "loaded", True))
            count_started = time.perf_counter_ns()
            conn = store._sqlite._connect(store._sqlite._db_path("local", REPO_NAME))
            try:
                sql_count = int(conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0])
            finally:
                conn.close()
            count_ms = (time.perf_counter_ns() - count_started) / 1_000_000
            add(
                "metadata_and_sql_count_stay_sparse",
                0,
                count_ms,
                {"symbol_count": sql_count},
                after_metadata,
                detail=f"loaded_before={int(before)}",
            )

            update_started = time.perf_counter_ns()
            store.incremental_save(
                owner="local",
                name=REPO_NAME,
                changed_files=[],
                new_files=[],
                deleted_files=[],
                new_symbols=[],
                raw_files={},
                file_mtimes={first_file: int(index.file_mtimes.get(first_file, 0)) + 1},
            )
            update_ms = (time.perf_counter_ns() - update_started) / 1_000_000
            add(
                "mtime_only_generic_write_promotes",
                0,
                update_ms,
                {"updated": True},
                bool(getattr(symbols, "loaded", True)),
                detail="generic incremental_save path",
            )
            branch_sparse_validation(mutation_storage)

    return rows


def _run_worker(mode: str) -> list[dict[str, Any]]:
    env = dict(os.environ)
    env["JCM_GENERATION_FOLLOWUP_WORKER"] = mode
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    return json.loads(completed.stdout)


def _mark_parity(rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in rows:
        if row["scenario"] in {
            "metadata_and_sql_count_stay_sparse",
            "mtime_only_generic_write_promotes",
        }:
            continue
        key = (row["scenario"], row["repetition"])
        grouped.setdefault(key, {})[row["mode"]] = row

    def without_index_channel(value: Any) -> Any:
        if isinstance(value, dict):
            result = {key: without_index_channel(item) for key, item in value.items()}
            channels = result.get("_meta", {}).get("verdict", {}).get("channels")
            if isinstance(channels, dict):
                channels.pop("index", None)
            return result
        if isinstance(value, list):
            return [without_index_channel(item) for item in value]
        return value

    for (scenario, _), pair in grouped.items():
        if "baseline" not in pair or "candidate" not in pair:
            continue
        baseline = pair["baseline"]
        candidate = pair["candidate"]
        full_parity = baseline["canonical_hash"] == candidate["canonical_hash"]
        core_parity = full_parity
        difference = ""
        if scenario.startswith("concurrent_") and not full_parity:
            baseline_detail = json.loads(str(baseline["detail"]))
            candidate_detail = json.loads(str(candidate["detail"]))
            core_parity = without_index_channel(baseline_detail) == without_index_channel(
                candidate_detail
            )
            if core_parity:
                difference = "verdict.channels.index: fresh vs rebuilding"
        for row in (baseline, candidate):
            row["parity_ok"] = int(full_parity)
            row["core_parity_ok"] = int(core_parity)
            row["parity_difference"] = difference


def main() -> None:
    worker = os.environ.get("JCM_GENERATION_FOLLOWUP_WORKER")
    if worker:
        print(json.dumps(_worker(worker), separators=(",", ":")))
        return

    rows = _run_worker("baseline") + _run_worker("candidate")
    _mark_parity(rows)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    parity_rows = [row for row in rows if row["core_parity_ok"] != ""]
    if not parity_rows or not all(row["core_parity_ok"] == 1 for row in parity_rows):
        raise RuntimeError("Baseline and candidate responses differed beyond the known verdict flag")
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "rows": len(rows),
                "parity_rows": len(parity_rows),
                "parity_ok": sum(row["parity_ok"] == 1 for row in parity_rows),
                "core_parity_ok": sum(
                    row["core_parity_ok"] == 1 for row in parity_rows
                ),
                "known_concurrency_verdict_mismatches": sum(
                    bool(row["parity_difference"]) for row in parity_rows
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
