#!/usr/bin/env python3
"""Verify the curated Arc 4 publication package.

Two kinds of check live here and the distinction is load-bearing:

* **Recomputed** means this file derives the number from raw shipped records and
  compares it to what the package claims. A summary file cannot make a
  recomputed check pass.
* **Cross-checked** means two independently authored surfaces are compared to
  each other, for example an experiment summary against INDEX.json. That catches
  drift between documents; it does not re-derive the measurement.

`main()` prints both sets. Do not describe this verifier as recomputing every
published figure. It does not, and the covered set is named below.

Nothing here skips. A file it cannot classify, a claim it cannot resolve, and a
disclosure entry it cannot confirm are all errors.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
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
    rb"019f[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
EM_DASH = bytes([0xE2, 0x80, 0x94])  # U+2014, spelled in bytes so this file does not contain it
_BS = chr(92)
LOCAL_PATH_PATTERNS = {
    # Matches the raw form and the JSON-escaped form, in any letter case. The
    # original check looked for one backslash and therefore could not see the
    # escaped form, which is the only form the JSON and JSONL records use.
    "windows_research_root": re.compile(
        (r"(?i)[A-Za-z]:" + _BS * 2 + "+[Uu]sers" + _BS * 2 + "+[Aa]dmin").encode()
    ),
    "file_url_research_root": re.compile(rb"(?i)/Users/Admin/"),
}
LOCAL_PATH_TOOLING = {
    "verify_package.py",
    "test_verify_package.py",
    "LOCAL-PATH-DISCLOSURE.json",
}
DISCLOSURE = Path("LOCAL-PATH-DISCLOSURE.json")
PAIRED_GZIP_METADATA = Path("evidence/comparison-v2/packet/paired.jsonl.gz.json")
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
    "LOCAL-PATH-DISCLOSURE.json",
    "RETAINED-VERIFIERS.md",
    "SOURCE-HASHES.sha256",
    "CHECKSUMS.sha256",
    "VALIDATION.txt",
}

RECOMPUTED = [
    "5,000 generated provider-text query records, counted from the shipped JSONL",
    "the 33 screen nominations, counted from the shipped screen output",
    "the 5 complete-replay findings, their first-changed positions, and their "
    "rank-0, top-25 and top-100 membership results, derived from the raw finding records",
    "3,211 geometric rank-0 changes, derived by pairing the two shipped geometric lane outputs",
    "10,002 geometric cases, counted from the shipped JSONL",
    "55 preserved attempt files, 96 comparison-v1 raw files and 360 full-ranking files, counted on disk",
    "the full-suite replay's rank-0, ordered top-k, membership and exact-tie results, "
    "derived from its shipped per-lane records",
    "lossless reconstruction of the single gzip-stored dataset",
    "every published file against its manifest digest",
    "the local-path disclosure, in both directions",
]
CROSS_CHECKED = [
    "each experiment summary against INDEX.json",
    "every numeric claim in INDEX.json against the surface that owns it",
    "comparison-v1 and comparison-v2 headline counts against their experiment summaries",
    "every CLAIM-LEDGER.csv evidence pointer against the filesystem",
    "local Markdown links, publication hygiene, and the repository file-size gate",
]
NOT_COVERED = [
    "comparison-v2 m5, m6, m10, m11 and m12, which are reproducible from "
    "packet/raw/full-rankings/ but are not re-derived here; see VALIDATION.txt for the "
    "external run that did reproduce m1 to m6, m10 and m12",
    "any claim resting on material outside the publication boundary, including the "
    "corpus databases, the dependency wheel, and the working/ artifacts cited in "
    "PACKET-STATUS.md and ACCEPTANCE-AUDIT.md",
]


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


def is_text(data: bytes) -> bool:
    """Decodes as UTF-8 and holds no NUL. Extension is never consulted."""
    if bytes([0]) in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def scan_bytes(relative: str, data: bytes) -> tuple[list[str], dict[str, int]]:
    """Publication-hygiene scan of one file's raw bytes, whatever its extension.

    Authoring rules apply to text. A byte sequence that happens to spell an em
    dash inside a compressed stream is a coincidence, not a style defect, so the
    text rules run only where the bytes are text. The local-path scan runs
    everywhere, because a path inside a compressed artifact is still a path.
    """
    errors: list[str] = []
    text = is_text(data)
    if text:
        if EM_DASH in data:
            errors.append(f"forbidden Unicode em dash: {relative}")
        if ("superseded" + "-web-output").encode() in data:
            errors.append(f"superseded web artifact reference: {relative}")
    if INTERNAL_TASK_ID.search(data):
        errors.append(f"internal task identifier: {relative}")
    hits = {}
    for name, pattern in LOCAL_PATH_PATTERNS.items():
        count = len(pattern.findall(data))
        if count:
            hits[name] = count
    return errors, hits


def verify_local_path_disclosure(observed: dict[str, dict[str, int]]) -> list[str]:
    """Every retained local path is declared, and every declaration is still true."""
    errors: list[str] = []
    path = ROOT / DISCLOSURE
    if not path.is_file():
        return [f"missing required disclosure record: {DISCLOSURE.as_posix()}"]
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [f"invalid local-path disclosure: {exc}"]
    if document.get("schema_version") != "arc4.local-path-disclosure/v1":
        errors.append("local-path disclosure has an unexpected schema_version")
    declared = document.get("files")
    if not isinstance(declared, dict):
        return errors + ["local-path disclosure has no files object"]

    seen = {k: v for k, v in observed.items() if k not in LOCAL_PATH_TOOLING}
    for relative in sorted(set(seen) - set(declared)):
        errors.append(f"undeclared local path: {relative} {seen[relative]}")
    for relative in sorted(set(declared) - set(seen)):
        errors.append(f"stale local-path declaration, file is now clean: {relative}")
    for relative in sorted(set(declared) & set(seen)):
        if declared[relative] != seen[relative]:
            errors.append(
                f"local-path count changed: {relative} declared {declared[relative]} "
                f"observed {seen[relative]}"
            )
    # Counted from what the loop examined, never from the declaration length.
    if document.get("file_count") != len(seen):
        errors.append(
            f"disclosure file_count {document.get('file_count')!r} != observed {len(seen)}"
        )
    total = sum(sum(v.values()) for v in seen.values())
    if document.get("occurrence_count") != total:
        errors.append(
            f"disclosure occurrence_count {document.get('occurrence_count')!r} != observed {total}"
        )
    return errors


def verify_paired_gzip(required: bool) -> list[str]:
    """Validate the one gzip-stored dataset.

    `required` is true for the release layout, where the dataset must be present.
    Elsewhere absence of both halves is legitimate, but a half-present pair is
    always an error: a gzip with no metadata, or metadata with no gzip, is
    exactly the state a silent skip would hide.
    """
    errors: list[str] = []
    metadata_path = ROOT / PAIRED_GZIP_METADATA
    gzip_only = metadata_path.with_suffix("")
    if not metadata_path.is_file():
        if required:
            return [f"missing paired gzip metadata: {PAIRED_GZIP_METADATA.as_posix()}"]
        if gzip_only.is_file():
            return [f"gzip present without metadata: {gzip_only.name}"]
        return []
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"invalid paired gzip metadata: {exc}"]

    gzip_path = metadata_path.with_suffix("")
    if not gzip_path.is_file():
        return errors + ["missing paired gzip file"]
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


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def recompute_geometric_rank0(artifacts: Path) -> tuple[int, int]:
    """Pair the two shipped geometric lane outputs and count rank-0 changes."""
    numpy_lane = {row["case_id"]: row for row in load_jsonl(artifacts / "screens/geometric-numpy.jsonl")}
    python_lane = {row["case_id"]: row for row in load_jsonl(artifacts / "screens/geometric-python.jsonl")}
    if set(numpy_lane) != set(python_lane):
        raise ValueError("geometric lane outputs cover different case sets")
    flips = 0
    for case_id, left in numpy_lane.items():
        right = python_lane[case_id]
        if not left["ordered"] or not right["ordered"]:
            raise ValueError(f"geometric case {case_id} has an empty ordering")
        flips += left["ordered"][0] != right["ordered"][0]
    return len(numpy_lane), flips


def recompute_full_suite_replay(root: Path) -> dict:
    """Derive the full-suite replay's four reported dimensions from its per-lane records."""
    corpora = ("django", "fastapi", "jcodemunch")
    ks = (1, 5, 10, 25, 50, 100)
    result = {
        "queries": 0,
        "rank0": 0,
        "ordered": {k: 0 for k in ks},
        "membership": {k: 0 for k in ks},
        "tie_partition": 0,
        "any_top_100": 0,
        "full_depth": 0,
    }
    for corpus in corpora:
        lanes = {}
        for lane in ("numpy", "python"):
            path = root / f"raw/{lane}-{corpus}.jsonl"
            with path.open("r", encoding="utf-8") as stream:
                header = json.loads(stream.readline())
                if header["lane"] != lane or header["corpus"] != corpus:
                    raise ValueError(f"{path.name}: header lane or corpus mismatch")
                if header["vectorised"] != (lane == "numpy"):
                    raise ValueError(f"{path.name}: lane and vectorised flag disagree")
                if header["jcodemunch_version"] != "1.108.228":
                    raise ValueError(f"{path.name}: unexpected package version")
                rows = {}
                for line in stream:
                    row = json.loads(line)
                    if row["query_id"] in rows:
                        raise ValueError(f"{path.name}: duplicate query {row['query_id']}")
                    rows[row["query_id"]] = row
            lanes[lane] = rows
        if set(lanes["numpy"]) != set(lanes["python"]):
            raise ValueError(f"{corpus}: lanes cover different query sets")
        for query_id, left in lanes["numpy"].items():
            right = lanes["python"][query_id]
            if left["vector_sha256"] != right["vector_sha256"]:
                raise ValueError(f"{query_id}: lanes used different query vectors")
            numpy_order = left["ordered_top_100"]
            python_order = right["ordered_top_100"]
            if len(numpy_order) != 100 or len(python_order) != 100:
                raise ValueError(f"{query_id}: a top-100 list is not 100 long")
            result["queries"] += 1
            result["rank0"] += numpy_order[0] != python_order[0]
            for k in ks:
                result["ordered"][k] += numpy_order[:k] != python_order[:k]
                result["membership"][k] += set(numpy_order[:k]) != set(python_order[:k])
            if numpy_order != python_order:
                result["any_top_100"] += 1
            if left["full_ordering_sha256"] != right["full_ordering_sha256"]:
                result["full_depth"] += 1

            def partition(score_hex: dict) -> frozenset:
                groups: dict[str, list[str]] = {}
                for symbol_id, encoded in score_hex.items():
                    groups.setdefault(encoded, []).append(symbol_id)
                return frozenset(frozenset(v) for v in groups.values() if len(v) > 1)

            if partition(left["score_hex"]) != partition(right["score_hex"]):
                result["tie_partition"] += 1
    return result


