"""Build, verify, audit, or install the Arc 4 prepared-index release asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO


HERE = Path(__file__).resolve().parent
PREPARED_INPUTS = HERE / "prepared-inputs.json"
CONFIG = HERE / "research_config.json"
TRACKED_MANIFEST = HERE / "release-asset-manifest.json"
ASSET_NAME = "arc4-real-embedding-indexes-v1.zip"
CHECKSUM_NAME = "arc4-real-embedding-indexes-v1.sha256"
OUTER_MANIFEST_NAME = "arc4-real-embedding-indexes-v1.manifest.json"
FORBIDDEN_LOCAL_MARKERS = (
    "C:\\Users\\Admin",
    "C:/Users/Admin",
    "\\.code-index\\",
    "/.code-index/",
)
LICENSE_FILES = {
    "licenses/django-LICENSE.txt": HERE / "licenses" / "django-LICENSE.txt",
    "licenses/fastapi-LICENSE.txt": HERE / "licenses" / "fastapi-LICENSE.txt",
}


class AssetError(RuntimeError):
    """Raised when an asset violates the release contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_stream(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical_json_bytes(value))


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def load_inputs() -> dict[str, Any]:
    value = json.loads(PREPARED_INPUTS.read_text(encoding="utf-8"))
    if value.get("release_asset") != ASSET_NAME:
        raise AssetError("prepared-inputs.json names a different release asset")
    return value


def audit_database(
    path: Path,
    expected: dict[str, Any],
    *,
    expected_hash: str | None = None,
    allow_local_meta_paths: bool = False,
) -> dict[str, Any]:
    if not path.is_file():
        raise AssetError(f"database is missing: {path}")
    actual_hash = sha256_file(path)
    required_hash = expected_hash or expected["working_database_sha256"]
    if actual_hash != required_hash:
        raise AssetError(f"database hash mismatch: {path.name}")
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise AssetError(f"SQLite integrity check failed for {path.name}: {integrity}")
        vector_count = int(
            connection.execute("SELECT COUNT(*) FROM symbol_embeddings").fetchone()[0]
        )
        if vector_count != int(expected["embedding_vector_count"]):
            raise AssetError(f"embedding count mismatch: {path.name}")
        dimensions = connection.execute(
            "SELECT MIN(length(embedding)), MAX(length(embedding)) FROM symbol_embeddings"
        ).fetchone()
        expected_bytes = 4 * int(expected["embedding_meta"]["embed_dimension"])
        if tuple(dimensions) != (expected_bytes, expected_bytes):
            raise AssetError(f"embedding blob width mismatch: {path.name}")

        local_hits: list[dict[str, str]] = []
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            if not row[0].startswith("sqlite_")
        ]
        for table in tables:
            columns = connection.execute(
                f"PRAGMA table_info({quote_identifier(table)})"
            ).fetchall()
            for _index, column, declared_type, *_rest in columns:
                if "BLOB" in (declared_type or "").upper():
                    continue
                for marker in FORBIDDEN_LOCAL_MARKERS:
                    sql = (
                        f"SELECT 1 FROM {quote_identifier(table)} "
                        f"WHERE instr(CAST({quote_identifier(column)} AS TEXT), ?) > 0 LIMIT 1"
                    )
                    if connection.execute(sql, (marker,)).fetchone() is not None:
                        local_hits.append(
                            {"table": table, "column": column, "marker": marker}
                        )
        unexpected_hits = [
            hit
            for hit in local_hits
            if not (
                allow_local_meta_paths
                and hit["table"] == "meta"
                and hit["column"] == "value"
            )
        ]
        if unexpected_hits:
            raise AssetError(
                f"machine-local path marker found in {path.name}: {unexpected_hits}"
            )
        return {
            "sha256": actual_hash,
            "size": path.stat().st_size,
            "sqlite_integrity": integrity,
            "embedding_vector_count": vector_count,
            "embedding_blob_bytes": expected_bytes,
            "local_path_scan": "PASS" if not local_hits else "REQUIRES_META_REDACTION",
            "local_meta_path_markers": sorted(
                {hit["marker"] for hit in local_hits}
            ),
        }
    finally:
        connection.close()


