from __future__ import annotations

import csv
import hashlib
import shutil
import sys
from pathlib import Path

from harness.cases import QUERY_IDS, generate_frozen_cases
from harness.campaign import ordered_rows_for_execution
from harness.artifacts import canonical_packet_paths
from harness.common import atomic_write, canonical_json, canonical_json_bytes, sha256_bytes, sha256_file
from harness.controls import assemble_control_records
from harness.environment import bind_environment_manifests, build_environment_lock, canonicalize_raw_manifest
from harness.metrics import ordering_sha256
from harness.packet import assemble_results, build_preregistration_inputs, build_source_inventory, decompose_original_matrix, write_manifest
from harness.verify import SELF_TESTS, _expected_controls
from harness.worker_protocol import build_worker_rejection


PROJECT = Path(__file__).resolve().parents[1]
OFFICIAL = PROJECT / "inputs" / "jcodemunch_mcp-1.108.228-py3-none-any.whl"
NUMPY = PROJECT / "inputs" / "numpy-2.4.4-cp313-cp313-win_amd64.whl"
PIP = PROJECT / "inputs" / "wheelhouse" / "pip-25.2-py3-none-any.whl"
DESIGN = PROJECT / "DESIGN.md"


def _query(query_id: str, index: int, vector: list[float]) -> dict:
    semantic_only = index < 2
    return {
        "query": query_id, "query_embedding_sha256": sha256_bytes(canonical_json(vector).encode("utf-8")),
        "serialized_args": {"query": query_id, "semantic_only": semantic_only, "semantic_weight": 1.0 if semantic_only else 0.5, "max_results": 10 if index in (0, 2) else 25, "detail_level": "compact", "debug": False},
    }


