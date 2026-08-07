import array
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from unittest import mock

from harness.worker import PROTOCOL_SELF_TEST_ENV, PROTOCOL_SELF_TEST_SCHEMA, _module_origin, _require_score_consistent_top_k, logical_embedding_identity, query_vector_sha256
from harness.common import ContractError, canonical_json, canonical_json_bytes, sha256_bytes, sha256_file
from harness.invocation import job_publication_path, lane_layout
from harness.orchestrator import RunLease, commit_pair_fragment, retained_worker_rejection, run_worker
from harness.packet import normalize_failure_error_code
from tests.worker_fixtures import RUN_ID, planned_row, protocol_job, successful_result, write_protocol_job
from tests.packet_fixture import build_packet


class WorkerHelpersTests(unittest.TestCase):
    @staticmethod
    def _entry_environment() -> dict[str, str]:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        environment[PROTOCOL_SELF_TEST_ENV] = "1"
        environment["PYTHONHASHSEED"] = "0"
        return environment

    def _run(self, job_path: Path, job: dict, attempt: Path):
        payload = job_path.read_bytes()
        publication = {"schema": "arc4.job-publication/v1", "path": str(job_path.resolve()), "sha256": sha256_bytes(payload), "bytes": len(payload)}
        job_publication_path(job_path).write_bytes(canonical_json_bytes(publication))
        command = [str(Path(sys.executable).resolve()), "-m", "harness.worker"]
        lane_root = Path(sys.executable).resolve().parent.parent
        return run_worker(
            command, attempt_root=attempt, timeout_seconds=10, run_id=RUN_ID,
            planned_row=job["planned_row"], attempt_n=1, methodology="initial",
            repair_reason=None, job_path=job_path, job_publication=publication,
            lane_root=lane_root, package_root=lane_root / "Lib" / "site-packages" / "jcodemunch_mcp",
            environment=self._entry_environment(),
        )

    def _retained(self, job_path: Path, job: dict, attempt: Path):
        publication = json.loads(job_publication_path(job_path).read_text(encoding="utf-8"))
        lane_root = Path(sys.executable).resolve().parent.parent
        return retained_worker_rejection(
            attempt, run_id=RUN_ID, planned_row=job["planned_row"], attempt_n=1,
            methodology="initial", repair_reason=None, job_path=job_path,
            command=[str(Path(sys.executable).resolve()), "-m", "harness.worker"],
            job_publication=publication, lane_root=lane_root,
            package_root=lane_root / "Lib" / "site-packages" / "jcodemunch_mcp",
        )

    def _direct(self, job_path: Path) -> subprocess.CompletedProcess[str]:
        attempt = job_path.parent / f"direct-{job_path.stem}"
        attempt.mkdir()
        artifact = attempt / "job-artifact.json"
        if job_path.exists():
            artifact.write_bytes(job_path.read_bytes())
            payload = artifact.read_bytes()
        else:
            payload = b"x"
        plan = planned_row()
        binding_path = attempt / "invocation-binding.json"
        interpreter = Path(sys.executable).resolve()
        lane_root = interpreter.parent.parent
        argv = [str(interpreter), "-m", "harness.worker", "--binding", str(binding_path.resolve()), str(artifact.resolve())]
        binding = {
            "schema": "arc4.worker-invocation-binding/v2", "run_id": RUN_ID,
            "row_identity": {key: plan[key] for key in ("row_id", "pair_id", "case_id", "problem_id", "arm", "lane")},
            "execution": {"namespace": "preflight", "is_control": False, "control_id": None, "python_hash_seed": "0"},
            "attempt": {"attempt_n": 1, "methodology": "initial", "repair_reason": None},
            "job": {"source_path": str(job_path.resolve()), "publication_path": str(job_publication_path(job_path).resolve()), "artifact_path": str(artifact.resolve()), "sha256": sha256_bytes(payload), "bytes": len(payload)},
            "interpreter": {"lane_root": str(lane_root), "path": str(interpreter), "sha256": sha256_file(interpreter), "package_root": str((lane_root / "Lib" / "site-packages" / "jcodemunch_mcp").resolve())},
            "paths": {"attempt_root": str(attempt.resolve()), "binding": str(binding_path.resolve()), "receipt": str((attempt / "receipt.json").resolve()), "stdout": str((attempt / "stdout.log").resolve()), "stderr": str((attempt / "stderr.log").resolve())},
            "command": {"argv": argv, "sha256": sha256_bytes(canonical_json(argv).encode("utf-8"))},
        }
        binding_path.write_bytes(canonical_json_bytes(binding))
        return subprocess.run(
            argv, cwd=job_path.parent,
            env=self._entry_environment(), stdin=subprocess.DEVNULL, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def test_actual_worker_entry_success_uses_authoritative_wire_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_path, job = write_protocol_job(root, name="success")
            result = self._run(job_path, job, root / "attempt")
            self.assertEqual(successful_result(), result)
            receipt = json.loads((root / "attempt" / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual("succeeded", receipt["status"])
            self.assertEqual(result, receipt["result"])

    def test_windows_lane_layout_reaches_production_module_origin_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            packet = build_packet(Path(directory))
            config = json.loads((packet / "CONFIG.json").read_text(encoding="utf-8"))
            layout = lane_layout(config, "numpy_present")
            self.assertEqual((layout["lane_root"] / "Scripts" / "python.exe").resolve(), layout["interpreter"])
            self.assertEqual((layout["lane_root"] / "Lib" / "site-packages" / "jcodemunch_mcp").resolve(), layout["package_root"])
            module_file = layout["package_root"] / "__init__.py"
            module_file.write_bytes(b"# minimal authenticated payload\n")
            self.assertEqual("__init__.py", _module_origin(SimpleNamespace(__file__=str(module_file)), layout["package_root"]))
            old_incorrect_root = layout["lane_root"] / "Scripts" / "Lib" / "site-packages" / "jcodemunch_mcp"
            with self.assertRaisesRegex(RuntimeError, "module_origin_escape"):
                _module_origin(SimpleNamespace(__file__=str(module_file)), old_incorrect_root)

    def test_actual_worker_entry_rejection_families_are_closed_and_classified(self):
        categories = {
            "public_tool_error": ("public_tool_error", "product_lane"),
            "lane_mismatch": ("lane_mismatch", "product_lane"),
            "fallback_firing": ("fallback_firing", "product_lane"),
            "embed_write_tripwire_firing": ("embed_write_tripwire_firing", "product_lane"),
            "generic_precondition": ("failed_precondition", "product_lane"),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for ordinal, (error_code, (expected_m9, journal_classification)) in enumerate(categories.items()):
                attempt = root / f"attempt-{ordinal}"
                job_path, job = write_protocol_job(root, name=f"job-{ordinal}", action="error", error_code=error_code)
                with self.subTest(error_code=error_code), self.assertRaises(RuntimeError) as raised:
                    self._run(job_path, job, attempt)
                self.assertEqual(error_code, getattr(raised.exception, "code", None))
                retained = self._retained(job_path, job, attempt)
                self.assertIsNotNone(retained)
                rejection = retained["rejection"]
                self.assertEqual(expected_m9, rejection["m9_classification"])
                self.assertEqual("jcodemunch_mcp", rejection["product"])
                self.assertEqual("numpy_present", rejection["lane"])
                self.assertEqual("hybrid", rejection["embedding_mode"])
                self.assertEqual(expected_m9, normalize_failure_error_code("worker", journal_classification, error_code))

    def test_actual_network_attempt_is_structured_and_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_path, job = write_protocol_job(root, name="network", action="network_connect")
            attempt = root / "attempt"
            with self.assertRaisesRegex(RuntimeError, "network_attempt"):
                self._run(job_path, job, attempt)
            rejection = self._retained(job_path, job, attempt)["rejection"]
            self.assertEqual("infrastructure_failure", rejection["m9_classification"])
            self.assertEqual([{"host": "127.0.0.1", "port": 9}], rejection["network_attempts"])

    def test_prelaunch_binding_attributes_job_missing_at_worker_open(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_path, job = write_protocol_job(root, name="will-disappear", action="network_connect")
            attempt = root / "attempt"
            original_popen = subprocess.Popen

            def remove_artifact_then_launch(command, *args, **kwargs):
                Path(command[-1]).unlink()
                return original_popen(command, *args, **kwargs)

            with mock.patch("harness.orchestrator.subprocess.Popen", side_effect=remove_artifact_then_launch):
                with self.assertRaisesRegex(RuntimeError, "worker_job_transport"):
                    self._run(job_path, job, attempt)
            retained = self._retained(job_path, job, attempt)
            self.assertIsNone(retained["rejection"]["lane"])
            self.assertEqual(job["planned_row"]["row_id"], retained["invocation_binding"]["row_identity"]["row_id"])
            self.assertFalse(json.loads((attempt / "receipt.json").read_text(encoding="utf-8"))["job_after"]["present"])

    def test_binding_rejects_valid_cross_lane_replacement_after_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job_path, job = write_protocol_job(root, name="original", action="success")
            replacement = canonical_json_bytes(protocol_job(root, lane="numpy_absent", action="success"))
            attempt = root / "attempt"
            original_popen = subprocess.Popen

            def replace_artifact_then_launch(command, *args, **kwargs):
                Path(command[-1]).write_bytes(replacement)
                return original_popen(command, *args, **kwargs)

            with mock.patch("harness.orchestrator.subprocess.Popen", side_effect=replace_artifact_then_launch):
                with self.assertRaisesRegex(RuntimeError, "worker_job_binding_hash"):
                    self._run(job_path, job, attempt)
            receipt = json.loads((attempt / "receipt.json").read_text(encoding="utf-8"))
            self.assertIsNone(receipt["rejection"]["lane"])
            self.assertEqual("worker_job_binding_hash", receipt["rejection"]["error_code"])
            with self.assertRaisesRegex(RuntimeError, "worker_binding_job_planned_identity"):
                self._retained(job_path, job, attempt)

    def test_restart_receipt_rehashes_logs_job_and_binding(self):
        mutations = ("stdout-path", "stdout-missing", "stdout-hash", "stdout-size", "stderr-replaced", "job-replaced", "binding-run", "binding-row")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, mutation in enumerate(mutations):
                case = root / str(index)
                case.mkdir()
                job_path, job = write_protocol_job(case, name="network", action="network_connect")
                attempt = case / "attempt"
                with self.assertRaisesRegex(RuntimeError, "network_attempt"):
                    self._run(job_path, job, attempt)
                receipt_path = attempt / "receipt.json"
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if mutation == "stdout-path":
                    receipt["stdout"]["path"] = "../stdout.log"
                elif mutation == "stdout-missing":
                    (attempt / "stdout.log").unlink()
                elif mutation == "stdout-hash":
                    receipt["stdout"]["sha256"] = "0" * 64
                elif mutation == "stdout-size":
                    receipt["stdout"]["bytes"] += 1
                elif mutation == "stderr-replaced":
                    (attempt / "stderr.log").write_bytes(b"replacement\n")
                elif mutation == "job-replaced":
                    (attempt / "job-artifact.json").write_bytes(b"replacement\n")
                    receipt["job_after"] = {"present": True, "sha256": sha256_bytes(b"replacement\n"), "bytes": len(b"replacement\n")}
                else:
                    binding_path = attempt / "invocation-binding.json"
                    binding = json.loads(binding_path.read_text(encoding="utf-8"))
                    if mutation == "binding-run":
                        binding["run_id"] = "alternate-run"
                    else:
                        binding["row_identity"]["row_id"] = "alternate-row"
                    raw = canonical_json_bytes(binding)
                    binding_path.write_bytes(raw)
                    receipt["binding"] = {"path": "invocation-binding.json", "sha256": sha256_bytes(raw), "bytes": len(raw)}
                if mutation not in {"stdout-missing", "stderr-replaced"}:
                    receipt_path.write_bytes(canonical_json_bytes(receipt))
                with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                    self._retained(job_path, job, attempt)

    def test_direct_worker_missing_malformed_and_invalid_job_are_metadata_free(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = {
                "missing": (root / "missing.json", "worker_job_transport"),
                "malformed": (root / "malformed.json", "worker_job_transport"),
                "invalid-schema": (root / "invalid-schema.json", "worker_protocol_self_test_schema"),
            }
            fixtures["malformed"][0].write_bytes(b"{\n")
            invalid = protocol_job(root)
            invalid["schema"] = "wrong"
            fixtures["invalid-schema"][0].write_bytes(canonical_json_bytes(invalid))
            for name, (path, code) in fixtures.items():
                with self.subTest(name=name):
                    completed = self._direct(path)
                    self.assertEqual(2, completed.returncode, completed.stderr)
                    rejection = json.loads(completed.stderr)
                    self.assertEqual(code, rejection["error_code"])
                    self.assertIsNone(rejection["lane"])
                    self.assertIsNone(rejection["embedding_mode"])
                    self.assertEqual("", completed.stdout)

    def test_success_contract_mutations_are_rejected_before_success_receipt(self):
        mutations = {
            "missing": lambda value: value.pop("final_scores"),
            "extra": lambda value: value.__setitem__("unknown", True),
            "wrong-type": lambda value: value.__setitem__("wall_ns", "1"),
            "wrong-identity": lambda value: value.__setitem__("row_id", "wrong"),
            "nonfinite": lambda value: value["final_scores"].__setitem__("a", "inf"),
            "schema-only": lambda value: (value.clear(), value.update({"schema": "arc4.row-result/v1"})),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (name, mutate) in enumerate(mutations.items()):
                result = deepcopy(successful_result())
                mutate(result)
                job_path, job = write_protocol_job(root, name=name, result=result)
                attempt = root / f"attempt-{index}"
                with self.subTest(name=name), self.assertRaises(RuntimeError):
                    self._run(job_path, job, attempt)
                receipt = json.loads((attempt / "receipt.json").read_text(encoding="utf-8"))
                self.assertEqual("rejected", receipt["status"])
                self.assertIsNone(receipt["result"] if "result" in receipt else None)

    def test_two_real_worker_successes_reach_atomic_pair_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [planned_row(lane=lane) for lane in ("numpy_present", "numpy_absent")]
            results = []
            for index, lane in enumerate(("numpy_present", "numpy_absent")):
                job_path, job = write_protocol_job(root, name=lane, lane=lane)
                results.append(self._run(job_path, job, root / f"attempt-{index}"))
            lease_root = root / "lease"
            lease = RunLease(lease_root, RUN_ID)
            lease.acquire()
            try:
                path = commit_pair_fragment(lease=lease, results=results, expected_rows=rows, attempt_n=1, methodology="initial", repair_reason=None, fragments_root=lease_root / "fragments")
                self.assertTrue(path.is_file())
            finally:
                lease.release()

    def test_query_vector_identity_matches_v1_canonical_json_rule(self):
        self.assertEqual(query_vector_sha256([0.25, -0.0]), query_vector_sha256([0.25, -0.0]))
        self.assertNotEqual(query_vector_sha256([0.25, -0.0]), query_vector_sha256([0.25, 0.0]))

    def test_logical_embedding_digest_is_order_stable_and_content_sensitive(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "index.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE symbol_embeddings(symbol_id TEXT PRIMARY KEY, embedding BLOB NOT NULL)")
                connection.execute("INSERT INTO symbol_embeddings VALUES (?, ?)", ("b", array.array("f", [2.0]).tobytes()))
                connection.execute("INSERT INTO symbol_embeddings VALUES (?, ?)", ("a", array.array("f", [1.0]).tobytes()))
                connection.commit()
            first = logical_embedding_identity(database)
            self.assertEqual(2, first[1])
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("UPDATE symbol_embeddings SET embedding=? WHERE symbol_id='a'", (array.array("f", [3.0]).tobytes(),))
                connection.commit()
            second = logical_embedding_identity(database)
            self.assertNotEqual(first[0], second[0])

    def test_public_top_k_parity_accepts_only_cutoff_tie_substitution(self):
        scores = {"a": 3.0, "b": 2.0, "c": 1.0, "d": 1.0}
        _require_score_consistent_top_k(["a", "b", "d"], scores, 3, "adapter_public_parity")
        with self.assertRaises(ContractError):
            _require_score_consistent_top_k(["a", "c", "d"], scores, 3, "adapter_public_parity")
        with self.assertRaises(ContractError):
            _require_score_consistent_top_k(["b", "a", "c"], scores, 3, "adapter_public_parity")

    def test_network_tripwire_survives_until_shutdown_and_fails_process(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "shutdown_tripwire.py"
            script.write_text(
                "import socket\nfrom harness.controls import OutboundSocketTripwire\n"
                "OutboundSocketTripwire().install(process_lifetime=True)\n"
                "try:\n socket.socket().connect(('127.0.0.1', 9))\nexcept RuntimeError:\n pass\n",
                encoding="utf-8",
            )
            log = Path(directory) / "shutdown.log"
            with log.open("wb") as stream:
                environment = dict(os.environ)
                environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
                process = subprocess.Popen([sys.executable, str(script)], stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, env=environment)
                code = process.wait(timeout=10)
            self.assertEqual(91, code, log.read_text(encoding="utf-8", errors="replace"))


if __name__ == "__main__":
    unittest.main()
