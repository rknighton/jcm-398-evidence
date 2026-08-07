"""Standard-library, fail-closed verifier for the local comparison packet."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCHEMA = "jcm-production-lane-v1"


class VerificationError(RuntimeError): pass


def require(value: bool, message: str) -> None:
    if not value: raise VerificationError(message)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def strict_json(path: Path, keys: set[str] | None = None) -> Any:
    value = json.loads(path.read_text(encoding="utf-8"))
    if keys is not None:
        require(set(value) == keys, f"unknown or missing columns in {path.name}: {set(value) ^ keys}")
    return value


TRIAL_KEYS = {"schema_version", "run_id", "trial_id", "paired_case_id", "repetition", "execution_order", "corpus", "role",
              "source_commit", "database_name", "database_sha256", "vector_count", "embedding_identity", "query_id", "query_text",
              "query_vector_sha256", "semantic_only", "semantic_weight", "top_k", "tag", "source_commit_jcodemunch", "wheel_sha256",
              "source_clean", "production_functions", "lane_requested", "lane_selected", "environment", "tool_ordered_top_k_ids",
              "adapter_ordered_top_k_ids", "adapter_parity", "score_evidence_path", "score_evidence_sha256", "terminal_status", "failure_reason"}


def verify(root: Path = HERE) -> dict[str, Any]:
    required = ["config.json", "REPORT.md", "artifacts/preflight.json", "artifacts/comparisons.jsonl", "artifacts/summary.json", "artifacts/manifest.json",
                "artifacts/controls/controls.json", "harness/common.py", "harness/worker.py", "harness/controller.py", "harness/test_common.py"]
    for name in required: require((root / name).is_file(), f"missing required file: {name}")
    config = strict_json(root / "config.json")
    require(config["schema_version"] == SCHEMA, "config schema mismatch")
    require(config["expected"] == {"paired_cases": 12, "lanes": 2, "repetitions": 2, "trials": 48}, "expected coverage changed")
    require(len(config["cases"]) == 12, "case count mismatch")
    require(len({c["paired_case_id"] for c in config["cases"]}) == 12, "duplicate paired case")
    preflight = strict_json(root / "artifacts" / "preflight.json")
    require(preflight["source_commit"] == config["production"]["commit"] and preflight["source_clean"], "preflight source identity failed")
    require(preflight["package_version"] == "1.108.228" and preflight["remote_tag_commit"] == config["production"]["commit"], "preflight release identity failed")
    require(preflight["wheel_sha256"] == config["production"]["wheel_sha256"] and preflight["disk_free_bytes"] >= 5 * 1024 * 1024 * 1024, "preflight wheel or disk gate failed")
    for name, corpus in config["corpora"].items():
        require(preflight["databases"][name]["sha256"] == corpus["database_sha256"] and preflight["databases"][name]["license"], f"preflight database/license failed: {name}")
    expected_ids = {(c["paired_case_id"], lane, rep) for c in config["cases"] for lane in ("numpy", "python") for rep in (1, 2)}
    paths = sorted((root / "artifacts" / "raw").glob("*.json"))
    require(len(paths) == 48, f"expected 48 raw trials, found {len(paths)}")
    records = []
    for path in paths:
        record = strict_json(path, TRIAL_KEYS)
        require(record["schema_version"] == SCHEMA, f"trial schema mismatch: {path.name}")
        require(record["terminal_status"] == "completed" and record["failure_reason"] is None, f"incomplete trial: {path.name}")
        require(record["lane_requested"] == record["lane_selected"], f"lane selection mismatch: {path.name}")
        require(record["adapter_parity"] and record["tool_ordered_top_k_ids"] == record["adapter_ordered_top_k_ids"], f"adapter parity failure: {path.name}")
        require(record["source_commit_jcodemunch"] == config["production"]["commit"], f"source mismatch: {path.name}")
        require(record["wheel_sha256"] == config["production"]["wheel_sha256"], f"wheel mismatch: {path.name}")
        corpus = config["corpora"][record["corpus"]]; query = config["queries"][record["query_id"]]
        require(record["database_sha256"] == corpus["database_sha256"], f"database mismatch: {path.name}")
        require(record["query_vector_sha256"] == query["vector_sha256"], f"query mismatch: {path.name}")
        if record["lane_requested"] == "numpy": require(record["environment"]["numpy_version"] == "2.4.4", f"NumPy version mismatch: {path.name}")
        else: require(record["environment"]["numpy_version"] is None, f"NumPy present in fallback: {path.name}")
        records.append(record)
    actual_ids = {(r["paired_case_id"], r["lane_requested"], r["repetition"]) for r in records}
    require(actual_ids == expected_ids and len(actual_ids) == 48, "missing or duplicate trial identity")
    common = {}
    for record in records:
        freeze = [line for line in record["environment"]["pip_freeze"] if not line.lower().startswith("numpy==")]
        identity = hashlib.sha256(("\n".join(freeze) + "\n").encode()).hexdigest()
        common.setdefault(record["lane_requested"], set()).add(identity)
    require(all(len(values) == 1 for values in common.values()) and common["numpy"] == common["python"], "common dependency manifests differ")
    by = defaultdict(dict)
    for record in records: by[record["paired_case_id"]][(record["lane_requested"], record["repetition"])] = record
    for case_id, rows in by.items():
        for lane in ("numpy", "python"):
            require(rows[(lane, 1)]["score_evidence_sha256"] == rows[(lane, 2)]["score_evidence_sha256"], f"nondeterminism: {case_id} {lane}")
            evidence = root / rows[(lane, 1)]["score_evidence_path"]
            require(evidence.is_file() and sha256(evidence) == rows[(lane, 1)]["score_evidence_sha256"], f"score evidence mismatch: {case_id} {lane}")
    comparisons = [json.loads(line) for line in (root / "artifacts" / "comparisons.jsonl").read_text(encoding="utf-8").splitlines() if line]
    require(len(comparisons) == 12 and {c["paired_case_id"] for c in comparisons} == set(by), "comparison coverage mismatch")
    sys.path.insert(0, str(root / "harness"))
    from common import compare_case
    recomputed = []
    case_map = {c["paired_case_id"]: c for c in config["cases"]}
    for case_id in sorted(by):
        rows = by[case_id]
        ne = strict_json(root / rows[("numpy", 1)]["score_evidence_path"])
        pe = strict_json(root / rows[("python", 1)]["score_evidence_path"])
        recomputed.append(compare_case(ne, pe, case_map[case_id]))
    require(sorted(comparisons, key=lambda x: x["paired_case_id"]) == recomputed, "comparisons not reproducible")
    summary = strict_json(root / "artifacts" / "summary.json")
    require(summary["paired_case_count"] == 12 and summary["trial_count"] == 48, "summary denominator mismatch")
    require(summary["rank_0_equal"] == sum(c["rank_0"]["equal"] for c in comparisons), "summary rank-0 mismatch")
    require(summary["ordered_top_k_equal"] == sum(c["ordered_top_k"]["equal"] for c in comparisons), "summary ordered mismatch")
    require(summary["membership_equal"] == sum(c["membership"]["equal"] for c in comparisons), "summary membership mismatch")
    for lane in ("numpy", "python"):
        require(summary["exact_ties"][lane]["full_ranking_group_count"] == sum(c["exact_ties"][lane]["group_count"] for c in comparisons), f"summary tie-group mismatch: {lane}")
        require(summary["exact_ties"][lane]["full_ranking_participant_count"] == sum(c["exact_ties"][lane]["participant_count"] for c in comparisons), f"summary tie-participant mismatch: {lane}")
        require(summary["exact_ties"][lane]["top_k_intersecting_group_count"] == sum(len(c["exact_ties"][lane]["intersecting_top_k"]) for c in comparisons), f"summary top-k tie mismatch: {lane}")
        require(summary["exact_ties"][lane]["top_k_boundary_crossing_group_count"] == sum(len(c["exact_ties"][lane]["crossing_top_k_boundary"]) for c in comparisons), f"summary boundary tie mismatch: {lane}")
    controls = strict_json(root / "artifacts" / "controls" / "controls.json")
    require(controls["positive"]["results"]["numpy"]["ordered"] != controls["positive"]["results"]["python"]["ordered"], "positive control vacuous")
    require(controls["exact_tie"]["ascending_id"] and all(v["ordered"] == ["alpha", "mu", "zeta"] for v in controls["exact_tie"]["results"].values()), "exact tie control failed")
    require(controls["negative"]["comparison_equal"], "negative control failed")
    report = (root / "REPORT.md").read_text(encoding="utf-8")
    for value in (f"{summary['rank_0_equal']}/12", f"{summary['ordered_top_k_equal']}/12", f"{summary['membership_equal']}/12"):
        require(value in report, f"report claim missing: {value}")
    for lane in ("numpy", "python"):
        require(str(summary["exact_ties"][lane]["full_ranking_group_count"]) in report, f"report tie claim missing: {lane}")
    require("### Per corpus" in report and "### Per query" in report, "report breakdown tables missing")
    if summary["rank_0_equal"] == summary["ordered_top_k_equal"] == summary["membership_equal"] == 12:
        require("No disagreement was observed in this fixed 12-case suite." in report, "required no-disagreement wording missing")
    manifest = strict_json(root / "artifacts" / "manifest.json")
    require(manifest["submission_state"] == "not_published", "local hold missing")
    for relative, expected in manifest["file_sha256"].items():
        require(sha256(root / relative) == expected, f"manifest mismatch: {relative}")
    private_tokens = ("working/", "working\\", "local-arc4-research", "C:\\Users\\Admin")
    for relative in manifest["public_safe_export_inventory"]:
        require(not any(token in relative for token in private_tokens), f"private path in public-safe inventory: {relative}")
    for path in required + [str(p.relative_to(root)) for p in paths]:
        require("\u2014" not in (root / path).read_text(encoding="utf-8"), f"U+2014 found: {path}")
    return {"status": "PASS", "trials": 48, "paired_cases": 12, "comparisons_sha256": sha256(root / "artifacts" / "comparisons.jsonl"), "manifest_sha256": sha256(root / "artifacts" / "manifest.json")}


def self_test() -> list[str]:
    rejected = []
    mutations = {
        "score": lambda root: _mutate_score(root), "remove_trial": lambda root: next((root / "artifacts" / "raw").glob("*.json")).unlink(),
        "lane_label": lambda root: _mutate_json(next((root / "artifacts" / "raw").glob("*.json")), "lane_requested", "corrupt"),
        "summary": lambda root: _mutate_summary(root),
    }
    with tempfile.TemporaryDirectory(prefix="jcm-lane-tamper-") as name:
        base = Path(name)
        for label, mutation in mutations.items():
            target = base / label; shutil.copytree(HERE, target, ignore=shutil.ignore_patterns("working", "__pycache__"))
            mutation(target)
            try: verify(target)
            except VerificationError: rejected.append(label)
    require(set(rejected) == set(mutations), f"tamper self-test mismatch: {rejected}")
    return rejected


def _mutate_json(path: Path, key: str, value: Any) -> None:
    data = strict_json(path); data[key] = value; path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _mutate_score(root: Path) -> None:
    path = next((root / "artifacts" / "raw" / "scores").glob("*.json")); data = strict_json(path)
    data["scores"][0]["final_hex"] = (float.fromhex(data["scores"][0]["final_hex"]) + 0.25).hex()
    path.write_text(canonical(data) + "\n", encoding="utf-8")


def _mutate_summary(root: Path) -> None:
    path = root / "artifacts" / "summary.json"; data = strict_json(path); data["rank_0_equal"] -= 1
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--self-test", action="store_true"); parser.add_argument("--write-receipt", action="store_true"); args = parser.parse_args()
    result = verify()
    if args.self_test: result["tamper_rejections"] = self_test(); result["self_test"] = "PASS"
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.write_receipt:
        temporary = HERE / "verification.txt.tmp"; temporary.write_text(rendered, encoding="utf-8", newline="\n"); temporary.replace(HERE / "verification.txt")
    print(rendered, end=""); return 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except VerificationError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, indent=2), file=sys.stderr); raise SystemExit(1)
