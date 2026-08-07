from __future__ import annotations

import argparse
import email.parser
import hashlib
import importlib.metadata
import importlib.util
import json
import locale
import os
import platform
import re
import shutil
import sqlite3
import ssl
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from .common import ContractError, atomic_write, canonical_json_bytes, exact_keys, load_json, require, sha256_file

LOCK_SCHEMA = "arc4.environment-lock/v1"
RAW_SCHEMA = "arc4.raw-environment/v1"
OFFICIAL_WHEEL_SHA256 = "ff74b6344430053c6fad9064892d6a3904ffba6265823e3fba4dfde78f9a0488"
ENV_KEYS = (
    "PYTHONHASHSEED", "PYTHONNOUSERSITE", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS", "JCODEMUNCH_EMBED_MATRIX_CACHE", "JCODEMUNCH_SHARE_SAVINGS",
)
ARTIFACT_KEYS = ("project", "version", "filename", "sha256")
LOCK_KEYS = (
    "schema", "python", "pip", "install", "wheelhouse_artifacts", "lanes",
    "only_declared_distribution_difference", "manifest_bindings",
)
REQUIRED_WHEELHOUSE_PROJECTS = {"jcodemunch-mcp", "numpy", "pip"}
MANIFEST_PATHS = {
    "raw": {"numpy_present": "env/raw-numpy-present.json", "numpy_absent": "env/raw-numpy-absent.json"},
    "canonical": {"numpy_present": "env/numpy-present.json", "numpy_absent": "env/numpy-absent.json"},
}


def normalize_project_name(name: str) -> str:
    return "-".join(filter(None, re.split(r"[-_.]+", name.lower())))


def freeze_wheelhouse(spec: Mapping[str, Any], output: Path) -> dict[str, Any]:
    """Materialize exactly the preregistered local artifacts with no replacement."""
    exact_keys(spec, ("schema", "artifacts"), "wheelhouse_spec_keys")
    require(spec["schema"] == "arc4.wheelhouse-spec/v1" and isinstance(spec["artifacts"], list) and bool(spec["artifacts"]), "wheelhouse_spec", str(spec.get("schema")))
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    output.mkdir(parents=True, exist_ok=False)
    for item in spec["artifacts"]:
        exact_keys(item, ("source_path", "filename", "sha256"), "wheelhouse_spec_artifact_keys")
        source = Path(item["source_path"]).resolve()
        require(source.is_file() and source.name == item["filename"] and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is not None and sha256_file(source) == item["sha256"], "wheelhouse_source", str(source))
        require(item["filename"] not in seen and item["filename"].endswith(".whl"), "wheelhouse_filename", item["filename"])
        destination = output / item["filename"]
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{item['filename']}.", suffix=".tmp", dir=output)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copyfile(source, temporary)
            with temporary.open("rb+") as stream:
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError as exc:
                raise ContractError("wheelhouse_destination_exists", str(destination)) from exc
        finally:
            temporary.unlink(missing_ok=True)
        entries.append({"filename": item["filename"], "sha256": item["sha256"]})
        seen.add(item["filename"])
    require([item["filename"] for item in entries] == sorted(seen), "wheelhouse_spec_order", "artifacts must be filename-sorted")
    aggregate = hashlib.sha256(canonical_json_bytes(entries)).hexdigest()
    return {"schema": "arc4.frozen-wheelhouse/v1", "artifacts": entries, "aggregate_sha256": aggregate}