def _raw_environment(packet: Path, lane: str, lock: dict, lane_venv: Path, trial_root: Path) -> dict:
    distributions = [
        {"project": item["project"], "version": item["version"], "artifact_sha256": item["sha256"]}
        for item in lock["lanes"][lane]["distributions"]
    ]
    numpy_artifact = next(item for item in lock["wheelhouse_artifacts"] if item["project"] == "numpy")
    numpy = {"present": True, "version": "2.4.4", "artifact_sha256": numpy_artifact["sha256"]} if lane == "numpy_present" else {"present": False, "version": None, "artifact_sha256": None}
    return {
        "schema": "arc4.raw-environment/v1", "lane": lane, "python_implementation": "CPython", "python_version": "3.13.7",
        "python_cache_tag": "cpython-313", "platform": "win32", "machine": "AMD64", "processor": "fixture",
        "locale": "C", "time_zone": "UTC", "sqlite_version": "3.50.0", "openssl_version": "OpenSSL fixture",
        "distributions": distributions, "treatment_wheel_sha256": sha256_file(OFFICIAL), "pip_version": lock["pip"]["version"],
        "numpy": numpy, "cpu": {"architecture": "64bit", "machine": "AMD64", "processor": "fixture", "logical_cpu_count": 8},
        "blas": {"source_lane": "numpy_present", "numpy_version": "2.4.4", "config_json_sha256": "c" * 64, "raw_receipt_sha256": "d" * 64},
        "environment": {"PYTHONHASHSEED": "0", "PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "JCODEMUNCH_EMBED_MATRIX_CACHE": None, "JCODEMUNCH_SHARE_SAVINGS": "0"},
        "configuration": {"share_savings": False, "perf_telemetry_enabled": False, "embed_model": "fixture"},
        "python_executable": str(lane_venv / "Scripts" / "python.exe"), "storage_path": str(trial_root / "store"), "cwd": str(packet),
    }


def _original_matrix(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["row_id", "case_id", "pair_id", "mode", "row_status"])
        writer.writeheader()
        ordinal = 0
        for case in range(24):
            for repetition in range(5):
                for mode in ("a", "b", "c"):
                    writer.writerow({"row_id": f"row-{ordinal}", "case_id": f"case-{case}", "pair_id": f"case-{case}:r{repetition}", "mode": mode, "row_status": "retained"})
                    ordinal += 1


def build_packet(root: Path) -> Path:
    packet = root / "packet"
    staging = root / "staging"
    wheelhouse = staging / "wheelhouse"
    packet.mkdir(parents=True)
    packet_paths = canonical_packet_paths(packet)
    staging.mkdir()
    wheelhouse.mkdir()
    shutil.copy2(OFFICIAL, wheelhouse / OFFICIAL.name)
    shutil.copy2(NUMPY, wheelhouse / NUMPY.name)
    shutil.copy2(PIP, wheelhouse / PIP.name)
    (packet / "inputs").mkdir()
    shutil.copy2(OFFICIAL, packet / "inputs" / OFFICIAL.name)

    frozen_root = root / "frozen-originals"
    frozen_root.mkdir()
    for name in ("django", "fastapi", "jcodemunch"):
        (frozen_root / f"{name}.db").write_bytes(name.encode("ascii"))
    corpora = [{"name": name, "working_database_sha256": sha256_file(frozen_root / f"{name}.db"), "candidate_ids": ["a", "b"]} for name in ("django", "fastapi", "jcodemunch")]
    query_vectors = {query_id: [float(index + 1)] * 384 for index, query_id in enumerate(QUERY_IDS)}
    queries = {query_id: _query(query_id, index, query_vectors[query_id]) for index, query_id in enumerate(QUERY_IDS)}
    cases = generate_frozen_cases(run_id="synthetic-run", corpora=corpora, queries=queries)
    atomic_write(packet / "frozen-cases.json", canonical_json_bytes(cases), allowed_root=packet)

    lock = build_environment_lock(wheelhouse)
    roots = {}
    for lane, raw_name, canonical_name in (("numpy_present", "raw-numpy-present.json", "numpy-present.json"), ("numpy_absent", "raw-numpy-absent.json", "numpy-absent.json")):
        lane_venv = root / "venvs" / lane
        trial_root = root / "trials" / lane
        lane_venv.mkdir(parents=True)
        interpreter = lane_venv / "Scripts" / "python.exe"
        interpreter.parent.mkdir(parents=True)
        shutil.copy2(Path(sys.executable).resolve(), interpreter)
        for dll_name in ("python313.dll", "python3.dll"):
            source_dll = Path(sys.executable).resolve().parent / dll_name
            if source_dll.is_file():
                shutil.copy2(source_dll, interpreter.parent / dll_name)
        (lane_venv / "Lib" / "site-packages" / "jcodemunch_mcp").mkdir(parents=True)
        trial_root.mkdir(parents=True)
        raw = _raw_environment(packet, lane, lock, lane_venv, trial_root)
        canonical = canonicalize_raw_manifest(raw, lane_venv=lane_venv, trial_root=trial_root, packet_root=packet)
        atomic_write(packet / "env" / raw_name, canonical_json_bytes(raw), allowed_root=packet)
        atomic_write(packet / "env" / canonical_name, canonical_json_bytes(canonical), allowed_root=packet)
        roots[lane] = {"lane_venv": lane_venv, "trial_root": trial_root}
    lock = bind_environment_manifests(lock, packet_root=packet, lane_roots=roots)
    atomic_write(packet / "ENVIRONMENT-LOCK.json", canonical_json_bytes(lock), allowed_root=packet)

    p0 = {
        "schema": "arc4.p0-wheel-comparison/v1", "status": "passed", "official_sha256": sha256_file(OFFICIAL),
        "rebuilt_sha256": "9" * 64, "comparison_tool_sha256": "8" * 64,
        "official_member_count": 100, "rebuilt_member_count": 100,
        "excluded_member": "jcodemunch_mcp-1.108.228.dist-info/RECORD", "missing_members": [], "extra_members": [],
        "raw_differences": [], "normalized_payload_differences": [],
        "official_record": {"schema": "arc4.official-record-validation/v1", "status": "valid", "row_count": 100},
        "normalization": "utf8_text_newlines_only_crlf_or_cr_to_lf",
        "claim_ceiling": "payload_equivalence_under_declared_newline_normalization_only",
        "does_not_establish": ["bit_reproducible_build", "publisher_build_environment", "end_to_end_supply_chain_authenticity"],
    }
    atomic_write(packet / "P0-RECEIPT.json", canonical_json_bytes(p0), allowed_root=packet)
    detached = root / "detached-source"
    detached.mkdir()
    build_home = root / "build-home"
    build_environment = {
        "SystemRoot": r"C:\Windows", "ComSpec": r"C:\Windows\System32\cmd.exe",
        "TEMP": str(root / "build-temp"), "TMP": str(root / "build-temp"),
        "USERPROFILE": str(build_home), "HOME": str(build_home), "HOMEDRIVE": "C:", "HOMEPATH": r"\build-home",
        "PATH": str(Path(sys.executable).resolve().parent), "PYTHONNOUSERSITE": "1", "PYTHONHASHSEED": "0", "PYTHONUTF8": "1", "PIP_NO_INDEX": "1",
    }
    build_receipt = {
        "schema": "arc4.source-build-receipt/v2", "source_commit": "8bed872e9436093be9f89d35fb84e0cb58a293af",
        "git": {"head": "8bed872e9436093be9f89d35fb84e0cb58a293af", "clean": True, "detached": True, "core_autocrlf": "false", "status_sha256": hashlib.sha256(b"").hexdigest()},
        "python": {"implementation": "CPython", "version": "3.13.7", "cache_tag": "cpython-313", "executable": str(Path(sys.executable).resolve()), "executable_sha256": sha256_file(Path(sys.executable))},
        "build": {"backend": "hatchling", "backend_version": "1.31.0", "command": [str(Path(sys.executable).resolve()), "-m", "build", "--wheel", "--no-isolation", "--outdir", str(detached / "dist"), "."], "cwd": str(detached.resolve()), "environment": build_environment},
        "produced_wheel": {"path": str(detached / "dist" / "rebuilt.whl"), "sha256": p0["rebuilt_sha256"]},
        "comparison_tool_sha256": p0["comparison_tool_sha256"], "generator_sha256": p0["comparison_tool_sha256"],
    }
    build_receipt_sha = sha256_bytes(canonical_json_bytes(build_receipt))
    atomic_write(packet_paths["source_build_receipt"], canonical_json_bytes(build_receipt), allowed_root=packet)
    atomic_write(packet_paths["source_build_receipt_digest"], (build_receipt_sha + "\n").encode("ascii"), allowed_root=packet)
    inventory = build_source_inventory(packet_root=packet, cases=cases, p0=p0, lock=lock, pypi_url="https://files.pythonhosted.org/packages/fixture.whl", build_receipt=build_receipt, build_receipt_sha256=build_receipt_sha, query_vector_values=query_vectors)
    atomic_write(packet / "SOURCE-INVENTORY.json", canonical_json_bytes(inventory), allowed_root=packet)
    config = {
        "schema": "arc4.campaign-config/v1", "run_id": "synthetic-run",
        "runtime_root": str((root / "runtime").resolve()), "packet_root": str(packet.resolve()),
        "harness_root": str((PROJECT / "harness").resolve()), "python_executable": str(Path(sys.executable).resolve()),
        "wheelhouse": str(wheelhouse.resolve()),
        "lane_interpreters": {lane: str((roots[lane]["lane_venv"] / "Scripts" / "python.exe").resolve()) for lane in ("numpy_present", "numpy_absent")},
        "frozen_cases": str((packet / "frozen-cases.json").resolve()), "environment_lock": str((packet / "ENVIRONMENT-LOCK.json").resolve()),
        "preregistration_inputs": str((packet / "PREREGISTRATION-INPUTS.json").resolve()),
        "preregistration_commit_receipt": str(packet_paths["preregistration_commit_receipt"]), "preregistration_repository": str(root.resolve()),
        "corpora": {item["name"]: {"database": str((root / "frozen-originals" / f"{item['name']}.db").resolve()), "repo_id": item["name"], "candidate_ids": item["candidate_ids"]} for item in corpora},
        "queries": {query_id: {"query_text": queries[query_id]["query"], "query_vector": query_vectors[query_id], "query_vector_sha256": queries[query_id]["query_embedding_sha256"]} for query_id in QUERY_IDS},
        "worker_timeout_seconds": 900, "official_wheel": str((packet / "inputs" / OFFICIAL.name).resolve()),
        "source_checkout": str(detached.resolve()), "source_build_output": str((detached / "dist").resolve()),
        "source_build_receipt": str(packet_paths["source_build_receipt"]), "source_build_receipt_digest": str(packet_paths["source_build_receipt_digest"]),
        "p0_receipt": str((packet / "P0-RECEIPT.json").resolve()), "design_path": str(DESIGN.resolve()),
        "frozen_config": str((root / "FROZEN-CONFIG.json").resolve()), "approved_utc": "2026-08-05T00:00:00Z",
        "pypi_url": "https://files.pythonhosted.org/packages/fixture.whl", "original_matrix_csv": str((staging / "measurements.csv").resolve()),
        "environment_capture_specs": {"numpy_present": str((packet / "env" / "raw-numpy-present.json").resolve()), "numpy_absent": str((packet / "env" / "raw-numpy-absent.json").resolve())},
        "environment_lane_roots": {lane: {"lane_venv": str(roots[lane]["lane_venv"].resolve()), "trial_root": str(roots[lane]["trial_root"].resolve())} for lane in ("numpy_present", "numpy_absent")},
        "wheelhouse_spec": str((staging / "wheelhouse-spec.json").resolve()), "wheelhouse_receipt": str((root / "wheelhouse-receipt.json").resolve()),
        "child_environment": {"system_root": r"C:\Windows", "temp": str((root / "temp").resolve()), "locale": "C", "timezone": "UTC", "pythonhashseed": "0"},
    }
    atomic_write(packet / "CONFIG.json", canonical_json_bytes(config), allowed_root=packet)
    atomic_write(Path(config["frozen_config"]), canonical_json_bytes(config), allowed_root=root)
    prereg = build_preregistration_inputs(design_path=DESIGN, config_path=packet / "CONFIG.json", frozen_cases_path=packet / "frozen-cases.json", environment_lock_path=packet / "ENVIRONMENT-LOCK.json", p0_receipt_path=packet / "P0-RECEIPT.json", source_inventory_path=packet / "SOURCE-INVENTORY.json", packet_root=packet, approved_utc="2026-08-05T00:00:00Z")
    atomic_write(packet / "PREREGISTRATION-INPUTS.json", canonical_json_bytes(prereg), allowed_root=packet)
    prereg_commit = {
        "schema": "arc4.preregistration-commit/v1", "commit_sha": "1" * 40, "committed": True,
        "files": {
            name: sha256_file(packet / name)
            for name in (
                "CONFIG.json", "ENVIRONMENT-LOCK.json", "P0-RECEIPT.json", "PREREGISTRATION-INPUTS.json",
                "SOURCE-BUILD-RECEIPT.json", "SOURCE-BUILD-RECEIPT.sha256", "SOURCE-INVENTORY.json", "frozen-cases.json",
            )
        },
    }
    atomic_write(packet_paths["preregistration_commit_receipt"], canonical_json_bytes(prereg_commit), allowed_root=packet)

    final = {"a": 1.0, "b": 0.5}
    rows = []
    repaired_pair_id = cases["planned_rows"][0]["pair_id"]
    repair_reason = "fixture operator repair"
    lock_sha = sha256_file(packet / "ENVIRONMENT-LOCK.json")
    for planned in cases["planned_rows"]:
        matrix = planned["arm"] == "matrix"
        warm = planned["cache_state"] == "generation_warm"
        provider_n = (3 if warm else 2) if matrix else 0
        lane = planned["lane"]
        lane_present = lane == "numpy_present"
        hybrid = planned["query_id"].startswith("hybrid_")
        row_final = {"a": 0.9, "b": 0.4} if matrix and hybrid else dict(final)
        raw_hex = {key: value.hex() for key, value in final.items()}
        final_hex = {key: value.hex() for key, value in row_final.items()}
        state = {"database_sha256": planned["corpus_sha256"], "wal_sha256": None, "wal_size": 0, "shm_sha256": None, "shm_size": 0, "logical_embedding_sha256": "7" * 64, "embedding_count": 2}
        origins = {"jcodemunch_mcp": "__init__.py"}
        debug_scores = [{"id": key, "public_score": round(value, 4), "adapter_rounded": round(value, 4)} for key, value in row_final.items()]
        first_lane = "numpy_present" if planned["lane_invocation_order"] == "numpy_first" else "numpy_absent"
        source_files = {"db": {"present": True, "sha256": planned["corpus_sha256"], "size": 1}, "wal": {"present": False, "sha256": None, "size": 0}, "shm": {"present": False, "sha256": None, "size": 0}}
        rows.append({
            **planned, "schema": "arc4.row-result/v1", "public_result_ids": ["a", "b"],
            "raw_cosine": dict(raw_hex) if matrix else {}, "final_scores": dict(final_hex) if matrix else {},
            "full_depth_ordering_sha256": ordering_sha256(row_final) if matrix else None,
            "provider_calls": [{"texts": [queries[planned["query_id"]]["query"]], "provider": "fixture", "model": "fixture", "task_type": "search_query", "query_vector_sha256": planned["query_vector_sha256"]} for _ in range(provider_n)],
            "warmup_result": {"results": ["warm"]} if warm else None,
            "cache_before": {"enabled": True, "repos": 0, "max_repos": 16, "vectors": 0, "numpy": lane_present},
            "cache_after_public": {"enabled": True, "repos": 1 if matrix else 0, "max_repos": 16, "vectors": 2 if matrix else 0, "numpy": lane_present},
            "cache_after_warmup": ({"enabled": True, "repos": 1 if matrix else 0, "max_repos": 16, "vectors": 2 if matrix else 0, "numpy": lane_present} if warm else None),
            "served_from_result_cache": warm if not matrix else False,
            "database_state_before": dict(state), "database_state": dict(state),
            "matrix_stamp_before_measurement": [1, 2] if matrix and warm else None,
            "matrix_stamp_after_measurement": [1, 2] if matrix else None,
            "wall_ns": 1, "process_cpu_ns": 1,
            "attempt_n": 2 if planned["pair_id"] == repaired_pair_id else 1,
            "attempt_methodology": "explicit_repair" if planned["pair_id"] == repaired_pair_id else "initial",
            "repair_reason": repair_reason if planned["pair_id"] == repaired_pair_id else None,
            "pair_invocation_ordinal": 1 if lane == first_lane else 2,
            "observed_query_vector_sha256": planned["query_vector_sha256"],
            "frozen_source_files": {"database_path": f"C:/frozen/{planned['corpus']}.db", "files": source_files},
            "trial_source_files": {"database_path": f"C:/trial/{planned['row_id']}.db", "files": source_files},
            "debug_observation": {"debug": True, "ordered_ids": ["a", "b"], "scores": debug_scores, "order_matches": True, "rounded_scores_match": True, "adapter_kind": "final" if matrix else "bm25_identity"},
            "package_evidence": {"official_wheel_sha256": sha256_file(OFFICIAL), "environment_lock_sha256": lock_sha, "installed_version": "1.108.228", "payload_file_count": 1, "payload_matches_official_wheel": True, "module_origins": origins},
            "lane_evidence": {"numpy_version": "2.4.4" if lane_present else None, "numpy_import_failed_before": not lane_present, "numpy_importable_before": lane_present, "numpy_helper_non_null_before": lane_present, "numpy_importable_after": lane_present, "numpy_import_failed_after": not lane_present, "numpy_helper_non_null_after": lane_present, "matrix_vectorised": lane_present if matrix else None},
            "controls": {"network_attempts": [], "network_tripwire_installed_before_config": True, "network_lifetime_guard_registered": True, "credentials_absent": True, "sharing_disabled": True, "package_unchanged": True, "database_unchanged": True, "candidate_set_matches": True, "provider_expected_calls": provider_n, "provider_observed_calls": provider_n, "topup_tripwire_events": 0, "storage_tuning_absent": True, "home_tuning_absent": True, "effective_weight_matches": True},
        })
    rows_path = staging / "rows.jsonl"
    rows_path.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))
    original_receipts = {}
    for name in ("django", "fastapi", "jcodemunch"):
        database = frozen_root / f"{name}.db"
        original_receipts[name] = {"database_path": str(database.resolve()), "files": {"db": {"present": True, "sha256": sha256_file(database), "size": database.stat().st_size}, "wal": {"present": False, "sha256": None, "size": 0}, "shm": {"present": False, "sha256": None, "size": 0}}}
    evidence = _expected_controls(packet, rows, cases, p0, lock, "0" * 64, 1, originals={"start": original_receipts, "end": original_receipts})
    seed_labels = ["0", "1", "2", "3", "4", "unset"]
    seed_hashes = {seed: ordering_sha256(final) for seed in seed_labels}
    evidence["C9"] = {"deterministic_groups": 48, "deterministic_groups_expected": 48, "seed_subset_row_id": rows[0]["row_id"], "seeds": seed_labels, "ordering_sha256_by_seed": seed_hashes, "seed_observations": [{"control_id": "C9", "is_control": True, "seed": None if seed == "unset" else seed, "row_id": rows[0]["row_id"], "lane": rows[0]["lane"], "ordering_sha256": seed_hashes[seed]} for seed in seed_labels], "seed_dependence_observed": False}
    controls = packet / "controls"
    for record in assemble_control_records(evidence):
        atomic_write(controls / f"{record['control_id']}.json", canonical_json_bytes(record), allowed_root=packet)
    repaired_rows = [row for row in rows if row["pair_id"] == repaired_pair_id]
    failure_row = ordered_rows_for_execution(repaired_rows)[0][0]
    failure_plan = next(row for row in cases["planned_rows"] if row["row_id"] == failure_row["row_id"])
    lane = failure_row["lane"]
    lane_root = roots[lane]["lane_venv"].resolve()
    interpreter = (lane_root / "Scripts" / "python.exe").resolve()
    package_root = (lane_root / "Lib" / "site-packages" / "jcodemunch_mcp").resolve()
    runtime_root = Path(config["runtime_root"]).resolve()
    source_job = runtime_root / "jobs" / "measured" / failure_row["row_id"] / "attempt-0001.json"
    attempt_root = runtime_root / "attempts" / "measured" / failure_row["row_id"] / "attempt-0001"
    binding_runtime = attempt_root / "invocation-binding.json"
    artifact_runtime = attempt_root / "job-artifact.json"
    trial_root = runtime_root / "trials" / "measured" / failure_row["row_id"] / "attempt-0001"
    trial_database = trial_root / f"{failure_row['corpus']}.db"
    frozen_receipt = original_receipts[failure_row["corpus"]]
    trial_receipt = {"database_path": str(trial_database.resolve()), "files": frozen_receipt["files"]}
    job = {
        **dict(failure_plan), "schema": "arc4.worker-job/v1", "run_id": cases["run_id"],
        "repo_id": config["corpora"][failure_row["corpus"]]["repo_id"], "database": str(trial_database.resolve()),
        "storage_path": str(trial_root.resolve()),
        "package_root": str(package_root), "treatment_wheel": config["official_wheel"],
        "config_path": str((packet / "CONFIG.json").resolve()), "config_sha256": sha256_file(packet / "CONFIG.json"),
        "environment_lock_path": config["environment_lock"], "environment_lock_sha256": lock_sha,
        "candidate_ids": ["a", "b"], "query_text": config["queries"][failure_row["query_id"]]["query_text"],
        "query_vector": config["queries"][failure_row["query_id"]]["query_vector"],
        "pair_invocation_ordinal": 1, "frozen_source_files": frozen_receipt,
        "trial_source_files": trial_receipt, "home_path": str((trial_root / "home").resolve()),
        "attempt_n": 1, "attempt_methodology": "initial", "repair_reason": None,
        "python_hash_seed": "0", "embed_model": "fixture", "execution_namespace": "measured",
        "is_control": False, "control_id": None,
    }
    job_bytes = canonical_json_bytes(job)
    evidence_id = sha256_bytes(canonical_json({"run_id": cases["run_id"], "row_id": failure_row["row_id"], "lane": lane, "attempt_n": 1, "namespace": "measured", "control_id": None}).encode("utf-8"))
    invocation_root = packet / "invocations" / evidence_id
    invocation_root.mkdir(parents=True)
    (invocation_root / "job-artifact.json").write_bytes(job_bytes)
    argv = [str(interpreter), "-m", "harness.worker", "--binding", str(binding_runtime.resolve()), str(artifact_runtime.resolve())]
    invocation_binding = {
        "schema": "arc4.worker-invocation-binding/v2", "run_id": cases["run_id"],
        "row_identity": {key: failure_row[key] for key in ("row_id", "pair_id", "case_id", "problem_id", "arm", "lane")},
        "execution": {"namespace": "measured", "is_control": False, "control_id": None, "python_hash_seed": "0"},
        "attempt": {"attempt_n": 1, "methodology": "initial", "repair_reason": None},
        "job": {"source_path": str(source_job.resolve()), "publication_path": str(source_job.with_suffix(source_job.suffix + ".publication.json").resolve()), "artifact_path": str(artifact_runtime.resolve()), "sha256": sha256_bytes(job_bytes), "bytes": len(job_bytes)},
        "interpreter": {"lane_root": str(lane_root), "path": str(interpreter), "sha256": sha256_file(interpreter), "package_root": str(package_root)},
        "paths": {"attempt_root": str(attempt_root.resolve()), "binding": str(binding_runtime.resolve()), "receipt": str((attempt_root / "receipt.json").resolve()), "stdout": str((attempt_root / "stdout.log").resolve()), "stderr": str((attempt_root / "stderr.log").resolve())},
        "command": {"argv": argv, "sha256": sha256_bytes(canonical_json(argv).encode("utf-8"))},
    }
    (invocation_root / "invocation-binding.json").write_bytes(canonical_json_bytes(invocation_binding))
    rejection = build_worker_rejection("network_attempt", job, network_attempts=[{"host": "127.0.0.1", "port": 9}])
    (invocation_root / "stdout.log").write_bytes(b"")
    (invocation_root / "stderr.log").write_bytes(canonical_json_bytes(rejection))
    def reference(name: str) -> dict:
        target = invocation_root / name
        return {"path": name, "sha256": sha256_file(target), "bytes": target.stat().st_size}
    receipt = {"schema": "arc4.worker-invocation/v2", "status": "rejected", "returncode": 2, "elapsed_seconds": 0.01, "binding": reference("invocation-binding.json"), "job_after": {"present": True, "sha256": sha256_bytes(job_bytes), "bytes": len(job_bytes)}, "stdout": reference("stdout.log"), "stderr": reference("stderr.log"), "rejection": rejection, "parse_error": None}
    (invocation_root / "receipt.json").write_bytes(canonical_json_bytes(receipt))
    failure = {
        "schema": "arc4.failure/v1", "stage": "worker", "classification": "infrastructure",
        "error_code": "infrastructure_failure", "reason": canonical_json(rejection), "attempt_n": 1,
        "row_identity": {
            "run_id": cases["run_id"], "row_id": failure_row["row_id"], "pair_id": repaired_pair_id,
            "case_id": failure_row["case_id"], "problem_id": failure_row["problem_id"],
            "arm": failure_row["arm"], "lane": failure_row["lane"],
        },
        "methodology": "initial", "evidence": {"cause_error_code": "network_attempt", "worker_rejection": rejection, "invocation_evidence_id": evidence_id},
    }
    repair = {
        "schema": "arc4.repair-declaration/v1", "run_id": cases["run_id"], "pair_id": repaired_pair_id,
        "case_id": repaired_rows[0]["case_id"], "problem_id": repaired_rows[0]["problem_id"],
        "arm": repaired_rows[0]["arm"], "attempt_n": 2, "repair_reason": repair_reason,
        "row_ids": {row["lane"]: row["row_id"] for row in repaired_rows},
    }
    atomic_write(packet / "FAILURE-JOURNAL.jsonl", canonical_json_bytes(failure), allowed_root=packet)
    atomic_write(packet / "REPAIR-JOURNAL.jsonl", canonical_json_bytes(repair), allowed_root=packet)
    assemble_results(packet_root=packet, rows_path=rows_path, controls_dir=controls)

    original_csv = staging / "measurements.csv"
    _original_matrix(original_csv)
    atomic_write(packet / "ORIGINAL-MATRIX-DECOMPOSITION.json", canonical_json_bytes(decompose_original_matrix(original_csv)), allowed_root=packet)
    shutil.copy2(PROJECT / "harness" / "verify.py", packet / "verify.py")
    write_manifest(packet)
    return packet
