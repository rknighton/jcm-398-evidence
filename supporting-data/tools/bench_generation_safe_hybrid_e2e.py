"""Interleaved end-to-end screen of baseline versus generation-safe hydration.

The controller keeps one isolated Python worker per source tree. Workers receive
identical requests in alternating order, invoke the real server ``call_tool``
path, clear application caches before each measured call, and return one JSON
record. The controller verifies canonical response parity before writing the
fixed-schema source CSV consumed by ``build_all_measurements_master.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import gc
import hashlib
import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path
from typing import Any, TextIO

import psutil


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
BASE_HARNESS = EVIDENCE_ROOT / "bench_public_full_blast_radius.py"
SOURCE_RUNS = HERE.parent / "source-runs"
LOG_DIR = HERE.parent / "logs"
RAW_CSV = SOURCE_RUNS / "generation_safe_hybrid_e2e_screen_v1.csv"
PARITY_FAILURE = LOG_DIR / "generation_safe_hybrid_e2e_screen_v1_parity_failure.json"
BASELINE_ROOT = _root_from_env("JCM_BASELINE_ROOT", "a clean checkout at c2201a55")
CANDIDATE_ROOT = _root_from_env("JCM_CANDIDATE_ROOT", "a checkout carrying the prototype")
PROTOCOL_PREFIX = "JCM_BENCH_RESULT "
TARGET_INDEX = 3
REPETITION = 1
WORKER_TIMEOUT_SECONDS = 180.0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_output(source_root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(source_root), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
    ).strip()


def _git_diff_sha256(source_root: Path) -> str:
    process = subprocess.Popen(
        ["git", "-C", str(source_root), "diff", "--binary", "HEAD"],
        stdout=subprocess.PIPE,
    )
    if process.stdout is None:
        raise RuntimeError("git diff stdout was not opened")
    digest = hashlib.sha256()
    for chunk in iter(lambda: process.stdout.read(1024 * 1024), b""):
        digest.update(chunk)
    return_code = process.wait()
    if return_code:
        raise RuntimeError(f"git diff failed with exit code {return_code}")
    return digest.hexdigest()


def _load_base_harness(source_root: Path):
    os.environ["JCM_BENCH_SOURCE_ROOT"] = str(source_root)
    spec = importlib.util.spec_from_file_location("jcm_base_benchmark", BASE_HARNESS)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {BASE_HARNESS}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _worker(source_root: Path, mode: str) -> None:
    base = _load_base_harness(source_root)
    from jcodemunch_mcp import __version__ as jcodemunch_version
    import jcodemunch_mcp.server as server_module
    import jcodemunch_mcp.storage.sqlite_store as sqlite_store_module
    from jcodemunch_mcp.storage import result_cache_invalidate
    from jcodemunch_mcp.storage import index_store as index_store_module

    call_tool = server_module.call_tool
    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)
    _cache_clear = sqlite_store_module._cache_clear
    unsafe_global_partial = mode.startswith("generation_unsafe_global_partial")
    unsafe_snapshot_token = None
    if unsafe_global_partial:
        # Experimental control only. It intentionally keeps request-local lazy
        # state alive across calls so its speed and correctness tradeoff can be
        # measured directly. Production code must not use this path.
        begin_request_snapshot = sqlite_store_module.begin_request_snapshot
        unsafe_snapshot_token = begin_request_snapshot()
        server_module.begin_request_snapshot = lambda: None
        server_module.end_request_snapshot = lambda _token: None

    IndexStore = index_store_module.IndexStore
    LazySymbolList = getattr(index_store_module, "LazySymbolList", None)
    process = psutil.Process()
    base.VOLATILE_KEYS.add("prior_session_at")
    benchmark_config_get = base.config_module.get

    def cold_benchmark_config_get(
        key: str,
        default: Any = None,
        repo: str | None = None,
    ) -> Any:
        if key == "search_result_cache_max":
            return 0
        return benchmark_config_get(key, default, repo)

    base.config_module.get = cold_benchmark_config_get
    source_sha = _git_output(source_root, "rev-parse", "HEAD")
    source_version = str(
        tomllib.loads((source_root / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]["version"]
    )
    dirty_paths = _git_output(source_root, "status", "--porcelain=v1")
    diff_sha = _git_diff_sha256(source_root)
    benchmark_sha = _sha256_file(Path(__file__))
    cases = {case.name: case for case in base.CASES}

    def emit(payload: dict[str, Any]) -> None:
        print(PROTOCOL_PREFIX + json.dumps(payload, ensure_ascii=False), flush=True)

    def reset_unsafe_snapshot() -> None:
        nonlocal unsafe_snapshot_token
        if not unsafe_global_partial:
            return
        begin_request_snapshot = sqlite_store_module.begin_request_snapshot
        end_request_snapshot = sqlite_store_module.end_request_snapshot
        if unsafe_snapshot_token is not None:
            end_request_snapshot(unsafe_snapshot_token)
        unsafe_snapshot_token = begin_request_snapshot()

    for line in sys.stdin:
        try:
            request = json.loads(line)
            command = request.get("command")
            if command == "stop":
                if unsafe_snapshot_token is not None:
                    sqlite_store_module.end_request_snapshot(unsafe_snapshot_token)
                    unsafe_snapshot_token = None
                event_loop.run_until_complete(event_loop.shutdown_default_executor())
                event_loop.close()
                emit({"status": "stopped"})
                return
            if command == "describe":
                emit(
                    {
                        "status": "ok",
                        "cases": [case.name for case in base.CASES],
                        "repos": base.REPOS,
                        "mode": mode,
                        "version": source_version,
                        "runtime_distribution_version": jcodemunch_version,
                        "source_sha": source_sha,
                        "dirty_paths": dirty_paths,
                        "source_diff_sha256": diff_sha,
                    }
                )
                continue
            if command == "fixture":
                repo_name = str(request["repo_name"])
                target_index = int(request.get("target_index", TARGET_INDEX))
                target = base._target(repo_name, target_index)
                target["target_index"] = target_index
                emit(
                    {
                        "status": "ok",
                        "target": target,
                        "source_root": str(
                            base._repo_fixture(repo_name)["meta"].get(
                                "source_root", ""
                            )
                        ),
                    }
                )
                continue
            if command != "measure":
                raise ValueError(f"Unknown worker command: {command!r}")

            repo = str(request["repo"])
            repo_name = str(request["repo_name"])
            target_index = int(request["target_index"])
            target = base._target(repo_name, target_index)
            target["target_index"] = target_index
            if "arguments" in request:
                case_name = str(request["case"])
                tool_name = str(request["tool"])
                profile = str(request.get("profile", "expanded_tool_surface"))
                arguments = copy.deepcopy(request["arguments"])
            else:
                case = cases[str(request["case"])]
                case_name = case.name
                tool_name = case.tool
                profile = case.profile
                arguments = base._arguments(case, repo_name, target)
            original_load = IndexStore.load_index
            original_ensure = getattr(LazySymbolList, "_ensure", None)
            original_get_by_id = getattr(LazySymbolList, "get_by_id", None)
            original_get_by_file = getattr(LazySymbolList, "get_by_file", None)
            original_get_by_name = getattr(LazySymbolList, "get_by_name", None)
            original_get_by_files = getattr(LazySymbolList, "get_by_files", None)
            load_calls = 0
            load_ms = 0.0
            hydration_trace: dict[str, Any] = {
                "load_results": [],
                "lazy_full_materializations": 0,
                "lazy_ensure_calls": 0,
                "sparse_by_id_calls": 0,
                "sparse_by_file_calls": 0,
                "sparse_by_name_calls": 0,
                "sparse_by_files_calls": 0,
            }
            original_cache_get = sqlite_store_module._cache_get
            cache_get_calls = 0
            cache_get_hits = 0
            cache_get_debug: list[dict[str, Any]] = []
            cache_policy = str(request.get("cache_policy", "cold"))
            if cache_policy not in {"cold", "warm_index"}:
                raise ValueError(f"Unknown cache policy: {cache_policy!r}")

            db_path = IndexStore()._sqlite._db_path("local", repo_name)
            mtime_before_warmup = sqlite_store_module._db_mtime_ns(db_path)
            result_cache_invalidate()
            _cache_clear()
            reset_unsafe_snapshot()
            gc.collect()
            event_loop.run_until_complete(
                call_tool(tool_name, copy.deepcopy(arguments))
            )
            mtime_after_warmup = sqlite_store_module._db_mtime_ns(db_path)
            wal_after_warmup = Path(str(db_path) + "-wal").exists()
            index_cache = getattr(sqlite_store_module, "_index_cache", {})
            cache_entry_after_warmup = index_cache.get(("local", repo_name, ""))
            cache_key_present_after_warmup = cache_entry_after_warmup is not None
            cache_entry_mtime_after_warmup = getattr(
                cache_entry_after_warmup, "mtime_ns", None
            )
            cached_symbols_loaded_after_warmup = bool(
                getattr(
                    getattr(
                        getattr(cache_entry_after_warmup, "code_index", None),
                        "symbols",
                        None,
                    ),
                    "loaded",
                    True,
                )
            )
            result_cache_invalidate()
            if cache_policy == "cold":
                _cache_clear()
                reset_unsafe_snapshot()
            mtime_before_measure = sqlite_store_module._db_mtime_ns(db_path)

            def measured_load(
                self: IndexStore,
                owner: str,
                name: str,
                *args: Any,
                **kwargs: Any,
            ):
                nonlocal load_calls, load_ms
                load_calls += 1
                started = time.perf_counter_ns()
                value = original_load(self, owner, name, *args, **kwargs)
                load_ms += (time.perf_counter_ns() - started) / 1_000_000
                hydration_trace["load_results"].append(
                    {
                        "repo": f"{owner}/{name}",
                        "branch": str(kwargs.get("branch", "")),
                        "requested_hydration": str(kwargs.get("hydration", "auto")),
                        "symbol_collection_type": (
                            type(value.symbols).__name__ if value is not None else None
                        ),
                        "lazy_loaded_at_return": (
                            bool(value.symbols.loaded)
                            if value is not None
                            and LazySymbolList is not None
                            and isinstance(value.symbols, LazySymbolList)
                            else None
                        ),
                    }
                )
                return value

            def measured_ensure(self: LazySymbolList) -> None:
                hydration_trace["lazy_ensure_calls"] += 1
                was_loaded = self.loaded
                assert original_ensure is not None
                original_ensure(self)
                if not was_loaded and self.loaded:
                    hydration_trace["lazy_full_materializations"] += 1

            def measured_get_by_id(self: LazySymbolList, symbol_id: str):
                hydration_trace["sparse_by_id_calls"] += 1
                assert original_get_by_id is not None
                return original_get_by_id(self, symbol_id)

            def measured_get_by_file(self: LazySymbolList, file_path: str):
                hydration_trace["sparse_by_file_calls"] += 1
                assert original_get_by_file is not None
                return original_get_by_file(self, file_path)

            def measured_get_by_name(
                self: LazySymbolList,
                name: str,
                *,
                case_sensitive: bool = True,
            ):
                hydration_trace["sparse_by_name_calls"] += 1
                assert original_get_by_name is not None
                return original_get_by_name(
                    self,
                    name,
                    case_sensitive=case_sensitive,
                )

            def measured_get_by_files(
                self: LazySymbolList,
                file_paths: list[str],
            ):
                hydration_trace["sparse_by_files_calls"] += 1
                assert original_get_by_files is not None
                return original_get_by_files(self, file_paths)

            def measured_cache_get(*args: Any, **kwargs: Any):
                nonlocal cache_get_calls, cache_get_hits
                cache_get_calls += 1
                owner_arg = args[0] if len(args) > 0 else kwargs.get("owner")
                name_arg = args[1] if len(args) > 1 else kwargs.get("name")
                mtime_arg = args[2] if len(args) > 2 else kwargs.get("mtime_ns")
                branch_arg = args[3] if len(args) > 3 else kwargs.get("branch", "")
                entry_before = getattr(sqlite_store_module, "_index_cache", {}).get(
                    (owner_arg, name_arg, branch_arg)
                )
                value = original_cache_get(*args, **kwargs)
                if value is not None:
                    cache_get_hits += 1
                cache_get_debug.append(
                    {
                        "owner": owner_arg,
                        "name": name_arg,
                        "branch": branch_arg,
                        "requested_mtime": mtime_arg,
                        "entry_present": entry_before is not None,
                        "entry_mtime": getattr(entry_before, "mtime_ns", None),
                        "mtime_equal": (
                            getattr(entry_before, "mtime_ns", None) == mtime_arg
                        ),
                        "hit": value is not None,
                    }
                )
                return value

            IndexStore.load_index = measured_load
            if LazySymbolList is not None:
                LazySymbolList._ensure = measured_ensure
                LazySymbolList.get_by_id = measured_get_by_id
                LazySymbolList.get_by_file = measured_get_by_file
                LazySymbolList.get_by_name = measured_get_by_name
                LazySymbolList.get_by_files = measured_get_by_files
            sqlite_store_module._cache_get = measured_cache_get
            try:
                rss_before = process.memory_info().rss
                cpu_before = time.process_time_ns()
                started = time.perf_counter_ns()
                result = event_loop.run_until_complete(
                    call_tool(tool_name, copy.deepcopy(arguments))
                )
                wall_ms = (time.perf_counter_ns() - started) / 1_000_000
                cpu_ms = (time.process_time_ns() - cpu_before) / 1_000_000
                rss_after = process.memory_info().rss
                mtime_after_measure = sqlite_store_module._db_mtime_ns(db_path)
                wal_after_measure = Path(str(db_path) + "-wal").exists()
            finally:
                IndexStore.load_index = original_load
                if LazySymbolList is not None:
                    LazySymbolList._ensure = original_ensure
                    LazySymbolList.get_by_id = original_get_by_id
                    LazySymbolList.get_by_file = original_get_by_file
                    LazySymbolList.get_by_name = original_get_by_name
                    LazySymbolList.get_by_files = original_get_by_files
                sqlite_store_module._cache_get = original_cache_get

            canonical = base._canonical(result)
            response_error = None
            if isinstance(canonical, list):
                for content_item in canonical:
                    if not isinstance(content_item, dict):
                        continue
                    payload = content_item.get("text")
                    if isinstance(payload, dict) and "error" in payload:
                        response_error = payload
                        break
            serialized = json.dumps(
                result,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            )
            emit(
                {
                    "status": "ok",
                    "row": {
                        "repo": repo,
                        "repo_name": repo_name,
                        "case": case_name,
                        "scope": str(
                            request.get("scope", "cold_generation_safe_hybrid_screen")
                        ),
                        "tool": tool_name,
                        "profile": profile,
                        "mode": mode,
                        "target_index": target_index,
                        "target_value": json.dumps(
                            arguments, sort_keys=True, ensure_ascii=False
                        ),
                        "repetition": int(request["repetition"]),
                        "order_position": int(request["order_position"]),
                        "symbol_count": target["symbol_count"],
                        "file_count": target["file_count"],
                        "database_size_bytes": db_path.stat().st_size,
                        "wall_ms": wall_ms,
                        "load_phase_ms": load_ms,
                        "load_phase_pct": (load_ms / wall_ms) * 100 if wall_ms else 0.0,
                        "load_calls": load_calls,
                        "response_bytes": len(serialized.encode("utf-8")),
                        "rss_before_bytes": rss_before,
                        "rss_after_bytes": rss_after,
                        "rss_delta_bytes": rss_after - rss_before,
                        "canonical_response_hash": base._hash(canonical),
                        "_canonical_response": canonical,
                        "_response_error": response_error,
                        "repo_git_head": target["repo_git_head"],
                        "repo_indexed_at": target["repo_indexed_at"],
                        "jcodemunch_version": source_version,
                        "jcodemunch_source_sha": source_sha,
                        "benchmark_sha256": benchmark_sha,
                        "staged_harness_sha256": str(
                            request.get("controller_sha256", "")
                        ),
                        "python_utf8_mode": int(sys.flags.utf8_mode),
                        "source_root_basename": source_root.name,
                        "source_diff_sha256": diff_sha,
                        "source_dirty_paths": dirty_paths,
                        "parity_debug_json": json.dumps(
                            {
                                "process_cpu_ms": cpu_ms,
                                "hydration_trace": hydration_trace,
                                "runtime_distribution_version": jcodemunch_version,
                                "worker_pid": os.getpid(),
                                "cache_policy": cache_policy,
                                "unsafe_global_partial_control": unsafe_global_partial,
                                "mtime_before_warmup": mtime_before_warmup,
                                "mtime_after_warmup": mtime_after_warmup,
                                "mtime_before_measure": mtime_before_measure,
                                "mtime_after_measure": mtime_after_measure,
                                "wal_after_warmup": wal_after_warmup,
                                "wal_after_measure": wal_after_measure,
                                "cache_key_present_after_warmup": (
                                    cache_key_present_after_warmup
                                ),
                                "cache_get_calls": cache_get_calls,
                                "cache_get_hits": cache_get_hits,
                                "cache_get_debug": cache_get_debug,
                                "cache_entry_mtime_after_warmup": (
                                    cache_entry_mtime_after_warmup
                                ),
                                "cached_symbols_loaded_after_warmup": (
                                    cached_symbols_loaded_after_warmup
                                ),
                                "target_policy": str(
                                    request.get(
                                        "target_policy",
                                        "middle stride target",
                                    )
                                ),
                            },
                            sort_keys=True,
                        ),
                    },
                }
            )
        except Exception as exc:
            emit(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    if unsafe_snapshot_token is not None:
        sqlite_store_module.end_request_snapshot(unsafe_snapshot_token)
    if not event_loop.is_closed():
        event_loop.run_until_complete(event_loop.shutdown_default_executor())
        event_loop.close()


class Worker:
    def __init__(
        self,
        source_root: Path,
        mode: str,
        *,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self._stderr = (LOG_DIR / f"generation_safe_hybrid_{mode}.log").open(
            "w", encoding="utf-8"
        )
        self._process = subprocess.Popen(
            [
                sys.executable,
                "-X",
                "utf8",
                str(Path(__file__).resolve()),
                "--worker",
                "--source-root",
                str(source_root),
                "--mode",
                mode,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env={
                **os.environ,
                "PYTHONHASHSEED": "0",
                **(extra_env or {}),
            },
        )
        if self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError(f"Failed to open {mode} worker pipes")
        self._stdin: TextIO = self._process.stdin
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            if line.startswith(PROTOCOL_PREFIX):
                self._responses.put(json.loads(line[len(PROTOCOL_PREFIX) :]))
        if self._process.poll() not in (None, 0):
            self._responses.put(
                {
                    "status": "error",
                    "error_type": "WorkerExited",
                    "error": f"{self.mode} worker exited before responding",
                }
            )

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._stdin.flush()
        try:
            response = self._responses.get(timeout=WORKER_TIMEOUT_SECONDS)
        except queue.Empty as exc:
            raise TimeoutError(f"{self.mode} worker timed out") from exc
        if response.get("status") == "error":
            raise RuntimeError(f"{self.mode} worker failed: {response}")
        return response

    def close(self) -> None:
        try:
            if self._process.poll() is None:
                self.request({"command": "stop"})
                self._process.wait(timeout=10)
        except (BrokenPipeError, RuntimeError, TimeoutError, subprocess.TimeoutExpired):
            self._process.kill()
            self._process.wait(timeout=10)
        finally:
            self._stdin.close()
            self._stderr.close()


def _controller() -> None:
    if not sys.flags.utf8_mode:
        raise RuntimeError("Run with Python UTF-8 mode enabled (-X utf8)")
    for source_root in (BASELINE_ROOT, CANDIDATE_ROOT):
        if not source_root.is_dir():
            raise FileNotFoundError(source_root)

    workers = {
        "baseline_full": Worker(BASELINE_ROOT, "baseline_full"),
        "generation_safe_hybrid": Worker(CANDIDATE_ROOT, "generation_safe_hybrid"),
    }
    rows: list[dict[str, Any]] = []
    try:
        descriptions = {
            mode: worker.request({"command": "describe"})
            for mode, worker in workers.items()
        }
        baseline_description = descriptions["baseline_full"]
        candidate_description = descriptions["generation_safe_hybrid"]
        if baseline_description["cases"] != candidate_description["cases"]:
            raise AssertionError("Source trees expose different benchmark cases")
        if baseline_description["repos"] != candidate_description["repos"]:
            raise AssertionError("Source trees expose different benchmark repositories")
        if baseline_description["version"] != candidate_description["version"]:
            raise AssertionError("Source trees expose different package versions")
        if baseline_description["source_sha"] != candidate_description["source_sha"]:
            raise AssertionError("Source trees are not based on the same commit")

        tasks = [
            (repo, repo_name, case)
            for repo, repo_name in baseline_description["repos"].items()
            for case in baseline_description["cases"]
        ]
        for task_number, (repo, repo_name, case) in enumerate(tasks, start=1):
            order = (
                ("baseline_full", "generation_safe_hybrid")
                if task_number % 2
                else ("generation_safe_hybrid", "baseline_full")
            )
            pair: list[dict[str, Any]] = []
            for order_position, mode in enumerate(order, start=1):
                response = workers[mode].request(
                    {
                        "command": "measure",
                        "repo": repo,
                        "repo_name": repo_name,
                        "case": case,
                        "target_index": TARGET_INDEX,
                        "repetition": REPETITION,
                        "order_position": order_position,
                    }
                )
                pair.append(response["row"])
            if len({row["canonical_response_hash"] for row in pair}) != 1:
                LOG_DIR.mkdir(parents=True, exist_ok=True)
                PARITY_FAILURE.write_text(
                    json.dumps(pair, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                raise AssertionError(f"Canonical response mismatch for {repo} {case}")
            for row in pair:
                row.pop("_canonical_response", None)
                row.pop("_response_error", None)
            rows.extend(pair)
            if task_number % 10 == 0 or task_number == len(tasks):
                print(
                    json.dumps({"completed_pairs": task_number, "total_pairs": len(tasks)}),
                    flush=True,
                )
    finally:
        for worker in workers.values():
            worker.close()

    SOURCE_RUNS.mkdir(parents=True, exist_ok=True)
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
                "pairs": len(rows) // 2,
                "raw_csv": str(RAW_CSV),
                "sha256": _sha256_file(RAW_CSV),
            }
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--mode")
    args = parser.parse_args()
    if args.worker:
        if args.source_root is None or not args.mode:
            parser.error("--worker requires --source-root and --mode")
        _worker(args.source_root.resolve(), args.mode)
        return
    _controller()


if __name__ == "__main__":
    main()
