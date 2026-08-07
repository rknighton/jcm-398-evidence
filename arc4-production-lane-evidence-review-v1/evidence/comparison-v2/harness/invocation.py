from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .common import (
    ContractError,
    atomic_write_new,
    canonical_json,
    canonical_json_bytes,
    exact_keys,
    load_json,
    require,
    sha256_bytes,
    sha256_file,
)


PUBLICATION_SCHEMA = "arc4.job-publication/v1"
EXECUTION_NAMESPACES = {"measured", "preflight", "repair", "control"}


def _resolved(path: str | Path) -> Path:
    return Path(path).resolve(strict=False)


def reject_reparse_or_escape(path: Path, root: Path, code: str) -> Path:
    resolved_root = root.resolve(strict=False)
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ContractError(code, f"{resolved} outside {resolved_root}") from exc
    cursor = path.absolute()
    while True:
        if cursor.exists():
            stat = cursor.lstat()
            attributes = getattr(stat, "st_file_attributes", 0)
            require(not cursor.is_symlink() and not (attributes & 0x400), code, str(cursor))
        if cursor == resolved_root or cursor.parent == cursor:
            break
        cursor = cursor.parent
    return resolved


def lane_layout(config: Mapping[str, Any], lane: str) -> dict[str, Path]:
    require(lane in {"numpy_present", "numpy_absent"}, "invocation_lane", lane)
    roots = config["environment_lane_roots"][lane]
    exact_keys(roots, ("lane_venv", "trial_root"), "invocation_lane_root_keys")
    lane_root = _resolved(roots["lane_venv"])
    interpreter = _resolved(config["lane_interpreters"][lane])
    expected_interpreter = _resolved(lane_root / "Scripts" / "python.exe")
    require(interpreter == expected_interpreter, "invocation_interpreter_layout", f"{interpreter} != {expected_interpreter}")
    package_root = _resolved(lane_root / "Lib" / "site-packages" / "jcodemunch_mcp")
    lock = load_json(_resolved(config["environment_lock"]))
    bindings = lock.get("manifest_bindings") if isinstance(lock, dict) else None
    require(isinstance(bindings, dict), "invocation_environment_lock", "bound environment lock required")
    bound_roots = bindings.get("roots")
    require(isinstance(bound_roots, dict) and isinstance(bound_roots.get(lane), dict), "invocation_environment_roots", lane)
    bound = bound_roots[lane]
    require(_resolved(bound.get("lane_venv", "")) == lane_root, "invocation_environment_lane_root", lane)
    require(_resolved(bound.get("python_executable", "")) == interpreter and bound.get("python_executable_sha256") == sha256_file(interpreter), "invocation_environment_interpreter", lane)
    require(_resolved(bound.get("package_root", "")) == package_root, "invocation_environment_package_root", lane)
    return {"lane_root": lane_root, "interpreter": interpreter, "package_root": package_root}


def job_publication_path(job_path: Path) -> Path:
    return job_path.with_suffix(job_path.suffix + ".publication.json")


def publish_job(job_path: Path, job: Mapping[str, Any], *, allowed_root: Path) -> dict[str, Any]:
    payload = canonical_json_bytes(dict(job))
    atomic_write_new(job_path, payload, allowed_root=allowed_root)
    receipt = {
        "schema": PUBLICATION_SCHEMA,
        "path": str(job_path.resolve()),
        "sha256": sha256_bytes(payload),
        "bytes": len(payload),
    }
    atomic_write_new(job_publication_path(job_path), canonical_json_bytes(receipt), allowed_root=allowed_root)
    return receipt


