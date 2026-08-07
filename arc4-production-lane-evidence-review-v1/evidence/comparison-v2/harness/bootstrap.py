from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .common import atomic_write, canonical_json_bytes, require, sha256_file
from .environment import wheel_identity


ROOT = Path(__file__).resolve().parent.parent
PREPARED_INPUTS = Path(
    r"<PUBLIC_EVIDENCE_ROOT>"
    r"\arc4-real-embedding-certification-v1\prepared-inputs.json"
)
ORIGINAL_ROOT = Path(
    r"<LOCAL_RESEARCH_ROOT>"
    r"\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1"
)
ORIGINAL_MATRIX = ORIGINAL_ROOT / "measurements.csv"
DATABASES = {
    "django": ORIGINAL_ROOT / "working" / "indexes" / "local-django-3eb2e228.db",
    "fastapi": ORIGINAL_ROOT / "working" / "indexes" / "local-fastapi-c1d6b9c4.db",
    "jcodemunch": ORIGINAL_ROOT / "working" / "indexes" / "local-arc4-research-v1-upstream-6f37f3de.db",
}
PYPI_URL = (
    "https://files.pythonhosted.org/packages/d1/f0/"
    "c909876da845369235486c8876ad6f5b870cb7332a67668ff1eda49a7897/"
    "jcodemunch_mcp-1.108.228-py3-none-any.whl"
)


def _candidate_ids(database: Path) -> list[str]:
    require(database.is_file(), "bootstrap_database_missing", str(database))
    uri = database.resolve().as_uri() + "?mode=ro&immutable=1"
    with sqlite3.connect(uri, uri=True) as connection:
        values = [str(row[0]) for row in connection.execute(
            "SELECT symbol_id FROM symbol_embeddings ORDER BY symbol_id"
        )]
    require(values == sorted(set(values)) and bool(values), "bootstrap_candidate_ids", str(database))
    return values


def _wheel_sources() -> list[Path]:
    values = list((ROOT / "inputs" / "wheelhouse").glob("*.whl"))
    values.extend(
        [
            ROOT / "inputs" / "jcodemunch_mcp-1.108.228-py3-none-any.whl",
            ROOT / "inputs" / "numpy-2.4.4-cp313-cp313-win_amd64.whl",
        ]
    )
    values = sorted((path.resolve() for path in values), key=lambda path: path.name)
    require(len(values) == 41 and len({path.name for path in values}) == 41, "bootstrap_wheel_count", str(len(values)))
    require(all(path.is_file() for path in values), "bootstrap_wheel_missing", "one or more wheel files are missing")
    return values


def derive() -> tuple[dict, dict[str, dict], dict[str, dict]]:
    prepared = json.loads(PREPARED_INPUTS.read_text(encoding="utf-8"))
    require(prepared.get("schema_version") == "arc4-real-embedding-certification-v1", "bootstrap_prepared_schema", str(prepared.get("schema_version")))
    require(sha256_file(PREPARED_INPUTS) == "623b077e57d0c6c8b0207c5124dd93e05a1a42d9015f92fd6ef0e5161c6e07c0", "bootstrap_prepared_hash", str(PREPARED_INPUTS))
    require(sha256_file(ORIGINAL_MATRIX) == "f50451015e4b56522fdbca84eddd677ecf3da77724e054a75c1e2e69005da303", "bootstrap_original_matrix_hash", str(ORIGINAL_MATRIX))

    wheel_items = []
    artifact_hashes: dict[str, str] = {}
    for source in _wheel_sources():
        identity = wheel_identity(source)
        artifact_hashes[identity["project"]] = identity["sha256"]
        wheel_items.append(
            {"source_path": str(source), "filename": source.name, "sha256": identity["sha256"]}
        )

    corpora: dict[str, dict] = {}
    for name, database in DATABASES.items():
        observed = sha256_file(database)
        require(observed == prepared["corpora"][name]["working_database_sha256"], "bootstrap_corpus_hash", name)
        corpora[name] = {
            "database": str(database.resolve()),
            "repo_id": prepared["corpora"][name]["source_repo_id"],
            "candidate_ids": _candidate_ids(database),
        }

    queries: dict[str, dict] = {}
    for query_id, value in prepared["queries"].items():
        arguments = json.loads(value["serialized_args_json"])
        queries[query_id] = {
            "query_text": arguments["query"],
            "query_vector": value["vector"],
            "query_vector_sha256": value["sha256"],
        }
    return {"schema": "arc4.wheelhouse-spec/v1", "artifacts": wheel_items}, corpora, queries