def wheel_identity(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as archive:
            metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            require(len(metadata_names) == 1, "wheel_metadata_count", str(path))
            message = email.parser.BytesParser().parsebytes(archive.read(metadata_names[0]))
    except (OSError, zipfile.BadZipFile) as exc:
        raise ContractError("wheel_metadata_read", f"{path}: {exc}") from exc
    name = message.get("Name")
    version = message.get("Version")
    require(bool(name) and bool(version), "wheel_metadata_fields", str(path))
    return {"project": normalize_project_name(str(name)), "version": str(version), "filename": path.name, "sha256": sha256_file(path)}


def build_environment_lock(wheelhouse: Path) -> dict[str, Any]:
    artifacts = [wheel_identity(path) for path in sorted(wheelhouse.glob("*.whl"), key=lambda value: value.name)]
    require(bool(artifacts), "wheelhouse_empty", str(wheelhouse))
    by_project = {item["project"]: item for item in artifacts}
    require(len(by_project) == len(artifacts), "wheelhouse_duplicate_project", str(wheelhouse))
    require(REQUIRED_WHEELHOUSE_PROJECTS <= set(by_project), "wheelhouse_artifact_set", f"required={sorted(REQUIRED_WHEELHOUSE_PROJECTS)} observed={sorted(by_project)}")
    target = by_project.get("jcodemunch-mcp")
    numpy = by_project.get("numpy")
    pip = by_project.get("pip")
    require(target is not None and target["version"] == "1.108.228" and target["sha256"] == OFFICIAL_WHEEL_SHA256, "treatment_wheel", "official 1.108.228 wheel is required")
    require(numpy is not None and numpy["version"] == "2.4.4", "numpy_wheel", "NumPy 2.4.4 wheel is required")
    require(pip is not None and bool(pip["version"]), "pip_wheel", "an explicitly versioned pip wheel is required")
    shared = [item for item in artifacts if item["project"] != "numpy"]
    result = {
        "schema": LOCK_SCHEMA,
        "python": {"implementation": "CPython", "version": "3.13.7"},
        "pip": {"version": pip["version"], "artifact_sha256": pip["sha256"]},
        "install": {"index": "none", "find_links": "<FROZEN_WHEELHOUSE>", "no_deps": True},
        "wheelhouse_artifacts": artifacts,
        "lanes": {
            "numpy_present": {"distributions": artifacts},
            "numpy_absent": {"distributions": shared},
        },
        "only_declared_distribution_difference": "numpy==2.4.4",
        "manifest_bindings": None,
    }
    validate_environment_lock(result, require_bound=False)
    return result


def validate_environment_lock(value: Mapping[str, Any], *, require_bound: bool) -> None:
    exact_keys(value, LOCK_KEYS, "environment_lock_keys")
    require(value["schema"] == LOCK_SCHEMA, "environment_lock_schema", str(value["schema"]))
    require(value["python"] == {"implementation": "CPython", "version": "3.13.7"}, "environment_python", str(value["python"]))
    exact_keys(value["pip"], ("version", "artifact_sha256"), "environment_pip_keys")
    require(isinstance(value["pip"]["version"], str) and bool(value["pip"]["version"]) and re.fullmatch(r"[0-9a-f]{64}", value["pip"]["artifact_sha256"]) is not None, "environment_pip", str(value["pip"]))
    require(value["install"] == {"index": "none", "find_links": "<FROZEN_WHEELHOUSE>", "no_deps": True}, "environment_install", str(value["install"]))
    artifacts = value["wheelhouse_artifacts"]
    require(isinstance(artifacts, list) and bool(artifacts), "environment_artifacts", "nonempty artifact list required")
    for artifact in artifacts:
        exact_keys(artifact, ARTIFACT_KEYS, "environment_artifact_keys")
        require(all(isinstance(artifact[key], str) and artifact[key] for key in ARTIFACT_KEYS), "environment_artifact_types", str(artifact))
        require(re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]) is not None, "environment_artifact_hash", str(artifact))
    require(artifacts == sorted(artifacts, key=lambda item: item["filename"]), "environment_artifact_order", "artifacts must be filename-sorted")
    by_project = {item["project"]: item for item in artifacts}
    require(len(by_project) == len(artifacts) and REQUIRED_WHEELHOUSE_PROJECTS <= set(by_project), "environment_artifact_set", str(sorted(by_project)))
    require(by_project["jcodemunch-mcp"]["version"] == "1.108.228" and by_project["jcodemunch-mcp"]["sha256"] == OFFICIAL_WHEEL_SHA256, "environment_treatment", str(by_project["jcodemunch-mcp"]))
    require(by_project["numpy"]["version"] == "2.4.4", "environment_numpy", str(by_project["numpy"]))
    require(value["pip"] == {"version": by_project["pip"]["version"], "artifact_sha256": by_project["pip"]["sha256"]}, "environment_pip_binding", "pip field must bind the retained artifact")
    exact_keys(value["lanes"], ("numpy_present", "numpy_absent"), "environment_lane_keys")
    for lane in ("numpy_present", "numpy_absent"):
        exact_keys(value["lanes"][lane], ("distributions",), "environment_lane_shape")
    require(value["lanes"]["numpy_present"]["distributions"] == artifacts, "environment_present_distributions", "present lane must install the complete lock")
    absent_expected = [item for item in artifacts if item["project"] != "numpy"]
    require(value["lanes"]["numpy_absent"]["distributions"] == absent_expected, "environment_absent_distributions", "absent lane must omit only NumPy")
    require(value["only_declared_distribution_difference"] == "numpy==2.4.4", "environment_lane_difference", str(value["only_declared_distribution_difference"]))
    bindings = value["manifest_bindings"]
    if not require_bound:
        require(bindings is None or isinstance(bindings, dict), "environment_bindings_type", str(type(bindings)))
        return
    require(isinstance(bindings, dict), "environment_bindings_missing", "manifest bindings are required before preregistration")
    exact_keys(bindings, ("schema", "raw", "canonical", "roots", "c16"), "environment_binding_keys")
    require(bindings["schema"] == "arc4.environment-manifest-bindings/v1", "environment_binding_schema", str(bindings["schema"]))
    for family in ("raw", "canonical"):
        exact_keys(bindings[family], ("numpy_present", "numpy_absent"), "environment_binding_lanes")
        for lane in ("numpy_present", "numpy_absent"):
            exact_keys(bindings[family][lane], ("path", "sha256"), "environment_binding_receipt")
            require(bindings[family][lane]["path"] == MANIFEST_PATHS[family][lane], "environment_binding_path", str(bindings[family][lane]["path"]))
            require(re.fullmatch(r"[0-9a-f]{64}", bindings[family][lane]["sha256"]) is not None, "environment_binding_hash", str(bindings[family][lane]))
    exact_keys(bindings["roots"], ("packet_root", "numpy_present", "numpy_absent"), "environment_root_keys")
    for lane in ("numpy_present", "numpy_absent"):
        exact_keys(bindings["roots"][lane], ("lane_venv", "trial_root", "python_executable", "python_executable_sha256", "package_root"), "environment_lane_root_keys")
        require(all(isinstance(bindings["roots"][lane][key], str) and bindings["roots"][lane][key] for key in ("lane_venv", "trial_root", "python_executable", "python_executable_sha256", "package_root")), "environment_lane_roots", lane)
        require(re.fullmatch(r"[0-9a-f]{64}", bindings["roots"][lane]["python_executable_sha256"]) is not None, "environment_interpreter_hash", lane)
    require(isinstance(bindings["roots"]["packet_root"], str) and bool(bindings["roots"]["packet_root"]), "environment_packet_root", str(bindings["roots"]["packet_root"]))
    require(bindings["c16"] == {"status": "passed", "only_declared_difference": "numpy==2.4.4"}, "environment_c16", str(bindings["c16"]))


