from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .artifacts import canonical_packet_paths, validate_canonical_config_paths
from .cases import generate_frozen_cases, validate_frozen_cases
from .common import ContractError, atomic_write, atomic_write_new, canonical_json_bytes, exact_keys, load_json, load_jsonl, require, sha256_bytes, sha256_file
from .controls import assemble_control_records, validate_control_record
from .environment import bind_environment_manifests, build_environment_lock, canonicalize_raw_manifest, freeze_wheelhouse
from .invocation import canonical_attempt_root, canonical_job_path, job_publication_path, lane_layout, publish_job, validate_job_publication
from .orchestrator import RunLease, append_failure, commit_pair_fragment, consolidate_fragments, load_pair_fragment, pair_fragment_name, retained_worker_rejection, run_worker
from .p0 import compare_wheels, generate_and_write_source_build_receipt, validate_source_build_receipt
from .packet import assemble_results, build_preregistration_inputs, build_source_inventory, decompose_original_matrix, normalize_failure_error_code, retain_failure_invocations, write_manifest
from .worker_protocol import JOB_SCHEMA, validate_worker_job, worker_journal_classification


MODES = ("staged", "preflight", "full-run", "repair")
RECORDED_QUERY_ARGS = {
    "semantic_input_validation": {"semantic_only": True, "semantic_weight": 1.0, "max_results": 10},
    "semantic_transaction_persistence": {"semantic_only": True, "semantic_weight": 1.0, "max_results": 25},
    "hybrid_authentication_middleware": {"semantic_only": False, "semantic_weight": 0.5, "max_results": 10},
    "hybrid_test_client_response": {"semantic_only": False, "semantic_weight": 0.5, "max_results": 25},
}
CONFIG_KEYS = (
    "schema", "run_id", "runtime_root", "packet_root", "harness_root", "python_executable",
    "wheelhouse", "lane_interpreters", "frozen_cases", "environment_lock", "preregistration_inputs",
    "preregistration_commit_receipt", "preregistration_repository", "corpora", "queries", "worker_timeout_seconds",
    "official_wheel", "source_checkout", "source_build_output", "source_build_receipt", "source_build_receipt_digest", "p0_receipt", "design_path", "frozen_config",
    "approved_utc", "pypi_url", "original_matrix_csv", "environment_capture_specs",
    "environment_lane_roots",
    "wheelhouse_spec", "wheelhouse_receipt", "child_environment",
)
ROW_JOB_EXTRA_KEYS = (
    "schema", "run_id", "repo_id", "database", "storage_path", "package_root", "treatment_wheel", "config_path", "config_sha256", "environment_lock_path",
    "environment_lock_sha256", "candidate_ids", "query_text", "query_vector",
    "pair_invocation_ordinal", "frozen_source_files", "trial_source_files", "home_path", "attempt_n",
    "attempt_methodology", "repair_reason", "python_hash_seed", "embed_model",
    "execution_namespace", "is_control", "control_id",
)


def validate_campaign_config(value: Mapping[str, Any]) -> None:
    exact_keys(value, CONFIG_KEYS, "campaign_config_keys")
    require(value["schema"] == "arc4.campaign-config/v1" and isinstance(value["run_id"], str) and bool(value["run_id"]), "campaign_config_schema", str(value.get("schema")))
    for key in ("runtime_root", "packet_root", "harness_root", "python_executable", "wheelhouse", "wheelhouse_spec", "wheelhouse_receipt", "frozen_cases", "environment_lock", "preregistration_inputs", "preregistration_commit_receipt", "preregistration_repository", "official_wheel", "source_checkout", "source_build_output", "source_build_receipt", "source_build_receipt_digest", "p0_receipt", "design_path", "frozen_config", "original_matrix_csv"):
        require(isinstance(value[key], str) and bool(value[key]), "campaign_path", key)
    exact_keys(value["lane_interpreters"], ("numpy_present", "numpy_absent"), "campaign_interpreters")
    exact_keys(value["environment_capture_specs"], ("numpy_present", "numpy_absent"), "campaign_capture_specs")
    exact_keys(value["environment_lane_roots"], ("numpy_present", "numpy_absent"), "campaign_environment_roots")
    for lane in ("numpy_present", "numpy_absent"):
        roots = value["environment_lane_roots"][lane]
        exact_keys(roots, ("lane_venv", "trial_root"), "campaign_environment_lane_root_keys")
        lane_root = Path(roots["lane_venv"]).resolve()
        require(Path(value["lane_interpreters"][lane]).resolve() == (lane_root / "Scripts" / "python.exe").resolve(), "campaign_interpreter_layout", lane)
    require(isinstance(value["pypi_url"], str) and value["pypi_url"].startswith("https://files.pythonhosted.org/"), "campaign_pypi_url", str(value["pypi_url"]))
    exact_keys(value["child_environment"], ("system_root", "temp", "locale", "timezone", "pythonhashseed"), "campaign_child_environment")
    require(all(isinstance(value["child_environment"][key], str) and bool(value["child_environment"][key]) for key in value["child_environment"]), "campaign_child_environment_values", str(value["child_environment"]))
    require(isinstance(value["approved_utc"], str) and value["approved_utc"].endswith("Z"), "campaign_approved_utc", str(value["approved_utc"]))
    exact_keys(value["corpora"], ("django", "fastapi", "jcodemunch"), "campaign_corpora")
    require(isinstance(value["queries"], dict) and len(value["queries"]) == 4, "campaign_queries", "exactly four queries required")
    require(isinstance(value["worker_timeout_seconds"], int) and not isinstance(value["worker_timeout_seconds"], bool) and 1 <= value["worker_timeout_seconds"] <= 3600, "campaign_timeout", str(value["worker_timeout_seconds"]))
    for name, corpus in value["corpora"].items():
        exact_keys(corpus, ("database", "repo_id", "candidate_ids"), "campaign_corpus_keys")
        require(isinstance(corpus["candidate_ids"], list) and corpus["candidate_ids"] == sorted(set(corpus["candidate_ids"])) and bool(corpus["candidate_ids"]), "campaign_candidate_ids", name)
    for query_id, query in value["queries"].items():
        exact_keys(query, ("query_text", "query_vector", "query_vector_sha256"), "campaign_query_keys")
        require(isinstance(query_id, str) and isinstance(query["query_text"], str) and bool(query["query_text"]) and isinstance(query["query_vector"], list) and len(query["query_vector"]) == 384, "campaign_query", query_id)
        require(sha256_bytes(canonical_json_bytes(query["query_vector"]).rstrip(b"\n")) == query["query_vector_sha256"], "campaign_query_hash", query_id)
    validate_canonical_config_paths(value)


def locked_trial_configuration(config: Mapping[str, Any]) -> dict[str, Any]:
    packet_root = Path(str(config["packet_root"])).resolve()
    lock = load_json(Path(str(config["environment_lock"])).resolve())
    require(isinstance(lock, dict) and isinstance(lock.get("manifest_bindings"), dict), "campaign_manifest_bindings", "environment lock bindings required")
    canonical = lock["manifest_bindings"].get("canonical")
    exact_keys(canonical, ("numpy_present", "numpy_absent"), "campaign_manifest_binding_lanes")
    observed: dict[str, dict[str, Any]] = {}
    for lane in ("numpy_present", "numpy_absent"):
        binding = canonical[lane]
        exact_keys(binding, ("path", "sha256"), "campaign_manifest_binding_keys")
        path = (packet_root / str(binding["path"])).resolve()
        try:
            path.relative_to(packet_root)
        except ValueError as exc:
            raise ContractError("campaign_manifest_path", str(path)) from exc
        require(path.is_file() and sha256_file(path) == binding["sha256"], "campaign_manifest_hash", str(path))
        manifest = load_json(path)
        require(path.read_bytes() == canonical_json_bytes(manifest), "campaign_manifest_canonical", str(path))
        configuration = manifest.get("configuration") if isinstance(manifest, dict) else None
        exact_keys(configuration, ("share_savings", "perf_telemetry_enabled", "embed_model"), "campaign_trial_configuration_keys")
        require(configuration["share_savings"] is False and configuration["perf_telemetry_enabled"] is False and isinstance(configuration["embed_model"], str) and bool(configuration["embed_model"]), "campaign_trial_configuration", str(configuration))
        observed[lane] = dict(configuration)
    require(observed["numpy_present"] == observed["numpy_absent"], "campaign_trial_configuration_lane_difference", str(observed))
    return observed["numpy_present"]