def validate_job_publication(value: Mapping[str, Any], job_path: Path) -> bytes:
    exact_keys(value, ("schema", "path", "sha256", "bytes"), "job_publication_keys")
    require(value["schema"] == PUBLICATION_SCHEMA, "job_publication_schema", str(value.get("schema")))
    require(value["path"] == str(job_path.resolve()), "job_publication_path", str(value.get("path")))
    require(isinstance(value["sha256"], str) and len(value["sha256"]) == 64, "job_publication_hash", str(value.get("sha256")))
    require(isinstance(value["bytes"], int) and not isinstance(value["bytes"], bool) and value["bytes"] > 0, "job_publication_bytes", str(value.get("bytes")))
    receipt_path = job_publication_path(job_path)
    try:
        retained_receipt = receipt_path.read_bytes()
    except OSError as exc:
        raise ContractError("job_publication_transport", str(exc)) from exc
    require(retained_receipt == canonical_json_bytes(dict(value)), "job_publication_retained", str(receipt_path))
    payload = job_path.read_bytes()
    require(len(payload) == value["bytes"] and sha256_bytes(payload) == value["sha256"], "job_publication_integrity", str(job_path))
    return payload


def canonical_job_path(runtime_root: Path, job: Mapping[str, Any]) -> Path:
    namespace = job["execution_namespace"]
    require(namespace in EXECUTION_NAMESPACES, "job_namespace", str(namespace))
    attempt = int(job["attempt_n"])
    if namespace == "control":
        require(job["is_control"] is True and job["control_id"] == "C9", "job_control_identity", str(job.get("control_id")))
        seed = "unset" if job["python_hash_seed"] is None else str(job["python_hash_seed"])
        return runtime_root / "jobs" / "control" / "C9" / job["row_id"] / f"seed-{seed}" / f"attempt-{attempt:04d}.json"
    require(job["is_control"] is False and job["control_id"] is None, "job_matrix_control_leak", str(job.get("control_id")))
    return runtime_root / "jobs" / namespace / job["row_id"] / f"attempt-{attempt:04d}.json"


def canonical_attempt_root(runtime_root: Path, job: Mapping[str, Any]) -> Path:
    namespace = job["execution_namespace"]
    attempt = int(job["attempt_n"])
    if namespace == "control":
        seed = "unset" if job["python_hash_seed"] is None else str(job["python_hash_seed"])
        return runtime_root / "attempts" / "control" / "C9" / job["row_id"] / f"seed-{seed}" / f"attempt-{attempt:04d}"
    return runtime_root / "attempts" / namespace / job["row_id"] / f"attempt-{attempt:04d}"


def command_receipt(argv: Sequence[str]) -> dict[str, Any]:
    normalized = list(argv)
    return {"argv": normalized, "sha256": sha256_bytes(canonical_json(normalized).encode("utf-8"))}


def validate_canonical_job_bytes(payload: bytes) -> dict[str, Any]:
    import json

    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("worker_job_transport", str(exc)) from exc
    require(isinstance(value, dict), "worker_job_schema", "job object required")
    require(payload == canonical_json_bytes(value), "worker_job_noncanonical", "job artifact must be canonical JSON")
    return value