def _path_rewrite(value: str, root: str, marker: str) -> str:
    resolved = Path(value).resolve()
    base = Path(root).resolve()
    try:
        suffix = resolved.relative_to(base).as_posix()
    except ValueError as exc:
        raise ContractError("manifest_path_escape", f"{resolved} is outside {base}") from exc
    return marker if suffix == "." else f"{marker}/{suffix}"


def canonicalize_raw_manifest(raw: Mapping[str, Any], *, lane_venv: Path, trial_root: Path, packet_root: Path) -> dict[str, Any]:
    required = (
        "schema", "lane", "python_implementation", "python_version", "python_cache_tag", "platform",
        "machine", "processor", "locale", "time_zone", "sqlite_version", "openssl_version",
        "distributions", "treatment_wheel_sha256", "pip_version", "numpy", "cpu", "blas",
        "environment", "configuration", "python_executable", "storage_path", "cwd",
    )
    exact_keys(raw, required, "manifest_keys")
    require(raw["schema"] == RAW_SCHEMA, "raw_manifest_schema", str(raw["schema"]))
    lane = raw["lane"]
    require(lane in ("numpy_present", "numpy_absent"), "manifest_lane", str(lane))
    distributions = sorted((dict(item) for item in raw["distributions"]), key=lambda item: item["project"])
    for item in distributions:
        exact_keys(item, ("project", "version", "artifact_sha256"), "distribution_keys")
        require(all(isinstance(item[key], str) and item[key] for key in ("project", "version")), "distribution_types", str(item))
        require(re.fullmatch(r"[0-9a-f]{64}", item["artifact_sha256"]) is not None, "distribution_hash", str(item))
    require(len({item["project"] for item in distributions}) == len(distributions), "distribution_duplicate", "project names must be unique")
    target = [item for item in distributions if item["project"] == "jcodemunch-mcp"]
    require(len(target) == 1 and target[0]["version"] == "1.108.228" and target[0]["artifact_sha256"] == OFFICIAL_WHEEL_SHA256, "manifest_treatment_distribution", str(target))
    numpy_distributions = [item for item in distributions if item["project"] == "numpy"]
    if lane == "numpy_present":
        require(len(numpy_distributions) == 1 and numpy_distributions[0]["version"] == "2.4.4", "manifest_numpy_distribution", str(numpy_distributions))
        require(raw["numpy"] == {"present": True, "version": "2.4.4", "artifact_sha256": numpy_distributions[0]["artifact_sha256"]}, "manifest_numpy_state", str(raw["numpy"]))
    else:
        require(not numpy_distributions and raw["numpy"] == {"present": False, "version": None, "artifact_sha256": None}, "manifest_numpy_absence", str(raw["numpy"]))
    exact_keys(raw["cpu"], ("architecture", "machine", "processor", "logical_cpu_count"), "cpu_keys")
    exact_keys(raw["blas"], ("source_lane", "numpy_version", "config_json_sha256", "raw_receipt_sha256"), "blas_keys")
    exact_keys(raw["environment"], ENV_KEYS, "environment_keys")
    exact_keys(raw["configuration"], ("share_savings", "perf_telemetry_enabled", "embed_model"), "configuration_keys")
    require(raw["python_version"] == "3.13.7" and raw["treatment_wheel_sha256"] == OFFICIAL_WHEEL_SHA256, "environment_identity", "Python or treatment wheel identity differs")
    require(isinstance(raw["cpu"]["logical_cpu_count"], int) and raw["cpu"]["logical_cpu_count"] > 0, "cpu_count", str(raw["cpu"]["logical_cpu_count"]))
    require(all(isinstance(raw["cpu"][key], str) for key in ("architecture", "machine", "processor")), "cpu_types", str(raw["cpu"]))
    require(raw["blas"]["source_lane"] == "numpy_present" and raw["blas"]["numpy_version"] == "2.4.4", "blas_identity", str(raw["blas"]))
    require(all(re.fullmatch(r"[0-9a-f]{64}", raw["blas"][key]) is not None for key in ("config_json_sha256", "raw_receipt_sha256")), "blas_hash", str(raw["blas"]))
    require(all(value is None or isinstance(value, str) for value in raw["environment"].values()), "environment_types", str(raw["environment"]))
    require(raw["configuration"]["share_savings"] is False and raw["configuration"]["perf_telemetry_enabled"] is False and isinstance(raw["configuration"]["embed_model"], str), "configuration_values", str(raw["configuration"]))
    return {
        **{key: raw[key] for key in required if key not in ("schema", "distributions", "python_executable", "storage_path", "cwd")},
        "schema": LOCK_SCHEMA,
        "distributions": distributions,
        "python_executable": _path_rewrite(str(raw["python_executable"]), str(lane_venv), "<LANE_VENV>"),
        "storage_path": _path_rewrite(str(raw["storage_path"]), str(trial_root), "<TRIAL_ROOT>"),
        "cwd": _path_rewrite(str(raw["cwd"]), str(packet_root), "<PACKET_ROOT>"),
    }