def environment_creation_commands(config: Mapping[str, Any]) -> list[list[str]]:
    """Return the only allowed environment-creation commands, in deterministic order."""
    validate_campaign_config(config)
    wheelhouse_path = Path(config["wheelhouse"]).resolve()
    wheelhouse = str(wheelhouse_path)
    lock = build_environment_lock(wheelhouse_path)
    pip_artifact = next(item for item in lock["wheelhouse_artifacts"] if item["project"] == "pip")
    commands: list[list[str]] = []
    for lane in ("numpy_present", "numpy_absent"):
        interpreter = str(Path(config["lane_interpreters"][lane]).resolve())
        lane_root = str(Path(interpreter).resolve().parent.parent)
        commands.append([str(Path(config["python_executable"]).resolve()), "-m", "venv", lane_root])
        commands.append([interpreter, "-m", "pip", "install", "--no-index", "--find-links", wheelhouse, "--no-deps", "--force-reinstall", str(wheelhouse_path / pip_artifact["filename"])])
        artifacts = [item for item in lock["lanes"][lane]["distributions"] if item["project"] != "pip"]
        commands.append([interpreter, "-m", "pip", "install", "--no-index", "--find-links", wheelhouse, "--no-deps", "--force-reinstall", *(str(wheelhouse_path / item["filename"]) for item in artifacts)])
    return commands


def validate_preregistration_commit(config: Mapping[str, Any]) -> Mapping[str, Any]:
    paths = validate_canonical_config_paths(config)
    receipt = load_json(paths["preregistration_commit_receipt"])
    exact_keys(receipt, ("schema", "commit_sha", "committed", "files"), "prereg_commit_keys")
    require(receipt["schema"] == "arc4.preregistration-commit/v1" and receipt["committed"] is True, "prereg_commit_status", str(receipt))
    require(isinstance(receipt["commit_sha"], str) and len(receipt["commit_sha"]) == 40 and all(character in "0123456789abcdef" for character in receipt["commit_sha"]), "prereg_commit_sha", str(receipt["commit_sha"]))
    repository = Path(config["preregistration_repository"]).resolve()
    require(repository.is_dir(), "prereg_repository", str(repository))
    artifacts = {
        "CONFIG.json": paths["config"],
        "ENVIRONMENT-LOCK.json": paths["environment_lock"],
        "P0-RECEIPT.json": paths["p0_receipt"],
        "PREREGISTRATION-INPUTS.json": paths["preregistration_inputs"],
        "SOURCE-BUILD-RECEIPT.json": paths["source_build_receipt"],
        "SOURCE-BUILD-RECEIPT.sha256": paths["source_build_receipt_digest"],
        "SOURCE-INVENTORY.json": paths["source_inventory"],
        "frozen-cases.json": paths["frozen_cases"],
    }
    expected = {name: sha256_file(path) for name, path in artifacts.items()}
    require(receipt["files"] == expected, "prereg_commit_files", "committed preregistration hashes differ")
    resolved = _git_text(repository, ["rev-parse", f"{receipt['commit_sha']}^{{commit}}"])
    require(resolved == receipt["commit_sha"], "prereg_commit_object", resolved)
    for name, path in artifacts.items():
        try:
            relative = path.relative_to(repository).as_posix()
        except ValueError as exc:
            raise ContractError("prereg_artifact_outside_repository", str(path)) from exc
        blob = _git_text(repository, ["rev-parse", f"{receipt['commit_sha']}:{relative}"])
        require(len(blob) == 40 and all(character in "0123456789abcdef" for character in blob), "prereg_tree_blob", f"{name}:{blob}")
        require(_git_blob_sha256(repository, blob) == expected[name], "prereg_tree_hash", name)
    return receipt


