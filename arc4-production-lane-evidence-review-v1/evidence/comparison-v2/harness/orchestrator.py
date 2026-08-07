from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Mapping, Sequence

from .common import ContractError, atomic_write, atomic_write_new, canonical_json, canonical_json_bytes, exact_keys, load_json, require, safe_relative_path, sha256_bytes, sha256_file
from .invocation import command_receipt, job_publication_path, lane_layout, validate_canonical_job_bytes, validate_job_publication, validate_production_job_campaign_binding
from .cases import validate_frozen_cases
from .worker_protocol import (
    INVOCATION_BINDING_SCHEMA, JOB_SCHEMA, PROTOCOL_SELF_TEST_SCHEMA, metadata_free_worker_error,
    expected_success_job_from_artifact, validate_invocation_binding,
    validate_protocol_self_test_job, validate_worker_job, validate_worker_rejection, validate_worker_success,
)

RESULT_PREFIX = "ARC4_RESULT "


def pair_fragment_name(pair_id: str) -> str:
    require(isinstance(pair_id, str) and bool(pair_id), "pair_fragment_identity", str(pair_id))
    return f"{sha256_bytes(pair_id.encode('utf-8'))}.json"


class RunLease:
    """Exclusive run authority with exact-process stale-owner recovery."""

    def __init__(self, run_root: Path, token: str) -> None:
        self.run_root = run_root.resolve()
        self.token = token
        self.path = self.run_root / "lease.json"
        self.owner = _current_owner_identity()
        self.value = {"schema": "arc4.run-lease/v2", "run_id": self.token, "owner": self.owner}
        self.recovered_owner: Mapping[str, Any] | None = None

    def _publish(self) -> None:
        payload = canonical_json_bytes(self.value)
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ContractError("lease_held", str(self.path)) from exc
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    def acquire(self) -> None:
        self.run_root.mkdir(parents=True, exist_ok=True)
        try:
            self._publish()
            return
        except ContractError as exc:
            if exc.code != "lease_held":
                raise
        raw = self.path.read_bytes()
        existing = load_json(self.path)
        exact_keys(existing, ("schema", "run_id", "owner"), "lease_keys")
        require(existing["schema"] == "arc4.run-lease/v2", "lease_identity", str(existing))
        _validate_owner_identity(existing["owner"])
        require(raw == canonical_json_bytes(existing), "lease_canonical", str(self.path))
        if _owner_is_current(existing["owner"]):
            raise ContractError("lease_held", str(self.path))
        require(existing["run_id"] == self.token, "lease_identity", str(existing))
        history = self.run_root / "lease-history"
        history.mkdir(parents=True, exist_ok=True)
        stale_path = history / f"{sha256_bytes(raw)}.json"
        require(not stale_path.exists(), "lease_stale_history_collision", str(stale_path))
        try:
            os.rename(self.path, stale_path)
        except OSError as exc:
            raise ContractError("lease_recovery_race", str(self.path)) from exc
        self.recovered_owner = dict(existing["owner"])
        self._publish()

    def assert_current(self) -> None:
        value = load_json(self.path)
        require(value == self.value, "stale_lease", "lease owner identity changed")

    def release(self) -> None:
        self.assert_current()
        self.path.unlink()


def _filetime_value(value: wintypes.FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def _windows_process_creation_time(pid: int) -> int | None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME))
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error in (87, 1168):
            return None
        raise ContractError("lease_owner_observation", f"OpenProcess({pid})={error}")
    creation = wintypes.FILETIME()
    exit_time = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    observation_error: ContractError | None = None
    result: int | None = None
    if kernel32.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)):
        result = _filetime_value(creation)
    else:
        observation_error = ContractError("lease_owner_observation", f"GetProcessTimes({pid})={ctypes.get_last_error()}")
    close_ok = kernel32.CloseHandle(handle)
    require(bool(close_ok), "lease_owner_handle_close", str(ctypes.get_last_error()))
    if observation_error is not None:
        raise observation_error
    return result


def _process_creation_time(pid: int) -> int | None:
    if os.name == "nt":
        return _windows_process_creation_time(pid)
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ContractError("lease_owner_observation", str(exc)) from exc
    require(len(fields) >= 22 and fields[21].isdigit(), "lease_owner_observation", str(pid))
    return int(fields[21])


