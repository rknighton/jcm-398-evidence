from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import DESIGN_SHA256
from .artifacts import CANONICAL_PACKET_PATHS
from .cases import validate_frozen_cases
from .common import ContractError, atomic_write, atomic_write_new, canonical_json, canonical_json_bytes, exact_keys, iter_files, load_json, require, sha256_bytes, sha256_file
from .controls import validate_control_records
from .environment import OFFICIAL_WHEEL_SHA256, validate_bound_environment, validate_environment_lock
from .metrics import compare_pair, ordering_sha256
from .p0 import CLAIM_CEILING as P0_CLAIM_CEILING, EMPTY_SHA256, SOURCE_COMMIT, validate_p0_receipt

EXCLUDED_MANIFEST_PATHS = {"MANIFEST.json", "MANIFEST.sha256", "verification.txt"}
P0_NONCOVERAGE = ["bit_reproducible_build", "publisher_build_environment", "end_to_end_supply_chain_authenticity"]
P0_REPORT_SENTENCE = "Provenance claim ceiling: newline-normalized payload equivalence only. This does not establish a reproducible build, the publisher build environment, or end-to-end supply-chain authenticity."
M9_CATEGORIES = (
    "public_tool_errors", "lane_mismatches", "fallback_firings",
    "embed_write_tripwire_firings", "failed_preconditions", "infrastructure_failures",
)
M9_ERROR_CODES = {
    "public_tool_error": "public_tool_errors", "lane_mismatch": "lane_mismatches",
    "fallback_firing": "fallback_firings", "embed_write_tripwire_firing": "embed_write_tripwire_firings",
    "failed_precondition": "failed_preconditions", "infrastructure_failure": "infrastructure_failures",
}
M9_STAGE_RULES = {
    "public_tool_error": {"worker"}, "lane_mismatch": {"worker", "control"},
    "fallback_firing": {"worker", "control"}, "embed_write_tripwire_firing": {"worker", "control"},
    "failed_precondition": {"setup", "p0", "worker", "control", "verification"},
    "infrastructure_failure": {"setup", "p0", "environment", "worker", "timeout", "control", "commit", "consolidation", "verification"},
}


def normalize_failure_error_code(stage: str, classification: str, cause_code: str) -> str:
    if classification == "infrastructure" or cause_code in {"network_attempt", "network_tripwire"}:
        normalized = "infrastructure_failure"
    elif cause_code in {"public_error", "warmup_error", "debug_public_error", "public_tool_error"}:
        normalized = "public_tool_error"
    elif cause_code in {"lane_selection", "numpy_absence", "numpy_present", "numpy_absence_after", "numpy_present_after", "cache_lane_before", "cache_lane_after", "lane_mismatch"}:
        normalized = "lane_mismatch"
    elif cause_code in {"fallback_fired", "fallback_firing"}:
        normalized = "fallback_firing"
    elif cause_code in {"provider_topup", "database_mutation", "embed_write_tripwire_firing"}:
        normalized = "embed_write_tripwire_firing"
    else:
        normalized = "failed_precondition"
    require(stage in M9_STAGE_RULES[normalized], "failure_category_stage", f"{stage}:{normalized}")
    return normalized


def failure_category(record: Mapping[str, Any]) -> str:
    code = record.get("error_code")
    require(code in M9_ERROR_CODES, "failure_error_code_mapping", str(code))
    require(record.get("stage") in M9_STAGE_RULES[str(code)], "failure_stage_mapping", f"{record.get('stage')}:{code}")
    classification = record.get("classification")
    if code == "infrastructure_failure":
        require(classification == "infrastructure", "failure_classification_mapping", str(classification))
    elif code in {"public_tool_error", "lane_mismatch", "fallback_firing", "embed_write_tripwire_firing"}:
        require(classification == "product_lane", "failure_classification_mapping", str(classification))
    else:
        require(classification in {"protocol", "verification", "product_lane"}, "failure_classification_mapping", str(classification))
    require(record.get("methodology") in {"initial", "explicit_repair"}, "failure_methodology", str(record.get("methodology")))
    evidence = record.get("evidence")
    expected_evidence = {"cause_error_code"} | ({"repair_reason"} if record.get("methodology") == "explicit_repair" else set())
    if record.get("stage") == "worker" and isinstance(evidence, dict) and "worker_rejection" in evidence:
        expected_evidence.update({"worker_rejection", "invocation_evidence_id"})
    require(isinstance(evidence, dict) and set(evidence) == expected_evidence and isinstance(evidence.get("cause_error_code"), str) and bool(evidence["cause_error_code"]), "failure_evidence", str(evidence))
    if "worker_rejection" in expected_evidence:
        from .worker_protocol import metadata_free_worker_error, validate_worker_rejection
        validate_worker_rejection(evidence["worker_rejection"])
        require(isinstance(evidence["invocation_evidence_id"], str) and len(evidence["invocation_evidence_id"]) == 64, "failure_worker_evidence_id", str(evidence.get("invocation_evidence_id")))
        require(evidence["worker_rejection"]["error_code"] == evidence["cause_error_code"] and evidence["worker_rejection"]["m9_classification"] == code, "failure_worker_rejection_binding", str(evidence["worker_rejection"]))
        identity = record.get("row_identity")
        require(isinstance(identity, dict), "failure_worker_invocation_binding", str(identity))
        require(
            evidence["worker_rejection"]["lane"] == (None if metadata_free_worker_error(evidence["worker_rejection"]["error_code"]) else identity.get("lane")),
            "failure_worker_rejection_lane", str(evidence["worker_rejection"]["lane"]),
        )
    if record.get("methodology") == "explicit_repair":
        require(isinstance(evidence.get("repair_reason"), str) and bool(evidence["repair_reason"].strip()), "failure_repair_reason", str(evidence.get("repair_reason")))
    return M9_ERROR_CODES[str(code)]


