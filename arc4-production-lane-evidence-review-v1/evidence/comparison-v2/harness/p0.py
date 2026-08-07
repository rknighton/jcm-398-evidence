from __future__ import annotations

import argparse
import base64
import ctypes
import csv
import io
import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
import zipfile
from ctypes import wintypes
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .common import ContractError, atomic_write, canonical_json_bytes, exact_keys, require, sha256_bytes, sha256_file

SCHEMA = "arc4.p0-wheel-comparison/v1"
RECORD_PATH = "jcodemunch_mcp-1.108.228.dist-info/RECORD"
OFFICIAL_WHEEL_SHA256 = "ff74b6344430053c6fad9064892d6a3904ffba6265823e3fba4dfde78f9a0488"
CLAIM_CEILING = "payload_equivalence_under_declared_newline_normalization_only"
DECIMAL = re.compile(r"0|[1-9][0-9]*\Z")
DIGEST = re.compile(r"[A-Za-z0-9_-]{43}\Z")
HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RECEIPT_KEYS = (
    "schema", "status", "official_sha256", "rebuilt_sha256", "comparison_tool_sha256",
    "official_member_count", "rebuilt_member_count", "excluded_member", "missing_members",
    "extra_members", "raw_differences", "normalized_payload_differences", "official_record",
    "normalization", "claim_ceiling", "does_not_establish",
)
SOURCE_COMMIT = "8bed872e9436093be9f89d35fb84e0cb58a293af"
BUILD_RECEIPT_KEYS = (
    "schema", "source_commit", "git", "python", "build", "produced_wheel",
    "comparison_tool_sha256", "generator_sha256",
)
EMPTY_SHA256 = sha256_bytes(b"")


