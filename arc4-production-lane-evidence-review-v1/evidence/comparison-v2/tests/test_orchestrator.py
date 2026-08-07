import os
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from harness.orchestrator import RunLease, append_failure, commit_fragment, commit_pair_fragment, load_pair_fragment, run_worker
from harness.packet import normalize_failure_error_code
from harness.common import canonical_json_bytes, sha256_bytes
from harness.invocation import job_publication_path
from harness.worker_protocol import build_worker_rejection
from harness.worker import PROTOCOL_SELF_TEST_ENV
from tests.worker_fixtures import RUN_ID, successful_result, write_protocol_job


class OrchestratorTests(unittest.TestCase):
    @staticmethod
    def invoke(root: Path, name: str, *, timeout: int = 5, action: str = "success", error_code: str | None = None, popen=None):
        job_path, job = write_protocol_job(root, name=f"job-{name}", action=action, error_code=error_code)
        payload = job_path.read_bytes()
        publication = {"schema": "arc4.job-publication/v1", "path": str(job_path.resolve()), "sha256": sha256_bytes(payload), "bytes": len(payload)}
        job_publication_path(job_path).write_bytes(canonical_json_bytes(publication))
        interpreter = Path(sys.executable).resolve()
        lane_root = interpreter.parent.parent
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        environment[PROTOCOL_SELF_TEST_ENV] = "1"
        environment["PYTHONHASHSEED"] = "0"
        call = lambda: run_worker(
            [str(interpreter), "-m", "harness.worker"], attempt_root=root / name,
            timeout_seconds=timeout, run_id=RUN_ID, planned_row=job["planned_row"],
            attempt_n=1, methodology="initial", repair_reason=None, job_path=job_path,
            job_publication=publication, lane_root=lane_root,
            package_root=lane_root / "Lib" / "site-packages" / "jcodemunch_mcp",
            environment=environment,
        )
        if popen is None:
            return call()
        with mock.patch("harness.orchestrator.subprocess.Popen", side_effect=popen):
            return call()

    @staticmethod
    def pair_rows(attempt_n=1, methodology="initial", repair_reason=None):
        planned = [
            {"row_id": f"row-{lane}", "pair_id": "pair:windows:unsafe", "case_id": "case", "problem_id": "problem", "lane": lane, "arm": "matrix"}
            for lane in ("numpy_present", "numpy_absent")
        ]
        results = [
            {**row, "schema": "arc4.row-result/v1", "attempt_n": attempt_n, "attempt_methodology": methodology, "repair_reason": repair_reason}
            for row in planned
        ]
        return planned, results

    def test_worker_requires_exactly_one_structured_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.invoke(root, "attempt")
            self.assertEqual("row-fixture-numpy_present", result["row_id"])

    def test_worker_nonzero_preserves_each_structured_m9_rejection(self):
        categories = {
            "public_tool_error": "public_tool_error", "lane_mismatch": "lane_mismatch",
            "fallback_firing": "fallback_firing", "embed_write_tripwire_firing": "embed_write_tripwire_firing",
            "network_attempt": "infrastructure_failure", "generic_precondition": "failed_precondition",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (error_code, expected_category) in enumerate(categories.items()):
                with self.assertRaises(RuntimeError) as raised:
                    if error_code == "network_attempt":
                        self.invoke(root, f"attempt-{index}", action="network_connect")
                    else:
                        self.invoke(root, f"attempt-{index}", action="error", error_code=error_code)
                self.assertEqual(error_code, getattr(raised.exception, "code", None))
                classification = "infrastructure" if expected_category == "infrastructure_failure" else "product_lane"
                self.assertEqual(expected_category, normalize_failure_error_code("worker", classification, error_code))
                retained = json.loads((root / f"attempt-{index}" / "receipt.json").read_text(encoding="utf-8"))
                self.assertEqual(error_code, retained["rejection"]["error_code"])
                self.assertEqual(2, retained["returncode"])

    def test_worker_rejects_malformed_or_multiple_rejection_receipts(self):
        fixtures = (
            ("malformed", "import sys\nprint('not-json', file=sys.stderr)\nraise SystemExit(2)\n", "worker_rejection_json"),
            ("multiple", "import sys\nprint('{\"schema\":\"arc4.row-result/v1\",\"status\":\"rejected\",\"error_code\":\"a\"}', file=sys.stderr)\nprint('{\"schema\":\"arc4.row-result/v1\",\"status\":\"rejected\",\"error_code\":\"b\"}', file=sys.stderr)\nraise SystemExit(2)\n", "worker_rejection_count"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original_popen = __import__("subprocess").Popen
            for name, source, expected in fixtures:
                script = root / f"{name}.py"
                script.write_text(source, encoding="utf-8")
                def substitute(_command, *args, **kwargs):
                    return original_popen([sys.executable, str(script)], *args, **kwargs)
                with self.assertRaisesRegex(RuntimeError, expected):
                    self.invoke(root, name, popen=substitute)

    def test_timeout_is_a_rejection_and_process_is_reaped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "slow.py"
            script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
            original_popen = __import__("subprocess").Popen
            def substitute(_command, *args, **kwargs):
                if Path(_command[0]).name.lower() == "taskkill":
                    return original_popen(_command, *args, **kwargs)
                return original_popen([sys.executable, str(script)], *args, **kwargs)
            with self.assertRaisesRegex(RuntimeError, "worker_timeout"):
                self.invoke(root, "attempt", timeout=1, popen=substitute)

    def test_stale_lease_cannot_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease = RunLease(root, "token-a")
            lease.acquire()
            lease.path.write_text('{"schema":"arc4.run-lease/v1","token":"token-b"}\n', encoding="utf-8")
            row = {"row_id": "r", "pair_id": "p", "lane": "numpy_present", "arm": "matrix"}
            with self.assertRaisesRegex(RuntimeError, "stale_lease"):
                commit_fragment(lease=lease, result=row, expected_row=row, fragments_root=root / "fragments")

    def test_duplicate_wake_cannot_acquire_same_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = RunLease(root, "first")
            first.acquire()
            with self.assertRaisesRegex(RuntimeError, "lease_held"):
                RunLease(root, "second").acquire()

    def test_dead_exact_owner_is_recovered_without_deleting_lease_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stale = {
                "schema": "arc4.run-lease/v2", "run_id": "run",
                "owner": {"pid": os.getpid(), "creation_time": 1, "executable": str(Path(sys.executable).resolve())},
            }
            root.mkdir(exist_ok=True)
            (root / "lease.json").write_bytes(canonical_json_bytes(stale))
            lease = RunLease(root, "run")
            lease.acquire()
            try:
                self.assertEqual(stale["owner"], lease.recovered_owner)
                history = list((root / "lease-history").glob("*.json"))
                self.assertEqual(1, len(history))
                self.assertEqual(canonical_json_bytes(stale), history[0].read_bytes())
            finally:
                lease.release()

    def test_lease_rejects_malformed_noncanonical_and_wrong_run_owners(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.mkdir(exist_ok=True)
            live = RunLease(root, "live-other-run")
            live.acquire()
            live_bytes = live.path.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "lease_held"):
                RunLease(root, "requested-run").acquire()
            self.assertEqual(live_bytes, live.path.read_bytes())
            live.release()

            malformed = {"schema": "arc4.run-lease/v2", "run_id": "requested-run", "owner": {"pid": os.getpid(), "creation_time": 1, "executable": str(Path(sys.executable).resolve())}}
            (root / "lease.json").write_bytes(json.dumps(malformed, sort_keys=True).encode("utf-8"))
            with self.assertRaisesRegex(RuntimeError, "lease_canonical"):
                RunLease(root, "requested-run").acquire()
            (root / "lease.json").unlink()

            malformed_canonical = {"schema": "arc4.run-lease/v2", "run_id": "requested-run", "owner": {"pid": True, "creation_time": 1, "executable": str(Path(sys.executable).resolve())}}
            (root / "lease.json").write_bytes(canonical_json_bytes(malformed_canonical))
            with self.assertRaisesRegex(RuntimeError, "lease_owner_pid"):
                RunLease(root, "requested-run").acquire()
            self.assertEqual(canonical_json_bytes(malformed_canonical), (root / "lease.json").read_bytes())
            (root / "lease.json").unlink()

            stale_wrong_run = {**malformed, "run_id": "stale-other-run"}
            (root / "lease.json").write_bytes(canonical_json_bytes(stale_wrong_run))
            with self.assertRaisesRegex(RuntimeError, "lease_identity"):
                RunLease(root, "requested-run").acquire()
            self.assertEqual(canonical_json_bytes(stale_wrong_run), (root / "lease.json").read_bytes())

    def test_lease_process_observation_failure_is_nonwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stale = {
                "schema": "arc4.run-lease/v2", "run_id": "run",
                "owner": {"pid": os.getpid(), "creation_time": 1, "executable": str(Path(sys.executable).resolve())},
            }
            root.mkdir(exist_ok=True)
            path = root / "lease.json"
            path.write_bytes(canonical_json_bytes(stale))
            with mock.patch("harness.orchestrator._owner_is_current", side_effect=PermissionError("protected process")):
                with self.assertRaisesRegex(PermissionError, "protected process"):
                    RunLease(root, "run").acquire()
            self.assertEqual(canonical_json_bytes(stale), path.read_bytes())
            self.assertFalse((root / "lease-history").exists())

    def test_concurrent_stale_takeover_has_one_owner_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.mkdir(exist_ok=True)
            stale = {
                "schema": "arc4.run-lease/v2", "run_id": "run",
                "owner": {"pid": os.getpid(), "creation_time": 1, "executable": str(Path(sys.executable).resolve())},
            }
            (root / "lease.json").write_bytes(canonical_json_bytes(stale))
            contenders = [RunLease(root, "run"), RunLease(root, "run")]

            def acquire(lease):
                try:
                    lease.acquire()
                    return "acquired"
                except RuntimeError as exc:
                    return getattr(exc, "code", str(exc))

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(acquire, contenders))
            self.assertEqual(1, outcomes.count("acquired"), outcomes)
            self.assertEqual(1, len(list((root / "lease-history").glob("*.json"))))
            winner = contenders[outcomes.index("acquired")]
            winner.assert_current()
            winner.release()

    def test_duplicate_commit_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease = RunLease(root, "token")
            lease.acquire()
            row = {"row_id": "r", "pair_id": "p", "case_id": "c", "lane": "numpy_present", "arm": "matrix"}
            commit_fragment(lease=lease, result=row, expected_row=row, fragments_root=root / "fragments")
            with self.assertRaisesRegex(RuntimeError, "duplicate_commit"):
                commit_fragment(lease=lease, result=row, expected_row=row, fragments_root=root / "fragments")

    def test_concurrent_duplicate_commit_has_exactly_one_winner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease = RunLease(root, "token")
            lease.acquire()
            row = {"row_id": "r", "pair_id": "p", "case_id": "c", "lane": "numpy_present", "arm": "matrix"}
            def attempt():
                try:
                    commit_fragment(lease=lease, result=row, expected_row=row, fragments_root=root / "fragments")
                    return "committed"
                except RuntimeError as exc:
                    return str(exc)
            with ThreadPoolExecutor(max_workers=8) as pool:
                outcomes = list(pool.map(lambda _index: attempt(), range(8)))
            self.assertEqual(1, outcomes.count("committed"), outcomes)
            self.assertEqual(7, sum(value.startswith("duplicate_commit:") for value in outcomes), outcomes)

    def test_pair_commit_rejects_incomplete_and_mixed_attempt_fragments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease = RunLease(root, "token")
            lease.acquire()
            planned, results = self.pair_rows(attempt_n=2, methodology="explicit_repair", repair_reason="declared")
            with self.assertRaisesRegex(RuntimeError, "pair_commit_rows"):
                commit_pair_fragment(lease=lease, results=results[:1], expected_rows=planned, attempt_n=2, methodology="explicit_repair", repair_reason="declared", fragments_root=root / "fragments")
            results[1]["attempt_n"] = 3
            with self.assertRaisesRegex(RuntimeError, "pair_commit_attempt"):
                commit_pair_fragment(lease=lease, results=results, expected_rows=planned, attempt_n=2, methodology="explicit_repair", repair_reason="declared", fragments_root=root / "fragments")

    def test_pair_commit_is_windows_safe_atomic_and_no_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease = RunLease(root, "token")
            lease.acquire()
            planned, results = self.pair_rows()
            def attempt():
                try:
                    path = commit_pair_fragment(lease=lease, results=results, expected_rows=planned, attempt_n=1, methodology="initial", repair_reason=None, fragments_root=root / "fragments")
                    return "committed", path
                except RuntimeError as exc:
                    return str(exc), None
            with ThreadPoolExecutor(max_workers=8) as pool:
                outcomes = list(pool.map(lambda _index: attempt(), range(8)))
            winners = [item for item in outcomes if item[0] == "committed"]
            self.assertEqual(1, len(winners), outcomes)
            self.assertEqual(7, sum(item[0].startswith("duplicate_pair_commit:") for item in outcomes), outcomes)
            self.assertEqual("pair:windows:unsafe", load_pair_fragment(winners[0][1])["pair_id"])

    def test_post_publication_temp_cleanup_failure_does_not_undo_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease = RunLease(root, "token")
            lease.acquire()
            planned, results = self.pair_rows()
            original_unlink = Path.unlink

            def injected_unlink(path, *args, **kwargs):
                if path.name.endswith(".tmp"):
                    raise PermissionError("injected post-link cleanup failure")
                return original_unlink(path, *args, **kwargs)

            with mock.patch.object(Path, "unlink", new=injected_unlink):
                committed = commit_pair_fragment(
                    lease=lease, results=results, expected_rows=planned, attempt_n=1,
                    methodology="initial", repair_reason=None, fragments_root=root / "fragments",
                )
            self.assertEqual("pair:windows:unsafe", load_pair_fragment(committed)["pair_id"])
            self.assertEqual(1, len(list((root / "fragments").glob("*.json"))))
            self.assertFalse((root / "FAILURE-JOURNAL.jsonl").exists())
            with self.assertRaisesRegex(RuntimeError, "duplicate_pair_commit"):
                commit_pair_fragment(
                    lease=lease, results=results, expected_rows=planned, attempt_n=1,
                    methodology="initial", repair_reason=None, fragments_root=root / "fragments",
                )
            lease.release()

    def test_failure_producer_rejects_bool_attempt_wrong_run_and_rowless_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lease = RunLease(root, "run")
            lease.acquire()
            base = {
                "schema": "arc4.failure/v1", "stage": "setup", "classification": "infrastructure",
                "error_code": "infrastructure_failure", "reason": "fixture", "attempt_n": 1,
                "row_identity": {"run_id": "run", "row_id": None, "pair_id": None, "case_id": None, "problem_id": None, "arm": None, "lane": None},
                "methodology": "initial", "evidence": {"cause_error_code": "fixture"},
            }
            try:
                pair_level = {**base, "stage": "commit", "row_identity": {"run_id": "run", "row_id": None, "pair_id": "pair", "case_id": "case", "problem_id": "problem", "arm": "matrix", "lane": None}}
                append_failure(lease=lease, journal=root / "pair.jsonl", record=pair_level)
                for name, mutate, expected in (
                    ("bool", lambda value: value.__setitem__("attempt_n", True), "attempt_number"),
                    ("run", lambda value: value["row_identity"].__setitem__("run_id", "wrong"), "failure_run_id"),
                    ("repair", lambda value: (value.__setitem__("attempt_n", 2), value.__setitem__("methodology", "explicit_repair")), "rowless_failure_semantics"),
                ):
                    record = json.loads(json.dumps(base))
                    mutate(record)
                    with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, expected):
                        append_failure(lease=lease, journal=root / f"{name}.jsonl", record=record)
            finally:
                lease.release()


if __name__ == "__main__":
    unittest.main()
