from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


class ContractError(RuntimeError):
    """A fail-closed contract rejection with a stable machine code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ContractError(code, message)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=False
    )


def canonical_json_bytes(value: Any) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def strict_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key", key)
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            return json.load(stream, object_pairs_hook=strict_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("invalid_json", f"{path}: {exc}") from exc


def load_jsonl(path: Path, *, expected_schema: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ContractError("jsonl_read_failed", f"{path}: {exc}") from exc
    require(not raw.startswith(b"\xef\xbb\xbf"), "jsonl_bom", str(path))
    require(not raw or raw.endswith(b"\n"), "jsonl_missing_final_lf", str(path))
    require(b"\r" not in raw, "jsonl_non_lf_ending", str(path))
    for number, line in enumerate(raw.splitlines(), 1):
        require(bool(line), "jsonl_blank_line", f"{path}:{number}")
        try:
            value = json.loads(line, object_pairs_hook=strict_object)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ContractError("jsonl_invalid", f"{path}:{number}: {exc}") from exc
        require(isinstance(value, dict), "jsonl_not_object", f"{path}:{number}")
        require(line + b"\n" == canonical_json_bytes(value), "jsonl_noncanonical", f"{path}:{number}")
        rows.append(value)
    if expected_schema is not None:
        require(bool(rows), "jsonl_empty", str(path))
        require(rows[0] == {"schema": expected_schema}, "jsonl_schema", str(path))
    return rows


def exact_keys(value: Mapping[str, Any], keys: Iterable[str], code: str) -> None:
    expected = set(keys)
    actual = set(value)
    require(actual == expected, code, f"missing={sorted(expected-actual)} unknown={sorted(actual-expected)}")


def ensure_finite_scores(scores: Mapping[str, float]) -> None:
    require(all(isinstance(k, str) and k for k in scores), "invalid_symbol_id", "IDs must be nonempty strings")
    require(all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in scores.values()), "nonfinite_score", "score vector contains a non-finite or non-numeric value")


def safe_relative_path(root: Path, candidate: Path) -> Path:
    def normalized(path: Path) -> Path:
        value = str(path.resolve())
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return Path(value)

    root_resolved = normalized(root)
    candidate_resolved = normalized(candidate)
    try:
        return candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ContractError("path_outside_root", f"{candidate_resolved} is outside {root_resolved}") from exc


def atomic_write(path: Path, data: bytes, *, allowed_root: Path) -> None:
    safe_relative_path(allowed_root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    safe_relative_path(allowed_root, temporary)
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def atomic_write_new(path: Path, data: bytes, *, allowed_root: Path) -> None:
    """Atomically publish bytes only when the destination does not exist."""

    safe_relative_path(allowed_root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    published = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
            published = True
        except FileExistsError as exc:
            raise ContractError("destination_exists", str(path)) from exc
    finally:
        cleanup_error: BaseException | None = None
        for _attempt in range(3):
            try:
                temporary.unlink(missing_ok=True)
                cleanup_error = None
                break
            except BaseException as exc:
                cleanup_error = exc
        if cleanup_error is not None and not published:
            raise cleanup_error


def iter_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_file():
            yield path


def tree_hashes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha256_file(path) for path in iter_files(root)}