def expected_databases(inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name, record in inputs["corpora"].items():
        if not record["license"]["release_included"]:
            continue
        filename = record["database_filename"]
        if Path(filename).name != filename or filename in result:
            raise AssetError(f"unsafe or duplicate database filename: {filename}")
        result[filename] = {"corpus": name, **record}
    return result


def internal_manifest(inputs: dict[str, Any], audits: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": inputs["schema_version"],
        "asset": ASSET_NAME,
        "release_tag": inputs["release_tag"],
        "format": "zip-with-prepared-jcodemunch-sqlite-indexes",
        "embedding_provider": inputs["embedding_provider"],
        "embedding_model": inputs["embedding_model"],
        "measured_config_sha256": inputs["measured_config_sha256"],
        "measured_harness_sha256": inputs["measured_harness_sha256"],
        "databases": audits,
        "coverage": inputs["release_coverage"],
        "license_files": {
            name: {"sha256": sha256_file(path), "size": path.stat().st_size}
            for name, path in sorted(LICENSE_FILES.items())
        },
    }


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def copy_zip_member(archive: zipfile.ZipFile, name: str, source: Path) -> None:
    with source.open("rb") as input_handle, archive.open(zip_info(name), "w") as output:
        shutil.copyfileobj(input_handle, output, length=1024 * 1024)


def sanitize_release_database(
    source: Path, destination: Path, expected: dict[str, Any]
) -> dict[str, Any]:
    source_audit = audit_database(
        source, expected, allow_local_meta_paths=True
    )
    shutil.copy2(source, destination)
    connection = sqlite3.connect(destination)
    try:
        for marker in FORBIDDEN_LOCAL_MARKERS:
            connection.execute(
                "UPDATE meta SET value = replace(value, ?, '<redacted-local-root>') "
                "WHERE instr(value, ?) > 0",
                (marker, marker),
            )
        connection.commit()
    finally:
        connection.close()
    release_hash = sha256_file(destination)
    release_audit = audit_database(
        destination, expected, expected_hash=release_hash
    )
    return {
        **release_audit,
        "measured_working_database_sha256": source_audit["sha256"],
        "release_database_sha256": release_hash,
        "metadata_path_transformation": {
            "table": "meta",
            "column": "value",
            "replacement": "<redacted-local-root>",
            "source_marker_count": len(source_audit["local_meta_path_markers"]),
            "source_marker_class": "measured Windows user-profile path",
        },
    }


def build(index_dir: Path, output_dir: Path) -> dict[str, Any]:
    inputs = load_inputs()
    databases = expected_databases(inputs)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "archive": output_dir / ASSET_NAME,
        "checksum": output_dir / CHECKSUM_NAME,
        "manifest": output_dir / OUTER_MANIFEST_NAME,
    }
    existing = [str(path) for path in paths.values() if path.exists()]
    if existing:
        raise AssetError(f"refusing to overwrite existing release files: {existing}")

    audits: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="arc4-release-databases-") as temporary_name:
        temporary = Path(temporary_name)
        sources: dict[str, Path] = {}
        for filename, expected in sorted(databases.items()):
            release_copy = temporary / filename
            audits[filename] = {
                **expected,
                **sanitize_release_database(index_dir / filename, release_copy, expected),
            }
            sources[filename] = release_copy
        inside = internal_manifest(inputs, audits)
        with zipfile.ZipFile(
            paths["archive"], "w", allowZip64=True, compresslevel=9
        ) as archive:
            archive.writestr(zip_info("manifest.json"), canonical_json_bytes(inside))
            for filename, source in sorted(sources.items()):
                copy_zip_member(archive, f"indexes/{filename}", source)
            for name, source in sorted(LICENSE_FILES.items()):
                if not source.is_file():
                    raise AssetError(f"license notice is missing: {source}")
                copy_zip_member(archive, name, source)

    archive_hash = sha256_file(paths["archive"])
    outer = {
        **inside,
        "archive": {
            "name": ASSET_NAME,
            "sha256": archive_hash,
            "size": paths["archive"].stat().st_size,
        },
        "publication_state": "local-draft-not-published",
    }
    write_json(paths["manifest"], outer)
    write_json(TRACKED_MANIFEST, outer)
    paths["checksum"].write_text(
        f"{archive_hash}  {ASSET_NAME}\n", encoding="ascii", newline="\n"
    )
    result = verify_archive(paths["archive"])
    result["output_dir"] = str(output_dir.resolve())
    return result


def safe_member(name: str) -> bool:
    value = PurePosixPath(name)
    return bool(name) and not value.is_absolute() and ".." not in value.parts