def compare_canonical_manifests(present: Mapping[str, Any], absent: Mapping[str, Any]) -> None:
    require(present.get("schema") == absent.get("schema") == LOCK_SCHEMA, "canonical_schema", "manifest schemas differ")
    p = json.loads(json.dumps(present))
    a = json.loads(json.dumps(absent))
    require(p.pop("lane") == "numpy_present" and a.pop("lane") == "numpy_absent", "canonical_lane", "lane labels invalid")
    p_numpy = p.pop("numpy")
    a_numpy = a.pop("numpy")
    require(p_numpy.get("present") is True and p_numpy.get("version") == "2.4.4", "canonical_numpy_present", str(p_numpy))
    require(a_numpy == {"present": False, "version": None, "artifact_sha256": None}, "canonical_numpy_absent", str(a_numpy))
    p["distributions"] = [item for item in p["distributions"] if item["project"] != "numpy"]
    a["distributions"] = [item for item in a["distributions"] if item["project"] != "numpy"]
    require(p == a, "environment_parity", "canonical manifests differ beyond declared NumPy treatment")


def bind_environment_manifests(
    lock: Mapping[str, Any], *, packet_root: Path, lane_roots: Mapping[str, Mapping[str, Path]],
) -> dict[str, Any]:
    """Bind raw and canonical receipts after independently repeating C16."""

    validate_environment_lock(lock, require_bound=False)
    require(lock["manifest_bindings"] is None, "environment_already_bound", "manifest bindings are immutable")
    require(set(lane_roots) == {"numpy_present", "numpy_absent"}, "environment_lane_roots", "both lane roots required")
    raw_values: dict[str, Mapping[str, Any]] = {}
    canonical_values: dict[str, Mapping[str, Any]] = {}
    bindings: dict[str, Any] = {
        "schema": "arc4.environment-manifest-bindings/v1",
        "raw": {},
        "canonical": {},
        "roots": {"packet_root": str(packet_root.resolve())},
        "c16": {"status": "passed", "only_declared_difference": "numpy==2.4.4"},
    }
    for lane in ("numpy_present", "numpy_absent"):
        roots = lane_roots[lane]
        exact_keys(roots, ("lane_venv", "trial_root"), "environment_lane_root_keys")
        lane_venv = Path(roots["lane_venv"]).resolve()
        interpreter = (lane_venv / "Scripts" / "python.exe").resolve()
        package_root = (lane_venv / "Lib" / "site-packages" / "jcodemunch_mcp").resolve()
        require(interpreter.is_file(), "environment_interpreter_missing", str(interpreter))
        raw_path = packet_root / MANIFEST_PATHS["raw"][lane]
        canonical_path = packet_root / MANIFEST_PATHS["canonical"][lane]
        raw = load_json(raw_path)
        canonical = load_json(canonical_path)
        expected = canonicalize_raw_manifest(raw, lane_venv=Path(roots["lane_venv"]), trial_root=Path(roots["trial_root"]), packet_root=packet_root)
        require(canonical == expected, "environment_canonical_receipt", lane)
        raw_values[lane] = raw
        canonical_values[lane] = canonical
        bindings["raw"][lane] = {"path": MANIFEST_PATHS["raw"][lane], "sha256": sha256_file(raw_path)}
        bindings["canonical"][lane] = {"path": MANIFEST_PATHS["canonical"][lane], "sha256": sha256_file(canonical_path)}
        bindings["roots"][lane] = {"lane_venv": str(lane_venv), "trial_root": str(Path(roots["trial_root"]).resolve()), "python_executable": str(interpreter), "python_executable_sha256": sha256_file(interpreter), "package_root": str(package_root)}
    compare_canonical_manifests(canonical_values["numpy_present"], canonical_values["numpy_absent"])
    result = dict(lock)
    result["manifest_bindings"] = bindings
    validate_environment_lock(result, require_bound=True)
    validate_bound_environment(result, packet_root=packet_root)
    return result