def retain_failure_invocations(packet_root: Path, failures: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Copy each worker invocation used by the failure journal into the packet."""

    retained: list[dict[str, Any]] = []
    seen: set[str] = set()
    required = ("invocation-binding.json", "receipt.json", "job-artifact.json", "stdout.log", "stderr.log")
    for original in failures:
        record = json.loads(json.dumps(original))
        evidence = record.get("evidence")
        if record.get("stage") == "worker" and isinstance(evidence, dict) and "invocation_binding" in evidence:
            raw_rejection = "rejection" in evidence
            normalized_rejection = "worker_rejection" in evidence
            require(raw_rejection != normalized_rejection, "failure_worker_rejection_source", str(evidence.keys()))
            if raw_rejection:
                evidence["worker_rejection"] = evidence.pop("rejection")
            binding = evidence.pop("invocation_binding")
            evidence_id = evidence.get("invocation_evidence_id")
            require(isinstance(evidence_id, str) and len(evidence_id) == 64 and evidence_id not in seen, "failure_worker_evidence_id", str(evidence_id))
            seen.add(evidence_id)
            attempt_root = Path(binding["paths"]["attempt_root"]).resolve()
            actual = {path.name for path in attempt_root.iterdir() if path.is_file()}
            require(actual in (set(required), set(required) - {"job-artifact.json"}), "failure_worker_runtime_file_set", str(sorted(actual)))
            destination = packet_root / "invocations" / evidence_id
            for name in required:
                source = attempt_root / name
                if name == "job-artifact.json" and not source.is_file():
                    source = Path(binding["job"]["source_path"])
                    require(source.is_file() and sha256_file(source) == binding["job"]["sha256"] and source.stat().st_size == binding["job"]["bytes"], "failure_worker_source_recovery", str(source))
                destination_path = destination / name
                source_bytes = source.read_bytes()
                if destination_path.exists():
                    require(destination_path.is_file() and destination_path.read_bytes() == source_bytes, "failure_worker_destination_mismatch", str(destination_path))
                else:
                    atomic_write_new(destination_path, source_bytes, allowed_root=packet_root)
        retained.append(record)
    return retained


def build_source_inventory(
    *, packet_root: Path, cases: Mapping[str, Any], p0: Mapping[str, Any], lock: Mapping[str, Any],
    pypi_url: str, build_receipt: Mapping[str, Any], build_receipt_sha256: str,
    query_vector_values: Mapping[str, Sequence[float]],
) -> dict[str, Any]:
    validate_frozen_cases(cases)
    validate_p0_receipt(p0, require_pass=True)
    validate_environment_lock(lock, require_bound=True)
    query_hashes = {row["query_id"]: row["query_vector_sha256"] for row in cases["planned_rows"]}
    value = {
        "schema": "arc4.source-inventory/v1",
        "official_wheel": {"path": "inputs/jcodemunch_mcp-1.108.228-py3-none-any.whl", "sha256": OFFICIAL_WHEEL_SHA256, "pypi_url": pypi_url},
        "p0": {"path": "P0-RECEIPT.json", "sha256": sha256_file(packet_root / "P0-RECEIPT.json"), "status": p0["status"], "claim_ceiling": p0["claim_ceiling"]},
        "source": {
            "commit": SOURCE_COMMIT, "build_receipt": dict(build_receipt),
            "build_receipt_path": CANONICAL_PACKET_PATHS["source_build_receipt"],
            "build_receipt_sha256": build_receipt_sha256,
            "build_receipt_digest_path": CANONICAL_PACKET_PATHS["source_build_receipt_digest"],
            "build_receipt_digest_sha256": sha256_file(packet_root / CANONICAL_PACKET_PATHS["source_build_receipt_digest"]),
            "rebuilt_wheel_sha256": p0["rebuilt_sha256"],
        },
        "corpora": [{key: corpus[key] for key in ("name", "working_database_sha256", "candidate_ids_sha256", "candidate_count")} for corpus in cases["corpora"]],
        "query_vectors": [{"query_id": query_id, "vector": list(query_vector_values[query_id]), "sha256": query_hashes[query_id]} for query_id in sorted(query_hashes)],
        "environment": {"lock_path": "ENVIRONMENT-LOCK.json", "lock_sha256": sha256_file(packet_root / "ENVIRONMENT-LOCK.json"), "manifest_bindings": lock["manifest_bindings"]},
        "unreproducible_elements": P0_NONCOVERAGE,
    }
    validate_source_inventory(value, packet_root=packet_root, cases=cases, p0=p0, lock=lock)
    return value


def validate_source_inventory(value: Mapping[str, Any], *, packet_root: Path, cases: Mapping[str, Any], p0: Mapping[str, Any], lock: Mapping[str, Any]) -> None:
    from .common import exact_keys

    exact_keys(value, ("schema", "official_wheel", "p0", "source", "corpora", "query_vectors", "environment", "unreproducible_elements"), "source_inventory_keys")
    require(value["schema"] == "arc4.source-inventory/v1", "source_inventory_schema", str(value["schema"]))
    exact_keys(value["official_wheel"], ("path", "sha256", "pypi_url"), "source_official_keys")
    require(value["official_wheel"]["path"] == "inputs/jcodemunch_mcp-1.108.228-py3-none-any.whl" and value["official_wheel"]["sha256"] == OFFICIAL_WHEEL_SHA256 and isinstance(value["official_wheel"]["pypi_url"], str) and value["official_wheel"]["pypi_url"].startswith("https://files.pythonhosted.org/"), "source_official_wheel", str(value["official_wheel"]))
    official_path = packet_root / value["official_wheel"]["path"]
    require(official_path.is_file() and sha256_file(official_path) == OFFICIAL_WHEEL_SHA256, "source_official_file", str(official_path))
    exact_keys(value["p0"], ("path", "sha256", "status", "claim_ceiling"), "source_p0_keys")
    require(value["p0"]["path"] == "P0-RECEIPT.json" and value["p0"]["sha256"] == sha256_file(packet_root / "P0-RECEIPT.json") and value["p0"]["status"] == p0["status"] == "passed" and value["p0"]["claim_ceiling"] == p0["claim_ceiling"] == P0_CLAIM_CEILING, "source_p0", str(value["p0"]))
    exact_keys(value["source"], ("commit", "build_receipt", "build_receipt_path", "build_receipt_sha256", "build_receipt_digest_path", "build_receipt_digest_sha256", "rebuilt_wheel_sha256"), "source_checkout_keys")
    require(value["source"]["commit"] == SOURCE_COMMIT, "source_checkout", str(value["source"]))
    build = value["source"]["build_receipt"]
    exact_keys(build, ("schema", "source_commit", "git", "python", "build", "produced_wheel", "comparison_tool_sha256", "generator_sha256"), "source_build_receipt_keys")
    require(build["schema"] == "arc4.source-build-receipt/v2" and build["source_commit"] == SOURCE_COMMIT, "source_build_receipt", str(build))
    exact_keys(build["git"], ("head", "clean", "detached", "core_autocrlf", "status_sha256"), "source_build_git_keys")
    require(build["git"] == {"head": SOURCE_COMMIT, "clean": True, "detached": True, "core_autocrlf": "false", "status_sha256": EMPTY_SHA256}, "source_build_git_state", str(build["git"]))
    exact_keys(build["python"], ("implementation", "version", "cache_tag", "executable", "executable_sha256"), "source_build_python_keys")
    require(build["python"]["implementation"] == "CPython" and build["python"]["version"] == "3.13.7" and build["python"]["cache_tag"] == "cpython-313", "source_build_python", str(build["python"]))
    exact_keys(build["build"], ("backend", "backend_version", "command", "cwd", "environment"), "source_build_command_keys")
    require(build["build"]["backend"] == "hatchling" and build["build"]["backend_version"] == "1.31.0" and Path(build["build"]["command"][0]).resolve() == Path(build["python"]["executable"]).resolve() and build["build"]["command"][1:5] == ["-m", "build", "--wheel", "--no-isolation"] and Path(build["build"]["cwd"]).is_dir(), "source_build_command", str(build["build"]))
    require(isinstance(build["build"]["environment"], dict) and build["build"]["environment"].get("PYTHONNOUSERSITE") == "1" and build["build"]["environment"].get("PIP_NO_INDEX") == "1", "source_build_environment", str(build["build"]["environment"]))
    exact_keys(build["produced_wheel"], ("path", "sha256"), "source_build_wheel_keys")
    require(build["produced_wheel"]["sha256"] == p0["rebuilt_sha256"] and build["comparison_tool_sha256"] == build["generator_sha256"] == p0["comparison_tool_sha256"], "source_build_p0_binding", str(build))
    require(value["source"]["build_receipt_sha256"] == sha256_bytes(canonical_json_bytes(build)), "source_build_receipt_hash", str(value["source"]["build_receipt_sha256"]))
    receipt_path = packet_root / value["source"]["build_receipt_path"]
    digest_path = packet_root / value["source"]["build_receipt_digest_path"]
    require(value["source"]["build_receipt_path"] == CANONICAL_PACKET_PATHS["source_build_receipt"] and receipt_path.read_bytes() == canonical_json_bytes(build), "source_build_receipt_file", str(receipt_path))
    require(value["source"]["build_receipt_digest_path"] == CANONICAL_PACKET_PATHS["source_build_receipt_digest"] and digest_path.read_bytes() == (value["source"]["build_receipt_sha256"] + "\n").encode("ascii"), "source_build_digest_file", str(digest_path))
    require(value["source"]["build_receipt_digest_sha256"] == sha256_file(digest_path), "source_build_digest_hash", str(digest_path))
    require(value["source"]["rebuilt_wheel_sha256"] == p0["rebuilt_sha256"], "source_rebuilt_wheel", str(value["source"]["rebuilt_wheel_sha256"]))
    expected_corpora = [{key: corpus[key] for key in ("name", "working_database_sha256", "candidate_ids_sha256", "candidate_count")} for corpus in cases["corpora"]]
    require(value["corpora"] == expected_corpora, "source_corpora", "source inventory differs from frozen cases")
    query_vectors = value["query_vectors"]
    require(isinstance(query_vectors, list) and len(query_vectors) == 4 and [item["query_id"] for item in query_vectors] == sorted({row["query_id"] for row in cases["planned_rows"]}), "source_query_ids", str(query_vectors))
    expected_query_hashes = {row["query_id"]: row["query_vector_sha256"] for row in cases["planned_rows"]}
    require(all(set(item) == {"query_id", "vector", "sha256"} and isinstance(item["vector"], list) and len(item["vector"]) == 384 and item["sha256"] == expected_query_hashes[item["query_id"]] and sha256_bytes(canonical_json(item["vector"]).encode("utf-8")) == item["sha256"] for item in query_vectors), "source_query_hashes", str(query_vectors))
    exact_keys(value["environment"], ("lock_path", "lock_sha256", "manifest_bindings"), "source_environment_keys")
    require(value["environment"]["lock_path"] == "ENVIRONMENT-LOCK.json" and value["environment"]["lock_sha256"] == sha256_file(packet_root / "ENVIRONMENT-LOCK.json") and value["environment"]["manifest_bindings"] == lock["manifest_bindings"], "source_environment", str(value["environment"]))
    require(value["unreproducible_elements"] == P0_NONCOVERAGE, "source_noncoverage", str(value["unreproducible_elements"]))


def decompose_original_matrix(source_csv: Path) -> dict[str, Any]:
    try:
        with source_csv.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream, strict=True))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ContractError("original_matrix_csv", f"{source_csv}: {exc}") from exc
    require(len(rows) == 360, "original_matrix_rows", str(len(rows)))
    require(len({row.get("row_id") for row in rows}) == 360, "original_matrix_row_ids", "row IDs not unique")
    cases: dict[str, list[dict[str, str]]] = defaultdict(list)
    pairs: dict[str, list[dict[str, str]]] = defaultdict(list)
    modes = {row.get("mode") for row in rows}
    for row in rows:
        cases[str(row.get("case_id"))].append(row)
        pairs[str(row.get("pair_id"))].append(row)
        require(row.get("row_status") == "retained", "original_matrix_status", str(row.get("row_id")))
    require(len(cases) == 24 and all(len(group) == 15 for group in cases.values()), "original_matrix_cases", str(len(cases)))
    require(len(pairs) == 120 and all(len(group) == 3 for group in pairs.values()), "original_matrix_pairs", str(len(pairs)))
    require(len(modes) == 3 and all({row.get("mode") for row in group} == modes for group in pairs.values()), "original_matrix_modes", str(modes))
    return {
        "schema": "arc4.original-matrix-decomposition/v1", "source_csv_path": str(source_csv.resolve()),
        "source_csv_sha256": sha256_file(source_csv), "rows": 360, "unique_row_ids": 360,
        "case_ids": 24, "pair_ids": 120, "modes": sorted(str(mode) for mode in modes),
        "rows_per_case": 15, "rows_per_pair": 3, "cartesian_complete": True,
    }


def score_vector_bytes(scores: Mapping[str, str], *, expected_ids: set[str] | None = None) -> bytes:
    require(bool(scores) and all(isinstance(key, str) and isinstance(value, str) for key, value in scores.items()), "score_vector_shape", "nonempty hex-score mapping required")
    if expected_ids is not None:
        require(set(scores) == expected_ids, "score_vector_id_set", "missing or extra candidate IDs")
    payload = [canonical_json_bytes({"schema": "arc4.full-score-vector/v1"})]
    for symbol_id in sorted(scores):
        value = float.fromhex(scores[symbol_id])
        require(value == value and value not in (float("inf"), float("-inf")), "score_vector_nonfinite", symbol_id)
        require(value.hex() == scores[symbol_id], "score_hex_noncanonical", symbol_id)
        payload.append(canonical_json_bytes({"symbol_id": symbol_id, "score_hex": scores[symbol_id]}))
    return b"".join(payload)


def materialize_full_rankings(row: Mapping[str, Any], full_rankings_root: Path, *, expected_ids: set[str] | None = None) -> dict[str, Any]:
    require(row.get("arm") == "matrix", "full_ranking_arm", "only matrix rows have score vectors")
    raw = row.get("raw_cosine")
    final = row.get("final_scores")
    require(isinstance(raw, dict) and isinstance(final, dict), "full_ranking_scores", str(row.get("row_id")))
    references: dict[str, Any] = {}
    for kind, scores in (("raw_cosine", raw), ("final", final)):
        if kind == "final" and scores == raw:
            references[kind] = {"same_as": "raw_cosine"}
            continue
        payload = score_vector_bytes(scores, expected_ids=expected_ids)
        path = full_rankings_root / f"{row['row_id']}--{kind}.jsonl"
        atomic_write(path, payload, allowed_root=full_rankings_root.parent)
        references[kind] = {"path": path.relative_to(full_rankings_root.parent.parent).as_posix(), "sha256": sha256_bytes(payload), "size": len(payload)}
    decoded_final = {key: float.fromhex(value) for key, value in final.items()}
    return {"files": references, "full_depth_ordering_sha256": ordering_sha256(decoded_final)}


def build_preregistration_inputs(
    *, design_path: Path, config_path: Path, frozen_cases_path: Path,
    environment_lock_path: Path, p0_receipt_path: Path, source_inventory_path: Path,
    packet_root: Path, approved_utc: str,
) -> dict[str, Any]:
    require(sha256_file(design_path) == DESIGN_SHA256, "design_hash", str(design_path))
    cases = load_json(frozen_cases_path)
    validate_frozen_cases(cases)
    p0 = load_json(p0_receipt_path)
    validate_p0_receipt(p0, require_pass=True)
    lock = load_json(environment_lock_path)
    validate_environment_lock(lock, require_bound=True)
    validate_bound_environment(lock, packet_root=packet_root)
    source_inventory = load_json(source_inventory_path)
    validate_source_inventory(source_inventory, packet_root=packet_root, cases=cases, p0=p0, lock=lock)
    require(approved_utc.endswith("Z"), "approval_timestamp", "explicit UTC timestamp ending in Z required")
    return {
        "schema": "arc4.preregistration-inputs/v1",
        "approved_utc": approved_utc,
        "design_sha256": DESIGN_SHA256,
        "config_sha256": sha256_file(config_path),
        "frozen_cases_sha256": sha256_file(frozen_cases_path),
        "environment_lock_sha256": sha256_file(environment_lock_path),
        "p0_receipt_sha256": sha256_file(p0_receipt_path),
        "source_inventory_sha256": sha256_file(source_inventory_path),
        "run_id": cases["run_id"],
        "matrix_rows": 240,
        "matrix_pairs": 120,
        "preflight_rows": 24,
        "preflight_pairs": 12,
        "claim_ceiling": "fixed_suite_descriptive_only_no_inference",
        "p0_claim_ceiling": P0_CLAIM_CEILING,
        "p0_does_not_establish": P0_NONCOVERAGE,
        "no_early_stop": True,
        "verdict_requires_complete_coverage": True,
    }


def _decode_scores(value: Mapping[str, str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for symbol_id, score_hex in value.items():
        require(isinstance(symbol_id, str) and isinstance(score_hex, str), "score_encoding", str(symbol_id))
        result[symbol_id] = float.fromhex(score_hex)
    return result


def pair_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        require(not row.get("is_control", False), "control_row_leak", str(row.get("row_id")))
        groups[str(row["pair_id"])].append(row)
    paired: list[dict[str, Any]] = []
    for pair_id in sorted(groups):
        pair = groups[pair_id]
        require(len(pair) == 2, "pair_size", pair_id)
        by_lane = {str(row["lane"]): row for row in pair}
        require(set(by_lane) == {"numpy_present", "numpy_absent"}, "pair_lanes", pair_id)
        left, right = by_lane["numpy_present"], by_lane["numpy_absent"]
        require(left["arm"] == right["arm"] and left["case_id"] == right["case_id"], "pair_identity", pair_id)
        require(left.get("attempt_n") == right.get("attempt_n") and left.get("attempt_methodology") == right.get("attempt_methodology") and left.get("repair_reason") == right.get("repair_reason"), "pair_attempt_provenance", pair_id)
        attempt_n = left.get("attempt_n")
        methodology = left.get("attempt_methodology")
        repair_reason = left.get("repair_reason")
        require(isinstance(attempt_n, int) and not isinstance(attempt_n, bool) and attempt_n >= 1 and methodology in {"initial", "explicit_repair"}, "pair_attempt_contract", pair_id)
        require((methodology == "initial" and attempt_n == 1 and repair_reason is None) or (methodology == "explicit_repair" and attempt_n >= 2 and isinstance(repair_reason, str) and bool(repair_reason.strip())), "pair_repair_reason", pair_id)
        base = {"schema": "arc4.paired-comparison/v1", "pair_id": pair_id, "problem_id": left["problem_id"], "case_id": left["case_id"], "arm": left["arm"], "row_ids": {"numpy_present": left["row_id"], "numpy_absent": right["row_id"]}, "attempt": {"attempt_n": attempt_n, "methodology": methodology, "repair_reason": repair_reason}}
        if left["arm"] == "matrix":
            metrics = compare_pair(
                _decode_scores(left["final_scores"]), _decode_scores(right["final_scores"]), int(left["top_k"]),
                numpy_raw_cosine=_decode_scores(left["raw_cosine"]), python_raw_cosine=_decode_scores(right["raw_cosine"]),
                include_hybrid_final=not bool(left["serialized_args"].get("semantic_only")),
            )
            paired.append({**base, "metrics": metrics})
        else:
            paired.append({**base, "metrics": {"m1_m9_only": True, "public_order_equal": left["public_result_ids"] == right["public_result_ids"]}})
    return paired


def validate_within_lane_determinism(rows: Sequence[Mapping[str, Any]]) -> None:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("arm") == "matrix":
            groups[(str(row["case_id"]), str(row["lane"]))].append(row)
    require(len(groups) == 48 and all(len(group) == 5 for group in groups.values()), "m7_coverage", "48 case/lane groups of five required")
    for identity, group in groups.items():
        reference = group[0]
        top_k = int(reference["top_k"])
        reference_top_scores = [reference["final_scores"][symbol_id] for symbol_id in reference["public_result_ids"][:top_k]]
        for row in group[1:]:
            candidate_top_scores = [row["final_scores"][symbol_id] for symbol_id in row["public_result_ids"][:top_k]]
            require(row["public_result_ids"] == reference["public_result_ids"], "m7_order", str(identity))
            require(row["full_depth_ordering_sha256"] == reference["full_depth_ordering_sha256"], "m7_full_depth", str(identity))
            require(candidate_top_scores == reference_top_scores, "m7_top_scores", str(identity))


def _margin_aggregate(matrix: Sequence[Mapping[str, Any]], lane_key: str, location: str, kind: str) -> dict[str, Any]:
    finite: list[float] = []
    counts = {"+inf": 0, "exact_tie": 0, "insufficient_ranking": 0, "finite_zero": 0}
    for pair in matrix:
        value = pair["metrics"][lane_key][location]
        if value == "insufficient_ranking":
            counts["insufficient_ranking"] += 1
            continue
        item = value[kind]
        if item in ("+inf", "exact_tie"):
            counts[item] += 1
        else:
            numeric = float(item)
            require(numeric >= 0.0 and numeric == numeric, "m11_value", str(item))
            finite.append(numeric)
            counts["finite_zero"] += numeric == 0.0
    from .metrics import numeric_summary
    return {"finite": numeric_summary(finite) if finite else "no_finite_values", **counts}


def validate_attempt_provenance(pairs: Sequence[Mapping[str, Any]], failures: Sequence[Mapping[str, Any]], repairs: Sequence[Mapping[str, Any]], *, run_id: str) -> dict[str, Any]:
    failures_by_pair: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    rowless = 0
    for failure in failures:
        identity = failure["row_identity"]
        require(identity["run_id"] == run_id, "failure_run_id", str(identity["run_id"]))
        require(isinstance(failure["attempt_n"], int) and not isinstance(failure["attempt_n"], bool) and failure["attempt_n"] >= 1, "failure_attempt_n", str(failure["attempt_n"]))
        if identity["pair_id"] is None:
            require(all(identity[key] is None for key in ("row_id", "case_id", "problem_id", "arm", "lane")), "rowless_failure_identity", str(identity))
            require(failure["stage"] in {"setup", "p0", "environment", "control", "consolidation", "verification"} and failure["attempt_n"] == 1 and failure["methodology"] == "initial", "rowless_failure_semantics", str(failure))
            rowless += 1
        else:
            if failure["stage"] in {"setup", "worker", "timeout", "commit"}:
                failures_by_pair[str(identity["pair_id"])].append(failure)
    attempts_by_number: dict[str, int] = defaultdict(int)
    repaired_successes = 0
    known_pairs = {str(pair["pair_id"]) for pair in pairs}
    require(set(failures_by_pair) <= known_pairs, "failure_unknown_pair", str(sorted(set(failures_by_pair) - known_pairs)))
    repair_by_attempt: dict[tuple[str, int], Mapping[str, Any]] = {}
    for repair in repairs:
        exact_keys(repair, ("schema", "run_id", "pair_id", "case_id", "problem_id", "arm", "attempt_n", "repair_reason", "row_ids"), "repair_declaration_keys")
        require(repair["schema"] == "arc4.repair-declaration/v1" and isinstance(repair["attempt_n"], int) and not isinstance(repair["attempt_n"], bool) and repair["attempt_n"] >= 2, "repair_declaration_record", str(repair))
        require(isinstance(repair["repair_reason"], str) and bool(repair["repair_reason"].strip()), "repair_declaration_reason", str(repair))
        key = (str(repair["pair_id"]), int(repair["attempt_n"]))
        require(key not in repair_by_attempt, "repair_declaration_duplicate", str(key))
        require(key[0] in known_pairs, "repair_declaration_unknown_pair", key[0])
        repair_by_attempt[key] = repair
    used_repairs: set[tuple[str, int]] = set()
    for pair in pairs:
        exact_keys(pair["attempt"], ("attempt_n", "methodology", "repair_reason"), "paired_attempt_keys")
        success_n = int(pair["attempt"]["attempt_n"])
        related = failures_by_pair.get(str(pair["pair_id"]), [])
        for declaration in (item for (declared_pair, _), item in repair_by_attempt.items() if declared_pair == str(pair["pair_id"])):
            require(declaration["run_id"] == run_id and declaration["case_id"] == pair["case_id"] and declaration["problem_id"] == pair["problem_id"] and declaration["arm"] == pair["arm"] and declaration["row_ids"] == pair["row_ids"], "repair_declaration_identity", str(pair["pair_id"]))
        failure_attempts = [int(item["attempt_n"]) for item in related]
        require(all(count == 1 for count in Counter(failure_attempts).values()), "attempt_duplicate", f"{pair['pair_id']}:{failure_attempts}")
        require(sorted(failure_attempts) == list(range(1, success_n)), "attempt_sequence", f"{pair['pair_id']}:{failure_attempts}->{success_n}")
        expected_rows = pair["row_ids"]
        for failure in related:
            identity = failure["row_identity"]
            pair_identity = identity["pair_id"] == pair["pair_id"] and identity["case_id"] == pair["case_id"] and identity["problem_id"] == pair["problem_id"] and identity["arm"] == pair["arm"]
            lane_identity = (identity["lane"] is None and identity["row_id"] is None) or (identity["lane"] in expected_rows and identity["row_id"] == expected_rows[identity["lane"]])
            require(pair_identity and lane_identity, "failure_pair_identity", str(identity))
            expected_methodology = "initial" if failure["attempt_n"] == 1 else "explicit_repair"
            require(failure["methodology"] == expected_methodology, "failure_attempt_methodology", str(failure["attempt_n"]))
            if failure["attempt_n"] >= 2:
                declaration_key = (str(pair["pair_id"]), int(failure["attempt_n"]))
                declaration = repair_by_attempt.get(declaration_key)
                if declaration is None:
                    require(failure["evidence"].get("cause_error_code") == "repair_declaration_persistence" and isinstance(failure["evidence"].get("repair_reason"), str) and bool(failure["evidence"]["repair_reason"].strip()), "failure_repair_declaration", str(declaration_key))
                else:
                    require(failure["evidence"].get("repair_reason") == declaration["repair_reason"], "failure_repair_declaration", str(declaration_key))
                    used_repairs.add(declaration_key)
            attempts_by_number[str(failure["attempt_n"])] += 1
        attempts_by_number[str(success_n)] += 1
        if success_n == 1:
            require(pair["attempt"] == {"attempt_n": 1, "methodology": "initial", "repair_reason": None}, "successful_initial_provenance", pair["pair_id"])
        else:
            require(pair["attempt"]["methodology"] == "explicit_repair" and isinstance(pair["attempt"]["repair_reason"], str) and bool(pair["attempt"]["repair_reason"].strip()), "successful_repair_provenance", pair["pair_id"])
            declaration_key = (str(pair["pair_id"]), success_n)
            declaration = repair_by_attempt.get(declaration_key)
            require(declaration is not None, "successful_repair_declaration", pair["pair_id"])
            require(declaration["run_id"] == run_id and declaration["case_id"] == pair["case_id"] and declaration["problem_id"] == pair["problem_id"] and declaration["arm"] == pair["arm"] and declaration["row_ids"] == pair["row_ids"] and declaration["repair_reason"] == pair["attempt"]["repair_reason"], "successful_repair_declaration", pair["pair_id"])
            used_repairs.add(declaration_key)
            repaired_successes += 1
    require(used_repairs == set(repair_by_attempt), "repair_declaration_orphan", str(sorted(set(repair_by_attempt) - used_repairs)))
    return {"attempts_by_number": dict(sorted(attempts_by_number.items(), key=lambda item: int(item[0]))), "successful_repair_pairs": repaired_successes, "repair_declarations": len(repairs), "rowless_failures": rowless}


def build_summary(pairs: Sequence[Mapping[str, Any]], controls: Sequence[Mapping[str, Any]], failures: Sequence[Mapping[str, Any]] = (), repairs: Sequence[Mapping[str, Any]] = (), *, run_id: str) -> dict[str, Any]:
    validate_control_records(list(controls))
    matrix = [pair for pair in pairs if pair["arm"] == "matrix"]
    preflight = [pair for pair in pairs if pair["arm"] == "preflight"]
    require(len(matrix) == 120 and len(preflight) == 12, "pair_coverage", f"matrix={len(matrix)} preflight={len(preflight)}")
    metrics = ("m1_rank0_difference", "m2_ordered_top_k_difference", "m3_membership_top_k_difference", "m4_exact_tie_difference")
    counts: dict[str, Any] = {}
    for metric in metrics:
        eligible = [pair for pair in matrix if metric != "m1_rank0_difference" or pair["metrics"]["m1_status"] == "eligible"]
        pair_count = sum(pair["metrics"].get(metric) is True for pair in eligible)
        problem_flags: dict[str, list[bool]] = defaultdict(list)
        for pair in eligible:
            problem_flags[pair["problem_id"]].append(pair["metrics"].get(metric) is True)
        heterogeneous = sorted(problem for problem, values in problem_flags.items() if len(set(values)) > 1)
        counts[metric] = {
            "pair_numerator": pair_count, "pair_denominator": len(eligible), "pair_excluded_no_results": 120 - len(eligible) if metric == "m1_rank0_difference" else 0, "pair_independence_level": "replicated_pair",
            "problem_numerator": sum(any(values) for values in problem_flags.values()), "problem_denominator": len(problem_flags),
            "problem_independence_level": "ranking_problem_not_independent_draw",
            "heterogeneous_within_problem": heterogeneous,
        }
    def aggregate_m10(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        require(bool(items), "m10_coverage", "at least one pair required")
        return {"pair_count": len(items), "candidate_comparisons": sum(item["candidate_count"] for item in items), "maximum_absolute_delta": max(item["max"] for item in items), "bit_identical": sum(item["bit_identical"] for item in items)}

    m10_raw = [pair["metrics"]["m10_raw_cosine"] for pair in matrix]
    m10_hybrid = [pair["metrics"]["m10_hybrid_final"] for pair in matrix if "m10_hybrid_final" in pair["metrics"]]
    require(len(m10_raw) == 120 and len(m10_hybrid) == 60, "m10_arm_coverage", f"raw={len(m10_raw)} hybrid={len(m10_hybrid)}")
    m11 = {}
    for lane_key in ("m11_numpy_order", "m11_python_order"):
        m11[lane_key] = {}
        for location in ("boundary", "minimum_internal"):
            m11[lane_key][location] = {
                kind: _margin_aggregate(matrix, lane_key, location, kind)
                for kind in ("observed", "conservative")
            }
    divergence = [pair["metrics"]["m12_first_divergence_rank"] for pair in matrix]
    categories: list[str] = []
    for failure in failures:
        exact_keys(failure, ("schema", "stage", "classification", "error_code", "reason", "attempt_n", "row_identity", "methodology", "evidence"), "summary_failure_keys")
        require(failure["schema"] == "arc4.failure/v1" and isinstance(failure["attempt_n"], int) and not isinstance(failure["attempt_n"], bool) and failure["attempt_n"] >= 1, "summary_failure_record", str(failure))
        categories.append(failure_category(failure))
    attempt_summary = validate_attempt_provenance(pairs, failures, repairs, run_id=run_id)
    failure_counts = {key: categories.count(key) for key in M9_CATEGORIES}
    return {
        "schema": "arc4.summary/v1", "verdict": "complete", "matrix_rows_observed": 240,
        "matrix_pairs_observed": 120, "preflight_rows_observed": 24, "preflight_pairs_observed": 12,
        "unique_query_vectors": 4, "ranking_problems": 12,
        "independence": {
            "matrix": {
                "unique_query_vectors": {"count": 4, "meaning": "query_diversity_ceiling"},
                "ranking_problems": {"count": 12, "meaning": "closest_unit_not_independent_draws"},
                "case_identities": {"count": 24, "meaning": "cache_nuisance_not_independent"},
                "case_executions": {"count": 120, "meaning": "replicates_not_new_cases"},
                "measured_rows": {"count": 240, "meaning": "two_lanes_per_pair"},
            },
            "preflight": {
                "ranking_problems": {"count": 6, "meaning": "contract_check_only"},
                "case_identities": {"count": 12, "meaning": "not_findings"},
                "case_executions": {"count": 12, "meaning": "one_execution_per_pair"},
                "measured_rows": {"count": 24, "meaning": "two_lanes_per_pair"},
            },
        },
        "counts": counts,
        "m5_top_k_inversions": sum(pair["metrics"]["m5_top_k_inversion_count"] for pair in matrix),
        "m5_full_inversions": sum(pair["metrics"]["m5_full_inversion_count"] for pair in matrix),
        "m6_top_k_genuine_disagreements": sum(pair["metrics"]["m6_top_k_genuine_disagreement_count"] for pair in matrix),
        "m6_full_genuine_disagreements": sum(pair["metrics"]["m6_full_genuine_disagreement_count"] for pair in matrix),
        "m9": {**failure_counts, "total": len(failures), **attempt_summary, "explicit_repair_failures": sum(item["methodology"] == "explicit_repair" for item in failures)},
        "m10": {"raw_cosine": aggregate_m10(m10_raw), "hybrid_final": aggregate_m10(m10_hybrid)},
        "m11": m11,
        "m12": {"none": sum(value is None for value in divergence), "first_divergence_histogram": {str(rank): divergence.count(rank) for rank in sorted({value for value in divergence if value is not None})}},
        "controls_passed": 21, "controls_expected": 21,
        "claim_ceiling": "fixed_suite_descriptive_only_no_inference",
    }


def build_report(summary: Mapping[str, Any]) -> str:
    require(summary.get("schema") == "arc4.summary/v1", "summary_schema", "unexpected summary schema")
    lines = [
        "# Arc 4 production-lane comparison v2 report",
        "",
        f"Verdict: **{summary['verdict']}**.",
        "",
        "This is a census of a fixed purposive suite: 12 ranking problems over 4 frozen query vectors. It is not a random sample. No p-values, confidence intervals, hypothesis tests, prevalence rates, timing conclusions, or memory conclusions are reported.",
        "",
        "The paired denominator is 120 replicated lane comparisons. The problem denominator is 12 non-independent ranking problems. Repetitions and cache states add repeatability evidence, not query diversity.",
        "",
    ]
    titles = (
        ("m1_rank0_difference", "M1 rank-0 difference"),
        ("m2_ordered_top_k_difference", "M2 ordered top-k difference"),
        ("m3_membership_top_k_difference", "M3 top-k membership difference"),
        ("m4_exact_tie_difference", "M4 exact-tie partition difference"),
    )
    for key, title in titles:
        value = summary["counts"][key]
        lines.extend([
            f"## {title}", "", "| Unit | Numerator | Denominator | Independence |", "| --- | ---: | ---: | --- |",
            f"| Paired comparisons | {value['pair_numerator']} | {value['pair_denominator']} | replicated pair |",
            f"| Ranking problems | {value['problem_numerator']} | {value['problem_denominator']} | not independent draws |",
            "", f"Heterogeneous within problem: {', '.join(value['heterogeneous_within_problem']) or 'none'}.", "",
        ])
        if key == "m1_rank0_difference":
            lines.extend([f"Excluded no-results pairs: {value['pair_excluded_no_results']}.", ""])
    lines.extend([
        "## M9 failures and lane-selection mismatches", "",
        f"Public-tool errors: {summary['m9']['public_tool_errors']}; lane mismatches: {summary['m9']['lane_mismatches']}; fallback firings: {summary['m9']['fallback_firings']}; embed-write tripwire firings: {summary['m9']['embed_write_tripwire_firings']}; failed preconditions: {summary['m9']['failed_preconditions']}; infrastructure failures: {summary['m9']['infrastructure_failures']}; total failed attempts: {summary['m9']['total']}; explicit-repair failures: {summary['m9']['explicit_repair_failures']}; successful repair pairs: {summary['m9']['successful_repair_pairs']}; repair declarations: {summary['m9']['repair_declarations']}; rowless failures: {summary['m9']['rowless_failures']}.", "",
        f"Attempt-number accounting: `{canonical_json(summary['m9']['attempts_by_number'])}`.", "",
        "## M10 score-difference magnitude", "",
        f"Raw cosine: all {summary['m10']['raw_cosine']['pair_count']} matrix pairs, {summary['m10']['raw_cosine']['candidate_comparisons']} candidate comparisons, maximum absolute delta `{float(summary['m10']['raw_cosine']['maximum_absolute_delta']).hex()}`, and {summary['m10']['raw_cosine']['bit_identical']} bit-identical scores.", "",
        f"Hybrid final: {summary['m10']['hybrid_final']['pair_count']} hybrid matrix pairs, {summary['m10']['hybrid_final']['candidate_comparisons']} candidate comparisons, maximum absolute delta `{float(summary['m10']['hybrid_final']['maximum_absolute_delta']).hex()}`, and {summary['m10']['hybrid_final']['bit_identical']} bit-identical scores.", "",
        "## M11 ordering margins", "",
        "Observed and conservative margins were computed at each lane's top-k boundary and minimum internal top-k gap. Finite zero remains eligible; `+inf`, `exact_tie`, and `insufficient_ranking` are counted separately in SUMMARY.json.", "",
        "## M12 first divergence at full depth", "",
        f"No full-depth divergence: {summary['m12']['none']} of 120 pairs. First-divergence histogram: `{canonical_json(summary['m12']['first_divergence_histogram'])}`.", "",
        "## Claim ceiling", "",
        "A zero establishes only observed parity and measured score/margin behavior on this frozen suite. One or more findings establish only that the shipped lanes can diverge on these retained real inputs. Neither outcome establishes production incidence or behavior outside the frozen suite.",
        "", P0_REPORT_SENTENCE,
        "",
        "## Limitations", "",
        "Four researcher-authored query vectors are reused across three corpora. NumPy-lane results are BLAS-dependent. Full-depth hybrid numeric evidence relies on a reconstruction adapter whose public top-k parity is checked on every matrix row. The private-source-derived control corpus remains local.",
        "",
    ])
    return "\n".join(lines)


def assemble_results(*, packet_root: Path, rows_path: Path, controls_dir: Path) -> None:
    from .common import load_jsonl

    rows = load_jsonl(rows_path)
    cases = load_json(packet_root / "frozen-cases.json")
    validate_frozen_cases(cases)
    candidates_by_corpus = {item["name"]: set(item["candidate_ids"]) for item in cases["corpora"]}
    validate_within_lane_determinism(rows)
    controls = [load_json(path) for path in sorted(controls_dir.glob("C*.json"), key=lambda path: int(path.stem[1:]))]
    pairs = pair_rows(rows)
    failure_path = packet_root / "FAILURE-JOURNAL.jsonl"
    if not failure_path.exists():
        atomic_write(failure_path, b"", allowed_root=packet_root)
    failures = load_jsonl(failure_path)
    repair_path = packet_root / "REPAIR-JOURNAL.jsonl"
    if not repair_path.exists():
        atomic_write(repair_path, b"", allowed_root=packet_root)
    repairs = load_jsonl(repair_path)
    summary = build_summary(pairs, controls, failures, repairs, run_id=cases["run_id"])
    packet_rows: list[dict[str, Any]] = []
    warmups_by_pair: dict[str, dict[str, Any]] = defaultdict(dict)
    full_root = packet_root / "raw" / "full-rankings"
    for original in rows:
        row = dict(original)
        warmup = row.pop("warmup_result", None)
        if row["cache_state"] == "generation_warm":
            require(warmup is not None, "warmup_missing", row["row_id"])
            warmups_by_pair[row["pair_id"]][row["lane"]] = warmup
        else:
            require(warmup is None, "cold_has_warmup", row["row_id"])
        if row["arm"] == "matrix":
            final_scores = dict(row["final_scores"])
            expected_ids = candidates_by_corpus.get(row["corpus"])
            require(expected_ids is not None, "row_corpus_candidates", str(row["corpus"]))
            evidence = materialize_full_rankings(row, full_root, expected_ids=expected_ids)
            row["full_ranking_evidence"] = evidence["files"]
            row["top_k_score_hex"] = [final_scores[symbol_id] for symbol_id in row["public_result_ids"]]
            row.pop("raw_cosine")
            row.pop("final_scores")
        packet_rows.append(row)
    require(len(warmups_by_pair) == 66 and all(set(value) == {"numpy_present", "numpy_absent"} for value in warmups_by_pair.values()), "warmup_coverage", f"pairs={len(warmups_by_pair)}")
    warmup_rows = [{"schema": "arc4.warmup-pair/v1", "pair_id": pair_id, "lane_results": warmups_by_pair[pair_id]} for pair_id in sorted(warmups_by_pair)]
    atomic_write(packet_root / "raw" / "rows.jsonl", b"".join(canonical_json_bytes(row) for row in sorted(packet_rows, key=lambda row: row["row_id"])), allowed_root=packet_root)
    atomic_write(packet_root / "raw" / "warmups.jsonl", b"".join(canonical_json_bytes(row) for row in warmup_rows), allowed_root=packet_root)
    paired_payload = b"".join(canonical_json_bytes(pair) for pair in pairs)
    atomic_write(packet_root / "paired.jsonl", paired_payload, allowed_root=packet_root)
    atomic_write(packet_root / "SUMMARY.json", canonical_json_bytes(summary), allowed_root=packet_root)
    atomic_write(packet_root / "REPORT.md", build_report(summary).encode("utf-8"), allowed_root=packet_root)


def build_manifest(packet_root: Path) -> tuple[dict[str, Any], str]:
    files: list[dict[str, Any]] = []
    for path in iter_files(packet_root):
        relative = path.relative_to(packet_root).as_posix()
        if relative in EXCLUDED_MANIFEST_PATHS:
            continue
        files.append({"path": relative, "sha256": sha256_file(path), "size": path.stat().st_size})
    manifest = {"schema": "arc4.manifest/v1", "files": files}
    manifest_sha = sha256_bytes(canonical_json_bytes(manifest))
    return manifest, manifest_sha


def write_manifest(packet_root: Path) -> None:
    manifest, digest = build_manifest(packet_root)
    atomic_write(packet_root / "MANIFEST.json", canonical_json_bytes(manifest), allowed_root=packet_root)
    atomic_write(packet_root / "MANIFEST.sha256", (digest + "\n").encode("ascii"), allowed_root=packet_root)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prereg = sub.add_parser("preregistration-inputs")
    for name in ("design", "config", "frozen_cases", "environment_lock", "p0_receipt", "source_inventory"):
        prereg.add_argument(f"--{name.replace('_','-')}", dest=name, type=Path, required=True)
    prereg.add_argument("--packet-root", type=Path, required=True)
    prereg.add_argument("--approved-utc", required=True)
    prereg.add_argument("--output", type=Path, required=True)
    manifest = sub.add_parser("manifest")
    manifest.add_argument("packet_root", type=Path)
    original = sub.add_parser("original-matrix")
    original.add_argument("source_csv", type=Path)
    original.add_argument("output", type=Path)
    assemble = sub.add_parser("assemble-results")
    assemble.add_argument("packet_root", type=Path)
    assemble.add_argument("rows", type=Path)
    assemble.add_argument("controls", type=Path)
    ns = parser.parse_args(argv)
    try:
        if ns.command == "manifest":
            write_manifest(ns.packet_root.resolve())
        elif ns.command == "original-matrix":
            atomic_write(ns.output, canonical_json_bytes(decompose_original_matrix(ns.source_csv)), allowed_root=Path.cwd())
        elif ns.command == "assemble-results":
            assemble_results(packet_root=ns.packet_root.resolve(), rows_path=ns.rows.resolve(), controls_dir=ns.controls.resolve())
        else:
            value = build_preregistration_inputs(design_path=ns.design, config_path=ns.config, frozen_cases_path=ns.frozen_cases, environment_lock_path=ns.environment_lock, p0_receipt_path=ns.p0_receipt, source_inventory_path=ns.source_inventory, packet_root=ns.packet_root.resolve(), approved_utc=ns.approved_utc)
            atomic_write(ns.output, canonical_json_bytes(value), allowed_root=Path.cwd())
        return 0
    except ContractError as exc:
        parser.error(str(exc))
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
