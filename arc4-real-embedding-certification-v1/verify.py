"""No-dependency verifier for the public Arc 4 evidence pack."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from arc4lib import CSV_COLUMNS, SCHEMA_VERSION, sha256_file, stable_row_id
from evidence import compute_summary, display_claims, load_rows


HERE = Path(__file__).resolve().parent
CONFIG = HERE / "research_config.json"
CSV_PATH = HERE / "measurements.csv"
CLAIMS = HERE / "claims.json"
INDEX = HERE / "INDEX.json"
REPORT = HERE / "REPORT.md"
README = HERE / "README.md"
UPSTREAM_RECHECK = HERE / "upstream-recheck.json"
RELEASE_MANIFEST = HERE / "release-asset-manifest.json"
CLAIM_PATTERN = re.compile(r"<!-- claim:([a-z0-9_]+)=(.*?) -->")
PUBLIC_PATHS = {
    "baseline_import_root": "<measured-baseline-checkout>/src",
    "candidate_import_root": "<measured-candidate-checkout>/src",
}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _decimal_fraction(row: dict[str, str], count_key: str, fraction_key: str) -> None:
    denominator = Decimal(row["candidate_count"])
    require(denominator > 0, f"zero denominator in retained row {row['row_id']}")
    require(
        Decimal(row[fraction_key]) == Decimal(row[count_key]) / denominator,
        f"fraction mismatch {fraction_key} in {row['row_id']}",
    )


def validate_rows(
    rows: list[dict[str, str]], config: dict[str, Any], index: dict[str, Any]
) -> dict[str, Any]:
    expected_count = (
        len(config["corpora"])
        * len(config["queries"])
        * len(config["measurement"]["cache_states"])
        * config["measurement"]["repetitions"]
        * len(config["measurement"]["modes"])
    )
    require(len(rows) == expected_count, f"expected {expected_count} rows, found {len(rows)}")
    row_ids = [row["row_id"] for row in rows]
    require(len(row_ids) == len(set(row_ids)), "duplicate row IDs")
    run_ids = {row["run_id"] for row in rows}
    require(len(run_ids) == 1, f"canonical CSV must contain one run, found {run_ids}")
    provenance = index["measurement_provenance"]
    by_pair: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        require(row["schema_version"] == SCHEMA_VERSION, f"schema mismatch {row['row_id']}")
        require(row["row_status"] == "retained", f"non-retained row {row['row_id']}")
        require(
            row["config_sha256"] == provenance["source_config_sha256"],
            f"measured config identity mismatch {row['row_id']}",
        )
        require(
            row["harness_sha256"] == provenance["measured_harness_sha256"],
            f"measured harness identity mismatch {row['row_id']}",
        )
        for column, placeholder in PUBLIC_PATHS.items():
            require(row[column] == placeholder, f"public path policy mismatch {row['row_id']}")
        expected_id = stable_row_id([row["run_id"], row["pair_id"], row["mode"]])
        require(row["row_id"] == expected_id, f"row ID is not reproducible {row['row_id']}")
        require(row["canonical_parity"] == "true", f"canonical parity failed {row['row_id']}")
        require(
            row["baseline_response_hash"] == row["candidate_response_hash"],
            f"response hash mismatch {row['row_id']}",
        )
        require(int(row["candidate_count"]) > 0, f"empty candidate set {row['row_id']}")
        require(int(row["result_count"]) > 0, f"empty result set {row['row_id']}")
        require(int(row["interval_violation_count"]) == 0, f"interval violation {row['row_id']}")
        require(
            int(row["total_certified_count"])
            == int(row["near_tie_count"])
            + int(row["genuine_disagreement_count"])
            + int(row["other_certified_count"]),
            f"certification bucket reconciliation failed {row['row_id']}",
        )
        require(
            int(row["exact_tie_count"]) + int(row["total_certified_count"])
            <= int(row["candidate_count"]),
            f"bucket counts exceed denominator {row['row_id']}",
        )
        for count_key, fraction_key in (
            ("exact_tie_count", "exact_tie_fraction"),
            ("near_tie_count", "near_tie_fraction"),
            ("genuine_disagreement_count", "genuine_disagreement_fraction"),
            ("total_certified_count", "total_certified_fraction"),
        ):
            _decimal_fraction(row, count_key, fraction_key)
        require(int(row["wall_ns"]) > 0, f"non-positive wall time {row['row_id']}")
        require(int(row["scoring_ns"]) > 0, f"non-positive scoring time {row['row_id']}")
        require(int(row["process_cpu_ns"]) >= 0, f"negative CPU time {row['row_id']}")
        require(
            int(row["peak_rss_bytes"]) >= int(row["rss_before_bytes"]),
            f"peak RSS invalid {row['row_id']}",
        )
        by_pair[row["pair_id"]].append(row)

    expected_modes = set(config["measurement"]["modes"])
    for pair_id, pair_rows in by_pair.items():
        require(len(pair_rows) == len(expected_modes), f"incomplete pair {pair_id}")
        require({row["mode"] for row in pair_rows} == expected_modes, f"mode mismatch {pair_id}")
        require(
            {int(row["execution_order"]) for row in pair_rows}
            == set(range(1, len(expected_modes) + 1)),
            f"execution-order mismatch {pair_id}",
        )
    order_counts = Counter((row["mode"], row["execution_order"]) for row in rows)
    tolerance = len(config["corpora"]) * len(config["queries"]) * len(
        config["measurement"]["cache_states"]
    )
    for mode in expected_modes:
        counts = [
            order_counts[(mode, str(position))]
            for position in range(1, len(expected_modes) + 1)
        ]
        require(max(counts) - min(counts) <= tolerance, f"unbalanced mode order {mode}")
    return compute_summary(rows, config)


def validate_claims(
    summary: dict[str, Any],
    *,
    claims_path: Path = CLAIMS,
    documents: tuple[Path, ...] = (REPORT, README),
    recheck_path: Path = UPSTREAM_RECHECK,
) -> dict[str, str]:
    expected = display_claims(summary)
    expected.update(
        {
            "django_pass_threshold": "10.0000%",
            "django_design_threshold": "25.0000%",
            "genuine_fail_threshold": "0.5000%",
            "warm_speed_rationale": "5.00x",
            "repetitions": "5",
            "query_count": "4",
            "corpus_count": "3",
        }
    )
    recheck = json.loads(recheck_path.read_text(encoding="utf-8"))
    expected.update(
        {
            "current_source_sha": recheck["main"]["current_sha"],
            "current_version": recheck["latest_release"]["tag"].removeprefix("v"),
            "roadmap_blob_sha": recheck["roadmap"]["blob_sha"],
        }
    )
    stored = json.loads(claims_path.read_text(encoding="utf-8"))
    require(stored == expected, "claims.json does not exactly match recomputed claims")
    for document in documents:
        markers = CLAIM_PATTERN.findall(document.read_text(encoding="utf-8"))
        require(markers, f"no numerical claim markers in {document.name}")
        for key, value in markers:
            require(key in expected, f"unknown claim marker {key} in {document.name}")
            require(value == expected[key], f"claim marker mismatch {key} in {document.name}")
    return expected


def validate_index(index: dict[str, Any], root: Path) -> None:
    require(index["schema_version"] == SCHEMA_VERSION, "index schema mismatch")
    require(
        index["release"]["publication_state"] == "local-draft-not-published",
        "unexpected publication state",
    )
    for relative, expected_hash in index["artifact_sha256"].items():
        path = root / relative
        require(path.is_file(), f"indexed artifact missing: {relative}")
        require(sha256_file(path) == expected_hash, f"artifact hash mismatch: {relative}")


def validate_release_manifest(path: Path, prepared: dict[str, Any]) -> None:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    require(manifest["asset"] == prepared["release_asset"], "release asset name mismatch")
    require(manifest["release_tag"] == prepared["release_tag"], "release tag mismatch")
    require(
        manifest["publication_state"] == "local-draft-not-published",
        "release manifest publication state mismatch",
    )
    included = [
        record
        for record in prepared["corpora"].values()
        if record["license"]["release_included"]
    ]
    require(
        set(manifest["databases"])
        == {record["database_filename"] for record in included},
        "release database set mismatch",
    )
    for record in included:
        item = manifest["databases"][record["database_filename"]]
        require(
            item["measured_working_database_sha256"]
            == record["working_database_sha256"],
            f"measured database provenance mismatch: {record['database_filename']}",
        )
        require(
            int(item["embedding_vector_count"]) == int(record["embedding_vector_count"]),
            f"release vector count mismatch: {record['database_filename']}",
        )


def verify(packet: Path = HERE) -> dict[str, Any]:
    packet = packet.resolve()
    required = (
        packet / "INDEX.json",
        packet / "research_config.json",
        packet / "prepared-inputs.json",
        packet / "measurements.csv",
        packet / "screen_measurements.csv",
        packet / "claims.json",
        packet / "REPORT.md",
        packet / "README.md",
        packet / "DATA-DICTIONARY.md",
        packet / "RELEASE-ASSET.md",
        packet / "THIRD-PARTY-NOTICES.md",
        packet / "licenses" / "django-LICENSE.txt",
        packet / "licenses" / "fastapi-LICENSE.txt",
        packet / "upstream-recheck.json",
        packet / "release-asset-manifest.json",
        packet / "arc4lib.py",
        packet / "evidence.py",
        packet / "worker.py",
        packet / "run_research.py",
        packet / "release_asset.py",
        packet / "test_arc4lib.py",
        packet / "test_release_asset.py",
        packet / "run_tests.py",
        packet / "TEST-RESULTS.json",
        packet / "verification.txt",
        packet / "tools" / "materialize_public_pack.py",
    )
    missing = [str(path) for path in required if not path.is_file()]
    require(not missing, f"required public files missing: {missing}")
    index = json.loads((packet / "INDEX.json").read_text(encoding="utf-8"))
    config = json.loads((packet / "research_config.json").read_text(encoding="utf-8"))
    prepared = json.loads((packet / "prepared-inputs.json").read_text(encoding="utf-8"))
    validate_index(index, packet)
    rows = load_rows(packet / "measurements.csv")
    summary = validate_rows(rows, config, index)
    claims = validate_claims(
        summary,
        claims_path=packet / "claims.json",
        documents=(packet / "REPORT.md", packet / "README.md"),
        recheck_path=packet / "upstream-recheck.json",
    )
    validate_release_manifest(packet / "release-asset-manifest.json", prepared)
    require(index["csvs"]["authoritative"]["rows"] == len(rows), "index row count mismatch")
    require(len(rows[0]) == len(CSV_COLUMNS), "CSV column count mismatch")
    for path in required:
        if path.suffix.lower() in {".md", ".json", ".py"}:
            text = path.read_text(encoding="utf-8")
            require("\u2014" not in text, f"U+2014 found in {path.name}")
        if path.suffix.lower() in {".md", ".json"}:
            text = path.read_text(encoding="utf-8")
            require("C:\\Users\\Admin" not in text, f"machine-local path found in {path.name}")
            require("C:/Users/Admin" not in text, f"machine-local path found in {path.name}")
    return {
        "status": "PASS",
        "row_count": len(rows),
        "column_count": len(CSV_COLUMNS),
        "claim_count": len(claims),
        "roadmap_verdict": summary["roadmap_verdict"],
        "csv_sha256": sha256_file(packet / "measurements.csv"),
        "release_asset_sha256": json.loads(
            (packet / "release-asset-manifest.json").read_text(encoding="utf-8")
        )["archive"]["sha256"],
    }


def self_test() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    rows = load_rows(CSV_PATH)
    summary = validate_rows(rows, config, index)
    expected_claims = validate_claims(summary)
    rejected: set[str] = set()

    def expect_rejection(name: str, action: Any) -> None:
        try:
            action()
        except VerificationError:
            rejected.add(name)

    with tempfile.TemporaryDirectory(prefix="arc4-public-verifier-") as temporary_name:
        temporary = Path(temporary_name)
        tampered_csv = temporary / "tampered.csv"
        shutil.copy2(CSV_PATH, tampered_csv)
        tampered_rows = load_rows(tampered_csv)
        tampered_rows[0]["total_certified_count"] = str(
            int(tampered_rows[0]["total_certified_count"]) + 1
        )
        with tampered_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(tampered_rows)
        expect_rejection(
            "row_arithmetic",
            lambda: validate_rows(load_rows(tampered_csv), config, index),
        )

        changed_claims = dict(expected_claims)
        changed_claims["row_count"] = "359"
        bad_claims = temporary / "claims.json"
        bad_claims.write_text(json.dumps(changed_claims), encoding="utf-8")
        expect_rejection(
            "stored_claims",
            lambda: validate_claims(summary, claims_path=bad_claims),
        )

        bad_index = json.loads(json.dumps(index))
        bad_index["artifact_sha256"]["REPORT.md"] = "0" * 64
        expect_rejection("artifact_hash", lambda: validate_index(bad_index, HERE))

    expected = {"row_arithmetic", "stored_claims", "artifact_hash"}
    require(rejected == expected, f"self-test rejection mismatch: {sorted(rejected)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--write-receipt", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = verify()
    if args.self_test:
        self_test()
        result["self_test"] = "PASS"
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.write_receipt:
        temporary = HERE / "verification.txt.tmp"
        temporary.write_text(rendered, encoding="utf-8", newline="\n")
        temporary.replace(HERE / "verification.txt")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerificationError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