def _database_receipt(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    files: dict[str, Any] = {}
    for name, candidate in (("db", resolved), ("wal", Path(str(resolved) + "-wal")), ("shm", Path(str(resolved) + "-shm"))):
        if candidate.is_file():
            files[name] = {"present": True, "sha256": sha256_file(candidate), "size": candidate.stat().st_size}
        else:
            files[name] = {"present": False, "sha256": None, "size": 0}
    return {"database_path": str(resolved), "files": files}


def validate_production_job_campaign_binding(job: Mapping[str, Any], *, binding: Mapping[str, Any] | None = None) -> dict[str, Any]:
    config_path = _resolved(str(job.get("config_path", "")))
    require(config_path.is_file() and sha256_file(config_path) == job.get("config_sha256"), "worker_job_config_hash", str(config_path))
    config = load_json(config_path)
    packet_root = _resolved(str(config.get("packet_root", "")))
    require(config_path == _resolved(packet_root / "CONFIG.json"), "worker_job_config_path", str(config_path))
    require(job.get("run_id") == config.get("run_id"), "worker_job_config_run", str(job.get("run_id")))
    lane = str(job.get("lane", ""))
    layout = lane_layout(config, lane)
    require(job.get("package_root") == str(layout["package_root"]), "worker_job_config_package", str(job.get("package_root")))
    require(_resolved(str(job.get("environment_lock_path", ""))) == _resolved(str(config.get("environment_lock", ""))), "worker_job_config_lock_path", str(job.get("environment_lock_path")))
    require(job.get("environment_lock_sha256") == sha256_file(_resolved(str(config["environment_lock"]))), "worker_job_config_lock_hash", str(job.get("environment_lock_sha256")))
    require(_resolved(str(job.get("treatment_wheel", ""))) == _resolved(str(config.get("official_wheel", ""))), "worker_job_config_wheel", str(job.get("treatment_wheel")))
    cases_path = _resolved(str(config.get("frozen_cases", "")))
    require(cases_path == _resolved(packet_root / "frozen-cases.json") and cases_path.is_file(), "worker_job_config_cases_path", str(cases_path))
    cases = load_json(cases_path)
    planned = [row for row in cases.get("planned_rows", []) if isinstance(row, dict) and row.get("row_id") == job.get("row_id")]
    require(len(planned) == 1, "worker_job_config_planned_row", str(job.get("row_id")))
    for key, expected in planned[0].items():
        require(job.get(key) == expected, "worker_job_config_planned_row", f"{key}:{job.get(key)!r}")
    corpus = config.get("corpora", {}).get(job.get("corpus"))
    require(isinstance(corpus, dict), "worker_job_config_corpus", str(job.get("corpus")))
    require(job.get("repo_id") == corpus.get("repo_id") and job.get("candidate_ids") == corpus.get("candidate_ids"), "worker_job_config_corpus", str(job.get("corpus")))
    source_database = _resolved(str(corpus.get("database", "")))
    require(job.get("frozen_source_files") == _database_receipt(source_database), "worker_job_config_frozen_source", str(source_database))
    seed = "unset" if job.get("python_hash_seed") is None else str(job.get("python_hash_seed"))
    trial_namespace = f"seed-{seed}" if job.get("is_control") is True else str(job.get("execution_namespace"))
    trial_root = _resolved(str(config["runtime_root"])) / "trials" / trial_namespace / str(job["row_id"]) / f"attempt-{int(job['attempt_n']):04d}"
    trial_database = trial_root / source_database.name
    require(_resolved(str(job.get("storage_path", ""))) == trial_root.resolve() and _resolved(str(job.get("database", ""))) == trial_database.resolve(), "worker_job_config_trial_path", str(job.get("database")))
    require(_resolved(str(job.get("home_path", ""))) == _resolved(trial_root / "home"), "worker_job_config_home", str(job.get("home_path")))
    require(job.get("trial_source_files") == _database_receipt(trial_database) and job["trial_source_files"]["files"] == job["frozen_source_files"]["files"], "worker_job_config_trial_source", str(trial_database))
    query = config.get("queries", {}).get(job.get("query_id"))
    require(isinstance(query, dict) and job.get("query_text") == query.get("query_text") and job.get("query_vector") == query.get("query_vector") and job.get("query_vector_sha256") == query.get("query_vector_sha256"), "worker_job_config_query", str(job.get("query_id")))
    expected_ordinal = 1 if (job["lane_invocation_order"] == "numpy_first") == (lane == "numpy_present") else 2
    require(job.get("pair_invocation_ordinal") == expected_ordinal, "worker_job_config_ordinal", str(job.get("pair_invocation_ordinal")))
    if binding is not None:
        require(binding["interpreter"] == {"lane_root": str(layout["lane_root"]), "path": str(layout["interpreter"]), "sha256": sha256_file(layout["interpreter"]), "package_root": str(layout["package_root"])}, "worker_job_config_interpreter", lane)
    return config