def verify_archive(archive_path: Path) -> dict[str, Any]:
    inputs = load_inputs()
    expected = expected_databases(inputs)
    if archive_path.name != ASSET_NAME:
        raise AssetError(f"unexpected asset filename: {archive_path.name}")
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or not all(safe_member(name) for name in names):
            raise AssetError("archive contains duplicate or unsafe member names")
        required = {
            "manifest.json",
            *(f"indexes/{name}" for name in expected),
            *LICENSE_FILES,
        }
        if set(names) != required:
            raise AssetError(f"archive member mismatch: {sorted(names)}")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("asset") != ASSET_NAME:
            raise AssetError("internal manifest asset mismatch")
        for filename, record in expected.items():
            manifest_record = manifest["databases"][filename]
            if (
                manifest_record["measured_working_database_sha256"]
                != record["working_database_sha256"]
            ):
                raise AssetError(f"manifest measured database hash mismatch: {filename}")
            with archive.open(f"indexes/{filename}", "r") as handle:
                if sha256_stream(handle) != manifest_record["sha256"]:
                    raise AssetError(f"archive database hash mismatch: {filename}")
        for name, source in LICENSE_FILES.items():
            record = manifest["license_files"][name]
            if record["sha256"] != sha256_file(source):
                raise AssetError(f"license manifest mismatch: {name}")
            with archive.open(name, "r") as handle:
                if sha256_stream(handle) != record["sha256"]:
                    raise AssetError(f"archive license hash mismatch: {name}")
    return {
        "status": "PASS",
        "archive": str(archive_path.resolve()),
        "archive_sha256": sha256_file(archive_path),
        "database_count": len(expected),
        "embedding_vector_count": sum(
            int(item["embedding_vector_count"]) for item in expected.values()
        ),
    }


def install(archive_path: Path, destination: Path) -> dict[str, Any]:
    result = verify_archive(archive_path)
    if destination.exists():
        raise AssetError(f"refusing to overwrite existing destination: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    inputs = load_inputs()
    expected = expected_databases(inputs)
    with zipfile.ZipFile(archive_path, "r") as archive:
        manifest = json.loads(archive.read("manifest.json"))
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}-install-", dir=destination.parent)
    )
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            for filename in sorted(expected):
                target = temporary / filename
                with archive.open(f"indexes/{filename}", "r") as source, target.open(
                    "wb"
                ) as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                audit_database(
                    target,
                    expected[filename],
                    expected_hash=manifest["databases"][filename]["sha256"],
                )
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    from run_research import _harness_identity
    from arc4lib import config_identity

    preparation = {
        "status": "installed-from-release-asset",
        "config_sha256": config_identity(CONFIG),
        "harness_sha256": _harness_identity(),
        "baseline_identity": inputs["baseline_identity"],
        "baseline_root": "<provided-at-run-time>",
        "baseline_import_root": "<provided-at-run-time>/src",
        "embedding_provider": inputs["embedding_provider"],
        "embedding_model": inputs["embedding_model"],
        "queries": inputs["queries"],
        "corpora": {},
        "asset_sha256": result["archive_sha256"],
    }
    for corpus, record in inputs["corpora"].items():
        if not record["license"]["release_included"]:
            continue
        preparation["corpora"][corpus] = {
            "source_database_sha256": record["source_database_sha256"],
            "working_database_sha256": manifest["databases"][
                record["database_filename"]
            ]["sha256"],
            "working_database": str((destination / record["database_filename"]).resolve()),
            "embedding_vector_count": record["embedding_vector_count"],
            "embedding_generation_identity": record[
                "embedding_generation_identity"
            ],
            "embedding_meta": record["embedding_meta"],
        }
    preparation_path = destination.parent / "preparation.json"
    if preparation_path.exists():
        raise AssetError(f"refusing to overwrite existing preparation: {preparation_path}")
    write_json(preparation_path, preparation)
    result["installed_to"] = str(destination.resolve())
    result["preparation"] = str(preparation_path.resolve())
    return result


def audit(index_dir: Path) -> dict[str, Any]:
    inputs = load_inputs()
    databases = expected_databases(inputs)
    results = {
        filename: audit_database(
            index_dir / filename, expected, allow_local_meta_paths=True
        )
        for filename, expected in sorted(databases.items())
    }
    return {
        "status": "PASS",
        "database_count": len(results),
        "embedding_vector_count": sum(
            int(value["embedding_vector_count"]) for value in results.values()
        ),
        "databases": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    audit_parser = commands.add_parser("audit")
    audit_parser.add_argument("--index-dir", required=True, type=Path)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--index-dir", required=True, type=Path)
    build_parser.add_argument("--output-dir", required=True, type=Path)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--archive", required=True, type=Path)
    install_parser = commands.add_parser("install")
    install_parser.add_argument("--archive", required=True, type=Path)
    install_parser.add_argument(
        "--destination", type=Path, default=HERE / "working" / "indexes"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "audit":
        result = audit(args.index_dir.resolve())
    elif args.command == "build":
        result = build(args.index_dir.resolve(), args.output_dir.resolve())
    elif args.command == "verify":
        result = verify_archive(args.archive.resolve())
    elif args.command == "install":
        result = install(args.archive.resolve(), args.destination.resolve())
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssetError, OSError, sqlite3.Error, zipfile.BadZipFile) as error:
        print(f"ERROR: {error}", file=os.sys.stderr)
        raise SystemExit(1)
