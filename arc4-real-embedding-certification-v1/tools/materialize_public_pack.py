"""Materialize the publication-safe Arc 4 data files from the canonical packet."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "arc4-real-embedding-certification-v1"
PACK_DIRECTORY = "arc4-real-embedding-certification-v1"
RELEASE_TAG = "arc4-real-embedding-certification-v1"
RELEASE_ASSET = "arc4-real-embedding-indexes-v1.zip"
ABSOLUTE_PATH = re.compile(r"(?:(?<![A-Za-z])[A-Za-z]:[\\/]|/Users/|/home/)")
PATH_COLUMNS = {
    "baseline_import_root": "<measured-baseline-checkout>/src",
    "candidate_import_root": "<measured-candidate-checkout>/src",
}
LICENSES = {
    "django": {
        "name": "BSD-3-Clause-style Django license",
        "url": "https://github.com/django/django/blob/274a1d494d11d87a1b767340d1f398f197810f93/LICENSE",
        "release_included": True,
    },
    "fastapi": {
        "name": "MIT",
        "url": "https://github.com/fastapi/fastapi/blob/95f8322ee1dcda7ceace7b1c4f6c9915b36d748f/LICENSE",
        "release_included": True,
    },
    "jcodemunch": {
        "name": "jCodeMunch-MCP Dual-Use License 1.1",
        "url": "https://github.com/jgravelle/jcodemunch-mcp/blob/c78392cac0d50570d5cf86558d8d3674c0bea068/LICENSE",
        "release_included": False,
        "exclusion_reason": "The control index is a repackaged derivative containing indexed source text. Public redistribution requires written permission under the pinned custom license.",
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def sanitize_config(source: Path, destination: Path) -> dict[str, Any]:
    config = json.loads(source.read_text(encoding="utf-8"))
    public = copy.deepcopy(config)
    for corpus in public["corpora"]:
        corpus["source_database"] = Path(corpus["source_database"]).name
        corpus["source_root"] = f"<local-checkout:{corpus['public_repo']}>"
    public["publication"] = {
        "path_policy": "Machine-local roots are replaced with explicit placeholders.",
        "source_config_sha256": sha256_file(source),
    }
    write_json(destination, public)
    return public


def sanitize_csv(source: Path, destination: Path) -> dict[str, Any]:
    source_hash = sha256_file(source)
    redactions = {name: 0 for name in PATH_COLUMNS}
    row_count = 0
    with source.open("r", encoding="utf-8", newline="") as input_handle:
        reader = csv.DictReader(input_handle)
        if reader.fieldnames is None:
            raise ValueError(f"missing CSV header: {source}")
        with destination.open("w", encoding="utf-8", newline="") as output_handle:
            writer = csv.DictWriter(
                output_handle,
                fieldnames=reader.fieldnames,
                lineterminator="\n",
            )
            writer.writeheader()
            for row in reader:
                for column, placeholder in PATH_COLUMNS.items():
                    if row.get(column) != placeholder:
                        redactions[column] += 1
                    row[column] = placeholder
                writer.writerow(row)
                row_count += 1
    return {
        "source_sha256": source_hash,
        "public_sha256": sha256_file(destination),
        "rows": row_count,
        "columns": len(reader.fieldnames),
        "redactions": redactions,
    }


def public_preparation(
    *, config: dict[str, Any], preparation: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    corpora: dict[str, Any] = {}
    for corpus in config["corpora"]:
        name = corpus["name"]
        source = preparation["corpora"][name]
        corpora[name] = {
            "database_filename": Path(corpus["source_database"]).name,
            "source_repo_id": corpus["source_repo_id"],
            "public_repo": corpus["public_repo"],
            "corpus_commit": manifest["corpora"][name]["commit"],
            "role": corpus["role"],
            "source_database_sha256": source["source_database_sha256"],
            "working_database_sha256": source["working_database_sha256"],
            "embedding_vector_count": source["embedding_vector_count"],
            "embedding_generation_identity": source["embedding_generation_identity"],
            "embedding_meta": source["embedding_meta"],
            "license": LICENSES[name],
        }
    result = {
        "schema_version": SCHEMA_VERSION,
        "release_tag": RELEASE_TAG,
        "release_asset": RELEASE_ASSET,
        "measured_config_sha256": manifest["config_sha256"],
        "measured_harness_sha256": manifest["measured_harness_sha256"],
        "baseline_identity": preparation["baseline_identity"],
        "embedding_provider": preparation["embedding_provider"],
        "embedding_model": preparation["embedding_model"],
        "corpora": corpora,
        "queries": preparation["queries"],
        "release_coverage": {
            "included": ["django", "fastapi"],
            "excluded": ["jcodemunch"],
            "note": "The public asset includes both load-bearing gate corpora. The raw control measurements remain in measurements.csv.",
        },
    }
    rendered = json.dumps(result, sort_keys=True)
    if ABSOLUTE_PATH.search(rendered):
        raise ValueError("prepared-inputs.json would contain a machine-local absolute path")
    return result


def build_index(
    *,
    output: Path,
    manifest: dict[str, Any],
    csv_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    artifact_names = [
        "README.md",
        "REPORT.md",
        "DATA-DICTIONARY.md",
        "claims.json",
        "research_config.json",
        "prepared-inputs.json",
        "measurements.csv",
        "screen_measurements.csv",
        "upstream-recheck.json",
        "arc4lib.py",
        "evidence.py",
        "worker.py",
        "run_research.py",
        "verify.py",
        "test_arc4lib.py",
        "release_asset.py",
        "test_release_asset.py",
        "run_tests.py",
        "TEST-RESULTS.json",
        "verification.txt",
        "tools/materialize_public_pack.py",
        "RELEASE-ASSET.md",
        "THIRD-PARTY-NOTICES.md",
        "licenses/django-LICENSE.txt",
        "licenses/fastapi-LICENSE.txt",
    ]
    release_manifest = output / "release-asset-manifest.json"
    release_publication: dict[str, Any] = {
        "publication_state": "local-draft-not-published"
    }
    if release_manifest.is_file():
        artifact_names.append(release_manifest.name)
        tracked_release = json.loads(release_manifest.read_text(encoding="utf-8"))
        release_publication["publication_state"] = tracked_release.get(
            "publication_state", "local-draft-not-published"
        )
        if tracked_release.get("release_url"):
            release_publication["url"] = tracked_release["release_url"]
    hashes = {
        name: sha256_file(output / name)
        for name in artifact_names
        if (output / name).is_file()
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "bundle": "Arc 4 real-embedding certification evidence for jgravelle/jcodemunch-mcp#398",
        "pack_directory": PACK_DIRECTORY,
        "upstream_umbrella_issue": "https://github.com/jgravelle/jcodemunch-mcp/issues/398",
        "release": {
            "tag": RELEASE_TAG,
            "asset": RELEASE_ASSET,
            **release_publication,
        },
        "measurement_provenance": {
            "source_config_sha256": manifest["config_sha256"],
            "measured_harness_sha256": manifest["measured_harness_sha256"],
            "canonical_source_csv_sha256": manifest["canonical_csv"]["sha256"],
            "run_id": manifest["run_id"],
        },
        "public_path_transformation": {
            "scope": sorted(PATH_COLUMNS),
            "replacement": PATH_COLUMNS,
            "note": "Only machine-local import-root fields were replaced. Row IDs, measurements, and all other fields are retained.",
        },
        "csvs": csv_records,
        "artifact_sha256": hashes,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-packet", required=True, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source_packet.resolve()
    output = args.output.resolve()
    required = [
        source / "research_config.json",
        source / "measurements.csv",
        source / "working" / "screen_measurements.csv",
        source / "working" / "preparation.json",
        source / "manifest.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"source packet is incomplete: {missing}")
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    config = sanitize_config(source / "research_config.json", output / "research_config.json")
    preparation = json.loads(
        (source / "working" / "preparation.json").read_text(encoding="utf-8")
    )
    write_json(
        output / "prepared-inputs.json",
        public_preparation(config=config, preparation=preparation, manifest=manifest),
    )
    csv_records = {
        "authoritative": sanitize_csv(
            source / "measurements.csv", output / "measurements.csv"
        ),
        "screen": sanitize_csv(
            source / "working" / "screen_measurements.csv",
            output / "screen_measurements.csv",
        ),
    }
    write_json(
        output / "INDEX.json",
        build_index(output=output, manifest=manifest, csv_records=csv_records),
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "output": str(output),
                "authoritative_rows": csv_records["authoritative"]["rows"],
                "screen_rows": csv_records["screen"]["rows"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
