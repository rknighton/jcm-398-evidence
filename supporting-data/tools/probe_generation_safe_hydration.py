from __future__ import annotations

import os
import csv
import gc
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Any, Callable


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

EVIDENCE_ROOT = HERE.parents[1]
OUTPUT = (
    EVIDENCE_ROOT
    / "supporting-data"
    / "source-runs"
    / "generation_boundary_architecture_probe_v1.csv"
)
CANDIDATE_SOURCE = _root_from_env("JCM_CANDIDATE_ROOT", "a checkout carrying the prototype")
REPO_NAME = "django-3eb2e228"
REPO_ID = f"local/{REPO_NAME}"
REPETITIONS = 5
FIELDS = [
    "repo",
    "repo_name",
    "case",
    "scope",
    "tool",
    "profile",
    "mode",
    "order_position",
    "target_index",
    "target_value",
    "repetition",
    "symbol_count",
    "file_count",
    "database_size_bytes",
    "elapsed_ms",
    "load_phase_ms",
    "symbol_hash",
    "repo_indexed_at",
    "jcodemunch_version",
    "jcodemunch_source_sha",
    "benchmark_sha256",
    "source_dirty_paths",
    "parity_debug_json",
]


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(CANDIDATE_SOURCE), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.stdout.strip()


def _sha(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _copy_database(source_db: Path, destination: Path) -> Path:
    target_db = destination / source_db.name
    source = sqlite3.connect(source_db)
    target = sqlite3.connect(target_db)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return target_db


def _read_target(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM symbols WHERE byte_length > 0 ORDER BY rowid LIMIT 1"
    ).fetchone()
    if row is None:
        raise RuntimeError("Probe database has no symbol with source content")
    return row


def _mutate_generation(
    connect: Callable[[Path], sqlite3.Connection],
    db_path: Path,
    target_id: str,
    marker: str,
) -> None:
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE symbols SET summary = ? WHERE id = ?",
            (marker, target_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("indexed_at", marker),
        )
        conn.commit()
    finally:
        conn.close()


def _build_snapshot_index(store: Any, db_path: Path) -> tuple[Any, sqlite3.Connection]:
    conn = store._sqlite._connect(db_path)
    conn.execute("BEGIN")
    meta = store._sqlite._read_meta(conn)
    file_rows = conn.execute("SELECT * FROM files").fetchall()

    def load_all() -> list[dict]:
        rows = conn.execute("SELECT * FROM symbols").fetchall()
        return [store._sqlite._row_to_symbol_dict(row) for row in rows]

    def load_one(symbol_id: str) -> dict | None:
        row = conn.execute(
            "SELECT * FROM symbols WHERE id = ?",
            (symbol_id,),
        ).fetchone()
        return store._sqlite._row_to_symbol_dict(row) if row is not None else None

    def load_file(file_path: str) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM symbols WHERE file = ?",
            (file_path,),
        ).fetchall()
        return [store._sqlite._row_to_symbol_dict(row) for row in rows]

    def load_name(name: str, case_sensitive: bool) -> list[dict]:
        if case_sensitive:
            rows = conn.execute(
                "SELECT * FROM symbols WHERE name = ?",
                (name,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM symbols WHERE lower(name) = ?",
                (name.lower(),),
            ).fetchall()
        return [store._sqlite._row_to_symbol_dict(row) for row in rows]

    def load_files(file_paths: list[str]) -> list[dict]:
        if not file_paths:
            return []
        placeholders = ",".join("?" for _ in file_paths)
        rows = conn.execute(
            f"SELECT * FROM symbols WHERE file IN ({placeholders})",
            tuple(file_paths),
        ).fetchall()
        return [store._sqlite._row_to_symbol_dict(row) for row in rows]

    index = store._sqlite._build_index_from_rows(
        meta,
        [],
        file_rows,
        "local",
        REPO_NAME,
        symbol_loaders=(load_all, load_one, load_file, load_name, load_files),
    )
    return index, conn


def main() -> None:
    sys.path.insert(0, str(CANDIDATE_SOURCE / "src"))

    from jcodemunch_mcp.storage.index_store import IndexStore
    from jcodemunch_mcp.storage.sqlite_store import _cache_clear

    source_store = IndexStore()
    source_db = source_store._sqlite._db_path("local", REPO_NAME)
    source_conn = source_store._sqlite._connect(source_db)
    try:
        target_row = _read_target(source_conn)
        target_id = str(target_row["id"])
        symbol_count = int(
            source_conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        )
        file_count = int(
            source_conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        )
        indexed_at = str(
            source_conn.execute(
                "SELECT value FROM meta WHERE key = 'indexed_at'"
            ).fetchone()[0]
        )
    finally:
        source_conn.close()

    source_sha = _git("rev-parse", "HEAD")
    dirty_paths = [line[3:] for line in _git("status", "--porcelain").splitlines()]
    with (CANDIDATE_SOURCE / "pyproject.toml").open("rb") as handle:
        version = str(tomllib.load(handle)["project"]["version"])
    benchmark_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    common = {
        "repo": "django/django",
        "repo_name": REPO_NAME,
        "scope": "generation_boundary_architecture",
        "tool": "get_symbol_source",
        "profile": "exact_symbol_storage_phase",
        "target_index": "0",
        "target_value": target_id,
        "symbol_count": str(symbol_count),
        "file_count": str(file_count),
        "database_size_bytes": str(source_db.stat().st_size),
        "repo_indexed_at": indexed_at,
        "jcodemunch_version": version,
        "jcodemunch_source_sha": source_sha,
        "benchmark_sha256": benchmark_sha,
        "source_dirty_paths": json.dumps(dirty_paths, separators=(",", ":")),
    }
    rows: list[dict[str, str]] = []

    def add(
        case: str,
        mode: str,
        repetition: int,
        elapsed_ms: float,
        result: Any,
        detail: dict[str, Any],
        load_phase_ms: float | None = None,
    ) -> None:
        row = {field: "" for field in FIELDS}
        row.update(common)
        row.update(
            {
                "case": case,
                "mode": mode,
                "repetition": str(repetition),
                "order_position": str(detail.get("order_position", "")),
                "elapsed_ms": f"{elapsed_ms:.6f}",
                "load_phase_ms": (
                    f"{load_phase_ms:.6f}" if load_phase_ms is not None else ""
                ),
                "symbol_hash": _sha(result),
                "parity_debug_json": json.dumps(
                    detail,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
        )
        rows.append(row)

    with tempfile.TemporaryDirectory(
        prefix="generation-architecture-",
        dir=EVIDENCE_ROOT,
    ) as temp_name:
        temp_root = Path(temp_name)

        timing_root = temp_root / "timing"
        timing_root.mkdir()
        timing_db = _copy_database(source_db, timing_root)
        timing_store = IndexStore(base_path=str(timing_root))

        def run_baseline_full() -> tuple[Any, float, float | None, dict[str, Any]]:
            _cache_clear()
            started = time.perf_counter_ns()
            full_conn = timing_store._sqlite._connect(timing_db)
            try:
                full_conn.execute("BEGIN")
                meta = timing_store._sqlite._read_meta(full_conn)
                file_rows = full_conn.execute("SELECT * FROM files").fetchall()
                symbol_rows = full_conn.execute("SELECT * FROM symbols").fetchall()
                full_index = timing_store._sqlite._build_index_from_rows(
                    meta,
                    symbol_rows,
                    file_rows,
                    "local",
                    REPO_NAME,
                )
                full_result = full_index.get_symbol(target_id)
            finally:
                full_conn.close()
            elapsed = (time.perf_counter_ns() - started) / 1_000_000
            return (
                full_result,
                elapsed,
                None,
                {"snapshot_consistent": True, "fully_hydrated": True},
            )

        def run_shared_lazy() -> tuple[Any, float, float | None, dict[str, Any]]:
            _cache_clear()
            started = time.perf_counter_ns()
            shared_index = timing_store.load_index("local", REPO_NAME)
            loaded_ms = (time.perf_counter_ns() - started) / 1_000_000
            if shared_index is None:
                raise RuntimeError("Shared lazy index failed to load")
            shared_result = shared_index.get_symbol(target_id)
            elapsed = (time.perf_counter_ns() - started) / 1_000_000
            return (
                shared_result,
                elapsed,
                loaded_ms,
                {
                    "snapshot_consistent_without_writer": True,
                    "fully_hydrated": bool(shared_index.symbols.loaded),
                },
            )

        def run_request_snapshot() -> tuple[Any, float, float | None, dict[str, Any]]:
            _cache_clear()
            started = time.perf_counter_ns()
            snapshot_index, snapshot_conn = _build_snapshot_index(
                timing_store,
                timing_db,
            )
            loaded_ms = (time.perf_counter_ns() - started) / 1_000_000
            try:
                snapshot_result = snapshot_index.get_symbol(target_id)
            finally:
                snapshot_conn.close()
            elapsed = (time.perf_counter_ns() - started) / 1_000_000
            return (
                snapshot_result,
                elapsed,
                loaded_ms,
                {
                    "snapshot_consistent": True,
                    "fully_hydrated": bool(snapshot_index.symbols.loaded),
                },
            )

        timing_modes = [
            ("baseline_full", run_baseline_full),
            ("shared_lazy_v1", run_shared_lazy),
            ("request_snapshot", run_request_snapshot),
        ]
        for repetition in range(REPETITIONS):
            rotated = timing_modes[repetition % len(timing_modes) :] + timing_modes[
                : repetition % len(timing_modes)
            ]
            repetition_hashes: dict[str, str] = {}
            for order_position, (mode, operation) in enumerate(rotated):
                gc.collect()
                result, elapsed, loaded_ms, detail = operation()
                result_hash = _sha(result)
                detail["order_position"] = order_position
                add(
                    "cold_exact_storage",
                    mode,
                    repetition,
                    elapsed,
                    result,
                    detail,
                    loaded_ms,
                )
                repetition_hashes[mode] = result_hash
            if len(set(repetition_hashes.values())) != 1:
                raise RuntimeError(
                    f"Storage-path parity failed at repetition {repetition}: "
                    f"{repetition_hashes}"
                )

        mixed_root = temp_root / "mixed"
        mixed_root.mkdir()
        mixed_db = _copy_database(source_db, mixed_root)
        mixed_store = IndexStore(base_path=str(mixed_root))
        _cache_clear()
        old_index = mixed_store.load_index("local", REPO_NAME)
        if old_index is None:
            raise RuntimeError("Mixed-generation probe index failed to load")
        old_generation = old_index.indexed_at
        mixed_marker = "probe-mixed-generation"
        _mutate_generation(
            mixed_store._sqlite._connect,
            mixed_db,
            target_id,
            mixed_marker,
        )
        started = time.perf_counter_ns()
        mixed_symbol = old_index.get_symbol(target_id)
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        mixed_observed = bool(
            mixed_symbol
            and old_index.indexed_at == old_generation
            and mixed_symbol.get("summary") == mixed_marker
        )
        add(
            "writer_commits_after_index_load",
            "shared_lazy_v1",
            0,
            elapsed,
            mixed_symbol,
            {
                "captured_generation": old_generation,
                "symbol_generation": mixed_marker,
                "mixed_generation_observed": mixed_observed,
            },
        )
        if not mixed_observed:
            raise RuntimeError("Expected shared-lazy generation mixture was not observed")

        snapshot_root = temp_root / "snapshot"
        snapshot_root.mkdir()
        snapshot_db = _copy_database(source_db, snapshot_root)
        snapshot_store = IndexStore(base_path=str(snapshot_root))
        snapshot_index, snapshot_conn = _build_snapshot_index(
            snapshot_store,
            snapshot_db,
        )
        snapshot_generation = snapshot_index.indexed_at
        snapshot_marker = "probe-request-snapshot"
        _mutate_generation(
            snapshot_store._sqlite._connect,
            snapshot_db,
            target_id,
            snapshot_marker,
        )
        started = time.perf_counter_ns()
        try:
            snapshot_symbol = snapshot_index.get_symbol(target_id)
        finally:
            snapshot_conn.close()
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        snapshot_preserved = bool(
            snapshot_symbol
            and snapshot_index.indexed_at == snapshot_generation
            and snapshot_symbol.get("summary") != snapshot_marker
        )
        add(
            "writer_commits_after_index_load",
            "request_snapshot",
            0,
            elapsed,
            snapshot_symbol,
            {
                "captured_generation": snapshot_generation,
                "writer_generation": snapshot_marker,
                "snapshot_preserved": snapshot_preserved,
            },
        )
        if not snapshot_preserved:
            raise RuntimeError("Request snapshot did not preserve one generation")

        monitor_root = temp_root / "monitor"
        monitor_root.mkdir()
        monitor_db = _copy_database(source_db, monitor_root)
        monitor_store = IndexStore(base_path=str(monitor_root))
        monitor_conn = monitor_store._sqlite._connect(monitor_db)
        try:
            before_version = int(monitor_conn.execute("PRAGMA data_version").fetchone()[0])
            _mutate_generation(
                monitor_store._sqlite._connect,
                monitor_db,
                target_id,
                "probe-data-version",
            )
            after_version = int(monitor_conn.execute("PRAGMA data_version").fetchone()[0])
        finally:
            monitor_conn.close()
        changed = after_version != before_version
        add(
            "cross_connection_commit_detection",
            "persistent_data_version_monitor",
            0,
            0.0,
            {"before": before_version, "after": after_version},
            {
                "before_data_version": before_version,
                "after_data_version": after_version,
                "commit_detected": changed,
            },
        )
        if not changed:
            raise RuntimeError("Persistent data_version monitor missed a commit")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "rows": len(rows),
                "shared_lazy_mixed_generation_observed": mixed_observed,
                "request_snapshot_preserved": snapshot_preserved,
                "data_version_commit_detected": changed,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