def _current_owner_identity() -> dict[str, Any]:
    creation = _process_creation_time(os.getpid())
    require(creation is not None, "lease_current_owner", str(os.getpid()))
    return {"pid": os.getpid(), "creation_time": creation, "executable": str(Path(sys.executable).resolve())}


def _validate_owner_identity(value: Any) -> None:
    require(isinstance(value, dict), "lease_owner_shape", str(value))
    exact_keys(value, ("pid", "creation_time", "executable"), "lease_owner_keys")
    require(isinstance(value["pid"], int) and not isinstance(value["pid"], bool) and value["pid"] > 0, "lease_owner_pid", str(value["pid"]))
    require(isinstance(value["creation_time"], int) and not isinstance(value["creation_time"], bool) and value["creation_time"] > 0, "lease_owner_creation", str(value["creation_time"]))
    require(isinstance(value["executable"], str) and bool(value["executable"]), "lease_owner_executable", str(value["executable"]))


def _owner_is_current(value: Mapping[str, Any]) -> bool:
    _validate_owner_identity(value)
    observed = _process_creation_time(int(value["pid"]))
    return observed == value["creation_time"]


def _terminate_exact_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        process.kill()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()


def _file_reference(path: Path, relative: str) -> dict[str, Any]:
    raw = path.read_bytes()
    return {"path": relative, "sha256": sha256_bytes(raw), "bytes": len(raw)}


def _job_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"present": False, "sha256": None, "bytes": 0}
    raw = path.read_bytes()
    return {"present": True, "sha256": sha256_bytes(raw), "bytes": len(raw)}


def _invocation_binding(
    *, run_id: str, planned_row: Mapping[str, Any], attempt_n: int, methodology: str,
    repair_reason: str | None, source_job: Path, publication: Mapping[str, Any], job_bytes: bytes,
    interpreter: Path, lane_root: Path, package_root: Path, execution: Mapping[str, Any], command: Sequence[str], attempt_root: Path,
) -> dict[str, Any]:
    binding_path = (attempt_root / "invocation-binding.json").resolve()
    artifact_path = (attempt_root / "job-artifact.json").resolve()
    actual_command = [*command, "--binding", str(binding_path), str(artifact_path)]
    binding = {
        "schema": INVOCATION_BINDING_SCHEMA, "run_id": run_id,
        "row_identity": {key: planned_row[key] for key in ("row_id", "pair_id", "case_id", "problem_id", "arm", "lane")},
        "execution": dict(execution),
        "attempt": {"attempt_n": attempt_n, "methodology": methodology, "repair_reason": repair_reason},
        "job": {"source_path": str(source_job.resolve()), "publication_path": str(job_publication_path(source_job).resolve()), "artifact_path": str(artifact_path), "sha256": publication["sha256"], "bytes": publication["bytes"]},
        "interpreter": {"lane_root": str(lane_root.resolve()), "path": str(interpreter.resolve()), "sha256": sha256_file(interpreter), "package_root": str(package_root.resolve())},
        "paths": {"attempt_root": str(attempt_root.resolve()), "binding": str(binding_path), "receipt": str((attempt_root / "receipt.json").resolve()), "stdout": str((attempt_root / "stdout.log").resolve()), "stderr": str((attempt_root / "stderr.log").resolve())},
        "command": command_receipt(actual_command),
    }
    require(sha256_bytes(job_bytes) == publication["sha256"] and len(job_bytes) == publication["bytes"], "worker_publication_binding", str(source_job))
    validate_invocation_binding(binding)
    return binding