def build_config(*, approved_utc: str) -> tuple[dict, dict, dict[str, dict]]:
    wheelhouse_spec, corpora, queries = derive()
    working = ROOT / "working"
    runtime = working / "runtime"
    packet = ROOT / "packet"
    lane_roots = {
        lane: {
            "lane_venv": str((working / "venvs" / lane).resolve()),
            "trial_root": str((working / "trials" / lane).resolve()),
        }
        for lane in ("numpy_present", "numpy_absent")
    }
    capture_specs: dict[str, dict] = {}
    artifact_hashes = {
        wheel_identity(Path(item["source_path"]))["project"]: item["sha256"]
        for item in wheelhouse_spec["artifacts"]
    }
    blas_receipt_path = working / "BLAS-BASELINE.json"
    require(blas_receipt_path.is_file(), "bootstrap_blas_receipt_missing", str(blas_receipt_path))
    blas_receipt = json.loads(blas_receipt_path.read_text(encoding="utf-8"))
    require(
        set(blas_receipt) == {"schema", "source_lane", "numpy_version", "python_executable", "config"}
        and blas_receipt["schema"] == "arc4.blas-baseline/v1"
        and blas_receipt["source_lane"] == "numpy_present"
        and blas_receipt["numpy_version"] == "2.4.4",
        "bootstrap_blas_receipt",
        str(blas_receipt_path),
    )
    blas = {
        "source_lane": "numpy_present",
        "numpy_version": "2.4.4",
        "config_json_sha256": __import__("hashlib").sha256(canonical_json_bytes(blas_receipt["config"])).hexdigest(),
        "raw_receipt_sha256": sha256_file(blas_receipt_path),
    }
    for lane in ("numpy_present", "numpy_absent"):
        capture_specs[lane] = {
            "lane": lane,
            "artifact_hashes": artifact_hashes,
            "treatment_wheel_sha256": "ff74b6344430053c6fad9064892d6a3904ffba6265823e3fba4dfde78f9a0488",
            "storage_path": lane_roots[lane]["trial_root"],
            "configuration": {
                "share_savings": False,
                "perf_telemetry_enabled": False,
                "embed_model": "all-MiniLM-L6-v2",
            },
            "blas": blas,
            "cwd": str(packet.resolve()),
        }

    config = {
        "schema": "arc4.campaign-config/v1",
        "run_id": "arc4-production-lane-v2-20260806",
        "runtime_root": str(runtime.resolve()),
        "packet_root": str(packet.resolve()),
        "harness_root": str((ROOT / "harness").resolve()),
        "python_executable": str((working / "build-python" / "Scripts" / "python.exe").resolve()),
        "wheelhouse": str((working / "frozen-wheelhouse").resolve()),
        "lane_interpreters": {
            lane: str((Path(lane_roots[lane]["lane_venv"]) / "Scripts" / "python.exe").resolve())
            for lane in lane_roots
        },
        "frozen_cases": str((packet / "frozen-cases.json").resolve()),
        "environment_lock": str((packet / "ENVIRONMENT-LOCK.json").resolve()),
        "preregistration_inputs": str((packet / "PREREGISTRATION-INPUTS.json").resolve()),
        "preregistration_commit_receipt": str((packet / "PREREGISTRATION-COMMIT.json").resolve()),
        "preregistration_repository": str(ROOT.resolve()),
        "corpora": corpora,
        "queries": queries,
        "worker_timeout_seconds": 900,
        "official_wheel": str((ROOT / "inputs" / "jcodemunch_mcp-1.108.228-py3-none-any.whl").resolve()),
        "source_checkout": str((working / "source-8bed872e").resolve()),
        "source_build_output": str((working / "p0-production-replay").resolve()),
        "source_build_receipt": str((packet / "SOURCE-BUILD-RECEIPT.json").resolve()),
        "source_build_receipt_digest": str((packet / "SOURCE-BUILD-RECEIPT.sha256").resolve()),
        "p0_receipt": str((packet / "P0-RECEIPT.json").resolve()),
        "design_path": str((ROOT / "DESIGN.md").resolve()),
        "frozen_config": str((working / "FROZEN-CONFIG.json").resolve()),
        "approved_utc": approved_utc,
        "pypi_url": PYPI_URL,
        "original_matrix_csv": str(ORIGINAL_MATRIX.resolve()),
        "environment_capture_specs": {
            "numpy_present": str((packet / "env" / "raw-numpy-present.json").resolve()),
            "numpy_absent": str((packet / "env" / "raw-numpy-absent.json").resolve()),
        },
        "environment_lane_roots": lane_roots,
        "wheelhouse_spec": str((working / "WHEELHOUSE-SPEC.json").resolve()),
        "wheelhouse_receipt": str((runtime / "wheelhouse-receipt.json").resolve()),
        "child_environment": {
            "system_root": os.environ.get("SystemRoot", r"C:\Windows"),
            "temp": str((working / "temp").resolve()),
            "locale": "C",
            "timezone": "UTC",
            "pythonhashseed": "0",
        },
    }
    return config, wheelhouse_spec, capture_specs


