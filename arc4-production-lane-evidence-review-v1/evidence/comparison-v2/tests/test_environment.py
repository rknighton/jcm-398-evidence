import tempfile
import unittest
import shutil
import hashlib
from pathlib import Path

from harness.environment import LOCK_SCHEMA, OFFICIAL_WHEEL_SHA256, RAW_SCHEMA, build_environment_lock, canonicalize_raw_manifest, compare_canonical_manifests, freeze_wheelhouse, validate_environment_lock
from tests.packet_fixture import NUMPY, OFFICIAL, PIP


def raw_manifest(root: Path, lane: str):
    venv = root / lane
    trial = root / "trial"
    packet = root / "packet"
    for path in (venv, trial, packet):
        path.mkdir(parents=True, exist_ok=True)
    numpy = {"present": True, "version": "2.4.4", "artifact_sha256": "a" * 64} if lane == "numpy_present" else {"present": False, "version": None, "artifact_sha256": None}
    distributions = [{"project": "jcodemunch-mcp", "version": "1.108.228", "artifact_sha256": OFFICIAL_WHEEL_SHA256}]
    if lane == "numpy_present":
        distributions.append({"project": "numpy", "version": "2.4.4", "artifact_sha256": "a" * 64})
    value = {
        "schema": RAW_SCHEMA, "lane": lane, "python_implementation": "CPython", "python_version": "3.13.7",
        "python_cache_tag": "cpython-313", "platform": "win", "machine": "AMD64", "processor": "x",
        "locale": "C", "time_zone": "UTC", "sqlite_version": "3", "openssl_version": "OpenSSL",
        "distributions": distributions, "treatment_wheel_sha256": OFFICIAL_WHEEL_SHA256, "pip_version": "25",
        "numpy": numpy, "cpu": {"architecture": "64bit", "machine": "AMD64", "processor": "x", "logical_cpu_count": 8},
        "blas": {"source_lane": "numpy_present", "numpy_version": "2.4.4", "config_json_sha256": "c" * 64, "raw_receipt_sha256": "d" * 64},
        "environment": {key: value for key, value in (("PYTHONHASHSEED", "0"), ("PYTHONNOUSERSITE", "1"), ("OMP_NUM_THREADS", "1"), ("OPENBLAS_NUM_THREADS", "1"), ("MKL_NUM_THREADS", "1"), ("JCODEMUNCH_EMBED_MATRIX_CACHE", None), ("JCODEMUNCH_SHARE_SAVINGS", "0"))},
        "configuration": {"share_savings": False, "perf_telemetry_enabled": False, "embed_model": "sentinel"},
        "python_executable": str(venv / "python.exe"), "storage_path": str(trial / "store"), "cwd": str(packet),
    }
    return value, venv, trial, packet


class EnvironmentTests(unittest.TestCase):
    def test_only_numpy_difference_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            p, pv, pt, pp = raw_manifest(root, "numpy_present")
            a, av, at, ap = raw_manifest(root, "numpy_absent")
            present = canonicalize_raw_manifest(p, lane_venv=pv, trial_root=pt, packet_root=pp)
            absent = canonicalize_raw_manifest(a, lane_venv=av, trial_root=at, packet_root=ap)
            compare_canonical_manifests(present, absent)
            self.assertEqual(LOCK_SCHEMA, present["schema"])

    def test_hidden_configuration_difference_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, av, at, ap = raw_manifest(root, "numpy_absent")
            a["configuration"]["share_savings"] = True
            with self.assertRaisesRegex(RuntimeError, "configuration_values"):
                canonicalize_raw_manifest(a, lane_venv=av, trial_root=at, packet_root=ap)

    def test_lock_pins_pip_and_exact_artifact_set(self):
        with tempfile.TemporaryDirectory() as directory:
            wheelhouse = Path(directory)
            for source in (OFFICIAL, NUMPY, PIP):
                shutil.copy2(source, wheelhouse / source.name)
            lock = build_environment_lock(wheelhouse)
            validate_environment_lock(lock, require_bound=False)
            self.assertEqual("25.2", lock["pip"]["version"])
            shutil.copy2(PIP, wheelhouse / "pip-99.9-py3-none-any.whl")
            with self.assertRaisesRegex(RuntimeError, "wheelhouse_duplicate_project"):
                build_environment_lock(wheelhouse)
            lock["lanes"]["numpy_absent"]["distributions"].pop()
            with self.assertRaisesRegex(RuntimeError, "environment_absent_distributions"):
                validate_environment_lock(lock, require_bound=False)

    def test_frozen_wheelhouse_is_exact_ordered_and_content_addressed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = root / "sources"
            sources.mkdir()
            artifacts = []
            for name, payload in (("a-1-py3-none-any.whl", b"a"), ("b-1-py3-none-any.whl", b"b")):
                path = sources / name
                path.write_bytes(payload)
                artifacts.append({"source_path": str(path), "filename": name, "sha256": hashlib.sha256(payload).hexdigest()})
            receipt = freeze_wheelhouse({"schema": "arc4.wheelhouse-spec/v1", "artifacts": artifacts}, root / "frozen")
            self.assertEqual(["a-1-py3-none-any.whl", "b-1-py3-none-any.whl"], [item["filename"] for item in receipt["artifacts"]])
            self.assertEqual(64, len(receipt["aggregate_sha256"]))


if __name__ == "__main__":
    unittest.main()