class _JobBasicLimits(ctypes.Structure):
    _fields_ = (("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD))


class _IoCounters(ctypes.Structure):
    _fields_ = (("ReadOperationCount", ctypes.c_ulonglong), ("WriteOperationCount", ctypes.c_ulonglong), ("OtherOperationCount", ctypes.c_ulonglong), ("ReadTransferCount", ctypes.c_ulonglong), ("WriteTransferCount", ctypes.c_ulonglong), ("OtherTransferCount", ctypes.c_ulonglong))


class _JobExtendedLimits(ctypes.Structure):
    _fields_ = (("BasicLimitInformation", _JobBasicLimits), ("IoInfo", _IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t))


class _OwnedProcessTree:
    """Own one subprocess tree. Closing the Windows job kills every descendant."""

    def __init__(self) -> None:
        self.handle: int | None = None
        self.kernel32: Any | None = None
        if os.name == "nt":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
            kernel32.SetInformationJobObject.restype = wintypes.BOOL
            kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
            kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
            kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
            kernel32.TerminateJobObject.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.CreateJobObjectW(None, None)
            require(bool(handle), "bounded_job_create", str(ctypes.get_last_error()))
            self.kernel32 = kernel32
            self.handle = int(handle)
            limits = _JobExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x00002000
            ok = kernel32.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            if not ok:
                configure_error = ctypes.get_last_error()
                cleanup_errors: list[dict[str, str]] = []
                closed = _cleanup_with_retries(self.close, "configure_close", cleanup_errors)
                if not closed and self.handle is not None:
                    _cleanup_with_retries(lambda: _force_close_job_handle(self), "configure_force_close", cleanup_errors, attempts=8)
                detail = {"configure_error": str(configure_error), "cleanup_errors": cleanup_errors}
                require(self.handle is None, "bounded_job_configure_cleanup", json.dumps(detail, sort_keys=True, separators=(",", ":")))
                raise ContractError("bounded_job_configure", json.dumps(detail, sort_keys=True, separators=(",", ":")))

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        if self.handle is not None:
            assert self.kernel32 is not None
            ok = self.kernel32.AssignProcessToJobObject(wintypes.HANDLE(self.handle), wintypes.HANDLE(int(process._handle)))
            require(bool(ok), "bounded_job_assign", str(ctypes.get_last_error()))

    def resume(self, process: subprocess.Popen[bytes]) -> None:
        if self.handle is not None:
            ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
            ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
            ntdll.NtResumeProcess.restype = ctypes.c_long
            status = ntdll.NtResumeProcess(wintypes.HANDLE(int(process._handle)))
            require(status == 0, "bounded_process_resume", hex(status & 0xFFFFFFFF))

    def terminate(self, process: subprocess.Popen[bytes]) -> None:
        if self.handle is not None:
            assert self.kernel32 is not None
            require(bool(self.kernel32.TerminateJobObject(wintypes.HANDLE(self.handle), 1)), "bounded_job_terminate", str(ctypes.get_last_error()))
        elif process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)

    def close(self) -> None:
        if self.handle is not None:
            assert self.kernel32 is not None
            require(bool(self.kernel32.CloseHandle(wintypes.HANDLE(self.handle))), "bounded_job_close", str(ctypes.get_last_error()))
            self.handle = None


def _failure_detail(exc: BaseException) -> dict[str, str]:
    return {"type": type(exc).__name__, "code": str(getattr(exc, "code", "exception")), "message": str(exc)}


def _close_process_handle(process: subprocess.Popen[bytes]) -> None:
    if os.name != "nt":
        return
    handle = getattr(process, "_handle", None)
    if handle is None:
        return
    handle.Close()
    process._handle = None


def _force_close_job_handle(tree: _OwnedProcessTree) -> None:
    if tree.handle is None:
        return
    require(tree.kernel32 is not None, "bounded_job_close_state", str(tree.handle))
    identity = tree.handle
    require(bool(tree.kernel32.CloseHandle(wintypes.HANDLE(identity))), "bounded_job_force_close", f"handle={identity} error={ctypes.get_last_error()}")
    tree.handle = None


def _cleanup_with_retries(action: Any, stage: str, errors: list[dict[str, str]], attempts: int = 3) -> bool:
    for ordinal in range(1, attempts + 1):
        try:
            action()
            return True
        except BaseException as exc:
            errors.append({"stage": stage, "attempt": str(ordinal), **_failure_detail(exc)})
    return False


def _run_bounded(
    command: Sequence[str], *, cwd: Path, environment: Mapping[str, str] | None = None,
    timeout_seconds: int = 900, allowed_exit_codes: tuple[int, ...] = (0,),
    max_output_bytes: int = 65536, log_path: Path | None = None,
) -> tuple[int, bytes, bytes]:
    require(bool(command) and all(isinstance(item, str) and item for item in command), "bounded_command_shape", str(command))
    require(isinstance(timeout_seconds, int) and timeout_seconds >= 1 and isinstance(max_output_bytes, int) and max_output_bytes >= 1, "bounded_command_limits", f"timeout={timeout_seconds} output={max_output_bytes}")
    temporary = tempfile.TemporaryDirectory(prefix="arc4-p0-command-") if log_path is None else None
    retained_log = (Path(temporary.name) / "command.log") if temporary is not None else Path(log_path).resolve()
    retained_log.parent.mkdir(parents=True, exist_ok=True)
    tree: _OwnedProcessTree | None = None
    process: subprocess.Popen[bytes] | None = None
    log: Any | None = None
    reader: threading.Thread | None = None
    output_exceeded = threading.Event()
    reader_errors: list[str] = []
    total_output = 0
    result: tuple[int, bytes, bytes] | None = None
    primary: BaseException | None = None
    try:
        tree = _OwnedProcessTree()
        log = retained_log.open("xb")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if os.name == "nt":
            creationflags |= getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
        process = subprocess.Popen(
            list(command), cwd=cwd, env=None if environment is None else dict(environment), shell=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=creationflags, start_new_session=os.name != "nt",
        )
        tree.assign(process)
        tree.resume(process)

        def drain() -> None:
            nonlocal total_output
            try:
                assert process is not None and process.stdout is not None and log is not None
                while True:
                    chunk = process.stdout.read(8192)
                    if not chunk:
                        break
                    remaining = max(0, max_output_bytes - total_output)
                    if remaining:
                        log.write(chunk[:remaining])
                        log.flush()
                    total_output += len(chunk)
                    if total_output > max_output_bytes:
                        output_exceeded.set()
            except Exception as exc:
                reader_errors.append(f"{type(exc).__name__}:{exc}")

        reader = threading.Thread(target=drain, name="arc4-p0-output", daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout_seconds
        failure_code: str | None = None
        while process.poll() is None:
            if output_exceeded.is_set():
                failure_code = "bounded_command_output"
                break
            if time.monotonic() >= deadline:
                failure_code = "bounded_command_timeout"
                break
            time.sleep(0.01)
        if failure_code == "bounded_command_output":
            raise ContractError(failure_code, f"output exceeded {max_output_bytes} bytes; receipt {retained_log}")
        if failure_code == "bounded_command_timeout":
            raise ContractError(failure_code, f"command exceeded {timeout_seconds} seconds; receipt {retained_log}")
        process.wait(timeout=30)
        reader.join(timeout=30)
        require(not reader.is_alive(), "bounded_output_reader", "output reader did not terminate")
        require(not reader_errors, "bounded_output_reader", ";".join(reader_errors))
        require(process.returncode in allowed_exit_codes, "bounded_command_exit", f"exit {process.returncode}; receipt {retained_log}")
        log.flush()
        payload = retained_log.read_bytes()
        require(len(payload) <= max_output_bytes, "bounded_command_output", f"receipt {retained_log}")
        result = int(process.returncode), payload, b""
    except BaseException as exc:
        primary = exc

    cleanup_errors: list[dict[str, str]] = []
    if process is not None:
        running = True
        try:
            running = process.poll() is None
        except BaseException as exc:
            cleanup_errors.append({"stage": "poll", "attempt": "1", **_failure_detail(exc)})
        if running:
            if tree is not None:
                _cleanup_with_retries(lambda: tree.terminate(process), "terminate_job", cleanup_errors)
            _cleanup_with_retries(lambda: process.kill() if process.poll() is None else None, "terminate_process", cleanup_errors)
        _cleanup_with_retries(lambda: process.wait(timeout=30), "wait", cleanup_errors)
    if reader is not None:
        _cleanup_with_retries(lambda: reader.join(timeout=30), "reader_join", cleanup_errors)
        if reader.is_alive():
            cleanup_errors.append({"stage": "reader_join", "attempt": "final", "type": "RuntimeError", "code": "bounded_output_reader", "message": "reader still alive"})
    if process is not None and process.stdout is not None and not process.stdout.closed:
        _cleanup_with_retries(process.stdout.close, "stdout_close", cleanup_errors)
    if log is not None and not log.closed:
        _cleanup_with_retries(log.close, "log_close", cleanup_errors)
    if process is not None:
        _cleanup_with_retries(lambda: _close_process_handle(process), "process_handle_close", cleanup_errors)
    if tree is not None:
        closed = _cleanup_with_retries(tree.close, "job_handle_close", cleanup_errors)
        if not closed and tree.handle is not None:
            _cleanup_with_retries(lambda: _force_close_job_handle(tree), "job_handle_force_close", cleanup_errors, attempts=8)
    if temporary is not None:
        _cleanup_with_retries(temporary.cleanup, "temporary_cleanup", cleanup_errors)
    if primary is not None or cleanup_errors:
        if cleanup_errors:
            detail = {"primary": _failure_detail(primary) if primary is not None else None, "cleanup": cleanup_errors}
            raise ContractError("bounded_cleanup_failure", json.dumps(detail, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) from primary
        assert primary is not None
        raise primary
    assert result is not None
    return result


def _build_environment(python_executable: Path, output_root: Path) -> dict[str, str]:
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve()
    temp = (output_root / "temp").resolve()
    home = (output_root / "home").resolve()
    temp.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    drive, tail = os.path.splitdrive(str(home))
    if not drive:
        drive = system_root.drive or "C:"
        tail = str(home)
    return {
        "SystemRoot": str(system_root),
        "ComSpec": str(system_root / "System32" / "cmd.exe"),
        "TEMP": str(temp), "TMP": str(temp),
        "USERPROFILE": str(home), "HOME": str(home),
        "HOMEDRIVE": drive, "HOMEPATH": tail,
        "PATH": os.pathsep.join((str(python_executable.parent), str(system_root / "System32"))),
        "PYTHONNOUSERSITE": "1", "PYTHONHASHSEED": "0", "PYTHONUTF8": "1",
        "PIP_NO_INDEX": "1",
    }


def _execute_build(command: Sequence[str], *, cwd: Path, environment: Mapping[str, str], timeout_seconds: int) -> None:
    _run_bounded(command, cwd=cwd, environment=environment, timeout_seconds=timeout_seconds, log_path=Path(environment["TEMP"]).parent / "build.log")


def _observe_python(python_executable: Path, checkout: Path) -> dict[str, str]:
    probe = (
        "import importlib.metadata,json,platform,sys;"
        "print(json.dumps({'implementation':platform.python_implementation(),'version':platform.python_version(),"
        "'cache_tag':sys.implementation.cache_tag,'executable':sys.executable,"
        "'backend_version':importlib.metadata.version('hatchling')},separators=(',',':')))"
    )
    return json.loads(_run_bounded([str(python_executable), "-I", "-c", probe], cwd=checkout, timeout_seconds=30)[1].decode("utf-8"))


def generate_source_build_receipt(
    *, checkout: Path, python_executable: Path, output_directory: Path,
    comparison_tool: Path, timeout_seconds: int = 900,
) -> dict[str, Any]:
    """Observe and execute the bounded clean detached build. No state assertion is accepted as input."""
    checkout = checkout.resolve()
    python_executable = python_executable.resolve()
    output_directory = output_directory.resolve()
    comparison_tool = comparison_tool.resolve()
    require(checkout.is_dir() and python_executable.is_file() and comparison_tool.is_file(), "source_build_inputs", "checkout, interpreter, and tool must exist")
    top = _run_bounded(["git", "-C", str(checkout), "rev-parse", "--show-toplevel"], cwd=checkout, timeout_seconds=30)[1].decode("utf-8").strip()
    require(Path(top).resolve() == checkout, "source_build_checkout_root", top)
    head = _run_bounded(["git", "-C", str(checkout), "rev-parse", "HEAD"], cwd=checkout, timeout_seconds=30)[1].decode("ascii").strip()
    status = _run_bounded(["git", "-C", str(checkout), "status", "--porcelain=v1", "--untracked-files=normal"], cwd=checkout, timeout_seconds=30)[1]
    symbolic_code, symbolic, _ = _run_bounded(["git", "-C", str(checkout), "symbolic-ref", "-q", "HEAD"], cwd=checkout, timeout_seconds=30, allowed_exit_codes=(0, 1))
    autocrlf = _run_bounded(["git", "-C", str(checkout), "config", "--get", "core.autocrlf"], cwd=checkout, timeout_seconds=30)[1].decode("ascii").strip()
    require(head == SOURCE_COMMIT and status == b"" and symbolic_code == 1 and symbolic == b"" and autocrlf == "false", "source_build_git_observation", "checkout is not the exact clean detached tagged commit")
    python_data = _observe_python(python_executable, checkout)
    observed_executable = Path(python_data["executable"]).resolve()
    require(observed_executable == python_executable, "source_build_python_observation", str(observed_executable))
    require(python_data["implementation"] == "CPython" and python_data["version"] == "3.13.7" and python_data["cache_tag"] == "cpython-313" and python_data["backend_version"] == "1.31.0", "source_build_python_environment", str(python_data))
    require(not output_directory.exists() or not any(output_directory.iterdir()), "source_build_output_not_empty", str(output_directory))
    output_directory.mkdir(parents=True, exist_ok=True)
    environment = _build_environment(python_executable, output_directory.parent / "build-runtime")
    command = [str(python_executable), "-m", "build", "--wheel", "--no-isolation", "--outdir", str(output_directory), "."]
    _execute_build(command, cwd=checkout, environment=environment, timeout_seconds=timeout_seconds)
    wheels = sorted(output_directory.glob("*.whl"), key=lambda path: path.name)
    require(len(wheels) == 1 and wheels[0].is_file(), "source_build_output_wheel", f"observed {len(wheels)} wheels")
    wheel = wheels[0].resolve()
    tool_hash = sha256_file(comparison_tool)
    return {
        "schema": "arc4.source-build-receipt/v2", "source_commit": head,
        "git": {"head": head, "clean": True, "detached": True, "core_autocrlf": autocrlf, "status_sha256": sha256_bytes(status)},
        "python": {"implementation": python_data["implementation"], "version": python_data["version"], "cache_tag": python_data["cache_tag"], "executable": str(python_executable), "executable_sha256": sha256_file(python_executable)},
        "build": {"backend": "hatchling", "backend_version": python_data["backend_version"], "command": command, "cwd": str(checkout), "environment": environment},
        "produced_wheel": {"path": str(wheel), "sha256": sha256_file(wheel)},
        "comparison_tool_sha256": tool_hash, "generator_sha256": sha256_file(Path(__file__).resolve()),
    }


def generate_and_write_source_build_receipt(
    *, checkout: Path, python_executable: Path, output_directory: Path,
    comparison_tool: Path, receipt_path: Path, digest_path: Path,
    allowed_root: Path, timeout_seconds: int = 900,
) -> tuple[dict[str, Any], str]:
    """Own generation and atomically retain its canonical receipt and stable digest."""
    allowed_root = allowed_root.resolve()
    receipt_path = receipt_path.resolve()
    digest_path = digest_path.resolve()
    require(receipt_path != digest_path, "source_build_receipt_paths", "receipt and digest paths must differ")
    for path in (receipt_path, digest_path):
        try:
            path.relative_to(allowed_root)
        except ValueError as exc:
            raise ContractError("source_build_receipt_scope", str(path)) from exc
    receipt = generate_source_build_receipt(
        checkout=checkout, python_executable=python_executable,
        output_directory=output_directory, comparison_tool=comparison_tool,
        timeout_seconds=timeout_seconds,
    )
    payload = canonical_json_bytes(receipt)
    digest = sha256_bytes(payload)
    atomic_write(receipt_path, payload, allowed_root=allowed_root)
    atomic_write(digest_path, (digest + "\n").encode("ascii"), allowed_root=allowed_root)
    require(receipt_path.read_bytes() == payload and digest_path.read_bytes() == (digest + "\n").encode("ascii"), "source_build_receipt_retention", str(receipt_path))
    return receipt, digest


def _safe_name(name: str) -> None:
    require(bool(name), "zip_empty_path", "empty ZIP member path")
    require("\\" not in name, "zip_backslash", name)
    require(not name.startswith("/"), "zip_absolute", name)
    path = PurePosixPath(name)
    require(not path.is_absolute() and all(part not in ("", ".", "..") for part in path.parts), "zip_traversal", name)
    require(path.as_posix() == name, "zip_noncanonical_path", name)


def read_wheel(path: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                _safe_name(info.filename)
                require(not info.is_dir() and not info.filename.endswith("/"), "zip_directory_entry", info.filename)
                require(info.filename not in result, "zip_duplicate_member", info.filename)
                result[info.filename] = archive.read(info)
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("wheel_read_failed", f"{path}: {exc}") from exc
    return result


def validate_record(members: Mapping[str, bytes]) -> dict[str, Any]:
    require(RECORD_PATH in members, "record_missing", RECORD_PATH)
    try:
        text = members[RECORD_PATH].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("record_utf8", str(exc)) from exc
    rows: dict[str, tuple[str, str]] = {}
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        for number, row in enumerate(reader, 1):
            require(len(row) == 3, "record_field_count", f"row {number}")
            name, hash_field, size_field = row
            _safe_name(name)
            require(name not in rows, "record_duplicate_path", name)
            rows[name] = (hash_field, size_field)
    except csv.Error as exc:
        raise ContractError("record_csv", str(exc)) from exc
    require(set(rows) == set(members), "record_path_set", f"missing={sorted(set(members)-set(rows))} extra={sorted(set(rows)-set(members))}")
    for name, (hash_field, size_field) in rows.items():
        if name == RECORD_PATH:
            require(hash_field == "" and size_field == "", "record_self_fields", name)
            continue
        require(hash_field.startswith("sha256="), "record_hash_kind", name)
        encoded = hash_field[7:]
        require(DIGEST.fullmatch(encoded) is not None, "record_hash_grammar", name)
        try:
            decoded = base64.urlsafe_b64decode(encoded + "=")
        except (ValueError, base64.binascii.Error) as exc:
            raise ContractError("record_hash_encoding", name) from exc
        canonical_digest = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
        require(len(decoded) == 32 and canonical_digest == encoded and decoded.hex() == sha256_bytes(members[name]), "record_hash_mismatch", name)
        require(DECIMAL.fullmatch(size_field) is not None, "record_size_spelling", name)
        require(int(size_field) == len(members[name]), "record_size_mismatch", name)
    return {"schema": "arc4.official-record-validation/v1", "status": "valid", "row_count": len(rows)}


def _normalized_text(left: bytes, right: bytes) -> tuple[bytes, bytes]:
    if b"\x00" in left or b"\x00" in right:
        return left, right
    try:
        left_text = left.decode("utf-8")
        right_text = right.decode("utf-8")
    except UnicodeDecodeError:
        return left, right
    normalize = lambda value: value.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    return normalize(left_text), normalize(right_text)


def compare_wheels(official: Path, rebuilt: Path, *, tool_sha256: str | None = None) -> dict[str, Any]:
    require(isinstance(tool_sha256, str) and HEX_SHA256.fullmatch(tool_sha256) is not None, "comparison_tool_hash", "a lowercase SHA-256 is required")
    official_sha256 = sha256_file(official)
    require(official_sha256 == OFFICIAL_WHEEL_SHA256, "official_wheel_hash", official_sha256)
    official_members = read_wheel(official)
    rebuilt_members = read_wheel(rebuilt)
    record = validate_record(official_members)
    missing = sorted(set(official_members) - set(rebuilt_members))
    extra = sorted(set(rebuilt_members) - set(official_members))
    raw_differences: list[str] = []
    normalized_differences: list[str] = []
    for name in sorted(set(official_members) & set(rebuilt_members)):
        if name == RECORD_PATH:
            continue
        left = official_members[name]
        right = rebuilt_members[name]
        if left != right:
            raw_differences.append(name)
        normalized_left, normalized_right = _normalized_text(left, right)
        if normalized_left != normalized_right:
            normalized_differences.append(name)
    passed = not missing and not extra and not normalized_differences
    receipt = {
        "schema": SCHEMA,
        "status": "passed" if passed else "rejected",
        "official_sha256": official_sha256,
        "rebuilt_sha256": sha256_file(rebuilt),
        "comparison_tool_sha256": tool_sha256,
        "official_member_count": len(official_members),
        "rebuilt_member_count": len(rebuilt_members),
        "excluded_member": RECORD_PATH,
        "missing_members": missing,
        "extra_members": extra,
        "raw_differences": raw_differences,
        "normalized_payload_differences": normalized_differences,
        "official_record": record,
        "normalization": "utf8_text_newlines_only_crlf_or_cr_to_lf",
        "claim_ceiling": CLAIM_CEILING,
        "does_not_establish": [
            "bit_reproducible_build",
            "publisher_build_environment",
            "end_to_end_supply_chain_authenticity",
        ],
    }
    validate_p0_receipt(receipt, require_pass=False)
    return receipt


def validate_p0_receipt(receipt: Mapping[str, Any], *, require_pass: bool = True) -> None:
    exact_keys(receipt, RECEIPT_KEYS, "p0_receipt_keys")
    require(receipt["schema"] == SCHEMA, "p0_schema", str(receipt["schema"]))
    require(receipt["status"] in ("passed", "rejected"), "p0_status", str(receipt["status"]))
    require(receipt["official_sha256"] == OFFICIAL_WHEEL_SHA256, "p0_official_hash", str(receipt["official_sha256"]))
    require(all(isinstance(receipt[key], str) and HEX_SHA256.fullmatch(receipt[key]) is not None for key in ("rebuilt_sha256", "comparison_tool_sha256")), "p0_hash_fields", "rebuilt and tool hashes must be lowercase SHA-256")
    require(all(isinstance(receipt[key], int) and not isinstance(receipt[key], bool) and receipt[key] >= 0 for key in ("official_member_count", "rebuilt_member_count")), "p0_member_counts", "nonnegative integers required")
    require(receipt["excluded_member"] == RECORD_PATH, "p0_excluded_member", str(receipt["excluded_member"]))
    require(all(isinstance(receipt[key], list) and all(isinstance(item, str) for item in receipt[key]) and receipt[key] == sorted(set(receipt[key])) for key in ("missing_members", "extra_members", "raw_differences", "normalized_payload_differences")), "p0_difference_lists", "difference lists must be sorted unique strings")
    exact_keys(receipt["official_record"], ("schema", "status", "row_count"), "p0_record_keys")
    require(receipt["official_record"]["schema"] == "arc4.official-record-validation/v1" and receipt["official_record"]["status"] == "valid", "p0_record_status", str(receipt["official_record"]))
    require(receipt["official_record"]["row_count"] == receipt["official_member_count"], "p0_record_count", "RECORD must cover every official member")
    require(receipt["normalization"] == "utf8_text_newlines_only_crlf_or_cr_to_lf", "p0_normalization", str(receipt["normalization"]))
    require(receipt["claim_ceiling"] == CLAIM_CEILING, "p0_claim_ceiling", str(receipt["claim_ceiling"]))
    require(receipt["does_not_establish"] == ["bit_reproducible_build", "publisher_build_environment", "end_to_end_supply_chain_authenticity"], "p0_noncoverage", str(receipt["does_not_establish"]))
    passed = not receipt["missing_members"] and not receipt["extra_members"] and not receipt["normalized_payload_differences"] and receipt["official_member_count"] == receipt["rebuilt_member_count"]
    require((receipt["status"] == "passed") is passed, "p0_status_invariants", "status does not match substantive comparison")
    if require_pass:
        require(passed, "p0_gate", "zero-difference invariants did not pass")


def validate_source_build_receipt(
    receipt: Mapping[str, Any], *, receipt_sha256: str, rebuilt_wheel: Path,
    comparison_tool: Path,
) -> None:
    """Validate an immutable, independently observed clean tagged-source rebuild receipt."""
    exact_keys(receipt, BUILD_RECEIPT_KEYS, "source_build_receipt_keys")
    require(receipt["schema"] == "arc4.source-build-receipt/v2", "source_build_receipt_schema", str(receipt.get("schema")))
    require(receipt["source_commit"] == SOURCE_COMMIT, "source_build_commit", str(receipt.get("source_commit")))
    exact_keys(receipt["git"], ("head", "clean", "detached", "core_autocrlf", "status_sha256"), "source_build_git_keys")
    require(receipt["git"] == {"head": SOURCE_COMMIT, "clean": True, "detached": True, "core_autocrlf": "false", "status_sha256": EMPTY_SHA256}, "source_build_git_state", str(receipt["git"]))
    exact_keys(receipt["python"], ("implementation", "version", "cache_tag", "executable", "executable_sha256"), "source_build_python_keys")
    require(receipt["python"]["implementation"] == "CPython" and receipt["python"]["version"] == "3.13.7" and receipt["python"]["cache_tag"] == "cpython-313", "source_build_python", str(receipt["python"]))
    require(HEX_SHA256.fullmatch(str(receipt["python"]["executable_sha256"])) is not None, "source_build_python_hash", str(receipt["python"]["executable_sha256"]))
    interpreter = Path(str(receipt["python"]["executable"])).resolve()
    require(interpreter.is_file() and sha256_file(interpreter) == receipt["python"]["executable_sha256"], "source_build_python_file", str(interpreter))
    exact_keys(receipt["build"], ("backend", "backend_version", "command", "cwd", "environment"), "source_build_command_keys")
    require(receipt["build"]["backend"] == "hatchling" and receipt["build"]["backend_version"] == "1.31.0", "source_build_backend", str(receipt["build"]))
    command = receipt["build"]["command"]
    require(isinstance(command, list) and all(isinstance(item, str) and item for item in command), "source_build_command", str(command))
    require(Path(command[0]).resolve() == interpreter and command[1:5] == ["-m", "build", "--wheel", "--no-isolation"], "source_build_command_shape", str(command))
    checkout = Path(str(receipt["build"]["cwd"])).resolve()
    require(checkout.is_dir(), "source_build_cwd", str(receipt["build"]["cwd"]))
    environment = receipt["build"]["environment"]
    require(isinstance(environment, dict) and set(environment) == {"SystemRoot", "ComSpec", "TEMP", "TMP", "USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH", "PATH", "PYTHONNOUSERSITE", "PYTHONHASHSEED", "PYTHONUTF8", "PIP_NO_INDEX"}, "source_build_environment_keys", str(environment))
    require(environment["PYTHONNOUSERSITE"] == "1" and environment["PYTHONHASHSEED"] == "0" and environment["PYTHONUTF8"] == "1" and environment["PIP_NO_INDEX"] == "1", "source_build_environment", str(environment))
    exact_keys(receipt["produced_wheel"], ("path", "sha256"), "source_build_wheel_keys")
    require(Path(receipt["produced_wheel"]["path"]).resolve() == rebuilt_wheel.resolve(), "source_build_wheel_path", str(receipt["produced_wheel"]["path"]))
    require(rebuilt_wheel.is_file() and receipt["produced_wheel"]["sha256"] == sha256_file(rebuilt_wheel), "source_build_wheel_hash", str(rebuilt_wheel))
    require(receipt["comparison_tool_sha256"] == sha256_file(comparison_tool), "source_build_tool_hash", str(receipt["comparison_tool_sha256"]))
    require(receipt["generator_sha256"] == sha256_file(Path(__file__).resolve()) == receipt["comparison_tool_sha256"], "source_build_generator_hash", str(receipt["generator_sha256"]))
    require(HEX_SHA256.fullmatch(receipt_sha256) is not None and receipt_sha256 == sha256_bytes(canonical_json_bytes(dict(receipt))), "source_build_receipt_hash", receipt_sha256)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("official", type=Path)
    compare_parser.add_argument("rebuilt", type=Path)
    compare_parser.add_argument("--output", type=Path)
    build_parser = subparsers.add_parser("build-receipt")
    build_parser.add_argument("--checkout", type=Path, required=True)
    build_parser.add_argument("--python", type=Path, required=True)
    build_parser.add_argument("--output-directory", type=Path, required=True)
    build_parser.add_argument("--comparison-tool", type=Path, required=True)
    build_parser.add_argument("--receipt", type=Path, required=True)
    build_parser.add_argument("--digest", type=Path, required=True)
    build_parser.add_argument("--allowed-root", type=Path, required=True)
    build_parser.add_argument("--timeout-seconds", type=int, default=900)
    ns = parser.parse_args(argv)
    try:
        if ns.command == "build-receipt":
            receipt, digest = generate_and_write_source_build_receipt(
                checkout=ns.checkout, python_executable=ns.python,
                output_directory=ns.output_directory, comparison_tool=ns.comparison_tool,
                receipt_path=ns.receipt, digest_path=ns.digest,
                allowed_root=ns.allowed_root, timeout_seconds=ns.timeout_seconds,
            )
            result = {
                "schema": "arc4.source-build-command/v1", "status": "passed",
                "receipt": str(ns.receipt.resolve()), "receipt_sha256": digest,
                "produced_wheel": receipt["produced_wheel"],
            }
            print(canonical_json_bytes(result).decode("utf-8"), end="")
            return 0
        receipt = compare_wheels(ns.official, ns.rebuilt, tool_sha256=sha256_file(Path(__file__)))
        payload = canonical_json_bytes(receipt)
        if ns.output:
            atomic_write(ns.output, payload, allowed_root=Path.cwd())
        else:
            print(payload.decode("utf-8"), end="")
        return 0 if receipt["status"] == "passed" else 2
    except ContractError as exc:
        print(canonical_json_bytes({"schema": SCHEMA, "status": "rejected", "error_code": exc.code}).decode(), end="")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