def prepare(*, repair_failed_bootstrap: bool = False) -> dict:
    approved_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    config, wheelhouse_spec, capture_specs = build_config(approved_utc=approved_utc)
    working = ROOT / "working"
    outputs = [
        working / "FROZEN-CONFIG.json",
        working / "WHEELHOUSE-SPEC.json",
        ROOT / "packet" / "env" / "raw-numpy-present.json",
        ROOT / "packet" / "env" / "raw-numpy-absent.json",
    ]
    previous_config_sha256 = None
    if repair_failed_bootstrap:
        require(outputs[0].is_file(), "bootstrap_repair_config_missing", str(outputs[0]))
        previous_config_sha256 = sha256_file(outputs[0])
        require(previous_config_sha256 in {
            "8b8297bd32a3bc8893303dd8c236d13bfd9cd9ab86507be3983815ef744e0695",
            "adf874cc6f06ea4aa16e33d4e09809822a7eb518a0abaff0204d94576f26407a",
            "c4ee7fcd50ba5492b8026e0a1100a0f8d938e7b00e06810d2a00662c76fd244c",
            "e8e79a1d36c5c9bed07378f7eb90eaca2600a5ca0fd689cee2fddac00c75fb77",
            "7affc81c2c5ccfd2970e6ffffbb274054dc41039f1b24dcd30a934c099611546",
        }, "bootstrap_repair_unexpected_config", previous_config_sha256)
        require(not (ROOT / "packet" / "CONFIG.json").exists(), "bootstrap_repair_staging_started", "packet CONFIG already exists")
        require(not (ROOT / "working" / "runtime" / "campaign-state.json").exists(), "bootstrap_repair_campaign_started", "campaign state already exists")
    else:
        require(not any(path.exists() for path in outputs), "bootstrap_output_exists", "bootstrap is create-new")
    atomic_write(outputs[0], canonical_json_bytes(config), allowed_root=ROOT)
    atomic_write(outputs[1], canonical_json_bytes(wheelhouse_spec), allowed_root=ROOT)
    for lane, path in zip(("numpy_present", "numpy_absent"), outputs[2:]):
        atomic_write(path, canonical_json_bytes(capture_specs[lane]), allowed_root=ROOT)
    receipt = {
        "schema": "arc4.bootstrap-receipt/v1",
        "approved_utc": approved_utc,
        "config_path": str(outputs[0].resolve()),
        "config_sha256": sha256_file(outputs[0]),
        "wheel_count": len(wheelhouse_spec["artifacts"]),
        "candidate_counts": {name: len(value["candidate_ids"]) for name, value in config["corpora"].items()},
        "packet_root": config["packet_root"],
        "runtime_root": config["runtime_root"],
        "supersedes_failed_config_sha256": previous_config_sha256,
        "preserved_failed_capture_specs": (
            ["working/capture-numpy_present.json", "working/capture-numpy_absent.json"]
            if repair_failed_bootstrap else []
        ),
    }
    atomic_write(working / "BOOTSTRAP-RECEIPT.json", canonical_json_bytes(receipt), allowed_root=ROOT)
    return receipt