def run_worker(
    command: Sequence[str], *, attempt_root: Path, timeout_seconds: int,
    run_id: str, planned_row: Mapping[str, Any], attempt_n: int, methodology: str,
    repair_reason: str | None, job_path: Path, job_publication: Mapping[str, Any],
    lane_root: Path, package_root: Path,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    require(timeout_seconds > 0, "worker_timeout", "timeout must be positive")
    require(len(command) == 3 and command[1:] == ["-m", "harness.worker"] and Path(command[0]).resolve().is_file(), "worker_command", str(command))
    require(isinstance(run_id, str) and bool(run_id), "worker_run_id", str(run_id))
    source_bytes = validate_job_publication(job_publication, job_path)
    artifact = validate_canonical_job_bytes(source_bytes)
    if artifact.get("schema") == JOB_SCHEMA:
        validate_worker_job(artifact)
        campaign_config = validate_production_job_campaign_binding(artifact)
        expected_layout = lane_layout(campaign_config, artifact["lane"])
        require(Path(command[0]).resolve() == expected_layout["interpreter"] and lane_root.resolve() == expected_layout["lane_root"] and package_root.resolve() == expected_layout["package_root"], "worker_campaign_layout", artifact["lane"])
        bound_plan = artifact
        execution = {"namespace": artifact["execution_namespace"], "is_control": artifact["is_control"], "control_id": artifact["control_id"], "python_hash_seed": artifact["python_hash_seed"]}
        attempt_context = artifact
    else:
        require(artifact.get("schema") == PROTOCOL_SELF_TEST_SCHEMA, "worker_job_schema", str(artifact.get("schema")))
        validate_protocol_self_test_job(artifact)
        bound_plan = artifact["planned_row"]
        execution = {"namespace": "preflight", "is_control": False, "control_id": None, "python_hash_seed": (environment or {}).get("PYTHONHASHSEED")}
        attempt_context = artifact["production_context"]
    expected_projection = dict(planned_row)
    for key, expected in expected_projection.items():
        require(bound_plan.get(key) == expected, "worker_job_planned_identity", f"{key}:{bound_plan.get(key)!r}")
    require(attempt_context["attempt_n"] == attempt_n and attempt_context["attempt_methodology"] == methodology and attempt_context["repair_reason"] == repair_reason, "worker_job_attempt_binding", str(bound_plan["row_id"]))
    if artifact.get("schema") == JOB_SCHEMA:
        require(artifact["package_root"] == str(package_root.resolve()), "worker_job_package_root", str(artifact["package_root"]))
    attempt_root.mkdir(parents=True, exist_ok=False)
    artifact_path = attempt_root / "job-artifact.json"
    atomic_write_new(artifact_path, source_bytes, allowed_root=attempt_root)
    interpreter = Path(command[0]).resolve()
    binding = _invocation_binding(
        run_id=run_id, planned_row=bound_plan, attempt_n=attempt_n, methodology=methodology,
        repair_reason=repair_reason, source_job=job_path, publication=job_publication, job_bytes=source_bytes,
        interpreter=interpreter, lane_root=lane_root, package_root=package_root, execution=execution, command=command, attempt_root=attempt_root,
    )
    binding_path = attempt_root / "invocation-binding.json"
    atomic_write_new(binding_path, canonical_json_bytes(binding), allowed_root=attempt_root)
    actual_command = binding["command"]["argv"]
    stdout_path = attempt_root / "stdout.log"
    stderr_path = attempt_root / "stderr.log"
    started = time.monotonic()
    creationflags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(actual_command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, cwd=attempt_root, creationflags=creationflags, env=dict(environment) if environment is not None else None)
        deadline = time.monotonic() + timeout_seconds
        while process.poll() is None:
            if time.monotonic() >= deadline:
                _terminate_exact_tree(process)
                raise ContractError("worker_timeout", f"pid={process.pid} timeout={timeout_seconds}")
            stdout.flush()
            stderr.flush()
            if stdout_path.stat().st_size > 16 * 1024 * 1024 or stderr_path.stat().st_size > 16 * 1024 * 1024:
                _terminate_exact_tree(process)
                raise ContractError("worker_log_limit", f"pid={process.pid}")
            time.sleep(0.05)
        returncode = process.returncode
    raw = stdout_path.read_bytes()
    raw_stderr = stderr_path.read_bytes()
    require(len(raw) <= 16 * 1024 * 1024, "worker_stdout_oversize", str(len(raw)))
    require(len(raw_stderr) <= 16 * 1024 * 1024, "worker_stderr_oversize", str(len(raw_stderr)))
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ContractError("worker_stdout_utf8", str(exc)) from exc
    result_lines = [line for line in lines if line.startswith(RESULT_PREFIX)]
    if returncode != 0:
        rejection: Mapping[str, Any] | None = None
        parse_error: ContractError | None = None
        try:
            require(not result_lines, "worker_rejection_stdout", str(len(result_lines)))
            stderr_lines = raw_stderr.decode("utf-8").splitlines()
            require(len(stderr_lines) == 1 and bool(stderr_lines[0]), "worker_rejection_count", str(len(stderr_lines)))
            parsed = json.loads(stderr_lines[0])
            require(isinstance(parsed, dict), "worker_rejection_type", "object required")
            validate_worker_rejection(parsed)
            require(stderr_lines[0].encode("utf-8") + b"\n" == canonical_json_bytes(parsed), "worker_rejection_canonical", stderr_lines[0])
            rejection = parsed
        except (UnicodeDecodeError, json.JSONDecodeError, ContractError) as exc:
            parse_error = exc if isinstance(exc, ContractError) else ContractError("worker_rejection_json", str(exc))
        retained = {
            "schema": "arc4.worker-invocation/v2", "status": "rejected", "returncode": returncode,
            "elapsed_seconds": time.monotonic() - started,
            "binding": _file_reference(binding_path, "invocation-binding.json"),
            "job_after": _job_state(artifact_path),
            "stdout": _file_reference(stdout_path, "stdout.log"),
            "stderr": _file_reference(stderr_path, "stderr.log"),
            "rejection": dict(rejection) if rejection is not None else None,
            "parse_error": None if parse_error is None else {"error_code": parse_error.code, "reason": parse_error.message},
        }
        atomic_write(attempt_root / "receipt.json", canonical_json_bytes(retained), allowed_root=attempt_root)
        if parse_error is not None:
            raise parse_error
        assert rejection is not None
        raise ContractError(str(rejection["error_code"]), canonical_json(retained))
    require(len(result_lines) == 1, "worker_result_count", str(len(result_lines)))
    try:
        result = json.loads(result_lines[0][len(RESULT_PREFIX):])
    except json.JSONDecodeError as exc:
        raise ContractError("worker_result_json", str(exc)) from exc
    require(isinstance(result, dict), "worker_result_type", "object required")
    artifact = validate_canonical_job_bytes(artifact_path.read_bytes())
    expected_job = expected_success_job_from_artifact(artifact)
    validate_worker_success(result, expected_job=expected_job)
    from .verify import Rejected, validate_row_evidence
    try:
        validate_row_evidence(result, set(expected_job["candidate_ids"]))
    except Rejected as exc:
        raise ContractError(f"worker_success_{exc.code}", str(exc)) from exc
    require(_job_state(artifact_path) == {"present": True, "sha256": binding["job"]["sha256"], "bytes": binding["job"]["bytes"]}, "worker_job_mutation", str(artifact_path))
    receipt = {
        "schema": "arc4.worker-invocation/v2", "status": "succeeded", "returncode": returncode,
        "elapsed_seconds": time.monotonic() - started,
        "binding": _file_reference(binding_path, "invocation-binding.json"),
        "job_after": _job_state(artifact_path),
        "stdout": _file_reference(stdout_path, "stdout.log"), "stderr": _file_reference(stderr_path, "stderr.log"),
        "result": result, "rejection": None, "parse_error": None,
    }
    atomic_write(attempt_root / "receipt.json", canonical_json_bytes(receipt), allowed_root=attempt_root)
    return result


def retained_worker_rejection(
    attempt_root: Path, *, run_id: str, planned_row: Mapping[str, Any], attempt_n: int,
    methodology: str, repair_reason: str | None, job_path: Path, command: Sequence[str],
    job_publication: Mapping[str, Any], lane_root: Path, package_root: Path,
) -> dict[str, Any] | None:
    """Load a canonical durable worker rejection retained before journal mutation."""

    receipt_path = attempt_root / "receipt.json"
    if not receipt_path.is_file():
        return None
    receipt = load_json(receipt_path)
    if receipt.get("schema") != "arc4.worker-invocation/v2" or receipt.get("status") != "rejected":
        return None
    exact_keys(
        receipt,
        ("schema", "status", "returncode", "elapsed_seconds", "binding", "job_after", "stdout", "stderr", "rejection", "parse_error"),
        "worker_invocation_receipt_keys",
    )
    require(isinstance(receipt["returncode"], int) and not isinstance(receipt["returncode"], bool) and receipt["returncode"] != 0, "worker_invocation_returncode", str(receipt["returncode"]))
    require(isinstance(receipt["elapsed_seconds"], (int, float)) and not isinstance(receipt["elapsed_seconds"], bool) and receipt["elapsed_seconds"] >= 0, "worker_invocation_elapsed", str(receipt["elapsed_seconds"]))
    require(receipt["parse_error"] is None and isinstance(receipt["rejection"], dict), "worker_invocation_rejection", str(receipt["parse_error"]))
    validate_worker_rejection(receipt["rejection"])
    require(receipt_path.read_bytes() == canonical_json_bytes(receipt), "worker_invocation_receipt_canonical", str(receipt_path))
    for key, fixed_name in (("binding", "invocation-binding.json"), ("stdout", "stdout.log"), ("stderr", "stderr.log")):
        reference = receipt[key]
        exact_keys(reference, ("path", "sha256", "bytes"), "worker_invocation_file_reference_keys")
        require(isinstance(reference["sha256"], str) and len(reference["sha256"]) == 64 and isinstance(reference["bytes"], int) and not isinstance(reference["bytes"], bool) and reference["bytes"] >= 0, "worker_invocation_file_reference", str(reference))
        require(reference["path"] == fixed_name, "worker_invocation_path", str(reference["path"]))
        target = attempt_root / fixed_name
        require(target.is_file() and _file_reference(target, fixed_name) == reference, "worker_invocation_file_integrity", fixed_name)
    binding = load_json(attempt_root / "invocation-binding.json")
    require(isinstance(binding, dict), "worker_binding_type", "object required")
    require((attempt_root / "invocation-binding.json").read_bytes() == canonical_json_bytes(binding), "worker_binding_canonical", str(attempt_root))
    validate_invocation_binding(binding)
    expected_identity = {key: planned_row[key] for key in ("row_id", "pair_id", "case_id", "problem_id", "arm", "lane")}
    require(binding["run_id"] == run_id and binding["row_identity"] == expected_identity, "worker_binding_planned_identity", str(binding["row_identity"]))
    require(binding["attempt"] == {"attempt_n": attempt_n, "methodology": methodology, "repair_reason": repair_reason}, "worker_binding_planned_attempt", str(binding["attempt"]))
    require(binding["job"]["source_path"] == str(job_path.resolve()), "worker_binding_source_path", str(binding["job"]["source_path"]))
    require(binding["job"]["publication_path"] == str(job_publication_path(job_path).resolve()), "worker_binding_publication_path", str(binding["job"]["publication_path"]))
    require(binding["job"]["sha256"] == job_publication["sha256"] and binding["job"]["bytes"] == job_publication["bytes"], "worker_binding_publication", str(job_path))
    interpreter = Path(command[0]).resolve()
    require(binding["interpreter"] == {"lane_root": str(lane_root.resolve()), "path": str(interpreter), "sha256": sha256_file(interpreter), "package_root": str(package_root.resolve())}, "worker_binding_interpreter_identity", str(binding["interpreter"]))
    expected_argv = [*command, "--binding", str((attempt_root / "invocation-binding.json").resolve()), str((attempt_root / "job-artifact.json").resolve())]
    require(binding["command"] == command_receipt(expected_argv), "worker_binding_command_identity", str(binding["command"]))
    require(binding["paths"] == {"attempt_root": str(attempt_root.resolve()), "binding": str((attempt_root / "invocation-binding.json").resolve()), "receipt": str(receipt_path.resolve()), "stdout": str((attempt_root / "stdout.log").resolve()), "stderr": str((attempt_root / "stderr.log").resolve())}, "worker_binding_paths", str(binding["paths"]))
    artifact_path = attempt_root / "job-artifact.json"
    expected_artifact = {"present": True, "sha256": binding["job"]["sha256"], "bytes": binding["job"]["bytes"]}
    artifact_state = _job_state(artifact_path)
    exact_keys(receipt["job_after"], ("present", "sha256", "bytes"), "worker_invocation_job_after_keys")
    require(isinstance(receipt["job_after"]["present"], bool) and isinstance(receipt["job_after"]["bytes"], int) and not isinstance(receipt["job_after"]["bytes"], bool), "worker_invocation_job_after", str(receipt["job_after"]))
    require(receipt["job_after"] == artifact_state, "worker_invocation_job_after", str(receipt["job_after"]))
    if artifact_state["present"]:
        artifact = validate_canonical_job_bytes(artifact_path.read_bytes())
        if artifact.get("schema") == JOB_SCHEMA:
            validate_worker_job(artifact)
            artifact_plan = artifact
            expected_execution = {"namespace": artifact["execution_namespace"], "is_control": artifact["is_control"], "control_id": artifact["control_id"], "python_hash_seed": artifact["python_hash_seed"]}
        else:
            validate_protocol_self_test_job(artifact)
            artifact_plan = artifact["planned_row"]
            expected_execution = binding["execution"]
        require(binding["execution"] == expected_execution, "worker_binding_job_execution", str(artifact_path))
        for key, expected in planned_row.items():
            require(artifact_plan.get(key) == expected, "worker_binding_job_planned_identity", key)
    rejection = receipt["rejection"]
    if metadata_free_worker_error(str(rejection["error_code"])):
        require(rejection["lane"] is None, "worker_rejection_binding_lane", str(rejection["lane"]))
        require(not artifact_state["present"] or artifact_state == expected_artifact, "worker_invocation_job_integrity", str(artifact_state))
    else:
        require(rejection["lane"] == planned_row["lane"], "worker_rejection_binding_lane", str(rejection["lane"]))
        require(artifact_state == expected_artifact, "worker_invocation_job_integrity", str(artifact_state))
    evidence_id = sha256_bytes(canonical_json({"run_id": run_id, "row_id": planned_row["row_id"], "lane": planned_row["lane"], "attempt_n": attempt_n, "namespace": binding["execution"]["namespace"], "control_id": binding["execution"]["control_id"]}).encode("utf-8"))
    return {"rejection": dict(rejection), "invocation_binding": dict(binding), "invocation_evidence_id": evidence_id}


def commit_fragment(*, lease: RunLease, result: Mapping[str, Any], expected_row: Mapping[str, Any], fragments_root: Path) -> Path:
    lease.assert_current()
    require(result.get("row_id") == expected_row.get("row_id") and result.get("pair_id") == expected_row.get("pair_id"), "result_identity", "worker identity differs from plan")
    require(result.get("lane") == expected_row.get("lane") and result.get("arm") == expected_row.get("arm"), "result_assignment", "worker assignment differs from plan")
    destination = fragments_root / f"{result['row_id']}.json"
    safe_relative_path(lease.run_root, destination)
    merged = {**dict(expected_row), **dict(result)}
    try:
        atomic_write_new(destination, canonical_json_bytes(merged), allowed_root=lease.run_root)
    except ContractError as exc:
        if exc.code == "destination_exists":
            raise ContractError("duplicate_commit", str(destination)) from exc
        raise
    return destination


def load_pair_fragment(path: Path) -> dict[str, Any]:
    value = load_json(path)
    exact_keys(value, ("schema", "pair_id", "attempt_n", "methodology", "repair_reason", "rows"), "pair_fragment_keys")
    require(value["schema"] == "arc4.pair-fragment/v1" and isinstance(value["pair_id"], str) and bool(value["pair_id"]), "pair_fragment_schema", str(path))
    require(isinstance(value["attempt_n"], int) and not isinstance(value["attempt_n"], bool) and value["attempt_n"] >= 1, "pair_fragment_attempt", str(value.get("attempt_n")))
    require(value["methodology"] in ("initial", "explicit_repair"), "pair_fragment_methodology", str(value.get("methodology")))
    require((value["methodology"] == "initial" and value["attempt_n"] == 1 and value["repair_reason"] is None) or (value["methodology"] == "explicit_repair" and value["attempt_n"] >= 2 and isinstance(value["repair_reason"], str) and bool(value["repair_reason"].strip())), "pair_fragment_repair", str(value.get("repair_reason")))
    require(isinstance(value["rows"], list) and len(value["rows"]) == 2 and all(isinstance(row, dict) for row in value["rows"]), "pair_fragment_rows", str(path))
    require([row.get("lane") for row in value["rows"]] == ["numpy_absent", "numpy_present"], "pair_fragment_lanes", str(path))
    for row in value["rows"]:
        require(row.get("schema") == "arc4.row-result/v1" and row.get("pair_id") == value["pair_id"] and row.get("attempt_n") == value["attempt_n"] and row.get("attempt_methodology") == value["methodology"] and row.get("repair_reason") == value["repair_reason"], "pair_fragment_row_provenance", str(row.get("row_id")))
    require(len({row.get("row_id") for row in value["rows"]}) == 2, "pair_fragment_duplicate_row", value["pair_id"])
    return value


def commit_pair_fragment(
    *, lease: RunLease, results: Sequence[Mapping[str, Any]], expected_rows: Sequence[Mapping[str, Any]],
    attempt_n: int, methodology: str, repair_reason: str | None, fragments_root: Path,
) -> Path:
    lease.assert_current()
    require(len(results) == len(expected_rows) == 2, "pair_commit_rows", "exactly two lanes required")
    expected_by_lane = {row["lane"]: row for row in expected_rows}
    result_by_lane = {row.get("lane"): row for row in results}
    require(set(expected_by_lane) == set(result_by_lane) == {"numpy_present", "numpy_absent"}, "pair_commit_lanes", str(result_by_lane))
    pair_ids = {row["pair_id"] for row in expected_rows}
    require(len(pair_ids) == 1, "pair_commit_identity", str(pair_ids))
    pair_id = next(iter(pair_ids))
    merged_rows: list[dict[str, Any]] = []
    for lane in ("numpy_absent", "numpy_present"):
        expected = expected_by_lane[lane]
        result = result_by_lane[lane]
        for key, value in expected.items():
            if key == "schema":
                continue
            require(result.get(key) == value, "pair_commit_row_identity", f"{pair_id}:{lane}:{key}")
        require(result.get("schema") == "arc4.row-result/v1" and result.get("attempt_n") == attempt_n and result.get("attempt_methodology") == methodology and result.get("repair_reason") == repair_reason, "pair_commit_attempt", f"{pair_id}:{lane}")
        merged_rows.append(dict(result))
    fragment = {"schema": "arc4.pair-fragment/v1", "pair_id": pair_id, "attempt_n": attempt_n, "methodology": methodology, "repair_reason": repair_reason, "rows": merged_rows}
    destination = fragments_root / pair_fragment_name(pair_id)
    safe_relative_path(lease.run_root, destination)
    try:
        atomic_write_new(destination, canonical_json_bytes(fragment), allowed_root=lease.run_root)
    except ContractError as exc:
        if exc.code == "destination_exists":
            raise ContractError("duplicate_pair_commit", str(destination)) from exc
        raise
    return destination


def append_failure(*, lease: RunLease, journal: Path, record: Mapping[str, Any]) -> None:
    lease.assert_current()
    required = ("schema", "stage", "classification", "error_code", "reason", "attempt_n", "row_identity", "methodology", "evidence")
    exact_keys(record, required, "failure_record_keys")
    require(record["schema"] == "arc4.failure/v1", "failure_schema", str(record["schema"]))
    require(record["stage"] in ("setup", "p0", "environment", "worker", "timeout", "control", "commit", "verification", "consolidation"), "failure_stage", str(record["stage"]))
    require(record["classification"] in ("infrastructure", "product_lane", "protocol", "verification"), "failure_classification", str(record["classification"]))
    require(isinstance(record["error_code"], str) and bool(record["error_code"]), "failure_error_code", str(record["error_code"]))
    require(isinstance(record["attempt_n"], int) and not isinstance(record["attempt_n"], bool) and record["attempt_n"] > 0, "attempt_number", str(record["attempt_n"]))
    identity = record["row_identity"]
    exact_keys(identity, ("run_id", "row_id", "pair_id", "case_id", "problem_id", "arm", "lane"), "failure_identity_keys")
    require(identity["run_id"] == lease.token, "failure_run_id", str(identity["run_id"]))
    require(all(identity[key] is None or isinstance(identity[key], str) for key in ("row_id", "pair_id", "case_id", "problem_id", "arm", "lane")), "failure_identity_types", str(identity))
    rowless = identity["pair_id"] is None
    pair_level = identity["pair_id"] is not None and identity["row_id"] is None and identity["lane"] is None
    row_level = identity["pair_id"] is not None and identity["row_id"] is not None and identity["lane"] in {"numpy_present", "numpy_absent"}
    if rowless:
        require(all(identity[key] is None for key in ("row_id", "pair_id", "case_id", "problem_id", "arm", "lane")), "rowless_failure_identity", str(identity))
        require(record["stage"] in {"setup", "p0", "environment", "control", "consolidation", "verification"} and record["attempt_n"] == 1 and record["methodology"] == "initial", "rowless_failure_semantics", str(record))
    else:
        require(pair_level or row_level, "failure_identity_grain", str(identity))
        require(all(isinstance(identity[key], str) and bool(identity[key]) for key in ("pair_id", "case_id", "problem_id", "arm")), "failure_pair_identity", str(identity))
    require((record["methodology"] == "initial" and record["attempt_n"] == 1) or (record["methodology"] == "explicit_repair" and record["attempt_n"] >= 2), "failure_attempt_methodology", str(record["attempt_n"]))
    require(isinstance(record["reason"], str) and bool(record["reason"]) and isinstance(record["methodology"], str) and bool(record["methodology"]) and isinstance(record["evidence"], dict), "failure_record_types", "reason, methodology, and evidence are required")
    safe_relative_path(lease.run_root, journal)
    journal.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "ab") as stream:
        stream.write(canonical_json_bytes(dict(record)))
        stream.flush()
        os.fsync(stream.fileno())