def validate_bound_environment(lock: Mapping[str, Any], *, packet_root: Path) -> None:
    validate_environment_lock(lock, require_bound=True)
    bindings = lock["manifest_bindings"]
    lane_roots = {
        lane: {key: Path(value) for key, value in bindings["roots"][lane].items() if key in {"lane_venv", "trial_root", "python_executable", "package_root"}}
        for lane in ("numpy_present", "numpy_absent")
    }
    raw_values: dict[str, Mapping[str, Any]] = {}
    canonical_values: dict[str, Mapping[str, Any]] = {}
    for family in ("raw", "canonical"):
        for lane in ("numpy_present", "numpy_absent"):
            receipt = bindings[family][lane]
            path = packet_root / receipt["path"]
            require(path.is_file() and sha256_file(path) == receipt["sha256"], "environment_receipt_hash", f"{family}:{lane}")
            value = load_json(path)
            if family == "raw":
                raw_values[lane] = value
            else:
                canonical_values[lane] = value
    for lane in ("numpy_present", "numpy_absent"):
        bound_root = bindings["roots"][lane]
        require(Path(bound_root["python_executable"]).resolve() == (Path(bound_root["lane_venv"]).resolve() / "Scripts" / "python.exe").resolve(), "environment_interpreter_layout", lane)
        require(Path(bound_root["package_root"]).resolve() == (Path(bound_root["lane_venv"]).resolve() / "Lib" / "site-packages" / "jcodemunch_mcp").resolve(), "environment_package_layout", lane)
        require(raw_values[lane]["python_executable"] == bound_root["python_executable"], "environment_raw_interpreter", lane)
        expected = canonicalize_raw_manifest(
            raw_values[lane], lane_venv=lane_roots[lane]["lane_venv"],
            trial_root=lane_roots[lane]["trial_root"], packet_root=Path(bindings["roots"]["packet_root"]),
        )
        require(canonical_values[lane] == expected, "environment_canonical_receipt", lane)
        expected_distributions = sorted(
            ({"project": item["project"], "version": item["version"], "artifact_sha256": item["sha256"]} for item in lock["lanes"][lane]["distributions"]),
            key=lambda item: item["project"],
        )
        require(canonical_values[lane]["distributions"] == expected_distributions, "environment_locked_distributions", lane)
        require(canonical_values[lane]["pip_version"] == lock["pip"]["version"], "environment_locked_pip", lane)
    compare_canonical_manifests(canonical_values["numpy_present"], canonical_values["numpy_absent"])


