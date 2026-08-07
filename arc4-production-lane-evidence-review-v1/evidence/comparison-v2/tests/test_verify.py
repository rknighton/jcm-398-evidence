import unittest
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from harness.verify import (
    SELF_TESTS,
    SELF_TEST_PROGRESS_NAME,
    SELF_TEST_PROGRESS_TEMP_NAME,
    Rejected,
    _self_test_progress,
    canonical,
    file_sha,
    main,
    receipt,
    run_self_tests,
    verify_packet,
)
from tests.packet_fixture import build_packet


class VerifyTests(unittest.TestCase):
    def test_all_mutation_self_tests_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            passed, complete, progress = run_self_tests(build_packet(Path(directory)))
            self.assertEqual(len(SELF_TESTS), passed)
            self.assertTrue(complete)
            self.assertEqual(list(SELF_TESTS), progress["passed_tests"])

    def test_bounded_self_tests_resume_only_the_authenticated_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            packet = build_packet(Path(directory))
            result = verify_packet(packet)
            progress_path = packet / SELF_TEST_PROGRESS_NAME
            verifier_sha = file_sha(packet / "verify.py")
            selected = ("lane_identity", "case_identity")
            with patch("harness.verify.SELF_TESTS", selected):
                with patch("harness.verify.time.monotonic", side_effect=[0.0, 2.0]):
                    passed, complete, progress = run_self_tests(
                        packet,
                        base_result=result,
                        verifier_sha=verifier_sha,
                        progress_path=progress_path,
                        deadline=1.0,
                    )
                self.assertEqual(1, passed)
                self.assertFalse(complete)
                self.assertEqual(["lane_identity"], progress["passed_tests"])
                self.assertEqual("case_identity", progress["next_test"])
            verify_packet(packet)
            with patch("harness.verify.SELF_TESTS", selected):
                passed, complete, progress = run_self_tests(
                    packet,
                    base_result=result,
                    verifier_sha=verifier_sha,
                    progress_path=progress_path,
                )
            self.assertEqual(2, passed)
            self.assertTrue(complete)
            self.assertEqual(list(selected), progress["passed_tests"])

    def test_reordered_self_test_progress_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            packet = build_packet(Path(directory))
            result = verify_packet(packet)
            progress_path = packet / SELF_TEST_PROGRESS_NAME
            verifier_sha = file_sha(packet / "verify.py")
            selected = ("lane_identity", "case_identity")
            with patch("harness.verify.SELF_TESTS", selected):
                progress = _self_test_progress(
                    verifier_sha=verifier_sha,
                    manifest_sha=result["manifest_sha256"],
                    passed_tests=["lane_identity"],
                )
                progress["passed_tests"] = ["case_identity"]
                progress_path.write_bytes(canonical(progress))
                with self.assertRaises(Rejected) as context:
                    run_self_tests(
                        packet,
                        base_result=result,
                        verifier_sha=verifier_sha,
                        progress_path=progress_path,
                    )
            self.assertEqual("self_test_progress", context.exception.code)

    def test_cli_budget_preserves_receipt_and_completion_removes_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            packet = build_packet(Path(directory))
            receipt_path = packet / "verification.txt"
            receipt_path.write_text("prior receipt\n", encoding="utf-8", newline="\n")
            progress_temp_path = packet / SELF_TEST_PROGRESS_TEMP_NAME
            progress_temp_path.write_text("interrupted write\n", encoding="utf-8", newline="\n")
            partial = subprocess.run(
                [sys.executable, str(packet / "verify.py"), "--self-test", "--self-test-budget-seconds", "1e-9", "--write-receipt"],
                cwd=packet,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
            self.assertEqual(75, partial.returncode, partial.stderr.decode("utf-8", errors="replace"))
            self.assertEqual("prior receipt\n", receipt_path.read_text(encoding="utf-8"))
            self.assertFalse(progress_temp_path.exists())
            progress_path = packet / SELF_TEST_PROGRESS_NAME
            self.assertTrue(progress_path.is_file())

            result = verify_packet(packet)
            progress_path.write_bytes(canonical(_self_test_progress(
                verifier_sha=file_sha(packet / "verify.py"),
                manifest_sha=result["manifest_sha256"],
                passed_tests=SELF_TESTS,
            )))
            completed = subprocess.run(
                [sys.executable, str(packet / "verify.py"), "--self-test", "--write-receipt"],
                cwd=packet,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
            self.assertEqual(0, completed.returncode, completed.stderr.decode("utf-8", errors="replace"))
            value = json.loads(completed.stdout.decode("utf-8"))
            self.assertEqual(len(SELF_TESTS), value["self_tests_passed"])
            self.assertFalse(progress_path.exists())
            self.assertEqual(value, json.loads(receipt_path.read_text(encoding="utf-8")))

    def test_receipt_key_order_is_contract_order(self):
        value = receipt("rejected", verifier_sha="a" * 64, errors=["z", "a", "a"])
        self.assertEqual(
            ["schema", "status", "verifier_sha256", "manifest_sha256", "matrix_rows_observed", "matrix_rows_expected", "matrix_pairs_observed", "matrix_pairs_expected", "preflight_rows_observed", "preflight_rows_expected", "controls_passed", "controls_expected", "manifest_files_verified", "self_tests_passed", "self_tests_expected", "verdict", "error_codes"],
            list(value),
        )
        self.assertEqual("arc4.verification-receipt/v1", value["schema"])
        self.assertEqual(["a", "z"], value["error_codes"])

    def test_invalid_cli_returns_64_with_usage_receipt(self):
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--bogus"])
        stdout.flush()
        stdout.buffer.seek(0)
        value = json.loads(stdout.buffer.read().decode("utf-8"))
        self.assertEqual(64, code)
        self.assertEqual("usage_error", value["status"])

    def test_budget_without_self_test_returns_64(self):
        stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--self-test-budget-seconds", "1"])
        stdout.flush()
        stdout.buffer.seek(0)
        value = json.loads(stdout.buffer.read().decode("utf-8"))
        self.assertEqual(64, code)
        self.assertEqual(["invalid_cli"], value["error_codes"])


if __name__ == "__main__":
    unittest.main()