def _git_text(repository: Path, arguments: Sequence[str]) -> str:
    process = subprocess.Popen(["git", "-C", str(repository), *arguments], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise ContractError("prereg_git_timeout", "Git observation timed out") from exc
    require(len(stdout) + len(stderr) <= 65536, "prereg_git_output", "Git observation output exceeded limit")
    require(process.returncode == 0, "prereg_git_command", stderr.decode("utf-8", errors="replace"))
    return stdout.decode("utf-8").strip()


def _git_blob_sha256(repository: Path, blob: str) -> str:
    with tempfile.TemporaryFile() as stream:
        process = subprocess.Popen(["git", "-C", str(repository), "cat-file", "blob", blob], stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.PIPE, shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            _, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise ContractError("prereg_git_timeout", "Git blob read timed out") from exc
        require(process.returncode == 0 and len(stderr) <= 65536, "prereg_git_blob", stderr.decode("utf-8", errors="replace"))
        stream.seek(0)
        import hashlib
        digest = hashlib.sha256()
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
        return digest.hexdigest()


def validate_frozen_execution_inputs(config: Mapping[str, Any]) -> Mapping[str, Any]:
    paths = validate_canonical_config_paths(config)
    source_bytes = Path(config["frozen_config"]).resolve().read_bytes()
    packet_bytes = paths["config"].read_bytes()
    require(source_bytes == packet_bytes, "external_frozen_config_bytes", "external frozen config differs from packet CONFIG.json")
    require(packet_bytes == canonical_json_bytes(dict(config)), "active_config_bytes", "active configuration differs from canonical packet CONFIG.json")
    prereg = load_json(paths["preregistration_inputs"])
    expected = {
        "config_sha256": sha256_file(paths["config"]),
        "frozen_cases_sha256": sha256_file(paths["frozen_cases"]),
        "environment_lock_sha256": sha256_file(paths["environment_lock"]),
        "p0_receipt_sha256": sha256_file(paths["p0_receipt"]),
        "source_inventory_sha256": sha256_file(paths["source_inventory"]),
    }
    require(all(prereg.get(key) == value for key, value in expected.items()), "active_preregistration_hashes", str(expected))
    require(prereg.get("design_sha256") == sha256_file(Path(config["design_path"])), "active_design_hash", str(prereg.get("design_sha256")))
    return prereg


def validate_full_preregistration_semantics(config: Mapping[str, Any]) -> Mapping[str, Any]:
    """Run the same preregistration semantic path used by the standalone verifier."""
    from .verify import verify_environment, verify_frozen_cases, verify_p0, verify_preregistration

    root = Path(config["packet_root"]).resolve()
    p0 = verify_p0(root)
    cases, _planned, _candidates = verify_frozen_cases(root)
    lock = verify_environment(root)
    verify_preregistration(root, cases=cases, p0=p0, lock=lock)
    require(cases["run_id"] == config["run_id"], "preregistration_run_identity", str(cases.get("run_id")))
    return cases


def rows_for_mode(cases: Mapping[str, Any], mode: str) -> list[Mapping[str, Any]]:
    require(mode in MODES, "campaign_mode", mode)
    validate_frozen_cases(cases)
    if mode == "staged":
        return []
    if mode == "preflight":
        return [row for row in cases["planned_rows"] if row["arm"] == "preflight"]
    require(mode == "full-run", "campaign_rows_mode", mode)
    return list(cases["planned_rows"])


def ordered_rows_for_execution(rows: Sequence[Mapping[str, Any]]) -> list[tuple[Mapping[str, Any], int]]:
    pairs: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        pairs.setdefault(str(row["pair_id"]), []).append(row)
    ordered: list[tuple[Mapping[str, Any], int]] = []
    for pair_id in sorted(pairs):
        pair = pairs[pair_id]
        require(len(pair) == 2 and {row["lane"] for row in pair} == {"numpy_present", "numpy_absent"}, "campaign_pair_lanes", pair_id)
        declared = {str(row["lane_invocation_order"]) for row in pair}
        require(len(declared) == 1 and next(iter(declared)) in ("numpy_first", "python_first"), "campaign_pair_order", pair_id)
        first = "numpy_present" if next(iter(declared)) == "numpy_first" else "numpy_absent"
        by_lane = {str(row["lane"]): row for row in pair}
        second = "numpy_absent" if first == "numpy_present" else "numpy_present"
        ordered.extend(((by_lane[first], 1), (by_lane[second], 2)))
    return ordered


def child_environment(config: Mapping[str, Any], interpreter: Path, *, home: Path, seed: str | None = None) -> dict[str, str]:
    values = config["child_environment"]
    system_root = Path(values["system_root"]).resolve()
    temp = Path(values["temp"]).resolve()
    home = home.resolve()
    home.mkdir(parents=True, exist_ok=True)
    drive, tail = os.path.splitdrive(str(home))
    if not drive:
        drive = system_root.drive or "C:"
        tail = str(home)
    result = {
        "SystemRoot": str(system_root), "ComSpec": str(system_root / "System32" / "cmd.exe"),
        "TEMP": str(temp), "TMP": str(temp),
        "USERPROFILE": str(home), "HOME": str(home), "HOMEDRIVE": drive, "HOMEPATH": tail,
        "PATH": os.pathsep.join((str(interpreter.resolve().parent), str(system_root / "System32"))),
        "PYTHONPATH": str(Path(config["harness_root"]).resolve().parent),
        "PYTHONNOUSERSITE": "1", "PYTHONHASHSEED": seed if seed is not None else values["pythonhashseed"],
        "PYTHONUTF8": "1", "LC_ALL": values["locale"], "LANG": values["locale"], "TZ": values["timezone"],
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "JCODEMUNCH_SHARE_SAVINGS": "0",
    }
    require(not any("KEY" in key or "TOKEN" in key or "CREDENTIAL" in key for key in result), "campaign_child_credentials", "credential variable admitted")
    return result


def database_file_receipts(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    result: dict[str, Any] = {"database_path": str(resolved), "files": {}}
    for suffix, candidate in (("db", resolved), ("wal", Path(str(resolved) + "-wal")), ("shm", Path(str(resolved) + "-shm"))):
        if candidate.exists():
            require(candidate.is_file(), "frozen_database_file", str(candidate))
            result["files"][suffix] = {"present": True, "sha256": sha256_file(candidate), "size": candidate.stat().st_size}
        else:
            result["files"][suffix] = {"present": False, "sha256": None, "size": 0}
    return result


def frozen_original_snapshot(config: Mapping[str, Any]) -> dict[str, Any]:
    return {name: database_file_receipts(Path(corpus["database"])) for name, corpus in sorted(config["corpora"].items())}


class CampaignOwner:
    """Single lifecycle owner. Every attempt is fresh; reruns require an explicit repair action."""

    def __init__(self, config: Mapping[str, Any], *, worker_runner: Callable[..., dict[str, Any]] = run_worker, setup_runner: Callable[[Sequence[str], Path, int], None] | None = None) -> None:
        validate_campaign_config(config)
        self.config = dict(config)
        self.runtime_root = Path(config["runtime_root"]).resolve()
        self.packet_root = Path(config["packet_root"]).resolve()
        self.harness_root = Path(config["harness_root"]).resolve()
        self.worker_runner = worker_runner
        self.setup_runner = setup_runner or self._run_setup
        self.lease = RunLease(self.runtime_root, str(config["run_id"]))
        self.failure_journal = self.runtime_root / "failure-journal.jsonl"
        self.repair_declarations_root = self.runtime_root / "repair-declarations"

    def _run_setup(self, command: Sequence[str], log_path: Path, timeout_seconds: int) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        Path(self.config["child_environment"]["temp"]).resolve().mkdir(parents=True, exist_ok=True)
        environment = child_environment(self.config, Path(command[0]), home=self.runtime_root / "setup-homes" / log_path.stem)
        with log_path.open("xb") as log:
            process = subprocess.Popen(list(command), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, cwd=self.packet_root, env=environment, shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False, shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                raise ContractError("setup_timeout", "setup command exceeded its bounded timeout") from exc
        require(code == 0, "setup_command_failed", f"exit {code}; receipt {log_path}")

    def _run_owned_p0(self) -> tuple[dict[str, Any], str, dict[str, Any]]:
        tool = Path(__file__).with_name("p0.py").resolve()
        receipt_path = Path(self.config["source_build_receipt"]).resolve()
        digest_path = Path(self.config["source_build_receipt_digest"]).resolve()
        build_receipt, receipt_sha256 = generate_and_write_source_build_receipt(
            checkout=Path(self.config["source_checkout"]),
            python_executable=Path(self.config["python_executable"]),
            output_directory=Path(self.config["source_build_output"]),
            comparison_tool=tool, receipt_path=receipt_path, digest_path=digest_path,
            allowed_root=self.packet_root, timeout_seconds=900,
        )
        expected_payload = canonical_json_bytes(build_receipt)
        require(receipt_path.read_bytes() == expected_payload, "owned_source_build_receipt_bytes", str(receipt_path))
        require(digest_path.read_bytes() == (receipt_sha256 + "\n").encode("ascii"), "owned_source_build_digest", str(digest_path))
        require(sha256_bytes(expected_payload) == receipt_sha256, "owned_source_build_receipt_hash", receipt_sha256)
        produced = build_receipt.get("produced_wheel", {})
        require(isinstance(produced, dict) and set(produced) == {"path", "sha256"}, "owned_source_build_wheel", str(produced))
        rebuilt_wheel = Path(str(produced["path"])).resolve()
        require(rebuilt_wheel.parent == Path(self.config["source_build_output"]).resolve(), "owned_source_build_wheel_root", str(rebuilt_wheel))
        validate_source_build_receipt(
            build_receipt, receipt_sha256=receipt_sha256,
            rebuilt_wheel=rebuilt_wheel, comparison_tool=tool,
        )
        p0 = compare_wheels(Path(self.config["official_wheel"]), rebuilt_wheel, tool_sha256=sha256_file(tool))
        require(p0["status"] == "passed" and p0["rebuilt_sha256"] == produced["sha256"], "owned_p0_binding", str(produced))
        atomic_write(Path(self.config["p0_receipt"]), canonical_json_bytes(p0), allowed_root=self.packet_root)
        return build_receipt, receipt_sha256, p0

    def _stage_inputs(self) -> dict[str, Any]:
        self.packet_root.mkdir(parents=True, exist_ok=True)
        paths = canonical_packet_paths(self.packet_root)
        wheelhouse_receipt = freeze_wheelhouse(load_json(Path(self.config["wheelhouse_spec"])), Path(self.config["wheelhouse"]))
        atomic_write(Path(self.config["wheelhouse_receipt"]), canonical_json_bytes(wheelhouse_receipt), allowed_root=self.runtime_root)
        (self.packet_root / "inputs").mkdir(parents=True, exist_ok=True)
        packet_wheel = self.packet_root / "inputs" / "jcodemunch_mcp-1.108.228-py3-none-any.whl"
        shutil.copy2(Path(self.config["official_wheel"]), packet_wheel)
        shutil.copy2(Path(self.config["frozen_config"]), paths["config"])
        require(sha256_file(packet_wheel) == "ff74b6344430053c6fad9064892d6a3904ffba6265823e3fba4dfde78f9a0488", "official_wheel_hash", str(packet_wheel))
        for index, command in enumerate(environment_creation_commands(self.config)):
            try:
                self.setup_runner(command, self.runtime_root / "setup-logs" / f"environment-{index:02d}.log", 900)
            except Exception as exc:
                self._failure(stage="environment", classification="infrastructure", code=getattr(exc, "code", "environment_failure"), reason=str(exc))
                raise ContractError("environment_failure", str(exc)) from exc
        try:
            build_receipt, build_receipt_sha256, p0 = self._run_owned_p0()
        except Exception as exc:
            self._failure(stage="p0", classification="protocol", code=getattr(exc, "code", "p0_failure"), reason=str(exc))
            raise ContractError("p0_failure", str(exc)) from exc
        lock = build_environment_lock(Path(self.config["wheelhouse"]))
        atomic_write(Path(self.config["environment_lock"]), canonical_json_bytes(lock), allowed_root=self.packet_root)
        raw_paths = {"numpy_present": self.packet_root / "env" / "raw-numpy-present.json", "numpy_absent": self.packet_root / "env" / "raw-numpy-absent.json"}
        for lane in ("numpy_present", "numpy_absent"):
            command = [str(Path(self.config["lane_interpreters"][lane]).resolve()), "-m", "harness.environment", "capture", str(Path(self.config["environment_capture_specs"][lane]).resolve()), str(raw_paths[lane])]
            try:
                self.setup_runner(command, self.runtime_root / "setup-logs" / f"capture-{lane}.log", 120)
            except Exception as exc:
                self._failure(stage="environment", classification="infrastructure", code=getattr(exc, "code", "environment_capture_failure"), reason=str(exc))
                raise ContractError("environment_failure", str(exc)) from exc
        roots = {lane: {key: Path(path) for key, path in self.config["environment_lane_roots"][lane].items()} for lane in ("numpy_present", "numpy_absent")}
        for lane, name in (("numpy_present", "numpy-present.json"), ("numpy_absent", "numpy-absent.json")):
            canonical = canonicalize_raw_manifest(load_json(raw_paths[lane]), lane_venv=roots[lane]["lane_venv"], trial_root=roots[lane]["trial_root"], packet_root=self.packet_root)
            atomic_write(self.packet_root / "env" / name, canonical_json_bytes(canonical), allowed_root=self.packet_root)
        lock = bind_environment_manifests(lock, packet_root=self.packet_root, lane_roots=roots)
        atomic_write(Path(self.config["environment_lock"]), canonical_json_bytes(lock), allowed_root=self.packet_root)
        corpora = [
            {"name": name, "working_database_sha256": sha256_file(Path(value["database"])), "candidate_ids": value["candidate_ids"]}
            for name, value in self.config["corpora"].items()
        ]
        queries = {
            key: {
                "query": value["query_text"],
                "query_embedding_sha256": value["query_vector_sha256"],
                "serialized_args": {
                    "query": value["query_text"],
                    **RECORDED_QUERY_ARGS[key],
                    "detail_level": "compact",
                    "debug": False,
                },
            }
            for key, value in self.config["queries"].items()
        }
        cases = generate_frozen_cases(run_id=self.config["run_id"], corpora=corpora, queries=queries)
        atomic_write(Path(self.config["frozen_cases"]), canonical_json_bytes(cases), allowed_root=self.packet_root)
        original_start = frozen_original_snapshot(self.config)
        atomic_write(self.runtime_root / "frozen-originals-start.json", canonical_json_bytes(original_start), allowed_root=self.runtime_root)
        inventory = build_source_inventory(
            packet_root=self.packet_root, cases=cases, p0=p0, lock=lock,
            pypi_url=self.config["pypi_url"], build_receipt=build_receipt,
            build_receipt_sha256=build_receipt_sha256,
            query_vector_values={key: value["query_vector"] for key, value in self.config["queries"].items()},
        )
        atomic_write(paths["source_inventory"], canonical_json_bytes(inventory), allowed_root=self.packet_root)
        prereg = build_preregistration_inputs(design_path=Path(self.config["design_path"]), config_path=paths["config"], frozen_cases_path=paths["frozen_cases"], environment_lock_path=paths["environment_lock"], p0_receipt_path=paths["p0_receipt"], source_inventory_path=paths["source_inventory"], packet_root=self.packet_root, approved_utc=self.config["approved_utc"])
        atomic_write(Path(self.config["preregistration_inputs"]), canonical_json_bytes(prereg), allowed_root=self.packet_root)
        original = decompose_original_matrix(Path(self.config["original_matrix_csv"]))
        atomic_write(self.packet_root / "ORIGINAL-MATRIX-DECOMPOSITION.json", canonical_json_bytes(original), allowed_root=self.packet_root)
        return cases

    def _failure(
        self, *, stage: str, classification: str, code: str, reason: str,
        row: Mapping[str, Any] | None = None, pair: Mapping[str, Any] | None = None, attempt_n: int = 1,
        methodology: str = "initial", evidence: Mapping[str, Any] | None = None,
    ) -> None:
        require(not (row is not None and pair is not None), "failure_identity_ambiguity", "row and pair identity are mutually exclusive")
        identity = {
            "run_id": self.config["run_id"], "row_id": None, "pair_id": None,
            "case_id": None, "problem_id": None, "arm": None, "lane": None,
        }
        if row is not None:
            for key in ("row_id", "pair_id", "case_id", "problem_id", "arm", "lane"):
                identity[key] = row[key]
        elif pair is not None:
            for key in ("pair_id", "case_id", "problem_id", "arm"):
                identity[key] = pair[key]
        normalized_code = normalize_failure_error_code(stage, classification, code)
        retained_evidence = {"cause_error_code": code, **dict(evidence or {})}
        append_failure(
            lease=self.lease, journal=self.failure_journal,
            record={
                "schema": "arc4.failure/v1", "stage": stage, "classification": classification,
                "error_code": normalized_code, "reason": reason, "attempt_n": attempt_n, "row_identity": identity,
                "methodology": methodology, "evidence": retained_evidence,
            },
        )

    def _materialize_job(self, row: Mapping[str, Any], *, namespace: str = "measured", pair_invocation_ordinal: int = 1, attempt_n: int = 1, methodology: str = "initial", repair_reason: str | None = None, control_id: str | None = None, python_hash_seed: str | None = None) -> Path:
        corpus = self.config["corpora"][row["corpus"]]
        query = self.config["queries"][row["query_id"]]
        source_database = Path(corpus["database"]).resolve()
        require(source_database.is_file() and sha256_file(source_database) == row["corpus_sha256"], "trial_database_source", str(source_database))
        trial_root = self.runtime_root / "trials" / namespace / row["row_id"] / f"attempt-{attempt_n:04d}"
        trial_root.mkdir(parents=True, exist_ok=False)
        trial_database = trial_root / source_database.name
        source_receipt = database_file_receipts(source_database)
        start_snapshot_path = self.runtime_root / "frozen-originals-start.json"
        if start_snapshot_path.is_file():
            start_snapshot = load_json(start_snapshot_path)
            require(source_receipt == start_snapshot[row["corpus"]], "frozen_database_changed_since_start", str(source_database))
        for suffix, source in (("db", source_database), ("wal", Path(str(source_database) + "-wal")), ("shm", Path(str(source_database) + "-shm"))):
            expected = source_receipt["files"][suffix]
            if expected["present"]:
                target = trial_database if suffix == "db" else Path(str(trial_database) + f"-{suffix}")
                shutil.copy2(source, target)
        trial_receipt = database_file_receipts(trial_database)
        require(source_receipt["files"] == trial_receipt["files"], "trial_database_copy", str(source_database))
        layout = lane_layout(self.config, row["lane"])
        package_root = layout["package_root"]
        trial_configuration = locked_trial_configuration(self.config)
        atomic_write(trial_root / "config.jsonc", canonical_json_bytes(trial_configuration), allowed_root=self.runtime_root)
        job = {
            **dict(row), "schema": JOB_SCHEMA, "run_id": self.config["run_id"],
            "repo_id": corpus["repo_id"], "database": str(trial_database),
            "storage_path": str(trial_root), "package_root": str(package_root),
            "treatment_wheel": str(Path(self.config["official_wheel"]).resolve()),
            "config_path": str((Path(self.config["packet_root"]) / "CONFIG.json").resolve()),
            "config_sha256": sha256_file(Path(self.config["packet_root"]) / "CONFIG.json"),
            "environment_lock_path": str(Path(self.config["environment_lock"]).resolve()),
            "environment_lock_sha256": sha256_file(Path(self.config["environment_lock"])),
            "candidate_ids": corpus["candidate_ids"], "query_text": query["query_text"],
            "query_vector": query["query_vector"],
            "pair_invocation_ordinal": pair_invocation_ordinal,
            "attempt_n": attempt_n, "attempt_methodology": methodology, "repair_reason": repair_reason,
            "python_hash_seed": self.config["child_environment"]["pythonhashseed"] if control_id is None else python_hash_seed,
            "embed_model": trial_configuration["embed_model"],
            "execution_namespace": "control" if control_id is not None else namespace,
            "is_control": control_id is not None, "control_id": control_id,
            "home_path": str((trial_root / "home").resolve()),
            "frozen_source_files": source_receipt, "trial_source_files": trial_receipt,
        }
        require(set(job) >= set(row) | set(ROW_JOB_EXTRA_KEYS), "job_materialization", row["row_id"])
        validate_worker_job(job)
        path = canonical_job_path(self.runtime_root, job)
        publish_job(path, job, allowed_root=self.runtime_root)
        return path

    def _failure_records(self) -> list[Mapping[str, Any]]:
        if not self.failure_journal.is_file() or self.failure_journal.stat().st_size == 0:
            return []
        records = load_jsonl(self.failure_journal)
        require(all(record.get("schema") == "arc4.failure/v1" for record in records), "failure_journal_schema", str(self.failure_journal))
        return records

    def _pair_failures(self, rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        require(len(rows) == 2 and len({row["pair_id"] for row in rows}) == 1, "repair_pair_rows", str(rows))
        pair_id = rows[0]["pair_id"]
        planned_by_row = {row["row_id"]: row for row in rows}
        matching = [
            record
            for record in self._failure_records()
            if record["stage"] in {"setup", "worker", "timeout", "commit"}
            and record["row_identity"]["pair_id"] == pair_id
        ]
        for record in matching:
            identity = record["row_identity"]
            require(identity["run_id"] == self.config["run_id"], "repair_failure_run_id", str(identity["run_id"]))
            first = rows[0]
            for key in ("pair_id", "case_id", "problem_id", "arm"):
                require(identity[key] == first[key], "repair_failure_identity", f"{pair_id}:{key}")
            if identity["row_id"] is None:
                require(identity["lane"] is None, "repair_failure_pair_grain", str(identity))
            else:
                require(identity["row_id"] in planned_by_row, "repair_failure_row_identity", str(identity))
                planned = planned_by_row[identity["row_id"]]
                require(identity["lane"] == planned["lane"], "repair_failure_identity", f"{pair_id}:lane")
        return matching

    def _repair_attempt(self, rows: Sequence[Mapping[str, Any]]) -> int:
        matching = self._pair_failures(rows)
        require(bool(matching), "repair_without_failure", rows[0]["pair_id"])
        attempts = [int(record["attempt_n"]) for record in matching]
        require(all(count == 1 for count in Counter(attempts).values()), "repair_duplicate_attempt", str(attempts))
        ordered = sorted(attempts)
        require(ordered == list(range(1, ordered[-1] + 1)), "repair_attempt_gap", str(ordered))
        for record in matching:
            expected_methodology = "initial" if record["attempt_n"] == 1 else "explicit_repair"
            require(record["methodology"] == expected_methodology, "repair_failure_methodology", str(record["attempt_n"]))
        return ordered[-1] + 1

    def _repair_declaration(self, rows: Sequence[Mapping[str, Any]], attempt_n: int, repair_reason: str) -> dict[str, Any]:
        require(len(rows) == 2 and len({row["pair_id"] for row in rows}) == 1, "repair_declaration_pair", str(rows))
        require(attempt_n >= 2 and bool(repair_reason.strip()), "repair_declaration_values", f"{attempt_n}:{repair_reason!r}")
        first = rows[0]
        declaration = {
            "schema": "arc4.repair-declaration/v1",
            "run_id": self.config["run_id"], "pair_id": first["pair_id"], "case_id": first["case_id"],
            "problem_id": first["problem_id"], "arm": first["arm"], "attempt_n": attempt_n,
            "repair_reason": repair_reason,
            "row_ids": {row["lane"]: row["row_id"] for row in rows},
        }
        require(set(declaration["row_ids"]) == {"numpy_present", "numpy_absent"}, "repair_declaration_lanes", str(declaration["row_ids"]))
        pair_directory = sha256_bytes(first["pair_id"].encode("utf-8"))
        path = self.repair_declarations_root / pair_directory / f"attempt-{attempt_n:04d}.json"
        if path.exists():
            observed = load_json(path)
            require(observed == declaration and path.read_bytes() == canonical_json_bytes(declaration), "repair_declaration_conflict", str(path))
            return declaration
        atomic_write_new(path, canonical_json_bytes(declaration), allowed_root=self.runtime_root)
        return declaration

    def _journal_then_raise(self, exc: BaseException, **failure: Any) -> None:
        try:
            self._failure(**failure)
        except BaseException as journal_exc:
            detail = {
                "original": {"type": type(exc).__name__, "code": getattr(exc, "code", "exception"), "reason": str(exc)},
                "journal": {"type": type(journal_exc).__name__, "code": getattr(journal_exc, "code", "exception"), "reason": str(journal_exc)},
            }
            raise ContractError("failure_journal_failed", canonical_json_bytes(detail).decode("utf-8").strip()) from journal_exc
        raise exc

    def _attempt_residue_exists(self, rows: Sequence[Mapping[str, Any]], *, attempt_n: int, methodology: str) -> bool:
        namespace = "repair" if methodology == "explicit_repair" else "measured"
        pair_directory = sha256_bytes(rows[0]["pair_id"].encode("utf-8"))
        result_root = self.runtime_root / "pair-attempts" / pair_directory / f"attempt-{attempt_n:04d}"
        if result_root.exists():
            return True
        for row in rows:
            relative = Path(row["row_id"]) / f"attempt-{attempt_n:04d}"
            execution_namespace = "repair" if methodology == "explicit_repair" else ("preflight" if row["arm"] == "preflight" else "measured")
            if (self.runtime_root / "trials" / namespace / relative).exists() or (self.runtime_root / "attempts" / execution_namespace / relative).exists() or (self.runtime_root / "jobs" / execution_namespace / row["row_id"] / f"attempt-{attempt_n:04d}.json").exists():
                return True
        return False

    def _recover_retained_worker_rejection(
        self, rows: Sequence[Mapping[str, Any]], *, attempt_n: int,
        methodology: str, repair_reason: str | None,
    ) -> bool:
        recovered: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
        namespace = "repair" if methodology == "explicit_repair" else ("preflight" if rows[0]["arm"] == "preflight" else "measured")
        for row in rows:
            job_path = self.runtime_root / "jobs" / namespace / row["row_id"] / f"attempt-{attempt_n:04d}.json"
            if not job_path.is_file() or not job_publication_path(job_path).is_file():
                continue
            publication = load_json(job_publication_path(job_path))
            job = json.loads(validate_job_publication(publication, job_path).decode("utf-8"))
            attempt_root = self.runtime_root / "attempts" / namespace / row["row_id"] / f"attempt-{attempt_n:04d}"
            layout = lane_layout(self.config, row["lane"])
            interpreter = layout["interpreter"]
            command = [str(interpreter), "-m", "harness.worker"]
            retained = retained_worker_rejection(
                attempt_root, run_id=self.config["run_id"], planned_row=row, attempt_n=attempt_n,
                methodology=methodology, repair_reason=repair_reason, job_path=job_path, command=command,
                job_publication=publication, lane_root=layout["lane_root"], package_root=layout["package_root"],
            )
            if retained is None:
                continue
            rejection = retained["rejection"]
            require(rejection["lane"] in {None, row["lane"]}, "worker_rejection_row_binding", str(row["row_id"]))
            recovered.append((row, retained))
        require(len(recovered) <= 1, "worker_rejection_pair_count", str([row["row_id"] for row, _ in recovered]))
        if not recovered:
            return False
        row, retained = recovered[0]
        rejection = retained["rejection"]
        evidence: dict[str, Any] = {"worker_rejection": dict(rejection), "invocation_binding": dict(retained["invocation_binding"]), "invocation_evidence_id": retained["invocation_evidence_id"]}
        if methodology == "explicit_repair":
            evidence["repair_reason"] = repair_reason
        self._failure(
            stage="worker", classification=worker_journal_classification(rejection),
            code=str(rejection["error_code"]), reason=canonical_json_bytes(rejection).decode("utf-8").strip(),
            row=row, attempt_n=attempt_n, methodology=methodology, evidence=evidence,
        )
        return True

    def _reconcile_attempt(
        self, rows: Sequence[Mapping[str, Any]], *, attempt_n: int,
        methodology: str, repair_reason: str | None,
    ) -> str:
        """Return none, promoted, or interrupted while preserving every residue."""
        from .verify import validate_row_evidence

        first = rows[0]
        pair_directory = sha256_bytes(first["pair_id"].encode("utf-8"))
        declaration_path = self.repair_declarations_root / pair_directory / f"attempt-{attempt_n:04d}.json"
        declaration_present = declaration_path.exists()
        if methodology == "explicit_repair" and declaration_present:
            expected = {
                "schema": "arc4.repair-declaration/v1", "run_id": self.config["run_id"], "pair_id": first["pair_id"],
                "case_id": first["case_id"], "problem_id": first["problem_id"], "arm": first["arm"],
                "attempt_n": attempt_n, "repair_reason": repair_reason,
                "row_ids": {row["lane"]: row["row_id"] for row in rows},
            }
            try:
                require(declaration_path.read_bytes() == canonical_json_bytes(expected) and load_json(declaration_path) == expected, "repair_declaration_conflict", str(declaration_path))
            except BaseException as exc:
                self._failure(stage="commit", classification="infrastructure", code="interrupted_declaration_conflict", reason=str(exc), pair=first, attempt_n=attempt_n, methodology=methodology, evidence={"repair_reason": repair_reason})
                return "interrupted"
        elif declaration_present:
            self._failure(stage="commit", classification="infrastructure", code="interrupted_unexpected_declaration", reason=str(declaration_path), pair=first, attempt_n=attempt_n, methodology=methodology)
            return "interrupted"

        if self._recover_retained_worker_rejection(
            rows, attempt_n=attempt_n, methodology=methodology, repair_reason=repair_reason,
        ):
            return "interrupted"

        result_root = self.runtime_root / "pair-attempts" / pair_directory / f"attempt-{attempt_n:04d}"
        result_paths = {lane: result_root / f"{lane}.json" for lane in ("numpy_present", "numpy_absent")}
        present = {lane: path for lane, path in result_paths.items() if path.exists()}
        results: dict[str, Mapping[str, Any]] = {}
        planned_by_lane = {row["lane"]: row for row in rows}
        for lane, path in present.items():
            planned = planned_by_lane[lane]
            try:
                result = load_json(path)
                for key, value in planned.items():
                    if key != "schema":
                        require(result.get(key) == value, "attempt_result_identity", f"{planned['row_id']}:{key}")
                require(result.get("attempt_n") == attempt_n and result.get("attempt_methodology") == methodology and result.get("repair_reason") == repair_reason, "attempt_result_provenance", str(path))
                validate_row_evidence(result, set(self.config["corpora"][planned["corpus"]]["candidate_ids"]))
                results[lane] = result
            except BaseException as exc:
                evidence = {"repair_reason": repair_reason} if methodology == "explicit_repair" else {}
                self._failure(stage="commit", classification="infrastructure", code="interrupted_invalid_lane_result", reason=str(exc), row=planned, attempt_n=attempt_n, methodology=methodology, evidence=evidence)
                return "interrupted"
        if set(results) == {"numpy_present", "numpy_absent"}:
            ordered_results = [results[row["lane"]] for row in rows]
            try:
                commit_pair_fragment(lease=self.lease, results=ordered_results, expected_rows=rows, attempt_n=attempt_n, methodology=methodology, repair_reason=repair_reason, fragments_root=self.runtime_root / "fragments")
                require(self._committed_fragment_valid(rows), "committed_pair_validation", first["pair_id"])
            except BaseException as exc:
                evidence = {"repair_reason": repair_reason} if methodology == "explicit_repair" else {}
                self._journal_then_raise(exc, stage="commit", classification="infrastructure", code=getattr(exc, "code", "pair_promotion_failure"), reason=str(exc), pair=first, attempt_n=attempt_n, methodology=methodology, evidence=evidence)
            return "promoted"
        if declaration_present or present or self._attempt_residue_exists(rows, attempt_n=attempt_n, methodology=methodology):
            evidence = {"repair_reason": repair_reason} if methodology == "explicit_repair" else {}
            self._failure(stage="commit", classification="infrastructure", code="interrupted_incomplete_attempt", reason=f"abrupt termination left incomplete attempt {attempt_n}", pair=first, attempt_n=attempt_n, methodology=methodology, evidence=evidence)
            return "interrupted"
        return "none"

    def _repair_declarations(self, pair_id: str) -> list[Mapping[str, Any]]:
        root = self.repair_declarations_root / sha256_bytes(pair_id.encode("utf-8"))
        if not root.exists():
            return []
        require(root.is_dir(), "repair_declarations_path_type", str(root))
        return [load_json(path) for path in sorted(root.glob("attempt-*.json"))]

    def _committed_fragment_valid(self, rows: Sequence[Mapping[str, Any]]) -> bool:
        from .verify import validate_row_evidence

        require(len(rows) == 2 and len({row["pair_id"] for row in rows}) == 1, "fragment_pair_rows", str(rows))
        pair_id = rows[0]["pair_id"]
        path = self.runtime_root / "fragments" / pair_fragment_name(pair_id)
        if not path.exists():
            return False
        require(path.is_file(), "fragment_path_type", str(path))
        fragment = load_pair_fragment(path)
        require(fragment["pair_id"] == pair_id, "existing_fragment_identity", pair_id)
        observed_by_lane = {row["lane"]: row for row in fragment["rows"]}
        planned_by_lane = {row["lane"]: row for row in rows}
        require(set(observed_by_lane) == set(planned_by_lane) == {"numpy_present", "numpy_absent"}, "existing_fragment_lanes", pair_id)
        for lane, planned in planned_by_lane.items():
            observed = observed_by_lane[lane]
            for key, value in planned.items():
                if key == "schema":
                    continue
                require(observed.get(key) == value, "existing_fragment_identity", f"{planned['row_id']}:{key}")
            validate_row_evidence(observed, set(self.config["corpora"][planned["corpus"]]["candidate_ids"]))
        failures = self._pair_failures(rows)
        if fragment["attempt_n"] == 1:
            require(not failures and fragment["methodology"] == "initial" and fragment["repair_reason"] is None, "existing_fragment_initial_provenance", pair_id)
        else:
            attempts = [int(record["attempt_n"]) for record in failures]
            require(all(count == 1 for count in Counter(attempts).values()) and sorted(attempts) == list(range(1, fragment["attempt_n"])), "existing_fragment_attempt_sequence", str(attempts))
            require(fragment["methodology"] == "explicit_repair" and isinstance(fragment["repair_reason"], str) and bool(fragment["repair_reason"].strip()), "existing_fragment_repair_reason", pair_id)
            matching = [item for item in self._repair_declarations(pair_id) if item.get("attempt_n") == fragment["attempt_n"]]
            require(len(matching) == 1, "existing_fragment_repair_declaration", pair_id)
            declaration = matching[0]
            exact_keys(declaration, ("schema", "run_id", "pair_id", "case_id", "problem_id", "arm", "attempt_n", "repair_reason", "row_ids"), "existing_repair_declaration_keys")
            first = rows[0]
            require(declaration == {
                "schema": "arc4.repair-declaration/v1", "run_id": self.config["run_id"], "pair_id": pair_id,
                "case_id": first["case_id"], "problem_id": first["problem_id"], "arm": first["arm"],
                "attempt_n": fragment["attempt_n"], "repair_reason": fragment["repair_reason"],
                "row_ids": {row["lane"]: row["row_id"] for row in rows},
            }, "existing_fragment_repair_declaration", pair_id)
        return True

    def _execute_rows(self, rows: Sequence[Mapping[str, Any]], *, repair_reason: str | None = None) -> tuple[int, int]:
        fragments = self.runtime_root / "fragments"
        executed = 0
        skipped = 0
        ordered = ordered_rows_for_execution(rows)
        require(len(ordered) % 2 == 0, "campaign_pair_count", str(len(ordered)))
        for offset in range(0, len(ordered), 2):
            pair_items = ordered[offset:offset + 2]
            pair_rows = [item[0] for item in pair_items]
            require(len({row["pair_id"] for row in pair_rows}) == 1 and {row["lane"] for row in pair_rows} == {"numpy_present", "numpy_absent"}, "campaign_pair_lanes", str(pair_rows))
            if self._committed_fragment_valid(pair_rows):
                skipped += 2
                continue
            methodology = "explicit_repair" if repair_reason is not None else "initial"
            if repair_reason is None:
                require(not self._pair_failures(pair_rows), "pair_attempt_requires_repair", pair_rows[0]["pair_id"])
                attempt_n = 1
                reconciliation = self._reconcile_attempt(pair_rows, attempt_n=attempt_n, methodology=methodology, repair_reason=None)
                if reconciliation == "promoted":
                    skipped += 2
                    continue
                require(reconciliation == "none", "pair_attempt_requires_repair", pair_rows[0]["pair_id"])
            else:
                attempt_n = self._repair_attempt(pair_rows)
                while True:
                    reconciliation = self._reconcile_attempt(pair_rows, attempt_n=attempt_n, methodology=methodology, repair_reason=repair_reason)
                    if reconciliation == "promoted":
                        skipped += 2
                        break
                    if reconciliation == "none":
                        break
                    attempt_n = self._repair_attempt(pair_rows)
                if reconciliation == "promoted":
                    continue
                try:
                    self._repair_declaration(pair_rows, attempt_n, repair_reason)
                except BaseException as exc:
                    self._journal_then_raise(exc, stage="commit", classification="infrastructure", code=getattr(exc, "code", "repair_declaration_persistence"), reason=str(exc), pair=pair_rows[0], attempt_n=attempt_n, methodology=methodology, evidence={"repair_reason": repair_reason})
            failure_evidence = {"repair_reason": repair_reason} if repair_reason is not None else {}
            namespace = "repair" if repair_reason is not None else ("preflight" if pair_rows[0]["arm"] == "preflight" else "measured")
            results: list[Mapping[str, Any]] = []
            for row, invocation_ordinal in pair_items:
                try:
                    job_path = self._materialize_job(row, namespace=namespace, pair_invocation_ordinal=invocation_ordinal, attempt_n=attempt_n, methodology=methodology, repair_reason=repair_reason)
                except Exception as exc:
                    self._failure(stage="setup", classification="infrastructure", code=getattr(exc, "code", "setup_failure"), reason=str(exc), row=row, attempt_n=attempt_n, methodology=methodology, evidence=failure_evidence)
                    raise
                layout = lane_layout(self.config, row["lane"])
                interpreter = layout["interpreter"]
                publication = load_json(job_publication_path(job_path))
                job_bytes = validate_job_publication(publication, job_path)
                job = json.loads(job_bytes.decode("utf-8"))
                environment = child_environment(self.config, interpreter, home=Path(job["home_path"]))
                command = [str(interpreter), "-m", "harness.worker"]
                attempt_root = self.runtime_root / "attempts" / namespace / row["row_id"] / f"attempt-{attempt_n:04d}"
                try:
                    result = self.worker_runner(
                        command, attempt_root=attempt_root, timeout_seconds=self.config["worker_timeout_seconds"],
                        run_id=self.config["run_id"], planned_row=row, attempt_n=attempt_n,
                        methodology=methodology, repair_reason=repair_reason, job_path=job_path,
                        job_publication=publication, lane_root=layout["lane_root"], package_root=layout["package_root"],
                        environment=environment,
                    )
                except Exception as exc:
                    code = getattr(exc, "code", "worker_failure")
                    stage = "timeout" if code == "worker_timeout" else "worker"
                    retained = retained_worker_rejection(
                        attempt_root, run_id=self.config["run_id"], planned_row=row, attempt_n=attempt_n,
                        methodology=methodology, repair_reason=repair_reason, job_path=job_path, command=command,
                        job_publication=publication, lane_root=layout["lane_root"], package_root=layout["package_root"],
                    ) if stage == "worker" else None
                    evidence = dict(failure_evidence)
                    if retained is not None:
                        rejection = retained["rejection"]
                        require(rejection["error_code"] == code, "worker_rejection_exception_binding", str(row["row_id"]))
                        require(rejection["lane"] in {None, row["lane"]}, "worker_rejection_exception_binding", str(row["row_id"]))
                        evidence.update(retained)
                        classification = worker_journal_classification(rejection)
                    else:
                        classification = "infrastructure"
                    self._journal_then_raise(
                        exc, stage=stage, classification=classification, code=code, reason=str(exc),
                        row=row, attempt_n=attempt_n, methodology=methodology, evidence=evidence,
                    )
                pair_directory = sha256_bytes(row["pair_id"].encode("utf-8"))
                attempt_path = self.runtime_root / "pair-attempts" / pair_directory / f"attempt-{attempt_n:04d}" / f"{row['lane']}.json"
                try:
                    atomic_write_new(attempt_path, canonical_json_bytes(result), allowed_root=self.runtime_root)
                except BaseException as exc:
                    self._journal_then_raise(exc, stage="commit", classification="infrastructure", code=getattr(exc, "code", "lane_result_persistence"), reason=str(exc), row=row, attempt_n=attempt_n, methodology=methodology, evidence=failure_evidence)
                results.append(result)
            from .verify import validate_row_evidence
            for result, planned in zip(results, pair_rows, strict=True):
                try:
                    for key, value in planned.items():
                        if key != "schema":
                            require(result.get(key) == value, "attempt_result_identity", f"{planned['row_id']}:{key}")
                    validate_row_evidence(result, set(self.config["corpora"][planned["corpus"]]["candidate_ids"]))
                except BaseException as exc:
                    self._journal_then_raise(exc, stage="commit", classification="infrastructure", code=getattr(exc, "code", "row_validation_failure"), reason=str(exc), row=planned, attempt_n=attempt_n, methodology=methodology, evidence=failure_evidence)
            try:
                commit_pair_fragment(lease=self.lease, results=results, expected_rows=pair_rows, attempt_n=attempt_n, methodology=methodology, repair_reason=repair_reason, fragments_root=fragments)
                require(self._committed_fragment_valid(pair_rows), "committed_pair_validation", pair_rows[0]["pair_id"])
            except BaseException as exc:
                self._journal_then_raise(exc, stage="commit", classification="infrastructure", code=getattr(exc, "code", "commit_failure"), reason=str(exc), pair=pair_rows[0], attempt_n=attempt_n, methodology=methodology, evidence=failure_evidence)
            executed += 2
        return executed, skipped

    def _seed_control(self, cases: Mapping[str, Any]) -> dict[str, Any]:
        row = next(item for item in cases["planned_rows"] if item["arm"] == "matrix" and item["cache_state"] == "cold_fresh_process" and item["repetition"] == 1)
        seeds = ["0", "1", "2", "3", "4", "unset"]
        hashes: dict[str, str] = {}
        observations: list[dict[str, Any]] = []
        ordinal = 1 if (row["lane_invocation_order"] == "numpy_first") == (row["lane"] == "numpy_present") else 2
        prior_attempts = [
            int(path.stem.split("-")[-1])
            for path in (self.runtime_root / "jobs" / "control" / "C9" / row["row_id"]).glob("seed-*/attempt-[0-9][0-9][0-9][0-9].json")
        ]
        attempt_n = max(prior_attempts, default=0) + 1
        methodology = "initial" if attempt_n == 1 else "explicit_repair"
        repair_reason = None if attempt_n == 1 else "resume_C9_after_observed_unset_seed_environment_null_mismatch"
        for seed in seeds:
            try:
                declared_seed = None if seed == "unset" else seed
                job_path = self._materialize_job(row, namespace=f"seed-{seed}", pair_invocation_ordinal=ordinal, attempt_n=attempt_n, methodology=methodology, repair_reason=repair_reason, control_id="C9", python_hash_seed=declared_seed)
                layout = lane_layout(self.config, row["lane"])
                interpreter = layout["interpreter"]
                publication = load_json(job_publication_path(job_path))
                job = json.loads(validate_job_publication(publication, job_path).decode("utf-8"))
                environment = child_environment(self.config, interpreter, home=Path(job["home_path"]), seed=declared_seed)
                if seed == "unset":
                    environment.pop("PYTHONHASHSEED", None)
                command = [str(interpreter), "-m", "harness.worker"]
                result = self.worker_runner(
                    command, attempt_root=canonical_attempt_root(self.runtime_root, job),
                    timeout_seconds=self.config["worker_timeout_seconds"], run_id=self.config["run_id"],
                    planned_row=row, attempt_n=attempt_n, methodology=methodology, repair_reason=repair_reason,
                    job_path=job_path, job_publication=publication, lane_root=layout["lane_root"],
                    package_root=layout["package_root"], environment=environment,
                )
                digest = result.get("full_depth_ordering_sha256")
                require(isinstance(digest, str) and len(digest) == 64, "seed_ordering_hash", seed)
                hashes[seed] = digest
                observations.append({"control_id": "C9", "is_control": True, "seed": declared_seed, "row_id": row["row_id"], "lane": row["lane"], "ordering_sha256": digest})
            except Exception as exc:
                self._failure(stage="control", classification="protocol", code=getattr(exc, "code", "seed_control_failure"), reason=str(exc), row=row, attempt_n=attempt_n, methodology=methodology, evidence={"repair_reason": repair_reason})
                raise
        return {"deterministic_groups": 48, "deterministic_groups_expected": 48, "seed_subset_row_id": row["row_id"], "seeds": seeds, "ordering_sha256_by_seed": hashes, "seed_observations": observations, "seed_dependence_observed": len(set(hashes.values())) > 1}

    def _finish_full_run(self, cases: Mapping[str, Any]) -> None:
        from .verify import _expected_controls, run_self_tests, verify_packet

        rows_path = self.runtime_root / "rows.jsonl"
        rows = [row for path in sorted((self.runtime_root / "fragments").glob("*.json")) for row in load_pair_fragment(path)["rows"]]
        p0 = load_json(Path(self.config["p0_receipt"]))
        lock = load_json(Path(self.config["environment_lock"]))
        try:
            retained_c9 = self.packet_root / "controls" / "C9.json"
            if retained_c9.is_file():
                retained_c9_record = load_json(retained_c9)
                validate_control_record(retained_c9_record)
                seed_evidence = retained_c9_record["evidence"]
            else:
                seed_evidence = self._seed_control(cases)
            originals = {"start": load_json(self.runtime_root / "frozen-originals-start.json"), "end": frozen_original_snapshot(self.config)}
            require(originals["start"] == originals["end"], "frozen_original_changed_during_seed_control", "final seed-control worker changed an original database or sidecar")
            evidence = _expected_controls(self.packet_root, rows, cases, p0, lock, "0" * 64, 1, originals=originals)
            evidence["C9"] = seed_evidence
            external = {key: value for key, value in evidence.items() if key not in {"C17", "C18", "C19"}}
            control_dir = self.packet_root / "controls"
            for record in assemble_control_records(external):
                atomic_write(control_dir / f"{record['control_id']}.json", canonical_json_bytes(record), allowed_root=self.packet_root)
        except Exception as exc:
            self._failure(stage="control", classification="protocol", code=getattr(exc, "code", "control_failure"), reason=str(exc))
            raise
        try:
            runtime_failures = load_jsonl(self.failure_journal) if self.failure_journal.is_file() and self.failure_journal.stat().st_size else []
            packet_failures = retain_failure_invocations(self.packet_root, runtime_failures)
            atomic_write(self.packet_root / "FAILURE-JOURNAL.jsonl", b"".join(canonical_json_bytes(item) for item in packet_failures), allowed_root=self.packet_root)
            declarations = [load_json(path) for path in sorted(self.repair_declarations_root.glob("*/attempt-*.json"))] if self.repair_declarations_root.exists() else []
            atomic_write(self.packet_root / "REPAIR-JOURNAL.jsonl", b"".join(canonical_json_bytes(item) for item in declarations), allowed_root=self.packet_root)
            assemble_results(packet_root=self.packet_root, rows_path=rows_path, controls_dir=self.packet_root / "controls")
            shutil.copy2(Path(__file__).with_name("verify.py"), self.packet_root / "verify.py")
            write_manifest(self.packet_root)
            verify_packet(self.packet_root)
            run_self_tests(self.packet_root)
        except Exception as exc:
            self._failure(stage="verification", classification="verification", code=getattr(exc, "code", "verification_failure"), reason=str(exc))
            raise

    def execute(self, mode: str, *, repair_pair_id: str | None = None, repair_reason: str | None = None) -> dict[str, Any]:
        require(mode in MODES, "campaign_mode", mode)
        require((mode == "repair") is (repair_pair_id is not None or repair_reason is not None), "repair_arguments", "repair mode and repair arguments must be used together")
        if mode == "repair":
            require(isinstance(repair_pair_id, str) and bool(repair_pair_id) and isinstance(repair_reason, str) and bool(repair_reason.strip()), "repair_declaration", "pair ID and nonempty reason are required")
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.lease.acquire()
        try:
            if mode == "staged":
                try:
                    cases = self._stage_inputs()
                except Exception as exc:
                    code = getattr(exc, "code", "setup_failure")
                    if code not in ("p0_failure", "environment_failure"):
                        self._failure(stage="timeout" if code == "setup_timeout" else "setup", classification="infrastructure", code=code, reason=str(exc))
                    raise
                state = {"schema": "arc4.campaign-state/v1", "run_id": self.config["run_id"], "stage": "staged", "measured_rows_created": 0, "environment_commands": environment_creation_commands(self.config)}
                atomic_write(self.runtime_root / "campaign-state.json", canonical_json_bytes(state), allowed_root=self.runtime_root)
                return state
            cases = load_json(Path(self.config["frozen_cases"]))
            try:
                validate_preregistration_commit(self.config)
                validate_frozen_execution_inputs(self.config)
                verified_cases = validate_full_preregistration_semantics(self.config)
                require(verified_cases == cases, "preregistration_case_bytes", "verified frozen cases differ from execution plan")
            except Exception as exc:
                self._failure(stage="setup", classification="protocol", code=getattr(exc, "code", "preregistration_not_committed"), reason=str(exc))
                raise
            state_path = self.runtime_root / "campaign-state.json"
            state = load_json(state_path)
            exact_keys(state, ("schema", "run_id", "stage", "measured_rows_created", "environment_commands"), "campaign_state_keys")
            require(state["schema"] == "arc4.campaign-state/v1" and state["run_id"] == self.config["run_id"] and state["stage"] in ("staged", "preflight-complete"), "campaign_state", str(state))
            require(not (mode == "preflight" and state["stage"] != "staged"), "preflight_already_executed", str(state["stage"]))
            if mode == "repair":
                rows = [row for row in cases["planned_rows"] if row["pair_id"] == repair_pair_id]
                require(len(rows) == 2 and {row["lane"] for row in rows} == {"numpy_present", "numpy_absent"}, "repair_pair_identity", str(repair_pair_id))
                executed, skipped = self._execute_rows(rows, repair_reason=repair_reason)
                return {"schema": "arc4.campaign-result/v1", "mode": mode, "rows_executed": executed, "rows_skipped_valid": skipped, "retries": 0, "repair_pair_id": repair_pair_id, "repair_reason": repair_reason}
            rows = rows_for_mode(cases, mode)
            if mode == "full-run" and state["stage"] == "preflight-complete":
                rows = [row for row in rows if row["arm"] == "matrix"]
            executed, skipped = self._execute_rows(rows)
            if mode == "full-run":
                fragments = self.runtime_root / "fragments"
                try:
                    consolidate_fragments(lease=self.lease, cases=cases, fragments_root=fragments, output=self.runtime_root / "rows.jsonl")
                except Exception as exc:
                    self._failure(stage="consolidation", classification="protocol", code=getattr(exc, "code", "consolidation_failure"), reason=str(exc))
                    raise
                self._finish_full_run(cases)
            else:
                state["stage"] = "preflight-complete"
                state["measured_rows_created"] = 24
                atomic_write(state_path, canonical_json_bytes(state), allowed_root=self.runtime_root)
            return {"schema": "arc4.campaign-result/v1", "mode": mode, "rows_executed": executed, "rows_skipped_valid": skipped, "retries": 0}
        finally:
            self.lease.release()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Own one Arc 4 campaign phase. No implicit retries.")
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repair-pair-id")
    parser.add_argument("--repair-reason")
    ns = parser.parse_args(argv)
    try:
        result = CampaignOwner(load_json(ns.config.resolve())).execute(ns.mode, repair_pair_id=ns.repair_pair_id, repair_reason=ns.repair_reason)
        print(canonical_json_bytes(result).decode("utf-8"), end="")
        return 0
    except ContractError as exc:
        print(canonical_json_bytes({"status": "rejected", "error_code": exc.code}).decode("utf-8"), end="", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