def consolidate_fragments(*, lease: RunLease, cases: Mapping[str, Any], fragments_root: Path, output: Path) -> None:
    lease.assert_current()
    validate_frozen_cases(cases)
    expected = {row["row_id"]: row for row in cases["planned_rows"]}
    paths = sorted(fragments_root.glob("*.json"), key=lambda path: path.name)
    require(len(paths) == 132, "fragment_coverage", f"observed {len(paths)}")
    rows: list[dict[str, Any]] = []
    for path in paths:
        fragment = load_pair_fragment(path)
        require(path.name == pair_fragment_name(fragment["pair_id"]), "fragment_identity", str(path))
        for row in fragment["rows"]:
            row_id = row.get("row_id")
            require(row_id in expected, "fragment_row_identity", str(row_id))
            planned = expected[row_id]
            for key, value in planned.items():
                if key == "schema":
                    continue
                require(row.get(key) == value, "fragment_assignment", f"{row_id}:{key}")
            rows.append(row)
    require(len({row["row_id"] for row in rows}) == 264, "fragment_duplicate", "duplicate fragment row")
    payload = b"".join(canonical_json_bytes(row) for row in sorted(rows, key=lambda row: row["row_id"]))
    atomic_write(output, payload, allowed_root=lease.run_root)


def build_worker_commands(*, cases: Mapping[str, Any], interpreters: Mapping[str, str], job_root: Path, harness_root: Path) -> list[dict[str, Any]]:
    validate_frozen_cases(cases)
    require(set(interpreters) == {"numpy_present", "numpy_absent"}, "interpreter_lanes", "two lane interpreters required")
    commands: list[dict[str, Any]] = []
    for row in cases["planned_rows"]:
        job_path = job_root / f"{row['row_id']}.json"
        command = [interpreters[row["lane"]], "-m", "harness.worker", str(job_path)]
        commands.append({"row_id": row["row_id"], "lane": row["lane"], "command": command, "job_path": str(job_path), "harness_root": str(harness_root)})
    return commands


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute one already-frozen Arc 4 row. No implicit retries.")
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--interpreter", type=Path, required=True)
    parser.add_argument("--attempt-root", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=900)
    ns = parser.parse_args(argv)
    try:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
        job = load_json(ns.job.resolve())
        require(isinstance(job, dict), "worker_job_schema", "object required")
        result = run_worker(
            [str(ns.interpreter), "-m", "harness.worker", str(ns.job.resolve())],
            attempt_root=ns.attempt_root.resolve(), timeout_seconds=ns.timeout,
            run_id=str(job["run_id"]), planned_row=job, attempt_n=int(job["attempt_n"]),
            methodology=str(job["attempt_methodology"]), repair_reason=job["repair_reason"],
            job_path=ns.job.resolve(), environment=environment,
        )
        print(canonical_json(result))
        return 0
    except ContractError as exc:
        print(canonical_json({"status": "rejected", "error_code": exc.code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
