import base64
import csv
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from harness.common import canonical_json_bytes
from harness import p0
from harness.p0 import RECORD_PATH, _run_bounded, compare_wheels, generate_and_write_source_build_receipt, generate_source_build_receipt, read_wheel, validate_p0_receipt, validate_source_build_receipt


def compare_fixture(official: Path, rebuilt: Path):
    digest = hashlib.sha256(official.read_bytes()).hexdigest()
    with mock.patch("harness.p0.OFFICIAL_WHEEL_SHA256", digest):
        return compare_wheels(official, rebuilt, tool_sha256="f" * 64)


def make_wheel(path: Path, members: dict[str, bytes], *, corrupt_record: bool = False):
    rows = []
    for name, payload in members.items():
        encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
        rows.append((name, f"sha256={encoded}", str(len(payload))))
    rows.append((RECORD_PATH, "", ""))
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(rows)
    record = stream.getvalue().encode()
    if corrupt_record:
        record = record.replace(b"sha256=", b"sha512=", 1)
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
        archive.writestr(RECORD_PATH, record)


class P0Tests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows Job Object constructor semantics")
    def test_job_constructor_owns_handle_before_configuration_and_retries_close(self):
        native = mock.Mock()
        native.CreateJobObjectW = mock.Mock(return_value=123)
        native.SetInformationJobObject = mock.Mock(return_value=0)
        native.AssignProcessToJobObject = mock.Mock(return_value=1)
        native.TerminateJobObject = mock.Mock(return_value=1)
        native.CloseHandle = mock.Mock(side_effect=[0, 0, 0, 1])
        observed: list[tuple[str, int | None, object | None]] = []
        original_cleanup = p0._cleanup_with_retries

        def observed_cleanup(action, stage, errors, attempts=3):
            if stage in {"configure_close", "configure_force_close"}:
                tree = getattr(action, "__self__", None)
                observed.append((stage, 123 if tree is None else tree.handle, native if tree is None else tree.kernel32))
            return original_cleanup(action, stage, errors, attempts)

        with mock.patch("harness.p0.ctypes.WinDLL", return_value=native), mock.patch(
            "harness.p0._cleanup_with_retries", side_effect=observed_cleanup
        ):
            with self.assertRaisesRegex(RuntimeError, "bounded_job_configure") as raised:
                p0._OwnedProcessTree()
        self.assertEqual([("configure_close", 123, native), ("configure_force_close", 123, native)], observed)
        self.assertEqual(4, native.CloseHandle.call_count)
        self.assertIn("bounded_job_close", str(raised.exception))

    def _build_receipt(self, wheel: Path, tool: Path) -> dict:
        interpreter = Path(sys.executable).resolve()
        checkout = wheel.parent / "detached"
        checkout.mkdir(exist_ok=True)
        home = wheel.parent / "home"
        environment = {
            "SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"), "ComSpec": os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe"),
            "TEMP": str(wheel.parent / "temp"), "TMP": str(wheel.parent / "temp"), "USERPROFILE": str(home), "HOME": str(home),
            "HOMEDRIVE": "C:", "HOMEPATH": r"\home", "PATH": str(interpreter.parent),
            "PYTHONNOUSERSITE": "1", "PYTHONHASHSEED": "0", "PYTHONUTF8": "1", "PIP_NO_INDEX": "1",
        }
        tool_hash = hashlib.sha256(tool.read_bytes()).hexdigest()
        return {
            "schema": "arc4.source-build-receipt/v2", "source_commit": "8bed872e9436093be9f89d35fb84e0cb58a293af",
            "git": {"head": "8bed872e9436093be9f89d35fb84e0cb58a293af", "clean": True, "detached": True, "core_autocrlf": "false", "status_sha256": hashlib.sha256(b"").hexdigest()},
            "python": {"implementation": "CPython", "version": "3.13.7", "cache_tag": "cpython-313", "executable": str(interpreter), "executable_sha256": hashlib.sha256(interpreter.read_bytes()).hexdigest()},
            "build": {"backend": "hatchling", "backend_version": "1.31.0", "command": [str(interpreter), "-m", "build", "--wheel", "--no-isolation", "--outdir", str(checkout / "dist"), "."], "cwd": str(checkout), "environment": environment},
            "produced_wheel": {"path": str(wheel), "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()},
            "comparison_tool_sha256": tool_hash, "generator_sha256": tool_hash,
        }

    def test_source_build_receipt_binds_clean_detached_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "rebuilt.whl"
            wheel.write_bytes(b"fixture")
            tool = Path(__file__).resolve().parents[1] / "harness" / "p0.py"
            receipt = self._build_receipt(wheel, tool)
            digest = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
            validate_source_build_receipt(receipt, receipt_sha256=digest, rebuilt_wheel=wheel, comparison_tool=tool)

    def test_source_build_receipt_rejects_attested_or_wrong_git_state(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "rebuilt.whl"
            wheel.write_bytes(b"fixture")
            tool = Path(__file__).resolve().parents[1] / "harness" / "p0.py"
            receipt = self._build_receipt(wheel, tool)
            receipt["git"]["clean"] = False
            digest = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
            with self.assertRaisesRegex(RuntimeError, "source_build_git_state"):
                validate_source_build_receipt(receipt, receipt_sha256=digest, rebuilt_wheel=wheel, comparison_tool=tool)
            receipt["git"]["clean"] = True
            receipt["attested"] = True
            digest = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
            with self.assertRaisesRegex(RuntimeError, "source_build_receipt_keys"):
                validate_source_build_receipt(receipt, receipt_sha256=digest, rebuilt_wheel=wheel, comparison_tool=tool)

    def test_source_build_receipt_rejects_wrong_interpreter_and_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "rebuilt.whl"
            wheel.write_bytes(b"fixture")
            tool = Path(__file__).resolve().parents[1] / "harness" / "p0.py"
            receipt = self._build_receipt(wheel, tool)
            receipt["build"]["command"][0] = str(wheel)
            digest = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
            with self.assertRaisesRegex(RuntimeError, "source_build_command_shape"):
                validate_source_build_receipt(receipt, receipt_sha256=digest, rebuilt_wheel=wheel, comparison_tool=tool)
            receipt = self._build_receipt(wheel, tool)
            receipt["build"]["cwd"] = str(Path(directory) / "missing-checkout")
            digest = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
            with self.assertRaisesRegex(RuntimeError, "source_build_cwd"):
                validate_source_build_receipt(receipt, receipt_sha256=digest, rebuilt_wheel=wheel, comparison_tool=tool)

    def test_generator_observes_real_clean_detached_git_and_owns_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "checkout"
            checkout.mkdir()
            for command in (["git", "init", "-q"], ["git", "config", "user.email", "arc4@example.invalid"], ["git", "config", "user.name", "Arc4"], ["git", "config", "core.autocrlf", "false"]):
                subprocess.run(command, cwd=checkout, check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            (checkout / "source.txt").write_text("source\n", encoding="utf-8", newline="\n")
            subprocess.run(["git", "add", "source.txt"], cwd=checkout, check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=checkout, check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout, check=True, timeout=10, text=True, stdout=subprocess.PIPE).stdout.strip()
            subprocess.run(["git", "checkout", "-q", "--detach", commit], cwd=checkout, check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            output = root / "dist"
            interpreter = Path(sys.executable).resolve()
            def fake_build(command, *, cwd, environment, timeout_seconds):
                self.assertEqual(checkout.resolve(), cwd)
                self.assertEqual(str(interpreter), command[0])
                output.mkdir(parents=True, exist_ok=True)
                (output / "fixture.whl").write_bytes(b"wheel")
            python_observation = {"implementation": "CPython", "version": "3.13.7", "cache_tag": "cpython-313", "executable": str(interpreter), "backend_version": "1.31.0"}
            tool = Path(__file__).resolve().parents[1] / "harness" / "p0.py"
            with mock.patch("harness.p0.SOURCE_COMMIT", commit), mock.patch("harness.p0._observe_python", return_value=python_observation), mock.patch("harness.p0._execute_build", side_effect=fake_build):
                receipt = generate_source_build_receipt(checkout=checkout, python_executable=interpreter, output_directory=output, comparison_tool=tool)
            self.assertEqual(commit, receipt["git"]["head"])
            self.assertEqual(hashlib.sha256(b"").hexdigest(), receipt["git"]["status_sha256"])
            self.assertEqual(str(interpreter), receipt["build"]["command"][0])

    def test_generator_rejects_fabricated_tagged_or_dirty_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "checkout"
            checkout.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=checkout, check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=checkout, check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            (checkout / "untracked.txt").write_text("dirty\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "bounded_command_exit|source_build_git_observation"):
                generate_source_build_receipt(checkout=checkout, python_executable=Path(sys.executable), output_directory=root / "dist", comparison_tool=Path(__file__).resolve().parents[1] / "harness" / "p0.py")

    def test_generator_writer_atomically_retains_canonical_receipt_and_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = root / "dist" / "rebuilt.whl"
            wheel.parent.mkdir()
            wheel.write_bytes(b"fixture")
            tool = Path(__file__).resolve().parents[1] / "harness" / "p0.py"
            receipt = self._build_receipt(wheel, tool)
            receipt_path = root / "packet" / "source-build.json"
            digest_path = root / "packet" / "source-build.sha256"
            with mock.patch("harness.p0.generate_source_build_receipt", return_value=receipt):
                observed, digest = generate_and_write_source_build_receipt(
                    checkout=Path(receipt["build"]["cwd"]), python_executable=Path(sys.executable),
                    output_directory=wheel.parent, comparison_tool=tool, receipt_path=receipt_path,
                    digest_path=digest_path, allowed_root=root / "packet",
                )
            self.assertEqual(receipt, observed)
            self.assertEqual(canonical_json_bytes(receipt), receipt_path.read_bytes())
            self.assertEqual((digest + "\n").encode("ascii"), digest_path.read_bytes())

    @unittest.skipUnless(os.name == "nt", "Windows Job Object semantics")
    def test_bounded_runner_timeout_terminates_owned_child_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "child-survived.txt"
            child = f"import time;from pathlib import Path;time.sleep(2);Path({str(marker)!r}).write_text('survived')"
            parent = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(30)"
            with self.assertRaisesRegex(RuntimeError, "bounded_command_timeout"):
                _run_bounded([sys.executable, "-c", parent], cwd=root, timeout_seconds=1, max_output_bytes=4096, log_path=root / "timeout.log")
            import time
            time.sleep(2.5)
            self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == "nt", "Windows suspended launch semantics")
    def test_bounded_runner_assigns_job_before_process_can_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "started.txt"
            original_assign = __import__("harness.p0", fromlist=["_OwnedProcessTree"])._OwnedProcessTree.assign
            def delayed_assign(tree, process):
                import time
                time.sleep(0.5)
                self.assertFalse(marker.exists())
                return original_assign(tree, process)
            script = f"from pathlib import Path;Path({str(marker)!r}).write_text('started')"
            with mock.patch("harness.p0._OwnedProcessTree.assign", new=delayed_assign):
                _run_bounded([sys.executable, "-c", script], cwd=root, timeout_seconds=5, max_output_bytes=1024, log_path=root / "suspended.log")
            self.assertTrue(marker.exists())

    @unittest.skipUnless(os.name == "nt", "Windows Job Object semantics")
    def test_bounded_runner_output_cap_terminates_tree_and_bounds_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "child-survived.txt"
            log = root / "bounded.log"
            child = f"import time;from pathlib import Path;time.sleep(2);Path({str(marker)!r}).write_text('survived')"
            parent = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);print('x'*200000,flush=True);time.sleep(30)"
            with self.assertRaisesRegex(RuntimeError, "bounded_command_output"):
                _run_bounded([sys.executable, "-c", parent], cwd=root, timeout_seconds=10, max_output_bytes=1024, log_path=log)
            import time
            time.sleep(2.5)
            self.assertLessEqual(log.stat().st_size, 1024)
            self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == "nt", "Windows Job Object failure injection")
    def test_bounded_runner_assign_failure_closes_handles_and_never_resumes_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "assign-child-ran.txt"
            script = f"from pathlib import Path;Path({str(marker)!r}).write_text('ran')"
            trees = []
            original_init = p0._OwnedProcessTree.__init__

            def observed_init(tree):
                original_init(tree)
                trees.append(tree)

            with mock.patch.object(p0._OwnedProcessTree, "__init__", observed_init), mock.patch.object(
                p0._OwnedProcessTree, "assign", side_effect=RuntimeError("injected assign")
            ):
                with self.assertRaisesRegex(RuntimeError, "injected assign"):
                    _run_bounded([sys.executable, "-c", script], cwd=root, timeout_seconds=5, log_path=root / "assign.log")
            time.sleep(0.25)
            self.assertFalse(marker.exists())
            self.assertEqual([None], [tree.handle for tree in trees])

    @unittest.skipUnless(os.name == "nt", "Windows Job Object failure injection")
    def test_bounded_runner_resume_failure_kills_assigned_child_and_closes_handles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "resume-child-ran.txt"
            script = f"from pathlib import Path;Path({str(marker)!r}).write_text('ran')"
            trees = []
            original_init = p0._OwnedProcessTree.__init__

            def observed_init(tree):
                original_init(tree)
                trees.append(tree)

            with mock.patch.object(p0._OwnedProcessTree, "__init__", observed_init), mock.patch.object(
                p0._OwnedProcessTree, "resume", side_effect=RuntimeError("injected resume")
            ):
                with self.assertRaisesRegex(RuntimeError, "injected resume"):
                    _run_bounded([sys.executable, "-c", script], cwd=root, timeout_seconds=5, log_path=root / "resume.log")
            time.sleep(0.25)
            self.assertFalse(marker.exists())
            self.assertEqual([None], [tree.handle for tree in trees])

    @unittest.skipUnless(os.name == "nt", "Windows Job Object failure injection")
    def test_bounded_runner_preserves_transient_terminate_wait_and_close_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "cleanup-child-survived.txt"
            child = f"import time;from pathlib import Path;time.sleep(2);Path({str(marker)!r}).write_text('survived')"
            parent = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(30)"
            trees = []
            original_init = p0._OwnedProcessTree.__init__
            original_terminate = p0._OwnedProcessTree.terminate
            original_close = p0._OwnedProcessTree.close
            original_wait = subprocess.Popen.wait
            calls = {"terminate": 0, "wait": 0, "close": 0}

            def observed_init(tree):
                original_init(tree)
                trees.append(tree)

            def flaky_terminate(tree, process):
                calls["terminate"] += 1
                if calls["terminate"] == 1:
                    raise RuntimeError("injected terminate")
                return original_terminate(tree, process)

            def flaky_wait(process, *args, **kwargs):
                calls["wait"] += 1
                if calls["wait"] == 1:
                    raise RuntimeError("injected wait")
                return original_wait(process, *args, **kwargs)

            def flaky_close(tree):
                calls["close"] += 1
                if calls["close"] == 1:
                    raise RuntimeError("injected close")
                return original_close(tree)

            with mock.patch.object(p0._OwnedProcessTree, "__init__", observed_init), mock.patch.object(
                p0._OwnedProcessTree, "terminate", flaky_terminate
            ), mock.patch.object(p0._OwnedProcessTree, "close", flaky_close), mock.patch.object(
                subprocess.Popen, "wait", flaky_wait
            ):
                with self.assertRaisesRegex(RuntimeError, "bounded_cleanup_failure") as raised:
                    _run_bounded([sys.executable, "-c", parent], cwd=root, timeout_seconds=1, log_path=root / "cleanup.log")
            message = str(raised.exception)
            self.assertIn("injected terminate", message)
            self.assertIn("injected wait", message)
            self.assertIn("injected close", message)
            time.sleep(2.5)
            self.assertFalse(marker.exists())
            self.assertEqual([None], [tree.handle for tree in trees])

    @unittest.skipUnless(os.name == "nt", "Windows Job Object failure injection")
    def test_bounded_runner_force_closes_job_after_persistent_wrapper_close_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "persistent-close-child.txt"
            child = f"import time;from pathlib import Path;time.sleep(2);Path({str(marker)!r}).write_text('survived')"
            parent = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(30)"
            trees = []
            original_init = p0._OwnedProcessTree.__init__

            def observed_init(tree):
                original_init(tree)
                trees.append(tree)

            with mock.patch.object(p0._OwnedProcessTree, "__init__", observed_init), mock.patch.object(
                p0._OwnedProcessTree, "close", side_effect=RuntimeError("persistent wrapper close failure")
            ):
                with self.assertRaisesRegex(RuntimeError, "bounded_cleanup_failure") as raised:
                    _run_bounded([sys.executable, "-c", parent], cwd=root, timeout_seconds=1, log_path=root / "persistent-close.log")
            self.assertIn("persistent wrapper close failure", str(raised.exception))
            time.sleep(2.5)
            self.assertFalse(marker.exists())
            self.assertEqual([None], [tree.handle for tree in trees])

    def test_newline_only_payload_difference_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            official, rebuilt = root / "official.whl", root / "rebuilt.whl"
            make_wheel(official, {"pkg/a.py": b"x=1\r\n"})
            make_wheel(rebuilt, {"pkg/a.py": b"x=1\n"})
            result = compare_fixture(official, rebuilt)
            self.assertEqual("passed", result["status"])
            self.assertEqual(["pkg/a.py"], result["raw_differences"])
            self.assertEqual([], result["normalized_payload_differences"])

    def test_substantive_difference_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            official, rebuilt = root / "official.whl", root / "rebuilt.whl"
            make_wheel(official, {"pkg/a.py": b"x=1\n"})
            make_wheel(rebuilt, {"pkg/a.py": b"x=2\n"})
            self.assertEqual("rejected", compare_fixture(official, rebuilt)["status"])

    def test_record_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            official, rebuilt = root / "official.whl", root / "rebuilt.whl"
            make_wheel(official, {"pkg/a.py": b"x=1\n"}, corrupt_record=True)
            make_wheel(rebuilt, {"pkg/a.py": b"x=1\n"})
            with self.assertRaisesRegex(RuntimeError, "record_hash_kind"):
                compare_fixture(official, rebuilt)

    def test_record_digest_must_be_exact_unpadded_urlsafe_sha256(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "official.whl"
            make_wheel(wheel, {"pkg/a.py": b"x=1\n"})
            members = read_wheel(wheel)
            record = members[RECORD_PATH].replace(b"sha256=", b"sha256=A", 1)
            members[RECORD_PATH] = record
            with self.assertRaisesRegex(RuntimeError, "record_hash_grammar"):
                from harness.p0 import validate_record
                validate_record(members)

    def test_traversal_member_rejects_before_path_set(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "bad.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("../escape", b"x")
            with self.assertRaisesRegex(RuntimeError, "zip_traversal"):
                read_wheel(wheel)

    def test_receipt_is_closed_and_tool_hash_is_non_null(self):
        receipt = {
            "schema": "arc4.p0-wheel-comparison/v1", "status": "passed", "official_sha256": "f" * 64,
            "rebuilt_sha256": "e" * 64, "comparison_tool_sha256": None, "official_member_count": 1,
            "rebuilt_member_count": 1, "excluded_member": RECORD_PATH, "missing_members": [], "extra_members": [],
            "raw_differences": [], "normalized_payload_differences": [],
            "official_record": {"schema": "arc4.official-record-validation/v1", "status": "valid", "row_count": 1},
            "normalization": "utf8_text_newlines_only_crlf_or_cr_to_lf",
            "claim_ceiling": "payload_equivalence_under_declared_newline_normalization_only",
            "does_not_establish": ["bit_reproducible_build", "publisher_build_environment", "end_to_end_supply_chain_authenticity"],
        }
        with mock.patch("harness.p0.OFFICIAL_WHEEL_SHA256", "f" * 64), self.assertRaisesRegex(RuntimeError, "p0_hash_fields"):
            validate_p0_receipt(receipt)
        receipt["comparison_tool_sha256"] = "d" * 64
        receipt["attested"] = True
        with self.assertRaisesRegex(RuntimeError, "p0_receipt_keys"):
            validate_p0_receipt(receipt)


if __name__ == "__main__":
    unittest.main()