def write_preregistration_commit_receipt() -> dict:
    packet = ROOT / "packet"
    output = packet / "PREREGISTRATION-COMMIT.json"
    require(not output.exists(), "bootstrap_prereg_receipt_exists", str(output))
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
        shell=False,
    )
    commit_sha = process.stdout.decode("ascii", errors="strict").strip()
    require(process.returncode == 0 and len(commit_sha) == 40, "bootstrap_prereg_commit", process.stderr.decode("utf-8", errors="replace"))
    names = (
        "CONFIG.json",
        "ENVIRONMENT-LOCK.json",
        "P0-RECEIPT.json",
        "PREREGISTRATION-INPUTS.json",
        "SOURCE-BUILD-RECEIPT.json",
        "SOURCE-BUILD-RECEIPT.sha256",
        "SOURCE-INVENTORY.json",
        "frozen-cases.json",
    )
    receipt = {
        "schema": "arc4.preregistration-commit/v1",
        "commit_sha": commit_sha,
        "committed": True,
        "files": {name: sha256_file(packet / name) for name in names},
    }
    atomic_write(output, canonical_json_bytes(receipt), allowed_root=packet)
    from .campaign import validate_preregistration_commit

    config = json.loads((packet / "CONFIG.json").read_text(encoding="utf-8"))
    validate_preregistration_commit(config)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("check", "prepare", "repair-failed-bootstrap", "record-blas", "write-prereg-receipt"))
    arguments = parser.parse_args(argv)
    if arguments.mode == "write-prereg-receipt":
        result = write_preregistration_commit_receipt()
    elif arguments.mode == "record-blas":
        expected = (ROOT / "working" / "venvs" / "numpy_present" / "Scripts" / "python.exe").resolve()
        require(Path(sys.executable).resolve() == expected, "bootstrap_blas_interpreter", str(sys.executable))
        import numpy

        config = numpy.show_config(mode="dicts")
        require(isinstance(config, dict) and bool(config), "bootstrap_blas_config", str(type(config)))
        receipt = {
            "schema": "arc4.blas-baseline/v1",
            "source_lane": "numpy_present",
            "numpy_version": numpy.__version__,
            "python_executable": str(expected),
            "config": config,
        }
        path = ROOT / "working" / "BLAS-BASELINE.json"
        require(not path.exists(), "bootstrap_blas_exists", str(path))
        atomic_write(path, canonical_json_bytes(receipt), allowed_root=ROOT)
        result = {
            "status": "recorded",
            "config_json_sha256": __import__("hashlib").sha256(canonical_json_bytes(config)).hexdigest(),
            "raw_receipt_sha256": sha256_file(path),
        }
    elif arguments.mode == "check":
        config, wheelhouse_spec, _capture_specs = build_config(approved_utc="2026-08-06T00:00:00Z")
        result = {
            "status": "ready",
            "wheel_count": len(wheelhouse_spec["artifacts"]),
            "candidate_counts": {name: len(value["candidate_ids"]) for name, value in config["corpora"].items()},
        }
    else:
        result = prepare(repair_failed_bootstrap=arguments.mode == "repair-failed-bootstrap")
    sys.stdout.buffer.write(canonical_json_bytes(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
