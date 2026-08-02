"""Controller for the reusable Arc 4 real-embedding certification research."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arc4lib import (
    CSV_COLUMNS,
    SCHEMA_VERSION,
    assert_fixed_schema,
    canonical_json,
    config_identity,
    sha256_file,
    stable_row_id,
)


HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "research_config.json"
WORKING = HERE / "working"
PREPARATION = WORKING / "preparation.json"
WORK_INDEXES = WORKING / "indexes"
CANONICAL_CSV = HERE / "measurements.csv"


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _harness_identity() -> str:
    digest = hashlib.sha256()
    for name in ("arc4lib.py", "worker.py", "run_research.py", "verify.py"):
        path = HERE / name
        if path.exists():
            encoded = name.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _run_worker(command: list[str], *, log_path: Path, timeout: int) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as stderr:
        completed = subprocess.run(
            command,
            cwd=HERE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            timeout=timeout,
            check=False,
        )
    stdout = completed.stdout.decode("utf-8", errors="replace")
    result_lines = [line for line in stdout.splitlines() if line.startswith("ARC4_RESULT ")]
    if completed.returncode != 0 or len(result_lines) != 1:
        raise RuntimeError(
            f"worker failed exit={completed.returncode} result_lines={len(result_lines)} "
            f"log={log_path} stdout_tail={stdout[-2000:]}"
        )
    return json.loads(result_lines[0][len("ARC4_RESULT ") :])


def _prepare(args: argparse.Namespace) -> int:
    if PREPARATION.exists() and not args.force:
        existing = json.loads(PREPARATION.read_text(encoding="utf-8"))
        if existing.get("status") == "prepared":
            print(f"preparation already complete: {PREPARATION}")
            return 0
        raise RuntimeError(f"preparation exists but is not complete: {PREPARATION}")
    if args.force and WORK_INDEXES.exists():
        raise RuntimeError(
            "refusing to overwrite prepared indexes; move the working folder aside for an additive rerun"
        )
    command = [
        sys.executable,
        str(HERE / "worker.py"),
        "prepare",
        "--config",
        str(args.config),
        "--baseline-root",
        str(args.baseline_root),
        "--source-index-root",
        str(args.source_index_root),
        "--work-index-root",
        str(WORK_INDEXES),
        "--batch-size",
        str(args.batch_size),
    ]
    payload = _run_worker(
        command,
        log_path=WORKING / "logs" / "prepare.log",
        timeout=args.timeout,
    )
    payload["config_sha256"] = config_identity(args.config)
    payload["harness_sha256"] = _harness_identity()
    _atomic_text(PREPARATION, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"prepared real embeddings: {PREPARATION}")
    return 0


def _new_run_id(phase: str, config_sha: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{phase}-{stamp}-{config_sha[:10]}"


def _exact_fraction(count: int, denominator: int) -> str:
    if denominator <= 0:
        raise ValueError("fraction denominator must be positive")
    return str(Decimal(count) / Decimal(denominator))


def _row_from_result(
    *,
    result: dict[str, Any],
    config: dict[str, Any],
    config_sha: str,
    harness_sha: str,
    run_id: str,
    corpus: dict[str, Any],
    query: dict[str, Any],
    mode: str,
    cache_state: str,
    repetition: int,
    execution_order: int,
) -> dict[str, Any]:
    case_id = f"{corpus['name']}:{query['query_id']}:{cache_state}"
    pair_id = f"{case_id}:r{repetition:02d}"
    row_id = stable_row_id([run_id, pair_id, mode])
    baseline = result["baseline_identity"]
    candidate = result["candidate_identity"]
    diagnostic = result["diagnostic"]
    row = {
        "schema_version": SCHEMA_VERSION,
        "row_id": row_id,
        "run_id": run_id,
        "row_status": "retained",
        "superseded_run_id": "",
        "supersession_reason": "",
        "case_id": case_id,
        "pair_id": pair_id,
        "repetition": repetition,
        "execution_order": execution_order,
        "mode": mode,
        "corpus": corpus["name"],
        "corpus_role": corpus["role"],
        "public_repo": corpus["public_repo"],
        "corpus_commit": result["corpus_commit"],
        "source_repo_id": corpus["source_repo_id"],
        "source_database_sha256": result["source_database_sha256"],
        "working_database_sha256": result["working_database_sha256"],
        "index_generation": result["index_generation"],
        "query_id": query["query_id"],
        "query_kind": "semantic_only" if query["semantic_only"] else "hybrid",
        "tie_heavy_query": str(bool(query["tie_heavy"])).lower(),
        "serialized_args_json": json.loads(PREPARATION.read_text(encoding="utf-8"))["queries"][query["query_id"]]["serialized_args_json"],
        "top_k": query["top_k"],
        "semantic_weight": format(query["semantic_weight"], ".17g"),
        "cache_state": cache_state,
        "cold_warm_state": cache_state,
        "lane_selected": result["lane_selected"],
        "fallback_reason": result["fallback_reason"],
        "candidate_count": result["candidate_count"],
        "result_count": result["result_count"],
        "result_boundary_score": format(result["result_boundary_score"], ".17g"),
        "exact_tie_count": result["exact_tie_count"],
        "near_tie_count": result["near_tie_count"],
        "genuine_disagreement_count": result["genuine_disagreement_count"],
        "other_certified_count": result["other_certified_count"],
        "total_certified_count": result["total_certified_count"],
        "exact_tie_fraction": _exact_fraction(result["exact_tie_count"], result["candidate_count"]),
        "near_tie_fraction": _exact_fraction(result["near_tie_count"], result["candidate_count"]),
        "genuine_disagreement_fraction": _exact_fraction(
            result["genuine_disagreement_count"], result["candidate_count"]
        ),
        "total_certified_fraction": _exact_fraction(
            result["total_certified_count"], result["candidate_count"]
        ),
        "interval_violation_count": result["interval_violation_count"],
        "wall_ns": result["wall_ns"],
        "scoring_ns": result["scoring_ns"],
        "process_cpu_ns": result["process_cpu_ns"],
        "rss_before_bytes": result["rss_before_bytes"],
        "rss_after_bytes": result["rss_after_bytes"],
        "peak_rss_bytes": result["peak_rss_bytes"],
        "baseline_response_hash": result["baseline_response_hash"],
        "candidate_response_hash": result["candidate_response_hash"],
        "canonical_parity": str(bool(result["canonical_parity"])).lower(),
        "ordered_result_id_hash": result["ordered_result_id_hash"],
        "baseline_version": baseline["version"],
        "baseline_source_sha": baseline["source_sha"],
        "baseline_diff_sha256": baseline["diff_sha256"],
        "baseline_dirty_paths_json": canonical_json(baseline["dirty_paths"]),
        "baseline_import_root": result["baseline_import_root"],
        "candidate_version": candidate["version"],
        "candidate_source_sha": candidate["source_sha"],
        "candidate_diff_sha256": candidate["diff_sha256"],
        "candidate_dirty_paths_json": canonical_json(candidate["dirty_paths"]),
        "candidate_import_root": result["candidate_import_root"],
        "candidate_classification": "source_identified_local_tiebreak_and_certification_candidate",
        "harness_sha256": harness_sha,
        "config_sha256": config_sha,
        "python_version": result["python_version"],
        "numpy_version": result["numpy_version"],
        "sqlite_version": result["sqlite_version"],
        "platform": result["platform"],
        "cpu_identity": result["cpu_identity"],
        "total_memory_bytes": result["total_memory_bytes"],
        "embedding_provider": config["embedding"]["provider"],
        "embedding_model": config["embedding"]["model"],
        "embedding_dimension": config["embedding"]["dimension"],
        "embedding_vector_count": result["embedding_vector_count"],
        "embedding_normalization": config["embedding"]["normalization"],
        "embedding_generation_identity": result["embedding_generation_identity"],
        "query_embedding_sha256": result["query_embedding_sha256"],
        "diagnostic_json": canonical_json(diagnostic),
    }
    assert_fixed_schema(row)
    return row


def _consolidate(fragment_dir: Path, output: Path) -> None:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(fragment_dir.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        denominator = int(row["candidate_count"])
        for count_key, fraction_key in (
            ("exact_tie_count", "exact_tie_fraction"),
            ("near_tie_count", "near_tie_fraction"),
            ("genuine_disagreement_count", "genuine_disagreement_fraction"),
            ("total_certified_count", "total_certified_fraction"),
        ):
            row[fraction_key] = _exact_fraction(int(row[count_key]), denominator)
        assert_fixed_schema(row)
        if row["row_id"] in seen:
            raise ValueError(f"duplicate row ID: {row['row_id']}")
        seen.add(row["row_id"])
        rows.append(row)
    rows.sort(key=lambda row: (row["case_id"], int(row["repetition"]), int(row["execution_order"])))
    temporary = output.with_name(output.name + f".tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(output)


def _measure(args: argparse.Namespace) -> int:
    if not PREPARATION.exists():
        raise RuntimeError("run prepare first")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    config_sha = config_identity(args.config)
    preparation = json.loads(PREPARATION.read_text(encoding="utf-8"))
    if preparation.get("config_sha256") != config_sha:
        raise RuntimeError("preparation config identity does not match frozen config")
    harness_sha = _harness_identity()
    phase = args.command
    repetitions = 1 if phase == "screen" else config["measurement"]["repetitions"]
    run_id = args.run_id or _new_run_id(phase, config_sha)
    state_path = WORKING / phase / "active_run.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("status") == "active" and not args.run_id:
            run_id = state["run_id"]
        elif state.get("run_id") != run_id:
            raise RuntimeError(f"another {phase} run is recorded at {state_path}")
    else:
        _atomic_text(
            state_path,
            json.dumps(
                {
                    "status": "active",
                    "run_id": run_id,
                    "config_sha256": config_sha,
                    "harness_sha256": harness_sha,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
    fragment_dir = WORKING / phase / run_id / "fragments"
    log_dir = WORKING / phase / run_id / "logs"
    fragment_dir.mkdir(parents=True, exist_ok=True)
    modes = list(config["measurement"]["modes"])
    total = len(config["corpora"]) * len(config["queries"]) * len(config["measurement"]["cache_states"]) * repetitions * len(modes)
    completed_count = 0
    for corpus in config["corpora"]:
        for query in config["queries"]:
            for cache_state in config["measurement"]["cache_states"]:
                for repetition in range(1, repetitions + 1):
                    offset = (repetition - 1) % len(modes)
                    ordered_modes = modes[offset:] + modes[:offset]
                    for execution_order, mode in enumerate(ordered_modes, start=1):
                        case_id = f"{corpus['name']}:{query['query_id']}:{cache_state}"
                        pair_id = f"{case_id}:r{repetition:02d}"
                        row_id = stable_row_id([run_id, pair_id, mode])
                        fragment = fragment_dir / f"{row_id}.json"
                        if fragment.exists():
                            completed_count += 1
                            continue
                        command = [
                            sys.executable,
                            str(HERE / "worker.py"),
                            "measure",
                            "--config",
                            str(args.config),
                            "--preparation",
                            str(PREPARATION),
                            "--baseline-root",
                            str(args.baseline_root),
                            "--candidate-root",
                            str(args.candidate_root),
                            "--work-index-root",
                            str(WORK_INDEXES),
                            "--corpus",
                            corpus["name"],
                            "--query-id",
                            query["query_id"],
                            "--mode",
                            mode,
                            "--cache-state",
                            cache_state,
                        ]
                        result = _run_worker(
                            command,
                            log_path=log_dir / f"{row_id}.log",
                            timeout=args.timeout,
                        )
                        row = _row_from_result(
                            result=result,
                            config=config,
                            config_sha=config_sha,
                            harness_sha=harness_sha,
                            run_id=run_id,
                            corpus=corpus,
                            query=query,
                            mode=mode,
                            cache_state=cache_state,
                            repetition=repetition,
                            execution_order=execution_order,
                        )
                        _atomic_text(fragment, json.dumps(row, sort_keys=True) + "\n")
                        completed_count += 1
                        print(f"[{completed_count}/{total}] {row_id} {case_id} {mode}", flush=True)
    output = WORKING / "screen_measurements.csv" if phase == "screen" else CANONICAL_CSV
    _consolidate(fragment_dir, output)
    _atomic_text(
        state_path,
        json.dumps(
            {
                "status": "complete",
                "run_id": run_id,
                "row_count": completed_count,
                "output": str(output),
                "output_sha256": sha256_file(output),
                "config_sha256": config_sha,
                "harness_sha256": harness_sha,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    print(f"{phase} complete: {output} ({completed_count} rows)")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--baseline-root", type=Path, required=True)
    prepare.add_argument("--source-index-root", type=Path, required=True)
    prepare.add_argument("--batch-size", type=int, default=128)
    prepare.add_argument("--timeout", type=int, default=7200)
    prepare.add_argument("--force", action="store_true")

    for name in ("screen", "authoritative"):
        command = sub.add_parser(name)
        command.add_argument("--baseline-root", type=Path, required=True)
        command.add_argument("--candidate-root", type=Path, required=True)
        command.add_argument("--timeout", type=int, default=900)
        command.add_argument("--run-id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "prepare":
        return _prepare(args)
    return _measure(args)


if __name__ == "__main__":
    raise SystemExit(main())
