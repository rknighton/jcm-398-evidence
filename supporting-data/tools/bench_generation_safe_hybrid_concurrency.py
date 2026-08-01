"""Concurrent cold-call benchmark for full and selective hydration paths."""

from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import gc
import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, TextIO

import psutil

import bench_generation_safe_hybrid_e2e as base


HERE = Path(__file__).resolve().parent
RAW_CSV = HERE.parent / "source-runs" / "generation_safe_hybrid_concurrency_v2.csv"
FAILURE = HERE.parent / "logs" / "generation_safe_hybrid_concurrency_v2_failure.json"
PREFIX = "JCM_CONCURRENT_RESULT "
REPO = "django/django"
REPO_NAME = "django-3eb2e228"
TARGET_INDEX = 3
CONCURRENCY_LEVELS = (1, 2, 4)
MODES = (
    ("baseline_full", base.BASELINE_ROOT),
    ("generation_safe_hybrid", base.CANDIDATE_ROOT),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _worker(source_root: Path, mode: str) -> None:
    harness = base._load_base_harness(source_root)
    import jcodemunch_mcp.server as server_module
    import jcodemunch_mcp.storage.sqlite_store as sqlite_store_module
    from jcodemunch_mcp.storage import result_cache_invalidate
    from jcodemunch_mcp.storage.index_store import IndexStore

    source_version = str(
        __import__("tomllib").loads(
            (source_root / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["version"]
    )
    source_sha = base._git_output(source_root, "rev-parse", "HEAD")
    source_diff_sha = base._git_diff_sha256(source_root)
    benchmark_sha = _sha256(Path(__file__))
    process = psutil.Process()
    harness.VOLATILE_KEYS.update(
        {"prior_session_at", "already_delivered", "hint"}
    )
    config_get = harness.config_module.get

    def benchmark_config_get(key: str, default: Any = None, repo: str | None = None):
        if key == "search_result_cache_max":
            return 0
        return config_get(key, default, repo)

    harness.config_module.get = benchmark_config_get
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def emit(value: dict[str, Any]) -> None:
        print(PREFIX + json.dumps(value, ensure_ascii=False), flush=True)

    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get("command") == "stop":
                loop.run_until_complete(loop.shutdown_default_executor())
                loop.close()
                emit({"status": "stopped"})
                return
            if request.get("command") != "measure":
                raise ValueError("Expected measure or stop command")

            concurrency = int(request["concurrency"])
            case = str(request["case"])
            target = harness._target(REPO_NAME, TARGET_INDEX)
            if case == "search_symbols_compact":
                tool = "search_symbols"
                profile = "all_symbols_search"
                arguments = {
                    "repo": f"local/{REPO_NAME}",
                    "query": target["symbol"]["name"],
                    "max_results": 10,
                    "detail_level": "compact",
                    "fusion": False,
                }
            else:
                case_spec = next(item for item in harness.CASES if item.name == case)
                tool = case_spec.tool
                profile = case_spec.profile
                arguments = harness._arguments(case_spec, REPO_NAME, target)
            arguments["format"] = "json"

            original_load = IndexStore.load_index
            count_lock = threading.Lock()
            load_calls = 0
            load_ms = 0.0
            load_durations_ms: list[float] = []

            def measured_load(self, owner: str, name: str, *args: Any, **kwargs: Any):
                nonlocal load_calls, load_ms
                started = time.perf_counter_ns()
                value = original_load(self, owner, name, *args, **kwargs)
                elapsed = (time.perf_counter_ns() - started) / 1_000_000
                with count_lock:
                    load_calls += 1
                    load_ms += elapsed
                    load_durations_ms.append(elapsed)
                return value

            result_cache_invalidate()
            sqlite_store_module._cache_clear()
            gc.collect()
            rss_before = process.memory_info().rss
            peak_rss = rss_before
            stop_sampling = threading.Event()

            def sample_memory() -> None:
                nonlocal peak_rss
                while not stop_sampling.wait(0.005):
                    peak_rss = max(peak_rss, process.memory_info().rss)

            sampler = threading.Thread(target=sample_memory, daemon=True)
            sampler.start()
            IndexStore.load_index = measured_load
            try:
                cpu_before = time.process_time_ns()
                started = time.perf_counter_ns()

                async def run_batch():
                    return await asyncio.gather(
                        *(
                            server_module.call_tool(tool, copy.deepcopy(arguments))
                            for _ in range(concurrency)
                        )
                    )

                results = loop.run_until_complete(run_batch())
                wall_ms = (time.perf_counter_ns() - started) / 1_000_000
                cpu_ms = (time.process_time_ns() - cpu_before) / 1_000_000
            finally:
                IndexStore.load_index = original_load
                stop_sampling.set()
                sampler.join(timeout=1)
            rss_after = process.memory_info().rss
            peak_rss = max(peak_rss, rss_after)
            derived_states = getattr(
                sqlite_store_module, "_generation_derived_cache", {}
            )
            derived_debug = [
                {
                    "key": list(key),
                    "symbol_count": (
                        len(state.symbols) if state.symbols is not None else None
                    ),
                    "bm25_keys": sorted(state.bm25_cache),
                }
                for key, state in derived_states.items()
            ]
            canonicals = [harness._canonical(result) for result in results]
            hashes = [harness._hash(value) for value in canonicals]
            if len(set(hashes)) != 1:
                failure_path = (
                    HERE.parent
                    / "logs"
                    / f"concurrency_within_batch_{mode}_{os.getpid()}.json"
                )
                failure_path.write_text(
                    json.dumps(
                        {
                            "mode": mode,
                            "case": case,
                            "concurrency": concurrency,
                            "hashes": hashes,
                            "canonicals": canonicals,
                        },
                        indent=2,
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                raise AssertionError(
                    f"Responses differed within {mode} batch; see {failure_path}"
                )
            serialized_bytes = sum(
                len(json.dumps(result, default=str, ensure_ascii=False).encode("utf-8"))
                for result in results
            )
            db_path = IndexStore()._sqlite._db_path("local", REPO_NAME)
            row = {
                "repo": REPO,
                "repo_name": REPO_NAME,
                "case": f"{case}_concurrency_{concurrency}",
                "scope": "cold_generation_safe_hybrid_concurrency",
                "tool": tool,
                "profile": profile,
                "mode": mode,
                "target_index": TARGET_INDEX,
                "target_value": json.dumps(arguments, sort_keys=True),
                "repetition": 1,
                "order_position": int(request["order_position"]),
                "symbol_count": target["symbol_count"],
                "file_count": target["file_count"],
                "database_size_bytes": db_path.stat().st_size,
                "wall_ms": wall_ms,
                "load_phase_ms": load_ms,
                "load_phase_pct": (load_ms / (wall_ms * concurrency)) * 100,
                "load_calls": load_calls,
                "response_bytes": serialized_bytes,
                "rss_before_bytes": rss_before,
                "rss_after_bytes": rss_after,
                "rss_delta_bytes": rss_after - rss_before,
                "canonical_response_hash": hashes[0],
                "repo_git_head": target["repo_git_head"],
                "repo_indexed_at": target["repo_indexed_at"],
                "jcodemunch_version": source_version,
                "jcodemunch_source_sha": source_sha,
                "benchmark_sha256": benchmark_sha,
                "staged_harness_sha256": str(request["controller_sha256"]),
                "python_utf8_mode": int(sys.flags.utf8_mode),
                "source_root_basename": source_root.name,
                "source_diff_sha256": source_diff_sha,
                "source_dirty_paths": base._git_output(
                    source_root, "status", "--porcelain=v1"
                ),
                "parity_debug_json": json.dumps(
                    {
                        "concurrency": concurrency,
                        "process_cpu_ms": cpu_ms,
                        "peak_rss_bytes": peak_rss,
                        "peak_rss_delta_bytes": peak_rss - rss_before,
                        "load_durations_ms": sorted(load_durations_ms),
                        "derived_states": derived_debug,
                        "within_batch_hashes": hashes,
                        "target_policy": (
                            "middle stride target; simultaneous cold calls; "
                            "forced JSON response encoding"
                        ),
                    },
                    sort_keys=True,
                ),
                "_canonical_response": canonicals[0],
            }
            emit({"status": "ok", "row": row})
        except Exception as exc:
            emit({"status": "error", "error_type": type(exc).__name__, "error": str(exc)})


class Worker:
    def __init__(self, source_root: Path, mode: str) -> None:
        self.mode = mode
        self.stderr = (HERE.parent / "logs" / f"concurrency_{mode}.log").open(
            "w", encoding="utf-8"
        )
        self.process = subprocess.Popen(
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
            stderr=self.stderr,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env={**os.environ, "PYTHONHASHSEED": "0"},
        )
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("Failed to open worker pipes")
        self.stdin: TextIO = self.process.stdin
        self.responses: queue.Queue[dict[str, Any]] = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            if line.startswith(PREFIX):
                self.responses.put(json.loads(line[len(PREFIX) :]))

    def request(self, value: dict[str, Any]) -> dict[str, Any]:
        self.stdin.write(json.dumps(value) + "\n")
        self.stdin.flush()
        response = self.responses.get(timeout=300)
        if response.get("status") == "error":
            raise RuntimeError(f"{self.mode} worker failed: {response}")
        return response

    def close(self) -> None:
        if self.process.poll() is None:
            self.request({"command": "stop"})
            self.process.wait(timeout=30)
        self.stdin.close()
        self.stderr.close()


def main() -> None:
    controller_sha = _sha256(Path(__file__))
    workers = {mode: Worker(root, mode) for mode, root in MODES}
    rows = []
    failures = []
    try:
        scenario = 0
        for case in ("symbol_source_single", "dependency_cycles", "search_symbols_compact"):
            for concurrency in CONCURRENCY_LEVELS:
                scenario += 1
                order = MODES if scenario % 2 else tuple(reversed(MODES))
                pair = []
                for order_position, (mode, _root) in enumerate(order, start=1):
                    response = workers[mode].request(
                        {
                            "command": "measure",
                            "case": case,
                            "concurrency": concurrency,
                            "order_position": order_position,
                            "controller_sha256": controller_sha,
                        }
                    )
                    pair.append(response["row"])
                if len({row["canonical_response_hash"] for row in pair}) != 1:
                    failures.append({"case": case, "concurrency": concurrency, "rows": pair})
                    continue
                for row in pair:
                    row.pop("_canonical_response", None)
                rows.extend(pair)
                print(
                    json.dumps(
                        {
                            "case": case,
                            "concurrency": concurrency,
                            "timings_ms": {row["mode"]: row["wall_ms"] for row in pair},
                        }
                    ),
                    flush=True,
                )
    finally:
        for worker in workers.values():
            worker.close()
    if failures:
        FAILURE.write_text(json.dumps(failures, indent=2) + "\n", encoding="utf-8")
        raise AssertionError(f"Concurrency benchmark had {len(failures)} parity failures")
    temporary = RAW_CSV.with_suffix(".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(RAW_CSV)
    print(json.dumps({"status": "ok", "rows": len(rows), "sha256": _sha256(RAW_CSV)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--mode")
    args = parser.parse_args()
    if args.worker:
        if args.source_root is None or args.mode is None:
            parser.error("worker mode requires source root and mode")
        _worker(args.source_root.resolve(), args.mode)
    else:
        main()