def verify_claim_ledger(root: Path) -> tuple[list[str], int, int]:
    """Every evidence pointer that looks like a path must resolve."""
    errors: list[str] = []
    with (root / "CLAIM-LEDGER.csv").open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    resolved = 0
    for row in rows:
        for part in row["primary_evidence"].split(";"):
            part = part.strip()
            if not part or part.startswith("http"):
                continue
            if re.fullmatch(r"C\d+(?: through C\d+)?", part):
                continue
            if "/" not in part and "." not in part:
                errors.append(f"{row['claim_id']}: unclassifiable evidence pointer {part!r}")
                continue
            if not (root / part).exists():
                errors.append(f"{row['claim_id']}: evidence pointer does not resolve: {part}")
                continue
            resolved += 1
    return errors, len(rows), resolved


def verify_headline_claims() -> list[str]:
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
        replay_index = datasets["full_suite_replay"]

        adversarial_root = ROOT / "evidence/adversarial-falsification"
        artifacts = adversarial_root / "artifacts"
        adversarial_summary = json.loads((artifacts / "summary.json").read_text(encoding="utf-8"))
        provider_queries = count_jsonl(artifacts / "queries/provider-text.jsonl")
        geometric_cases = count_jsonl(artifacts / "queries/geometric.jsonl")
        screen = json.loads(
            (artifacts / "screens/provider-text-screen.json").read_text(encoding="utf-8")
        )
        findings = json.loads(
            (artifacts / "findings/provider-actual-findings.json").read_text(encoding="utf-8")
        )

        check("provider query records", provider_queries, 5000)
        check("provider query summary", adversarial_summary["provider_text"]["generated"], provider_queries)
        check("provider query index", adversarial_index["provider_text_queries"], provider_queries)
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
            adversarial_summary["provider_text"]["actual_shipped_scorer_findings"],
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
                    for position, pair in enumerate(zip(numpy_order, python_order), start=1)
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

        check("first changed positions", sorted(first_changed_positions), [38, 65, 65, 76, 78])
        check(
            "first changed positions index",
            adversarial_index["provider_text_complete_replay_first_changed_positions_one_based"],
            sorted(first_changed_positions),
        )
        check("provider rank0 changes", rank0_changes, 0)
        check("provider top25 changes", top25_changes, 0)
        check("provider membership changes", membership_changes, 0)
        check("provider rank0 index", adversarial_index["provider_text_rank0_changes"], rank0_changes)
        check("provider top25 index", adversarial_index["provider_text_top25_changes"], top25_changes)
        check(
            "provider membership index",
            adversarial_index["provider_text_top100_membership_changes"],
            membership_changes,
        )

        check("geometric records", geometric_cases, 10002)
        check("geometric summary", adversarial_summary["geometric"]["executed"], geometric_cases)
        check("geometric index", adversarial_index["geometric_executed_cases"], geometric_cases)
        check(
            "geometric independent cases",
            adversarial_summary["geometric"]["independent_boundary_cases"],
            10000,
        )
        check(
            "geometric independent cases index",
            adversarial_index["geometric_independent_boundary_cases"],
            adversarial_summary["geometric"]["independent_boundary_cases"],
        )
        executed, flips = recompute_geometric_rank0(artifacts)
        check("geometric cases recomputed from lane outputs", executed, geometric_cases)
        check("geometric rank0 changes recomputed", flips, 3211)
        check("geometric rank0 summary", adversarial_summary["geometric"]["rank0_flips"], flips)
        check("geometric rank0 index", adversarial_index["geometric_rank0_changes"], flips)

        attempt_files = sum(1 for path in (artifacts / "attempts").rglob("*") if path.is_file())
        check("preserved attempt files", attempt_files, 55)
        check("preserved attempt index", adversarial_index["preserved_attempt_files"], attempt_files)

        v1_root = ROOT / "evidence/comparison-v1/artifacts"
        v1_summary = json.loads((v1_root / "SUMMARY.json").read_text(encoding="utf-8"))
        v1_raw_files = sum(1 for path in (v1_root / "raw").rglob("*") if path.is_file())
        check("v1 ranking problems", v1_summary["paired_case_count"], 12)
        check("v1 ranking problems index", v1_index["ranking_problems"], v1_summary["paired_case_count"])
        check("v1 rank0 matches", v1_summary["rank_0_equal"], 12)
        check("v1 rank0 index", v1_index["rank0_matches"], v1_summary["rank_0_equal"])
        check("v1 ordered top-k matches", v1_summary["ordered_top_k_equal"], 12)
        check("v1 ordered index", v1_index["ordered_top_k_matches"], v1_summary["ordered_top_k_equal"])
        check("v1 membership matches", v1_summary["membership_equal"], 12)
        check("v1 membership index", v1_index["top_k_membership_matches"], v1_summary["membership_equal"])
        check("v1 raw files", v1_raw_files, 96)
        check("v1 raw-file index", v1_index["raw_files"], v1_raw_files)

        v2_root = ROOT / "evidence/comparison-v2/packet"
        v2_summary = json.loads((v2_root / "SUMMARY.json").read_text(encoding="utf-8"))
        check("v2 verdict", v2_summary["verdict"], "complete")
        check("v2 ranking problems", v2_summary["ranking_problems"], 12)
        check("v2 ranking problems index", v2_index["ranking_problems"], v2_summary["ranking_problems"])
        check("v2 replicated pairs", v2_summary["matrix_pairs_observed"], 120)
        check("v2 replicated pairs index", v2_index["replicated_pairs"], v2_summary["matrix_pairs_observed"])
        check("v2 unique query vectors", v2_summary["unique_query_vectors"], 4)
        check("v2 unique query vectors index", v2_index["unique_query_vectors"], v2_summary["unique_query_vectors"])
        check("v2 returned depths index", sorted(v2_index["returned_result_depths"]), [10, 25])
        for metric, label, index_key in (
            ("m1_rank0_difference", "v2 rank0 differences", "rank0_difference_problems"),
            ("m2_ordered_top_k_difference", "v2 ordered top-k differences", "ordered_top_k_difference_problems"),
            ("m3_membership_top_k_difference", "v2 membership differences", "top_k_membership_difference_problems"),
        ):
            counts = v2_summary["counts"][metric]
            check(f"{label} numerator", counts["problem_numerator"], 0)
            check(f"{label} denominator", counts["problem_denominator"], 12)
            check(f"{label} index", v2_index[index_key], counts["problem_numerator"])
        tie_counts = v2_summary["counts"]["m4_exact_tie_difference"]
        check("v2 exact-tie difference problems", tie_counts["problem_numerator"], 8)
        check("v2 exact-tie problem denominator", tie_counts["problem_denominator"], 12)
        check("v2 exact-tie index", v2_index["exact_tie_difference_problems"], tie_counts["problem_numerator"])
        histogram = v2_summary["m12"]["first_divergence_histogram"]
        check("v2 full-depth divergence problems", len(histogram), 10)
        check("v2 full-depth divergence index", v2_index["full_depth_divergence_problems"], len(histogram))
        check("v2 full-depth divergence repetitions", sorted(histogram.values()), [10] * 10)
        check("v2 no-divergence pairs", v2_summary["m12"]["none"], 20)
        check(
            "v2 earliest full-depth divergence is deeper than 100",
            min(int(k) for k in histogram) > 100,
            True,
        )
        check("v2 controls passed", v2_summary["controls_passed"], 21)
        check("v2 controls passed index", v2_index["controls_passed"], v2_summary["controls_passed"])
        check("v2 controls expected", v2_summary["controls_expected"], 21)
        check("v2 controls expected index", v2_index["controls_expected"], v2_summary["controls_expected"])
        check("v2 claim ceiling", v2_summary["claim_ceiling"], "fixed_suite_descriptive_only_no_inference")
        check("v2 claim-ceiling index", v2_index["claim_ceiling"], v2_summary["claim_ceiling"])
        full_ranking_files = sum(
            1 for path in (v2_root / "raw/full-rankings").rglob("*") if path.is_file()
        )
        check("v2 full-ranking files", full_ranking_files, 360)
        check("v2 full-ranking index", v2_index["full_ranking_files"], full_ranking_files)
        distinct_rankings = len(
            {sha256(path) for path in (v2_root / "raw/full-rankings").rglob("*") if path.is_file()}
        )
        check("v2 distinct full-ranking contents", distinct_rankings, 36)
        check("v2 distinct full-ranking index", v2_index["distinct_full_ranking_contents"], distinct_rankings)

        paired_metadata = json.loads(
            (v2_root / "paired.jsonl.gz.json").read_text(encoding="utf-8")
        )
        check("v2 paired source lines index", v2_index["paired_data"]["source_lines"], paired_metadata["source_lines"])
        check("v2 paired source hash index", v2_index["paired_data"]["source_sha256"], paired_metadata["source_sha256"])

        replay_root = ROOT / "evidence/full-suite-replay"
        replay_summary = json.loads((replay_root / "results-summary.json").read_text(encoding="utf-8"))
        replay = recompute_full_suite_replay(replay_root)
        check("replay queries recomputed", replay["queries"], 5000)
        check("replay queries summary", replay_summary["queries_total"], replay["queries"])
        check("replay queries index", replay_index["queries"], replay["queries"])
        check("replay rank0 recomputed", replay["rank0"], 0)
        check("replay rank0 summary", replay_summary["rank0_differences"], replay["rank0"])
        check("replay rank0 index", replay_index["rank0_differences"], replay["rank0"])
        check("replay any top-100 difference", replay["any_top_100"], 114)
        check("replay any top-100 index", replay_index["ordered_top_100_difference_queries"], replay["any_top_100"])
        check("replay full-depth differences", replay["full_depth"], 4971)
        check("replay full-depth index", replay_index["full_depth_ordering_difference_queries"], replay["full_depth"])
        check("replay exact-tie partition differences", replay["tie_partition"], 130)
        check(
            "replay exact-tie index",
            replay_index["exact_tie_partition_difference_queries"],
            replay["tie_partition"],
        )
        for k, expected_ordered, expected_membership in (
            (1, 0, 0), (5, 5, 4), (10, 11, 10), (25, 19, 16), (50, 51, 33), (100, 114, 29)
        ):
            check(f"replay ordered differences at k={k}", replay["ordered"][k], expected_ordered)
            check(f"replay membership differences at k={k}", replay["membership"][k], expected_membership)
            check(
                f"replay ordered index at k={k}",
                replay_index["ordered_differences_by_k"][str(k)],
                replay["ordered"][k],
            )
            check(
                f"replay membership index at k={k}",
                replay_index["membership_differences_by_k"][str(k)],
                replay["membership"][k],
            )
        check(
            "replay reproduces the five published findings",
            replay_summary["published_findings_control"]["reproduced"],
            5,
        )
        check(
            "replay control has no mismatch",
            replay_summary["published_findings_control"]["mismatches"],
            [],
        )
        check("replay screen misses", replay_summary["screen_miss_count"], 109)
        check("replay screen misses index", replay_index["screen_missed_disagreements"], 109)
        check(
            "replay swap classification",
            replay_summary["swap_classification"],
            {
                "genuine_score_order_inversion": 2,
                "numpy_exact_tie_separated_by_python": 9,
                "python_exact_tie_separated_by_numpy": 103,
            },
        )

        ledger_errors, ledger_rows, ledger_resolved = verify_claim_ledger(ROOT)
        errors.extend(ledger_errors)
        check("claim ledger rows", ledger_rows, 13)
        check("claim ledger index", index["integrity"]["claim_ledger_rows"], ledger_rows)
        with (ROOT / "CLAIM-LEDGER.csv").open("r", encoding="utf-8", newline="") as stream:
            ledger_ids = {row["claim_id"] for row in csv.DictReader(stream)}
        check("claim ledger unique IDs", len(ledger_ids), ledger_rows)
        check("claim ledger resolved evidence pointers", ledger_resolved > 0, True)

        zip_files = [path for path in ROOT.rglob("*.zip") if path.is_file()]
        check("multi-file ZIP archives", len(zip_files), 0)
        check("multi-file archive index", index["integrity"]["multi_file_archives"], len(zip_files))
        check(
            "maximum repository file index",
            index["integrity"]["maximum_repository_file_mib"],
            MAX_REPO_FILE_BYTES // (1024 * 1024),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"unable to recompute headline claims: {exc!r}")
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

        observed_local_paths: dict[str, dict[str, int]] = {}
        for relative in sorted(actual_files | ALLOWED_UNLISTED):
            path = ROOT / relative
            if not path.is_file():
                errors.append(f"expected file disappeared during verification: {relative}")
                continue
            if relative in entries:
                if path.stat().st_size > MAX_REPO_FILE_BYTES:
                    errors.append(f"repository file exceeds 95 MiB: {relative}")
                if sha256(path) != entries[relative]:
                    errors.append(f"hash mismatch: {relative}")

            data = path.read_bytes()
            hygiene, hits = scan_bytes(relative, data)
            errors.extend(hygiene)
            if hits:
                observed_local_paths[relative] = hits

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

        errors.extend(verify_local_path_disclosure(observed_local_paths))
        errors.extend(verify_paired_gzip(require_release_layout))
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
    print()
    print("Recomputed from raw shipped records:")
    for item in RECOMPUTED:
        print(f"  - {item}")
    print("Cross-checked between independently authored surfaces:")
    for item in CROSS_CHECKED:
        print(f"  - {item}")
    print("Not covered by this verifier:")
    for item in NOT_COVERED:
        print(f"  - {item}")
    print()
    print(
        "HEADLINES: 5,000 generated queries; 33 screen nominations; 5 confirmed deep swaps; "
        "10,002 geometric cases with 3,211 rank-0 changes; 12 official-package ranking "
        "problems; 5,000-query two-lane replay with 0 rank-0 differences."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