def capture_raw_environment_manifest(
    *, lane: str, artifact_hashes: Mapping[str, str], treatment_wheel_sha256: str,
    storage_path: Path, configuration: Mapping[str, Any], blas: Mapping[str, Any], cwd: Path | None = None,
) -> dict[str, Any]:
    require(lane in ("numpy_present", "numpy_absent"), "manifest_lane", lane)
    distributions: list[dict[str, Any]] = []
    for distribution in importlib.metadata.distributions():
        project = normalize_project_name(distribution.metadata["Name"])
        require(project in artifact_hashes, "undeclared_distribution", project)
        distributions.append({"project": project, "version": distribution.version, "artifact_sha256": artifact_hashes[project]})
    distributions.sort(key=lambda item: item["project"])
    spec = importlib.util.find_spec("numpy")
    numpy_state: dict[str, Any]
    if spec is None:
        numpy_state = {"present": False, "version": None, "artifact_sha256": None}
    else:
        numpy_version = importlib.metadata.version("numpy")
        numpy_state = {"present": True, "version": numpy_version, "artifact_sha256": artifact_hashes.get("numpy")}
    return {
        "schema": RAW_SCHEMA,
        "lane": lane,
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_cache_tag": sys.implementation.cache_tag or "",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "locale": locale.setlocale(locale.LC_ALL, None),
        "time_zone": os.environ.get("TZ", ""),
        "sqlite_version": sqlite3.sqlite_version,
        "openssl_version": ssl.OPENSSL_VERSION,
        "distributions": distributions,
        "treatment_wheel_sha256": treatment_wheel_sha256,
        "pip_version": importlib.metadata.version("pip"),
        "numpy": numpy_state,
        "cpu": {"architecture": platform.architecture()[0], "machine": platform.machine(), "processor": platform.processor(), "logical_cpu_count": os.cpu_count() or 1},
        "blas": dict(blas),
        "environment": {key: os.environ.get(key) for key in ENV_KEYS},
        "configuration": dict(configuration),
        "python_executable": sys.executable,
        "storage_path": str(storage_path.resolve()),
        "cwd": str((cwd or Path.cwd()).resolve()),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    lock = sub.add_parser("lock")
    lock.add_argument("wheelhouse", type=Path)
    lock.add_argument("output", type=Path)
    freeze = sub.add_parser("freeze-wheelhouse")
    freeze.add_argument("spec", type=Path)
    freeze.add_argument("output_dir", type=Path)
    freeze.add_argument("receipt", type=Path)
    canonical = sub.add_parser("canonicalize")
    canonical.add_argument("raw", type=Path)
    canonical.add_argument("output", type=Path)
    canonical.add_argument("--lane-venv", type=Path, required=True)
    canonical.add_argument("--trial-root", type=Path, required=True)
    canonical.add_argument("--packet-root", type=Path, required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("spec", type=Path)
    capture.add_argument("output", type=Path)
    bind = sub.add_parser("bind")
    bind.add_argument("lock", type=Path)
    bind.add_argument("packet_root", type=Path)
    bind.add_argument("lane_roots", type=Path)
    bind.add_argument("output", type=Path)
    ns = parser.parse_args(argv)
    try:
        if ns.command == "freeze-wheelhouse":
            value = freeze_wheelhouse(load_json(ns.spec), ns.output_dir)
            atomic_write(ns.receipt, canonical_json_bytes(value), allowed_root=Path.cwd())
            return 0
        if ns.command == "lock":
            value = build_environment_lock(ns.wheelhouse)
        elif ns.command == "canonicalize":
            value = canonicalize_raw_manifest(load_json(ns.raw), lane_venv=ns.lane_venv, trial_root=ns.trial_root, packet_root=ns.packet_root)
        elif ns.command == "capture":
            spec = load_json(ns.spec)
            exact_keys(spec, ("lane", "artifact_hashes", "treatment_wheel_sha256", "storage_path", "configuration", "blas", "cwd"), "capture_spec_keys")
            value = capture_raw_environment_manifest(
                lane=spec["lane"], artifact_hashes=spec["artifact_hashes"],
                treatment_wheel_sha256=spec["treatment_wheel_sha256"], storage_path=Path(spec["storage_path"]),
                configuration=spec["configuration"], blas=spec["blas"], cwd=Path(spec["cwd"]),
            )
        else:
            roots_value = load_json(ns.lane_roots)
            require(isinstance(roots_value, dict), "environment_lane_roots", "object required")
            roots = {lane: {key: Path(path) for key, path in values.items()} for lane, values in roots_value.items()}
            value = bind_environment_manifests(load_json(ns.lock), packet_root=ns.packet_root.resolve(), lane_roots=roots)
        atomic_write(ns.output, canonical_json_bytes(value), allowed_root=ns.output.resolve().parent)
        return 0
    except ContractError as exc:
        parser.error(str(exc))
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
