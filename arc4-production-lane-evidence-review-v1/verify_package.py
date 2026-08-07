#!/usr/bin/env python3
"""Verify the curated Arc 4 publication package."""

from __future__ import annotations

import hashlib
import csv
import gzip
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PACKAGE_ROOT = ROOT
REPO_ROOT = ROOT.parent
MANIFEST = ROOT / "CHECKSUMS.sha256"
ALLOWED_UNLISTED = {"CHECKSUMS.sha256"}
MAX_REPO_FILE_BYTES = 95 * 1024 * 1024
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
INTERNAL_TASK_ID = re.compile(
    r"019f[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
PAIRED_GZIP_METADATA = Path(
    "evidence/comparison-v2/packet/paired.jsonl.gz.json"
)
REQUIRED_RELEASE_FILES = {
    "README.md",
    "REPORT.md",
    "INDEX.json",
    "DATA-DICTIONARY.md",
    "DATASET-INVENTORY.md",
    "CLAIM-LEDGER.csv",
    "SOURCE-MAP.md",
    "SOURCE-NOTES.md",
    "PROVENANCE-ANNOTATION.md",
    "SOURCE-HASHES.sha256",
    "CHECKSUMS.sha256",
    "VALIDATION.txt",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_manifest(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\\]+)", line)
        if not match:
            raise ValueError(f"invalid manifest line {line_number}: {line!r}")
        digest, relative = match.groups()
        candidate = (ROOT / relative).resolve()
        if ROOT not in candidate.parents:
            raise ValueError(f"manifest path leaves package: {relative}")
        if relative in entries:
            raise ValueError(f"duplicate manifest path: {relative}")
        entries[relative] = digest
    if not entries:
        raise ValueError("manifest has no file entries")
    return entries


def local_markdown_targets(path: Path) -> list[Path]:
    targets: list[Path] = []
    for raw in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
        target = raw.strip().split("#", 1)[0]
        if not target or "://" in target or target.startswith("mailto:"):
            continue
        resolved = (path.parent / target).resolve()
        if REPO_ROOT != resolved and REPO_ROOT not in resolved.parents:
            raise ValueError(f"link leaves repository: {path.relative_to(ROOT)} -> {raw}")
        targets.append(resolved)
    return targets


def verify_paired_gzip() -> list[str]:
    metadata_path = ROOT / PAIRED_GZIP_METADATA
    if not metadata_path.exists():
        return []
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"invalid paired gzip metadata: {exc}"]

    errors: list[str] = []
    gzip_path = metadata_path.with_suffix("")
    if not gzip_path.is_file():
        return ["missing paired gzip file"]
    if sha256(gzip_path) != metadata.get("compressed_sha256"):
        errors.append("paired gzip compressed hash mismatch")
    if gzip_path.stat().st_size != metadata.get("compressed_bytes"):
        errors.append("paired gzip compressed byte mismatch")

    source_hash = hashlib.sha256()
    source_bytes = 0
    source_lines = 0
    try:
        with gzip.open(gzip_path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                source_hash.update(chunk)
                source_bytes += len(chunk)
                source_lines += chunk.count(b"\n")
    except (OSError, EOFError) as exc:
        return errors + [f"paired gzip decompression failed: {exc}"]
    if source_bytes != metadata.get("source_bytes"):
        errors.append("paired gzip source byte mismatch")
    if source_lines != metadata.get("source_lines"):
        errors.append("paired gzip source line mismatch")
    if source_hash.hexdigest() != metadata.get("source_sha256"):
        errors.append("paired gzip source hash mismatch")
    return errors


def count_jsonl(path: Path) -> int:
    with path.open("r", encoding="utf-8") as stream:
        return sum(1 for line in stream if line.strip())


def verify_headline_claims() -> list[str]:
    """Recompute decision-facing counts from the shipped evidence."""
    errors: list[str] = []

    def check(label: str, actual: object, expected: object) -> None:
        if actual != expected:
            errors.append(f"headline mismatch: {label}: {actual!r} != {expected!r}")

    try:
        index = json.loads((ROOT / "INDEX.json").read_text(encoding="utf-8"))
        check(
            "index schema",
            index.get("schema_version"),
            "arc4-production-lane-evidence-review/v1",
        )
        datasets = index["datasets"]
        adversarial_index = datasets["adversarial_falsification"]
        v1_index = datasets["comparison_v1"]
        v2_index = datasets["comparison_v2"]

        adversarial_root = ROOT / "evidence/adversarial-falsification"
        artifacts = adversarial_root / "artifacts"
        adversarial_summary = json.loads(
            (artifacts / "summary.json").read_text(encoding="utf-8")
        )
        provider_queries = count_jsonl(artifacts / "queries/provider-text.jsonl")
        geometric_cases = count_jsonl(artifacts / "queries/geometric.jsonl")
        screen = json.loads(
            (artifacts / "screens/provider-text-screen.json").read_text(
                encoding="utf-8"
            )
        )
        findings = json.loads(
            (artifacts / "findings/provider-actual-findings.json").read_text(
                encoding="utf-8"
            )
        )

        check("provider query records", provider_queries, 5000)
        check(
            "provider query summary",
            adversarial_summary["provider_text"]["generated"],
            provider_queries,
        )
        check(
            "provider query index",
            adversarial_index["provider_text_queries"],
            provider_queries,
        )
        check("screen status", screen["status"], "screen_only_not_proof")
        check("screen nominations", len(screen["hits"]), 33)
        check(
            "screen nomination summary",
            adversarial_summary["provider_text"]["screen_hits"],
            len(screen["hits"]),
        )
        check(
            "screen nomination index",
            adversarial_index["provider_text_screen_nominations"],
            len(screen["hits"]),
        )
        check("complete replay findings", len(findings), 5)
        check(
            "complete replay summary",
            adversarial_summary["provider_text"][
                "actual_shipped_scorer_findings"
            ],
            len(findings),
        )
        check(
            "complete replay index",
            adversarial_index["provider_text_complete_replay_findings"],
            len(findings),
        )

        first_changed_positions: list[int] = []
        rank0_changes = 0
        top25_changes = 0
        membership_changes = 0
        for finding in findings:
            numpy_order = finding["numpy"]["ordered_top_100"]
            python_order = finding["python"]["ordered_top_100"]
            if len(numpy_order) != 100 or len(python_order) != 100:
                errors.append("headline mismatch: a complete replay is not top 100")
                continue
            first = next(
                (
                    position
                    for position, pair in enumerate(
                        zip(numpy_order, python_order), start=1
                    )
                    if pair[0] != pair[1]
                ),
                None,
            )
            if first is None:
                errors.append("headline mismatch: finding has no ordering difference")
                continue
            first_changed_positions.append(first)
            rank0_changes += numpy_order[0] != python_order[0]
            top25_changes += numpy_order[:25] != python_order[:25]
            membership_changes += set(numpy_order) != set(python_order)

        check(
            "first changed positions",
            sorted(first_changed_positions),
            [38, 65, 65, 76, 78],
        )
        check(
            "first changed positions index",
            adversarial_index[
                "provider_text_complete_replay_first_changed_positions_one_based"
            ],
            sorted(first_changed_positions),
        )
        check("provider rank0 changes", rank0_changes, 0)
        check("provider top25 changes", top25_changes, 0)
        check("provider membership changes", membership_changes, 0)
        check(
            "provider rank0 index",
            adversarial_index["provider_text_rank0_changes"],
            rank0_changes,
        )
        check(
            "provider top25 index",
            adversarial_index["provider_text_top25_changes"],
            top25_changes,
        )
        check(
            "provider membership index",
            adversarial_index["provider_text_top100_membership_changes"],
            membership_changes,
        )

        check("geometric records", geometric_cases, 10002)
        check(
            "geometric summary",
            adversarial_summary["geometric"]["executed"],
            geometric_cases,
        )
        check(
            "geometric index",
            adversarial_index["geometric_executed_cases"],
            geometric_cases,
        )
        check(
            "geometric independent cases",
            adversarial_summary["geometric"]["independent_boundary_cases"],
            10000,
        )
        check(
            "geometric rank0 changes",
            adversarial_summary["geometric"]["rank0_flips"],
            3211,
        )
        attempt_files = sum(
            1 for path in (artifacts / "attempts").rglob("*") if path.is_file()
        )
        check("preserved attempt files", attempt_files, 55)
        check(
            "preserved attempt index",
            adversarial_index["preserved_attempt_files"],
            attempt_files,
        )

        v1_root = ROOT / "evidence/comparison-v1/artifacts"
        v1_summary = json.loads(
            (v1_root / "SUMMARY.json").read_text(encoding="utf-8")
        )
        v1_raw_files = sum(1 for path in (v1_root / "raw").rglob("*") if path.is_file())
        check("v1 ranking problems", v1_summary["paired_case_count"], 12)
        check("v1 rank0 matches", v1_summary["rank_0_equal"], 12)
        check("v1 ordered top-k matches", v1_summary["ordered_top_k_equal"], 12)
        check("v1 membership matches", v1_summary["membership_equal"], 12)
        check("v1 raw files", v1_raw_files, 96)
        check("v1 raw-file index", v1_index["raw_files"], v1_raw_files)

        v2_root = ROOT / "evidence/comparison-v2/packet"
        v2_summary = json.loads(
            (v2_root / "SUMMARY.json").read_text(encoding="utf-8")
        )
        check("v2 verdict", v2_summary["verdict"], "complete")
        check("v2 ranking problems", v2_summary["ranking_problems"], 12)
        check("v2 replicated pairs", v2_summary["matrix_pairs_observed"], 120)
        for metric, label in (
            ("m1_rank0_difference", "v2 rank0 differences"),
            ("m2_ordered_top_k_difference", "v2 ordered top-k differences"),
            ("m3_membership_top_k_difference", "v2 membership differences"),
        ):
            counts = v2_summary["counts"][metric]
            check(f"{label} numerator", counts["problem_numerator"], 0)
            check(f"{label} denominator", counts["problem_denominator"], 12)
        tie_counts = v2_summary["counts"]["m4_exact_tie_difference"]
        check("v2 exact-tie difference problems", tie_counts["problem_numerator"], 8)
        check("v2 exact-tie problem denominator", tie_counts["problem_denominator"], 12)
        histogram = v2_summary["m12"]["first_divergence_histogram"]
        check("v2 full-depth divergence problems", len(histogram), 10)
        check("v2 full-depth divergence repetitions", sorted(histogram.values()), [10] * 10)
        check("v2 no-divergence pairs", v2_summary["m12"]["none"], 20)
        check("v2 controls passed", v2_summary["controls_passed"], 21)
        check("v2 controls expected", v2_summary["controls_expected"], 21)
        check(
            "v2 claim ceiling",
            v2_summary["claim_ceiling"],
            "fixed_suite_descriptive_only_no_inference",
        )
        full_ranking_files = sum(
            1
            for path in (v2_root / "raw/full-rankings").rglob("*")
            if path.is_file()
        )
        check("v2 full-ranking files", full_ranking_files, 360)
        check(
            "v2 full-ranking index",
            v2_index["full_ranking_files"],
            full_ranking_files,
        )
        check(
            "v2 claim-ceiling index",
            v2_index["claim_ceiling"],
            v2_summary["claim_ceiling"],
        )

        with (ROOT / "CLAIM-LEDGER.csv").open(
            "r", encoding="utf-8", newline=""
        ) as stream:
            claim_rows = list(csv.DictReader(stream))
        check("claim ledger rows", len(claim_rows), 11)
        check(
            "claim ledger unique IDs",
            len({row["claim_id"] for row in claim_rows}),
            len(claim_rows),
        )
        check(
            "claim ledger index",
            index["integrity"]["claim_ledger_rows"],
            len(claim_rows),
        )

        zip_files = [path for path in ROOT.rglob("*.zip") if path.is_file()]
        check("multi-file ZIP archives", len(zip_files), 0)
        check(
            "multi-file archive index",
            index["integrity"]["multi_file_archives"],
            len(zip_files),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"unable to recompute headline claims: {exc}")
    return errors


def verify(root: Path = ROOT) -> list[str]:
    global ROOT, REPO_ROOT, MANIFEST
    original = ROOT, REPO_ROOT, MANIFEST
    ROOT = root.resolve()
    REPO_ROOT = ROOT.parent
    MANIFEST = ROOT / "CHECKSUMS.sha256"
    errors: list[str] = []
    try:
        require_release_layout = ROOT == PACKAGE_ROOT
        if require_release_layout:
            for relative in sorted(REQUIRED_RELEASE_FILES):
                if not (ROOT / relative).is_file():
                    errors.append(f"missing required release file: {relative}")
        try:
            entries = parse_manifest(MANIFEST)
        except (OSError, ValueError) as exc:
            return [str(exc)]

        actual_files = {
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix.lower() != ".pyc"
            and path.relative_to(ROOT).as_posix() not in ALLOWED_UNLISTED
        }
        listed_files = set(entries)
        for relative in sorted(listed_files - actual_files):
            errors.append(f"missing file: {relative}")
        for relative in sorted(actual_files - listed_files):
            errors.append(f"unlisted file: {relative}")

        for relative, expected in entries.items():
            path = ROOT / relative
            if not path.is_file():
                continue
            if path.stat().st_size > MAX_REPO_FILE_BYTES:
                errors.append(f"repository file exceeds 95 MiB: {relative}")
            actual = sha256(path)
            if actual != expected:
                errors.append(f"hash mismatch: {relative}")

            if path.suffix.lower() in {".md", ".py", ".json", ".jsonl", ".csv", ".txt"}:
                text = path.read_text(encoding="utf-8", errors="replace")
                if "\u2014" in text:
                    errors.append(f"forbidden Unicode em dash: {relative}")
                if "C:\\Users\\Admin" in text:
                    errors.append(f"private absolute path: {relative}")
                if INTERNAL_TASK_ID.search(text):
                    errors.append(f"internal task identifier: {relative}")
                if "superseded" + "-web-output" in text:
                    errors.append(f"superseded web artifact reference: {relative}")

            if path.suffix.lower() == ".md":
                try:
                    targets = local_markdown_targets(path)
                except ValueError as exc:
                    errors.append(str(exc))
                    targets = []
                for target in targets:
                    if not target.exists():
                        errors.append(
                            f"broken local link: {relative} -> {target.relative_to(REPO_ROOT)}"
                        )
        errors.extend(verify_paired_gzip())
        if require_release_layout:
            errors.extend(verify_headline_claims())
        return errors
    finally:
        ROOT, REPO_ROOT, MANIFEST = original


def main() -> int:
    errors = verify()
    if errors:
        print("FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    count = len(parse_manifest(MANIFEST))
    print(f"PASS: {count} files match the package manifest and publication checks.")
    print(
        "HEADLINES: 5,000 generated queries; 33 screen nominations; "
        "5 confirmed deep swaps; 10,002 geometric cases; "
        "12 official-package ranking problems."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
