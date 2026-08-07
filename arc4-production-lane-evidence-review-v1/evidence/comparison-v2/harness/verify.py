from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

RECEIPT_SCHEMA = "arc4.verification-receipt/v1"
SELF_TEST_PROGRESS_SCHEMA = "arc4.self-test-progress/v1"
SELF_TEST_PROGRESS_NAME = "self-test-progress.json"
SELF_TEST_PROGRESS_TEMP_NAME = ".self-test-progress.json.tmp"
SELF_TEST_PROGRESS_EXIT = 75
GENERATED_PACKET_FILES = {"verification.txt", SELF_TEST_PROGRESS_NAME}
OFFICIAL_WHEEL_SHA256 = "ff74b6344430053c6fad9064892d6a3904ffba6265823e3fba4dfde78f9a0488"
P0_CLAIM_CEILING = "payload_equivalence_under_declared_newline_normalization_only"
P0_NONCOVERAGE = ["bit_reproducible_build", "publisher_build_environment", "end_to_end_supply_chain_authenticity"]
P0_REPORT_SENTENCE = "Provenance claim ceiling: newline-normalized payload equivalence only. This does not establish a reproducible build, the publisher build environment, or end-to-end supply-chain authenticity."
CAMPAIGN_CONFIG_KEYS = (
    "schema", "run_id", "runtime_root", "packet_root", "harness_root", "python_executable",
    "wheelhouse", "lane_interpreters", "frozen_cases", "environment_lock", "preregistration_inputs",
    "preregistration_commit_receipt", "preregistration_repository", "corpora", "queries", "worker_timeout_seconds",
    "official_wheel", "source_checkout", "source_build_output", "source_build_receipt", "source_build_receipt_digest",
    "p0_receipt", "design_path", "frozen_config", "approved_utc", "pypi_url", "original_matrix_csv",
    "environment_capture_specs", "environment_lane_roots", "wheelhouse_spec", "wheelhouse_receipt", "child_environment",
)
SOURCE_BUILD_RECEIPT_PATH = "SOURCE-BUILD-RECEIPT.json"
SOURCE_BUILD_DIGEST_PATH = "SOURCE-BUILD-RECEIPT.sha256"
DESIGN_SHA256 = "4e885e262545660378ca508748ab5a8df49cf1aa8b2af96dda0a6748afe88fbe"
EXPECTED_MATRIX_ROWS = 240
EXPECTED_MATRIX_PAIRS = 120
EXPECTED_PREFLIGHT_ROWS = 24
EXPECTED_PREFLIGHT_PAIRS = 12
EXPECTED_CONTROLS = 21
CONTROL_SEMANTIC_SELF_TESTS = tuple(f"control_c{number}_semantic" for number in (*range(1, 17), 20, 21))
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
SELF_TESTS = (
    "lane_identity", "case_identity", "pair_identity", "query_vector_hash", "corpus_hash",
    "ordered_result_ids", "top_k_membership", "rank0", "tie_classification",
    "full_depth_ordering_hash", "coverage", "arm_assignment", "control_status", "summary_verdict",
    "both_lanes_mutated", "candidate_domain", "p0_receipt", "environment_binding",
    "preregistration_hash", "source_inventory", "synthetic_projection", "p0_claim_ceiling", "extra_packet_file",
    "network_attempt", "provider_topup", "incomplete_lane_execution", "debug_truncated", "paired_extra_metric", "frozen_sidecar_mutation",
    "debug_empty", "query_vector_observation", "summary_m10", "summary_schema",
    "summary_preflight_pairs", "summary_query_vectors", "summary_ranking_problems",
    "summary_control_total", "summary_claim_ceiling", "summary_independence",
    "summary_denominator", "summary_m9_categories",
    "repair_reason_removed", "repair_reason_changed", "repair_attempt_duplicate",
    "repair_attempt_gap", "repair_declaration_missing", "repair_identity_mismatch",
    "repair_row_attempt_changed", "repair_failure_identity_mismatch",
    "source_build_receipt_file", "source_build_digest_file", "campaign_alternate_path", "campaign_packet_root",
    "failure_row_run_id", "failure_rowless_run_id", "failure_bool_attempt",
    "failure_rowless_repair", "failure_wrong_lane", "failure_wrong_pair_identity", "worker_rejection_m9",
    "worker_network_address", "worker_invocation_binding",
    "invocation_opposite_lane_interpreter", "invocation_alternate_interpreter_path",
    "invocation_source_path", "invocation_artifact_path", "invocation_wrong_namespace",
    "invocation_stderr_refreshed", "invocation_job_refreshed", "invocation_alias",
    "invocation_job_corpus_refreshed", "invocation_job_source_refreshed", "invocation_job_config_refreshed",
    "invocation_orphan", "invocation_extra_file",
) + CONTROL_SEMANTIC_SELF_TESTS
CONTROL_PROJECTION_SHA256 = {
    "deep_rank_only": "bedecd719e0e6271b5e0841ff3438110d1b1a54aeb686c479bcc9337317cb9b0",
    "known_zero": "ad9a6233f10b6852720d1c34a83b6bf28abe65b70d5bcbadba4ea3db05e4aa58",
    "membership_boundary": "331e60f9adc0fb24cded154a2fa6bf333d2432aa3066e12a45ba365e36bb7f92",
    "one_ulp_cross": "9629b353eb95b38b5ad0305f69c80448410faabdc264901e482fbf4abac015ed",
    "ordered_only": "288b08e736b438fa738c9761e1d73d0fb674c2e48c76ed8abaf9c6454f4f5977",
    "rank0_swap": "ead676f06672a657beb07cb44d95fc445ecbc9b2b00ffd33d03bba7f67865f0a",
    "same_tie": "1c0c682bc4bae694dd72855d71863c28bd76714e0c3b142b98d24f24aa47b0a0",
    "tie_split": "01a01f54434b25f7ec4326660e01d5709f52e0b475783c60ca78668726090443",
    "unchanged_positive_gap": "8c9b0bdce60617f0985a01b27133d63e1dd3f2d7e9e25f124fa4dca431a3ffb7",
}
PROJECTION_KEYS = (
    "m1_rank0_difference", "m1_status", "m2_ordered_top_k_difference",
    "m3_membership_top_k_difference", "m4_exact_tie_difference", "m4_numpy", "m4_python",
    "m4_participant_symmetric_difference", "m5_top_k_inversion_count", "m5_full_inversion_count",
    "m6_top_k_genuine_disagreement_count", "m6_full_genuine_disagreement_count",
    "m11_numpy_order", "m11_python_order", "m12_first_divergence_rank", "overlaps",
)
PLANNED_JOB_KEYS = (
    "arm", "problem_id", "case_id", "pair_id", "corpus", "form_id", "query_id", "cache_state",
    "repetition", "top_k", "serialized_args", "serialized_args_sha256", "debug_observation_args",
    "debug_observation_args_sha256", "corpus_sha256", "candidate_ids_sha256", "candidate_count",
    "query_vector_sha256", "lane_invocation_order", "lane", "row_id",
)
PRODUCTION_JOB_KEYS = PLANNED_JOB_KEYS + (
    "schema", "run_id", "repo_id", "database", "storage_path", "package_root", "treatment_wheel",
    "config_path", "config_sha256",
    "environment_lock_path", "environment_lock_sha256", "candidate_ids", "query_text", "query_vector",
    "pair_invocation_ordinal", "frozen_source_files", "trial_source_files", "home_path", "attempt_n",
    "attempt_methodology", "repair_reason", "python_hash_seed", "embed_model", "execution_namespace",
    "is_control", "control_id",
)
FORBIDDEN_REPORT = re.compile(r"(?i)(p\s*[=:]\s*[0-9.]|(?:95\s*%\s*)?ci\s*[=:]\s*[\[(]|confidence_interval\s*[\":=]|hypothesis_test\s*[\":=]|wall_ns|scoring_ns|process_cpu_ns|peak_rss|rss_(?:before|after))")
FORBIDDEN_P0_CLAIM = re.compile(r"(?i)((?<!not )establish(?:es|ed)?\s+(?:a\s+)?(?:bit[- ]?)?reproducible\s+build|reproduc(?:es|ed)\s+the\s+publisher(?:'s)?\s+build\s+environment|(?:proves|establishes)\s+(?:end[- ]to[- ]end\s+)?supply[- ]chain\s+authenticity)")


class Rejected(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def need(condition: bool, code: str) -> None:
    if not condition:
        raise Rejected(code)


def exact(value: Any, keys: Sequence[str], code: str) -> None:
    need(isinstance(value, dict) and set(value) == set(keys), code)


def _validate_worker_invocation_binding(value: Any, record: Mapping[str, Any]) -> None:
    exact(value, ("schema", "run_id", "row_identity", "execution", "attempt", "job", "interpreter", "paths", "command"), "failure_worker_invocation_binding_keys")
    need(value["schema"] == "arc4.worker-invocation-binding/v2" and isinstance(value["run_id"], str) and bool(value["run_id"]), "failure_worker_invocation_binding")
    identity = value["row_identity"]
    exact(identity, ("row_id", "pair_id", "case_id", "problem_id", "arm", "lane"), "failure_worker_invocation_identity_keys")
    need(all(isinstance(identity[key], str) and bool(identity[key]) for key in ("row_id", "pair_id", "case_id", "problem_id")) and identity["arm"] in {"matrix", "preflight"} and identity["lane"] in {"numpy_present", "numpy_absent"}, "failure_worker_invocation_binding")
    failure_identity = record.get("row_identity")
    need(isinstance(failure_identity, dict) and value["run_id"] == failure_identity.get("run_id"), "failure_worker_invocation_binding")
    need(all(identity[key] == failure_identity.get(key) for key in identity), "failure_worker_invocation_binding")
    execution = value["execution"]
    exact(execution, ("namespace", "is_control", "control_id", "python_hash_seed"), "failure_worker_invocation_execution_keys")
    need(execution["namespace"] in {"measured", "preflight", "repair", "control"} and isinstance(execution["is_control"], bool), "failure_worker_invocation_execution")
    need((execution["is_control"] and execution["namespace"] == "control" and execution["control_id"] == "C9" and (execution["python_hash_seed"] is None or execution["python_hash_seed"] in {"0", "1", "2", "3", "4"})) or (not execution["is_control"] and execution["namespace"] != "control" and execution["control_id"] is None and isinstance(execution["python_hash_seed"], str)), "failure_worker_invocation_execution")
    attempt = value["attempt"]
    exact(attempt, ("attempt_n", "methodology", "repair_reason"), "failure_worker_invocation_attempt_keys")
    need(isinstance(attempt["attempt_n"], int) and not isinstance(attempt["attempt_n"], bool) and attempt["attempt_n"] >= 1, "failure_worker_invocation_attempt")
    need((attempt["methodology"] == "initial" and attempt["attempt_n"] == 1 and attempt["repair_reason"] is None) or (attempt["methodology"] == "explicit_repair" and attempt["attempt_n"] >= 2 and isinstance(attempt["repair_reason"], str) and bool(attempt["repair_reason"].strip())), "failure_worker_invocation_attempt")
    need(attempt == {"attempt_n": record.get("attempt_n"), "methodology": record.get("methodology"), "repair_reason": record.get("evidence", {}).get("repair_reason")}, "failure_worker_invocation_binding")
    job = value["job"]
    exact(job, ("source_path", "publication_path", "artifact_path", "sha256", "bytes"), "failure_worker_invocation_job_keys")
    need(all(isinstance(job[key], str) and Path(job[key]).is_absolute() for key in ("source_path", "publication_path", "artifact_path")) and sha256_text(job["sha256"]), "failure_worker_invocation_job")
    need(isinstance(job["bytes"], int) and not isinstance(job["bytes"], bool) and job["bytes"] > 0, "failure_worker_invocation_job")
    interpreter = value["interpreter"]
    exact(interpreter, ("lane_root", "path", "sha256", "package_root"), "failure_worker_invocation_interpreter_keys")
    need(all(isinstance(interpreter[key], str) and Path(interpreter[key]).is_absolute() for key in ("lane_root", "path", "package_root")) and sha256_text(interpreter["sha256"]), "failure_worker_invocation_interpreter")
    paths = value["paths"]
    exact(paths, ("attempt_root", "binding", "receipt", "stdout", "stderr"), "failure_worker_invocation_path_keys")
    need(all(isinstance(item, str) and Path(item).is_absolute() for item in paths.values()), "failure_worker_invocation_paths")
    command = value["command"]
    exact(command, ("argv", "sha256"), "failure_worker_invocation_command_keys")
    need(isinstance(command["argv"], list) and len(command["argv"]) >= 2 and all(isinstance(item, str) and bool(item) for item in command["argv"]), "failure_worker_invocation_command")
    need(command["argv"] == [interpreter["path"], "-m", "harness.worker", "--binding", paths["binding"], job["artifact_path"]], "failure_worker_invocation_command")
    command_sha = hashlib.sha256(json.dumps(command["argv"], ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=False).encode("utf-8")).hexdigest()
    need(command["sha256"] == command_sha, "failure_worker_invocation_command")


def failure_category(record: Mapping[str, Any]) -> str:
    code = record.get("error_code")
    need(code in M9_ERROR_CODES, "failure_error_code_mapping")
    need(record.get("stage") in M9_STAGE_RULES[str(code)], "failure_stage_mapping")
    classification = record.get("classification")
    if code == "infrastructure_failure":
        need(classification == "infrastructure", "failure_classification_mapping")
    elif code in {"public_tool_error", "lane_mismatch", "fallback_firing", "embed_write_tripwire_firing"}:
        need(classification == "product_lane", "failure_classification_mapping")
    else:
        need(classification in {"protocol", "verification", "product_lane"}, "failure_classification_mapping")
    methodology = record.get("methodology")
    need(methodology in {"initial", "explicit_repair"}, "failure_methodology")
    evidence = record.get("evidence")
    expected = {"cause_error_code"} | ({"repair_reason"} if methodology == "explicit_repair" else set())
    if record.get("stage") == "worker" and isinstance(evidence, dict) and "worker_rejection" in evidence:
        expected.update({"worker_rejection", "invocation_evidence_id"})
    need(isinstance(evidence, dict) and set(evidence) == expected and isinstance(evidence.get("cause_error_code"), str) and bool(evidence["cause_error_code"]), "failure_evidence")
    if "worker_rejection" in expected:
        rejection = evidence["worker_rejection"]
        exact(rejection, ("schema", "status", "error_code", "failure_family", "m9_classification", "product", "lane", "fallback_state", "embedding_mode", "network_attempts", "execution_namespace", "is_control", "control_id"), "failure_worker_rejection_keys")
        worker_error = rejection["error_code"]
        expected_worker_code = (
            "public_tool_error" if worker_error in {"public_error", "warmup_error", "debug_public_error", "public_tool_error"}
            else "lane_mismatch" if worker_error in {"lane_selection", "numpy_absence", "numpy_present", "numpy_absence_after", "numpy_present_after", "cache_lane_before", "cache_lane_after", "lane_mismatch"}
            else "fallback_firing" if worker_error in {"fallback_fired", "fallback_firing"}
            else "embed_write_tripwire_firing" if worker_error in {"provider_topup", "database_mutation", "embed_write_tripwire_firing"}
            else "infrastructure_failure" if worker_error in {"network_attempt", "network_tripwire", "invalid_json"} or worker_error.startswith("worker_job_") or worker_error.startswith("worker_binding_") or worker_error.startswith("worker_protocol_self_test_")
            else "failed_precondition"
        )
        need(
            rejection["schema"] == "arc4.row-result/v1" and rejection["status"] == "rejected"
            and rejection["failure_family"] == expected_worker_code and rejection["m9_classification"] == expected_worker_code
            and rejection["product"] == "jcodemunch_mcp"
            and (rejection["lane"] is None or rejection["lane"] in {"numpy_present", "numpy_absent"})
            and (rejection["embedding_mode"] is None or rejection["embedding_mode"] in {"semantic_only", "hybrid"})
            and rejection["fallback_state"] == ("fired" if expected_worker_code == "fallback_firing" else "not_observed")
            and rejection["error_code"] == evidence["cause_error_code"] and rejection["m9_classification"] == code,
            "failure_worker_rejection_binding",
        )
        attempts = rejection["network_attempts"]
        need(isinstance(attempts, list) and len(attempts) <= 8 and bool(attempts) == (rejection["error_code"] == "network_attempt"), "failure_worker_network_attempts")
        for item in attempts:
            exact(item, ("host", "port"), "failure_worker_network_attempt_keys")
            need(isinstance(item["host"], str) and 0 < len(item["host"]) <= 255 and isinstance(item["port"], int) and not isinstance(item["port"], bool) and 0 <= item["port"] <= 65535, "failure_worker_network_attempt")
        need(isinstance(evidence["invocation_evidence_id"], str) and sha256_text(evidence["invocation_evidence_id"]), "failure_worker_evidence_id")
        metadata_free = worker_error == "invalid_json" or worker_error.startswith("worker_job_") or worker_error.startswith("worker_binding_") or worker_error.startswith("worker_protocol_self_test_")
        need(rejection["lane"] == (None if metadata_free else record["row_identity"]["lane"]), "failure_worker_rejection_lane")
    if methodology == "explicit_repair":
        need(isinstance(evidence.get("repair_reason"), str) and bool(evidence["repair_reason"].strip()), "failure_repair_reason")
    return M9_ERROR_CODES[str(code)]


def sha256_text(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=False) + "\n").encode("utf-8")


def reconstruct_report(summary: Mapping[str, Any]) -> str:
    need(summary.get("schema") == "arc4.summary/v1", "summary_schema")
    lines = [
        "# Arc 4 production-lane comparison v2 report", "", f"Verdict: **{summary['verdict']}**.", "",
        "This is a census of a fixed purposive suite: 12 ranking problems over 4 frozen query vectors. It is not a random sample. No p-values, confidence intervals, hypothesis tests, prevalence rates, timing conclusions, or memory conclusions are reported.", "",
        "The paired denominator is 120 replicated lane comparisons. The problem denominator is 12 non-independent ranking problems. Repetitions and cache states add repeatability evidence, not query diversity.", "",
    ]
    for key, title in (("m1_rank0_difference", "M1 rank-0 difference"), ("m2_ordered_top_k_difference", "M2 ordered top-k difference"), ("m3_membership_top_k_difference", "M3 top-k membership difference"), ("m4_exact_tie_difference", "M4 exact-tie partition difference")):
        value = summary["counts"][key]
        lines.extend([f"## {title}", "", "| Unit | Numerator | Denominator | Independence |", "| --- | ---: | ---: | --- |", f"| Paired comparisons | {value['pair_numerator']} | {value['pair_denominator']} | replicated pair |", f"| Ranking problems | {value['problem_numerator']} | {value['problem_denominator']} | not independent draws |", "", f"Heterogeneous within problem: {', '.join(value['heterogeneous_within_problem']) or 'none'}.", ""])
        if key == "m1_rank0_difference":
            lines.extend([f"Excluded no-results pairs: {value['pair_excluded_no_results']}.", ""])
    lines.extend([
        "## M9 failures and lane-selection mismatches", "", f"Public-tool errors: {summary['m9']['public_tool_errors']}; lane mismatches: {summary['m9']['lane_mismatches']}; fallback firings: {summary['m9']['fallback_firings']}; embed-write tripwire firings: {summary['m9']['embed_write_tripwire_firings']}; failed preconditions: {summary['m9']['failed_preconditions']}; infrastructure failures: {summary['m9']['infrastructure_failures']}; total failed attempts: {summary['m9']['total']}; explicit-repair failures: {summary['m9']['explicit_repair_failures']}; successful repair pairs: {summary['m9']['successful_repair_pairs']}; repair declarations: {summary['m9']['repair_declarations']}; rowless failures: {summary['m9']['rowless_failures']}.", "", f"Attempt-number accounting: `{json.dumps(summary['m9']['attempts_by_number'], ensure_ascii=False, allow_nan=False, separators=(',', ':'), sort_keys=True)}`.", "",
        "## M10 score-difference magnitude", "", f"Raw cosine: all {summary['m10']['raw_cosine']['pair_count']} matrix pairs, {summary['m10']['raw_cosine']['candidate_comparisons']} candidate comparisons, maximum absolute delta `{float(summary['m10']['raw_cosine']['maximum_absolute_delta']).hex()}`, and {summary['m10']['raw_cosine']['bit_identical']} bit-identical scores.", "", f"Hybrid final: {summary['m10']['hybrid_final']['pair_count']} hybrid matrix pairs, {summary['m10']['hybrid_final']['candidate_comparisons']} candidate comparisons, maximum absolute delta `{float(summary['m10']['hybrid_final']['maximum_absolute_delta']).hex()}`, and {summary['m10']['hybrid_final']['bit_identical']} bit-identical scores.", "",
        "## M11 ordering margins", "", "Observed and conservative margins were computed at each lane's top-k boundary and minimum internal top-k gap. Finite zero remains eligible; `+inf`, `exact_tie`, and `insufficient_ranking` are counted separately in SUMMARY.json.", "",
        "## M12 first divergence at full depth", "", f"No full-depth divergence: {summary['m12']['none']} of 120 pairs. First-divergence histogram: `{json.dumps(summary['m12']['first_divergence_histogram'], ensure_ascii=False, allow_nan=False, separators=(',', ':'), sort_keys=False)}`.", "",
        "## Claim ceiling", "", "A zero establishes only observed parity and measured score/margin behavior on this frozen suite. One or more findings establish only that the shipped lanes can diverge on these retained real inputs. Neither outcome establishes production incidence or behavior outside the frozen suite.", "", P0_REPORT_SENTENCE, "",
        "## Limitations", "", "Four researcher-authored query vectors are reused across three corpora. NumPy-lane results are BLAS-dependent. Full-depth hybrid numeric evidence relies on a reconstruction adapter whose public top-k parity is checked on every matrix row. The private-source-derived control corpus remains local.", "",
    ])
    return "\n".join(lines)


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Rejected("invalid_json", str(path)) from exc


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Rejected("missing_jsonl", str(path)) from exc
    need(not raw.startswith(b"\xef\xbb\xbf") and b"\r" not in raw and raw.endswith(b"\n"), "noncanonical_jsonl")
    values: list[dict[str, Any]] = []
    for line in raw.splitlines():
        need(bool(line), "blank_jsonl_line")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise Rejected("invalid_jsonl") from exc
        need(isinstance(value, dict) and canonical(value) == line + b"\n", "noncanonical_jsonl")
        values.append(value)
    return values


def verify_failure_invocations(
    root: Path, failures: Sequence[Mapping[str, Any]], planned: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any], lock: Mapping[str, Any],
) -> None:
    required = {"invocation-binding.json", "receipt.json", "job-artifact.json", "stdout.log", "stderr.log"}
    worker_failures = [record for record in failures if record.get("stage") == "worker" and isinstance(record.get("evidence"), dict) and "worker_rejection" in record["evidence"]]
    evidence_ids = [record["evidence"]["invocation_evidence_id"] for record in worker_failures]
    need(len(evidence_ids) == len(set(evidence_ids)), "failure_invocation_alias")
    invocation_root = root / "invocations"
    actual_ids = {path.name for path in invocation_root.iterdir() if path.is_dir()} if invocation_root.is_dir() else set()
    need(actual_ids == set(evidence_ids), "failure_invocation_file_set")
    runtime_root = Path(config["runtime_root"]).resolve()
    lock_roots = lock["manifest_bindings"]["roots"]
    for record, evidence_id in zip(worker_failures, evidence_ids, strict=True):
        evidence_root = invocation_root / evidence_id
        need({path.name for path in evidence_root.iterdir() if path.is_file()} == required and not any(path.is_dir() for path in evidence_root.iterdir()), "failure_invocation_file_set")
        binding_path = evidence_root / "invocation-binding.json"
        receipt_path = evidence_root / "receipt.json"
        artifact_path = evidence_root / "job-artifact.json"
        binding = load(binding_path)
        receipt = load(receipt_path)
        job = load(artifact_path)
        need(binding_path.read_bytes() == canonical(binding) and receipt_path.read_bytes() == canonical(receipt) and artifact_path.read_bytes() == canonical(job), "failure_invocation_canonical")
        _validate_worker_invocation_binding(binding, record)
        identity = record["row_identity"]
        need(identity["row_id"] in planned, "failure_invocation_planned_row")
        frozen = planned[identity["row_id"]]
        exact(job, PRODUCTION_JOB_KEYS, "failure_invocation_job_keys")
        need(job["schema"] == "arc4.worker-job/v1", "failure_invocation_job_schema")
        need(all(job.get(key) == value for key, value in frozen.items()), "failure_invocation_job_plan")
        need(job.get("run_id") == config["run_id"] and job.get("lane") == identity["lane"], "failure_invocation_job_identity")
        need(job.get("attempt_n") == record["attempt_n"] and job.get("attempt_methodology") == record["methodology"] and job.get("repair_reason") == record["evidence"].get("repair_reason"), "failure_invocation_job_attempt")
        lane = identity["lane"]
        lane_root = Path(config["environment_lane_roots"][lane]["lane_venv"]).resolve()
        interpreter = Path(config["lane_interpreters"][lane]).resolve()
        package_root = (lane_root / "Lib" / "site-packages" / "jcodemunch_mcp").resolve()
        need(interpreter == (lane_root / "Scripts" / "python.exe").resolve(), "failure_invocation_interpreter_layout")
        need(Path(lock_roots[lane]["lane_venv"]).resolve() == lane_root, "failure_invocation_environment_root")
        need(binding["interpreter"]["lane_root"] == str(lane_root) and binding["interpreter"]["path"] == str(interpreter) and binding["interpreter"]["package_root"] == str(package_root), "failure_invocation_interpreter")
        need(binding["interpreter"]["sha256"] == lock_roots[lane]["python_executable_sha256"], "failure_invocation_interpreter_hash")
        need(job.get("config_path") == str((root / "CONFIG.json").resolve()) and job.get("config_sha256") == file_sha(root / "CONFIG.json"), "failure_invocation_job_config")
        need(job.get("package_root") == str(package_root) and job.get("environment_lock_path") == str((root / "ENVIRONMENT-LOCK.json").resolve()) and job.get("environment_lock_sha256") == file_sha(root / "ENVIRONMENT-LOCK.json"), "failure_invocation_job_environment")
        execution = binding["execution"]
        need(job["execution_namespace"] == execution["namespace"] and job["is_control"] == execution["is_control"] and job["control_id"] == execution["control_id"] and job["python_hash_seed"] == execution["python_hash_seed"], "failure_invocation_job_execution")
        rejection = record["evidence"]["worker_rejection"]
        metadata_free_rejection = str(rejection["error_code"]).startswith(("worker_job_", "worker_binding_", "worker_protocol_self_test_")) or rejection["error_code"] == "invalid_json"
        if metadata_free_rejection:
            need(rejection["execution_namespace"] is None and rejection["is_control"] is False and rejection["control_id"] is None, "failure_invocation_rejection_execution")
        else:
            need(rejection["execution_namespace"] == execution["namespace"] and rejection["is_control"] == execution["is_control"] and rejection["control_id"] == execution["control_id"], "failure_invocation_rejection_execution")
        seed = "unset" if execution["python_hash_seed"] is None else str(execution["python_hash_seed"])
        if execution["namespace"] == "control":
            source = runtime_root / "jobs" / "control" / "C9" / identity["row_id"] / f"seed-{seed}" / f"attempt-{record['attempt_n']:04d}.json"
            attempt_root = runtime_root / "attempts" / "control" / "C9" / identity["row_id"] / f"seed-{seed}" / f"attempt-{record['attempt_n']:04d}"
        else:
            source = runtime_root / "jobs" / execution["namespace"] / identity["row_id"] / f"attempt-{record['attempt_n']:04d}.json"
            attempt_root = runtime_root / "attempts" / execution["namespace"] / identity["row_id"] / f"attempt-{record['attempt_n']:04d}"
        expected_paths = {"attempt_root": str(attempt_root.resolve()), "binding": str((attempt_root / "invocation-binding.json").resolve()), "receipt": str((attempt_root / "receipt.json").resolve()), "stdout": str((attempt_root / "stdout.log").resolve()), "stderr": str((attempt_root / "stderr.log").resolve())}
        need(binding["paths"] == expected_paths, "failure_invocation_paths")
        need(binding["job"]["source_path"] == str(source.resolve()) and binding["job"]["publication_path"] == str(source.with_suffix(source.suffix + ".publication.json").resolve()) and binding["job"]["artifact_path"] == expected_paths["attempt_root"] + os.sep + "job-artifact.json", "failure_invocation_job_paths")
        trial_namespace = f"seed-{seed}" if execution["namespace"] == "control" else execution["namespace"]
        trial_root = runtime_root / "trials" / trial_namespace / identity["row_id"] / f"attempt-{record['attempt_n']:04d}"
        source_database = Path(config["corpora"][job["corpus"]]["database"]).resolve()
        trial_database = trial_root / source_database.name
        need(job["repo_id"] == config["corpora"][job["corpus"]]["repo_id"] and job["candidate_ids"] == config["corpora"][job["corpus"]]["candidate_ids"], "failure_invocation_job_corpus")
        need(job["database"] == str(trial_database.resolve()) and job["storage_path"] == str(trial_root.resolve()) and job["home_path"] == str((trial_root / "home").resolve()), "failure_invocation_job_trial_paths")
        need(job["treatment_wheel"] == str(Path(config["official_wheel"]).resolve()), "failure_invocation_job_wheel")
        query = config["queries"][job["query_id"]]
        need(job["query_text"] == query["query_text"] and job["query_vector"] == query["query_vector"] and job["query_vector_sha256"] == query["query_vector_sha256"], "failure_invocation_job_query")
        need(job["frozen_source_files"]["database_path"] == str(source_database) and job["trial_source_files"]["database_path"] == str(trial_database.resolve()) and job["frozen_source_files"]["files"] == job["trial_source_files"]["files"], "failure_invocation_job_source_receipts")
        need(file_sha(artifact_path) == binding["job"]["sha256"] and artifact_path.stat().st_size == binding["job"]["bytes"], "failure_invocation_job_hash")
        exact(receipt, ("schema", "status", "returncode", "elapsed_seconds", "binding", "job_after", "stdout", "stderr", "rejection", "parse_error"), "failure_invocation_receipt_keys")
        need(receipt["schema"] == "arc4.worker-invocation/v2" and receipt["status"] == "rejected" and receipt["returncode"] != 0 and receipt["parse_error"] is None and receipt["rejection"] == record["evidence"]["worker_rejection"], "failure_invocation_receipt")
        for key, name in (("binding", "invocation-binding.json"), ("stdout", "stdout.log"), ("stderr", "stderr.log")):
            reference = receipt[key]
            exact(reference, ("path", "sha256", "bytes"), "failure_invocation_reference_keys")
            target = evidence_root / name
            need(reference == {"path": name, "sha256": file_sha(target), "bytes": target.stat().st_size}, "failure_invocation_reference")
        expected_present = {"present": True, "sha256": file_sha(artifact_path), "bytes": artifact_path.stat().st_size}
        metadata_free = str(record["evidence"]["worker_rejection"]["error_code"]).startswith(("worker_job_", "worker_binding_"))
        need(receipt["job_after"] == expected_present or (metadata_free and receipt["job_after"] == {"present": False, "sha256": None, "bytes": 0}), "failure_invocation_job_after")
        stderr = (evidence_root / "stderr.log").read_bytes()
        need(stderr == canonical(record["evidence"]["worker_rejection"]), "failure_invocation_stderr")


def load_score_vector(root: Path, reference: Mapping[str, Any]) -> dict[str, str]:
    path = root / str(reference.get("path", ""))
    need(path.is_file() and path.stat().st_size == reference.get("size") and file_sha(path) == reference.get("sha256"), "score_vector_hash")
    values = load_jsonl(path)
    need(bool(values) and values[0] == {"schema": "arc4.full-score-vector/v1"}, "score_vector_schema")
    result: dict[str, str] = {}
    prior: str | None = None
    for row in values[1:]:
        need(list(row) == ["symbol_id", "score_hex"] and isinstance(row["symbol_id"], str) and isinstance(row["score_hex"], str), "score_vector_row")
        need(prior is None or prior < row["symbol_id"], "score_vector_order")
        value = float.fromhex(row["score_hex"])
        need(math.isfinite(value) and value.hex() == row["score_hex"], "score_vector_value")
        result[row["symbol_id"]] = row["score_hex"]
        prior = row["symbol_id"]
    need(bool(result), "score_vector_empty")
    return result


def hydrate_row(root: Path, stored: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(stored)
    if row.get("arm") != "matrix":
        return row
    evidence = row.get("full_ranking_evidence")
    need(isinstance(evidence, dict) and set(evidence) == {"raw_cosine", "final"}, "score_vector_evidence")
    raw = load_score_vector(root, evidence["raw_cosine"])
    final_reference = evidence["final"]
    if final_reference == {"same_as": "raw_cosine"}:
        final = dict(raw)
    else:
        final = load_score_vector(root, final_reference)
    row["raw_cosine"] = raw
    row["final_scores"] = final
    return row


def ranking(scores: Mapping[str, str]) -> list[str]:
    decoded = {key: float.fromhex(value) for key, value in scores.items()}
    need(all(math.isfinite(value) for value in decoded.values()), "nonfinite_score")
    return sorted((key for key, value in decoded.items() if value > 0.0), key=lambda key: (-decoded[key], key))


def order_hash(scores: Mapping[str, str]) -> str:
    payload = [canonical({"schema": "arc4.positive-ranking/v1"})]
    for symbol_id in ranking(scores):
        payload.append(canonical({"symbol_id": symbol_id, "score_hex": scores[symbol_id]}))
    return hashlib.sha256(b"".join(payload)).hexdigest()


def tie_partition(scores: Mapping[str, str]) -> list[list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for symbol_id in ranking(scores):
        groups[scores[symbol_id]].append(symbol_id)
    return sorted(sorted(group) for group in groups.values() if len(group) > 1)


def tie_evidence(scores: Mapping[str, str], top_k: int) -> dict[str, Any]:
    ordered = ranking(scores)
    groups = tie_partition(scores)
    top = set(ordered[:top_k])
    right = set(ordered[top_k:])
    participants = sorted({item for group in groups for item in group})
    return {
        "tie_partition_sha256": hashlib.sha256(canonical(groups)).hexdigest(),
        "groups": groups,
        "participants": participants,
        "groups_intersecting_top_k": [group for group in groups if set(group) & top],
        "groups_crossing_top_k_boundary": [group for group in groups if set(group) & top and set(group) & right],
    }


def stable(value: Any) -> Any:
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, list):
        return [stable(item) for item in value]
    if isinstance(value, dict):
        return {key: stable(item) for key, item in value.items()}
    return value


def control_projection(observed: Mapping[str, Any]) -> dict[str, Any]:
    projection = {key: observed[key] for key in PROJECTION_KEYS if key != "overlaps"}
    overlaps: list[str] = []
    for label, key in (
        ("M1", "m1_rank0_difference"), ("M2", "m2_ordered_top_k_difference"),
        ("M3", "m3_membership_top_k_difference"), ("M4", "m4_exact_tie_difference"),
    ):
        if projection[key] is True:
            overlaps.append(label)
    if projection["m5_top_k_inversion_count"] or projection["m5_full_inversion_count"]:
        overlaps.append("M5")
    if projection["m6_top_k_genuine_disagreement_count"] or projection["m6_full_genuine_disagreement_count"]:
        overlaps.append("M6")
    projection["overlaps"] = overlaps
    return stable(projection)


def first_divergence(left: Sequence[str], right: Sequence[str]) -> int | None:
    for index, pair in enumerate(zip(left, right)):
        if pair[0] != pair[1]:
            return index
    return None if len(left) == len(right) else min(len(left), len(right))


def inversion_count(left: Mapping[str, float], right: Mapping[str, float], ids: set[str]) -> int:
    values = sorted({right[item] for item in ids})
    coordinate = {value: index for index, value in enumerate(values)}
    tree = [0] * (len(values) + 1)
    def add(index: int) -> None:
        index += 1
        while index < len(tree):
            tree[index] += 1
            index += index & -index
    def prefix(end: int) -> int:
        total = 0
        while end:
            total += tree[end]
            end -= end & -end
        return total
    ordered = sorted(ids, key=lambda item: -left[item])
    result = cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and left[ordered[end]] == left[ordered[cursor]]:
            end += 1
        for item in ordered[cursor:end]:
            result += prefix(coordinate[right[item]])
        for item in ordered[cursor:end]:
            add(coordinate[right[item]])
        cursor = end
    return result


def split_count(tied: Mapping[str, float], other: Mapping[str, float], ids: set[str]) -> int:
    groups: dict[str, list[str]] = defaultdict(list)
    for item in ids:
        groups[float(tied[item]).hex()].append(item)
    total = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        same: dict[str, int] = defaultdict(int)
        for item in group:
            same[float(other[item]).hex()] += 1
        total += len(group) * (len(group) - 1) // 2 - sum(value * (value - 1) // 2 for value in same.values())
    return total


def percentile_summary(values: Sequence[float]) -> dict[str, Any]:
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0
    p99 = ordered[max(0, min(len(ordered) - 1, math.ceil(0.99 * len(ordered)) - 1))]
    return {"max": ordered[-1], "median": median, "p99_nearest_rank": p99}


def ratio(gap: float, denominator: float) -> float | str:
    if denominator == 0.0:
        return "+inf" if gap > 0.0 else "exact_tie"
    return 0.0 if gap == 0.0 else gap / denominator


def margins(order_scores: Mapping[str, float], other_scores: Mapping[str, float], top_k: int) -> dict[str, Any]:
    order = sorted((item for item, score in order_scores.items() if score > 0.0), key=lambda item: (-order_scores[item], item))
    max_delta = max(abs(other_scores[item] - order_scores[item]) for item in order_scores)
    def item(a: str, b: str) -> dict[str, Any]:
        gap = order_scores[a] - order_scores[b]
        other_gap = other_scores[a] - other_scores[b]
        observed_denominator = abs(gap - other_gap)
        conservative_denominator = 2.0 * max_delta
        return {"symbols": [a, b], "gap": gap, "observed_denominator": observed_denominator, "conservative_denominator": conservative_denominator, "observed": ratio(gap, observed_denominator), "conservative": ratio(gap, conservative_denominator)}
    boundary: Any = "insufficient_ranking"
    if len(order) >= top_k + 1:
        boundary = item(order[top_k - 1], order[top_k])
    internal: Any = "insufficient_ranking"
    limit = min(top_k, len(order))
    if limit >= 2:
        internal = min((item(order[index], order[index + 1]) for index in range(limit - 1)), key=lambda value: value["gap"])
    return {"boundary": boundary, "minimum_internal": internal}


def margin_aggregate(matrix: Sequence[Mapping[str, Any]], lane_key: str, location: str, kind: str) -> dict[str, Any]:
    finite: list[float] = []
    counts = {"+inf": 0, "exact_tie": 0, "insufficient_ranking": 0, "finite_zero": 0}
    for pair in matrix:
        value = pair["metrics"][lane_key][location]
        if value == "insufficient_ranking":
            counts["insufficient_ranking"] += 1
        else:
            item = value[kind]
            if item in ("+inf", "exact_tie"):
                counts[item] += 1
            else:
                numeric = float(item)
                finite.append(numeric)
                counts["finite_zero"] += numeric == 0.0
    if finite:
        ordered = sorted(finite)
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0
        p99 = ordered[max(0, min(len(ordered) - 1, math.ceil(0.99 * len(ordered)) - 1))]
        finite_summary: Any = {"minimum": ordered[0], "median": median, "p99_nearest_rank": p99, "maximum": ordered[-1], "count": len(ordered)}
    else:
        finite_summary = "no_finite_values"
    return {"finite": finite_summary, **counts}


def recompute_pair(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    need(set(left["final_scores"]) == set(right["final_scores"]), "score_id_set")
    n = ranking(left["final_scores"])
    p = ranking(right["final_scores"])
    n_scores = {key: float.fromhex(value) for key, value in left["final_scores"].items()}
    p_scores = {key: float.fromhex(value) for key, value in right["final_scores"].items()}
    k = int(left["top_k"])
    union_top = set(n[:k]) | set(p[:k])
    union_full = set(n) | set(p)
    need(set(left["raw_cosine"]) == set(right["raw_cosine"]) == set(n_scores), "raw_score_id_set")
    n_raw = {key: float.fromhex(value) for key, value in left["raw_cosine"].items()}
    p_raw = {key: float.fromhex(value) for key, value in right["raw_cosine"].items()}
    deltas = [abs(n_raw[key] - p_raw[key]) for key in n_raw]
    delta_summary = percentile_summary(deltas)
    result = {
        "m1_rank0_difference": None if not n or not p else n[0] != p[0],
        "m1_status": "no_results" if not n or not p else "eligible",
        "m2_ordered_top_k_difference": n[:k] != p[:k],
        "m3_membership_top_k_difference": set(n[:k]) != set(p[:k]),
        "m4_exact_tie_difference": tie_partition(left["final_scores"]) != tie_partition(right["final_scores"]),
        "m4_numpy": tie_evidence(left["final_scores"], k),
        "m4_python": tie_evidence(right["final_scores"], k),
        "m4_participant_symmetric_difference": sorted(set(tie_evidence(left["final_scores"], k)["participants"]) ^ set(tie_evidence(right["final_scores"], k)["participants"])),
        "m5_top_k_inversion_count": inversion_count(n_scores, p_scores, union_top),
        "m5_full_inversion_count": inversion_count(n_scores, p_scores, union_full),
        "m6_top_k_genuine_disagreement_count": split_count(n_scores, p_scores, union_top) + split_count(p_scores, n_scores, union_top),
        "m6_full_genuine_disagreement_count": split_count(n_scores, p_scores, union_full) + split_count(p_scores, n_scores, union_full),
        "m10_raw_cosine": {**delta_summary, "bit_identical": sum(left["raw_cosine"][key] == right["raw_cosine"][key] for key in n_raw), "candidate_count": len(n_raw)},
        "m11_numpy_order": margins(n_scores, p_scores, k),
        "m11_python_order": margins(p_scores, n_scores, k),
        "m12_first_divergence_rank": first_divergence(n, p),
        "numpy_ordering_sha256": order_hash(left["final_scores"]),
        "python_ordering_sha256": order_hash(right["final_scores"]),
    }
    if not bool(left.get("serialized_args", {}).get("semantic_only", True)):
        final_deltas = [abs(n_scores[key] - p_scores[key]) for key in n_scores]
        final_summary = percentile_summary(final_deltas)
        result["m10_hybrid_final"] = {**final_summary, "bit_identical": sum(left["final_scores"][key] == right["final_scores"][key] for key in n_scores), "candidate_count": len(n_scores)}
    return result


def validate_row_evidence(row: Mapping[str, Any], expected_ids: set[str]) -> None:
    attempt_n = row.get("attempt_n")
    methodology = row.get("attempt_methodology")
    repair_reason = row.get("repair_reason")
    need(isinstance(attempt_n, int) and not isinstance(attempt_n, bool) and attempt_n >= 1, "row_attempt_n")
    need((methodology == "initial" and attempt_n == 1 and repair_reason is None) or (methodology == "explicit_repair" and attempt_n >= 2 and isinstance(repair_reason, str) and bool(repair_reason.strip())), "row_repair_provenance")
    need(row.get("observed_query_vector_sha256") == row.get("query_vector_sha256"), "observed_query_vector_hash")
    need(row.get("pair_invocation_ordinal") in (1, 2), "pair_invocation_ordinal")
    frozen_files = row.get("frozen_source_files")
    trial_files = row.get("trial_source_files")
    for receipt in (frozen_files, trial_files):
        exact(receipt, ("database_path", "files"), "row_source_receipt_keys")
        exact(receipt["files"], ("db", "wal", "shm"), "row_source_file_set")
    need(frozen_files["files"] == trial_files["files"], "row_sidecar_copy")
    package = row.get("package_evidence")
    exact(package, ("official_wheel_sha256", "environment_lock_sha256", "installed_version", "payload_file_count", "payload_matches_official_wheel", "module_origins"), "package_evidence_keys")
    need(package["official_wheel_sha256"] == OFFICIAL_WHEEL_SHA256 and sha256_text(package["environment_lock_sha256"]) and package["installed_version"] == "1.108.228" and isinstance(package["payload_file_count"], int) and package["payload_file_count"] > 0 and package["payload_matches_official_wheel"] is True, "package_evidence")
    need(isinstance(package["module_origins"], dict) and bool(package["module_origins"]) and all(isinstance(key, str) and isinstance(value, str) and value for key, value in package["module_origins"].items()), "module_origin_evidence")
    lane = row.get("lane_evidence")
    exact(lane, ("numpy_version", "numpy_import_failed_before", "numpy_importable_before", "numpy_helper_non_null_before", "numpy_importable_after", "numpy_import_failed_after", "numpy_helper_non_null_after", "matrix_vectorised"), "lane_evidence_keys")
    controls = row.get("controls")
    exact(controls, ("network_attempts", "network_tripwire_installed_before_config", "network_lifetime_guard_registered", "credentials_absent", "sharing_disabled", "package_unchanged", "database_unchanged", "candidate_set_matches", "provider_expected_calls", "provider_observed_calls", "topup_tripwire_events", "storage_tuning_absent", "home_tuning_absent", "effective_weight_matches"), "row_control_keys")
    need(controls["network_attempts"] == [] and controls["network_tripwire_installed_before_config"] is True and controls["network_lifetime_guard_registered"] is True and controls["credentials_absent"] is True and controls["sharing_disabled"] is True, "row_network_control")
    need(all(controls[key] is True for key in ("package_unchanged", "database_unchanged", "candidate_set_matches", "storage_tuning_absent", "home_tuning_absent", "effective_weight_matches")), "row_success_controls")
    need(controls["provider_expected_calls"] == controls["provider_observed_calls"] and controls["topup_tripwire_events"] == 0, "row_provider_control")
    debug = row.get("debug_observation")
    need(isinstance(debug, dict) and set(debug) == {"debug", "ordered_ids", "scores", "order_matches", "rounded_scores_match", "adapter_kind"}, "debug_observation_keys")
    need(debug["debug"] is True and debug["order_matches"] is True and debug["rounded_scores_match"] is True, "debug_observation_status")
    need(isinstance(debug["scores"], list) and len(debug["scores"]) == len(debug["ordered_ids"]), "debug_score_count")
    for index, item in enumerate(debug["scores"]):
        exact(item, ("id", "public_score", "adapter_rounded"), "debug_score_keys")
        need(item["id"] == debug["ordered_ids"][index] and isinstance(item["public_score"], (int, float)) and not isinstance(item["public_score"], bool), "debug_score_identity")
        need(float(item["public_score"]) == float(item["adapter_rounded"]) == round(float(item["adapter_rounded"]), 4), "debug_score_rounding")
    if row.get("arm") != "matrix":
        need(debug["adapter_kind"] == "bm25_identity" and debug["ordered_ids"] == row.get("public_result_ids"), "debug_preflight_parity")
        need(len(debug["ordered_ids"]) == min(int(row["top_k"]), len(expected_ids)) and len(debug["scores"]) == len(debug["ordered_ids"]), "debug_preflight_complete")
        return
    scores = row.get("final_scores")
    raw = row.get("raw_cosine")
    need(isinstance(scores, dict) and isinstance(raw, dict) and set(scores) == set(raw) == expected_ids, "full_score_vector")
    ordered = ranking(scores)
    need(row.get("public_result_ids") == ordered[: int(row["top_k"])], "ordered_result_ids")
    need(row.get("full_depth_ordering_sha256") == order_hash(scores), "full_depth_ordering_hash")
    expected_debug_ids = ordered[: int(row["top_k"])]
    need(debug["adapter_kind"] == "final" and debug["ordered_ids"] == expected_debug_ids, "debug_matrix_parity")
    for index, item in enumerate(debug["scores"]):
        expected = round(float.fromhex(scores[item["id"]]), 4)
        need(float(item["public_score"]) == expected and float(item["adapter_rounded"]) == expected, "debug_rounded_score")


def validate_pair_claim(claimed: Mapping[str, Any], observed: Mapping[str, Any]) -> None:
    need(set(claimed) == set(observed), "paired_metric_keys")
    for key, value in observed.items():
        need(claimed[key] == value, "paired_metric_mismatch")


def verify_manifest(root: Path) -> tuple[str, int]:
    manifest_path = root / "MANIFEST.json"
    detached = (root / "MANIFEST.sha256").read_text(encoding="ascii").strip()
    need(re.fullmatch(r"[0-9a-f]{64}", detached) is not None, "manifest_detached_format")
    need(file_sha(manifest_path) == detached, "manifest_detached_hash")
    manifest = load(manifest_path)
    need(isinstance(manifest, dict) and set(manifest) == {"schema", "files"} and manifest.get("schema") == "arc4.manifest/v1" and isinstance(manifest.get("files"), list), "manifest_schema")
    seen: set[str] = set()
    for item in manifest["files"]:
        need(isinstance(item, dict) and set(item) == {"path", "sha256", "size"}, "manifest_item_keys")
        path = item.get("path")
        need(isinstance(path, str) and path not in seen and "\\" not in path and not path.startswith("/") and ".." not in Path(path).parts, "manifest_path")
        seen.add(path)
        target = root / path
        need(target.is_file() and not target.is_symlink() and isinstance(item.get("size"), int) and not isinstance(item.get("size"), bool) and item["size"] >= 0 and re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256"))) is not None and target.stat().st_size == item.get("size") and file_sha(target) == item.get("sha256"), "manifest_file_hash")
    need(not ({"MANIFEST.json", "MANIFEST.sha256", *GENERATED_PACKET_FILES} & seen), "manifest_circular_entry")
    need([item["path"] for item in manifest["files"]] == sorted(seen), "manifest_order")
    actual = {
        path.relative_to(root).as_posix() for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() not in {"MANIFEST.json", "MANIFEST.sha256", *GENERATED_PACKET_FILES}
    }
    need(actual == seen, "manifest_closed_world")
    return detached, len(seen)


def verify_p0(root: Path) -> Mapping[str, Any]:
    receipt = load(root / "P0-RECEIPT.json")
    keys = (
        "schema", "status", "official_sha256", "rebuilt_sha256", "comparison_tool_sha256",
        "official_member_count", "rebuilt_member_count", "excluded_member", "missing_members",
        "extra_members", "raw_differences", "normalized_payload_differences", "official_record",
        "normalization", "claim_ceiling", "does_not_establish",
    )
    exact(receipt, keys, "p0_receipt_keys")
    need(receipt["schema"] == "arc4.p0-wheel-comparison/v1" and receipt["status"] == "passed", "p0_status")
    need(receipt["official_sha256"] == OFFICIAL_WHEEL_SHA256 and sha256_text(receipt["rebuilt_sha256"]) and sha256_text(receipt["comparison_tool_sha256"]), "p0_hashes")
    need(receipt["official_member_count"] == receipt["rebuilt_member_count"] and isinstance(receipt["official_member_count"], int) and receipt["official_member_count"] > 0, "p0_member_counts")
    need(receipt["excluded_member"] == "jcodemunch_mcp-1.108.228.dist-info/RECORD", "p0_excluded_member")
    for key in ("missing_members", "extra_members", "raw_differences", "normalized_payload_differences"):
        need(isinstance(receipt[key], list) and receipt[key] == sorted(set(receipt[key])) and all(isinstance(item, str) for item in receipt[key]), "p0_difference_lists")
    need(not receipt["missing_members"] and not receipt["extra_members"] and not receipt["normalized_payload_differences"], "p0_zero_difference")
    exact(receipt["official_record"], ("schema", "status", "row_count"), "p0_record_keys")
    need(receipt["official_record"] == {"schema": "arc4.official-record-validation/v1", "status": "valid", "row_count": receipt["official_member_count"]}, "p0_record")
    need(receipt["normalization"] == "utf8_text_newlines_only_crlf_or_cr_to_lf" and receipt["claim_ceiling"] == P0_CLAIM_CEILING and receipt["does_not_establish"] == P0_NONCOVERAGE, "p0_claim_ceiling")
    return receipt


PLAN_FIELDS = (
    "arm", "problem_id", "case_id", "pair_id", "corpus", "form_id", "query_id", "cache_state",
    "repetition", "top_k", "serialized_args", "serialized_args_sha256", "debug_observation_args",
    "debug_observation_args_sha256", "corpus_sha256", "candidate_ids_sha256", "candidate_count",
    "query_vector_sha256", "lane_invocation_order", "lane", "row_id",
)


def verify_frozen_cases(root: Path) -> tuple[Mapping[str, Any], dict[str, Mapping[str, Any]], dict[str, set[str]]]:
    cases = load(root / "frozen-cases.json")
    exact(cases, ("schema", "run_id", "corpora", "case_executions", "planned_rows"), "frozen_cases_keys")
    need(cases["schema"] == "arc4.frozen-cases/v1" and isinstance(cases["run_id"], str) and bool(cases["run_id"]), "frozen_cases_schema")
    need(isinstance(cases["corpora"], list) and [item.get("name") for item in cases["corpora"]] == ["django", "fastapi", "jcodemunch"], "frozen_corpora")
    candidates: dict[str, set[str]] = {}
    corpus_meta: dict[str, Mapping[str, Any]] = {}
    for corpus in cases["corpora"]:
        exact(corpus, ("name", "working_database_sha256", "candidate_ids_sha256", "candidate_count", "candidate_ids"), "frozen_corpus_keys")
        ids = corpus["candidate_ids"]
        need(isinstance(ids, list) and ids == sorted(set(ids)) and bool(ids), "frozen_candidate_ids")
        need(corpus["candidate_count"] == len(ids) and corpus["candidate_ids_sha256"] == hashlib.sha256(json.dumps(ids, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=False).encode("utf-8")).hexdigest(), "frozen_candidate_hash")
        need(sha256_text(corpus["working_database_sha256"]), "frozen_database_hash")
        candidates[corpus["name"]] = set(ids)
        corpus_meta[corpus["name"]] = corpus
    rows = cases["planned_rows"]
    need(isinstance(rows, list) and len(rows) == 264, "frozen_row_count")
    planned: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        exact(row, PLAN_FIELDS, "frozen_row_keys")
        need(row["row_id"] not in planned and row["lane"] in ("numpy_present", "numpy_absent") and row["arm"] in ("matrix", "preflight"), "frozen_row_identity")
        corpus = corpus_meta.get(row["corpus"])
        need(corpus is not None and row["corpus_sha256"] == corpus["working_database_sha256"] and row["candidate_ids_sha256"] == corpus["candidate_ids_sha256"] and row["candidate_count"] == corpus["candidate_count"], "frozen_row_corpus")
        debug_args = dict(row["serialized_args"])
        debug_args["debug"] = True
        need(row["debug_observation_args"] == debug_args and row["debug_observation_args_sha256"] == hashlib.sha256(json.dumps(debug_args, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=False).encode("utf-8")).hexdigest(), "frozen_debug_args")
        planned[row["row_id"]] = row
    matrix = [row for row in rows if row["arm"] == "matrix"]
    preflight = [row for row in rows if row["arm"] == "preflight"]
    need(len(matrix) == 240 and len(preflight) == 24 and len({row["problem_id"] for row in matrix}) == 12 and len({row["query_id"] for row in rows}) == 4, "frozen_factor_counts")
    need(all(sum(row["problem_id"] == value for row in matrix) == 20 for value in {row["problem_id"] for row in matrix}), "frozen_problem_multiplicity")
    need(all(sum(row["query_id"] == value for row in matrix) == 60 for value in {row["query_id"] for row in matrix}), "frozen_query_multiplicity")
    need(all(sum(row["lane"] == value for row in matrix) == 120 for value in ("numpy_present", "numpy_absent")), "frozen_lane_multiplicity")
    need(all(sum(row["cache_state"] == value for row in matrix) == 120 for value in ("cold_fresh_process", "generation_warm")), "frozen_cache_multiplicity")
    need(all(sum(row["repetition"] == value for row in matrix) == 48 for value in range(1, 6)), "frozen_repetition_multiplicity")
    return cases, planned, candidates


def _rewrite_path(value: str, root: str, marker: str) -> str:
    resolved = Path(value).resolve()
    base = Path(root).resolve()
    try:
        suffix = resolved.relative_to(base).as_posix()
    except ValueError as exc:
        raise Rejected("environment_path_escape") from exc
    return marker if suffix == "." else f"{marker}/{suffix}"


def _canonical_environment(raw: Mapping[str, Any], *, lane_venv: str, trial_root: str, packet_root: str) -> dict[str, Any]:
    required = (
        "schema", "lane", "python_implementation", "python_version", "python_cache_tag", "platform", "machine",
        "processor", "locale", "time_zone", "sqlite_version", "openssl_version", "distributions",
        "treatment_wheel_sha256", "pip_version", "numpy", "cpu", "blas", "environment", "configuration",
        "python_executable", "storage_path", "cwd",
    )
    exact(raw, required, "raw_environment_keys")
    need(raw["schema"] == "arc4.raw-environment/v1" and raw["lane"] in ("numpy_present", "numpy_absent"), "raw_environment_schema")
    distributions = sorted((dict(item) for item in raw["distributions"]), key=lambda item: item["project"])
    for item in distributions:
        exact(item, ("project", "version", "artifact_sha256"), "raw_distribution_keys")
        need(isinstance(item["project"], str) and isinstance(item["version"], str) and sha256_text(item["artifact_sha256"]), "raw_distribution")
    need(len({item["project"] for item in distributions}) == len(distributions), "raw_distribution_duplicate")
    need(raw["python_version"] == "3.13.7" and raw["treatment_wheel_sha256"] == OFFICIAL_WHEEL_SHA256, "raw_environment_identity")
    exact(raw["environment"], ("PYTHONHASHSEED", "PYTHONNOUSERSITE", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "JCODEMUNCH_EMBED_MATRIX_CACHE", "JCODEMUNCH_SHARE_SAVINGS"), "raw_environment_variables")
    exact(raw["configuration"], ("share_savings", "perf_telemetry_enabled", "embed_model"), "raw_configuration_keys")
    need(raw["configuration"]["share_savings"] is False and raw["configuration"]["perf_telemetry_enabled"] is False and isinstance(raw["configuration"]["embed_model"], str), "raw_configuration")
    return {
        **{key: raw[key] for key in required if key not in ("schema", "distributions", "python_executable", "storage_path", "cwd")},
        "schema": "arc4.environment-lock/v1", "distributions": distributions,
        "python_executable": _rewrite_path(str(raw["python_executable"]), lane_venv, "<LANE_VENV>"),
        "storage_path": _rewrite_path(str(raw["storage_path"]), trial_root, "<TRIAL_ROOT>"),
        "cwd": _rewrite_path(str(raw["cwd"]), packet_root, "<PACKET_ROOT>"),
    }


def verify_environment(root: Path) -> Mapping[str, Any]:
    lock = load(root / "ENVIRONMENT-LOCK.json")
    exact(lock, ("schema", "python", "pip", "install", "wheelhouse_artifacts", "lanes", "only_declared_distribution_difference", "manifest_bindings"), "environment_lock_keys")
    need(lock["schema"] == "arc4.environment-lock/v1" and lock["python"] == {"implementation": "CPython", "version": "3.13.7"}, "environment_lock_schema")
    exact(lock["pip"], ("version", "artifact_sha256"), "environment_pip_keys")
    need(isinstance(lock["pip"]["version"], str) and bool(lock["pip"]["version"]) and sha256_text(lock["pip"]["artifact_sha256"]), "environment_pip")
    need(lock["install"] == {"index": "none", "find_links": "<FROZEN_WHEELHOUSE>", "no_deps": True}, "environment_install")
    artifacts = lock["wheelhouse_artifacts"]
    need(isinstance(artifacts, list) and artifacts == sorted(artifacts, key=lambda item: item["filename"]), "environment_artifact_order")
    for item in artifacts:
        exact(item, ("project", "version", "filename", "sha256"), "environment_artifact_keys")
        need(all(isinstance(item[key], str) and item[key] for key in item) and sha256_text(item["sha256"]), "environment_artifact")
    by_project = {item["project"]: item for item in artifacts}
    need(len(by_project) == len(artifacts) and {"jcodemunch-mcp", "numpy", "pip"} <= set(by_project), "environment_artifact_set")
    need(by_project["jcodemunch-mcp"]["version"] == "1.108.228" and by_project["jcodemunch-mcp"]["sha256"] == OFFICIAL_WHEEL_SHA256 and by_project["numpy"]["version"] == "2.4.4", "environment_artifact_identity")
    need(lock["pip"] == {"version": by_project["pip"]["version"], "artifact_sha256": by_project["pip"]["sha256"]}, "environment_pip_binding")
    exact(lock["lanes"], ("numpy_present", "numpy_absent"), "environment_lanes")
    for lane in ("numpy_present", "numpy_absent"):
        exact(lock["lanes"][lane], ("distributions",), "environment_lane_keys")
    need(lock["lanes"]["numpy_present"]["distributions"] == artifacts and lock["lanes"]["numpy_absent"]["distributions"] == [item for item in artifacts if item["project"] != "numpy"] and lock["only_declared_distribution_difference"] == "numpy==2.4.4", "environment_lane_relationship")
    bindings = lock["manifest_bindings"]
    exact(bindings, ("schema", "raw", "canonical", "roots", "c16"), "environment_binding_keys")
    need(bindings["schema"] == "arc4.environment-manifest-bindings/v1" and bindings["c16"] == {"status": "passed", "only_declared_difference": "numpy==2.4.4"}, "environment_c16")
    expected_paths = {"raw": {"numpy_present": "env/raw-numpy-present.json", "numpy_absent": "env/raw-numpy-absent.json"}, "canonical": {"numpy_present": "env/numpy-present.json", "numpy_absent": "env/numpy-absent.json"}}
    exact(bindings["roots"], ("packet_root", "numpy_present", "numpy_absent"), "environment_roots")
    canonical_values: dict[str, Mapping[str, Any]] = {}
    for family in ("raw", "canonical"):
        exact(bindings[family], ("numpy_present", "numpy_absent"), "environment_binding_lanes")
        for lane in ("numpy_present", "numpy_absent"):
            receipt = bindings[family][lane]
            exact(receipt, ("path", "sha256"), "environment_receipt_keys")
            need(receipt["path"] == expected_paths[family][lane] and sha256_text(receipt["sha256"]), "environment_receipt")
            path = root / receipt["path"]
            need(path.is_file() and file_sha(path) == receipt["sha256"], "environment_receipt_hash")
    for lane in ("numpy_present", "numpy_absent"):
        exact(bindings["roots"][lane], ("lane_venv", "trial_root", "python_executable", "python_executable_sha256", "package_root"), "environment_lane_roots")
        lane_root = Path(bindings["roots"][lane]["lane_venv"]).resolve()
        need(Path(bindings["roots"][lane]["python_executable"]).resolve() == (lane_root / "Scripts" / "python.exe").resolve() and sha256_text(bindings["roots"][lane]["python_executable_sha256"]), "environment_interpreter_binding")
        need(Path(bindings["roots"][lane]["package_root"]).resolve() == (lane_root / "Lib" / "site-packages" / "jcodemunch_mcp").resolve(), "environment_package_binding")
        raw = load(root / bindings["raw"][lane]["path"])
        need(raw.get("python_executable") == bindings["roots"][lane]["python_executable"], "environment_raw_interpreter")
        canonical_value = load(root / bindings["canonical"][lane]["path"])
        expected = _canonical_environment(raw, lane_venv=bindings["roots"][lane]["lane_venv"], trial_root=bindings["roots"][lane]["trial_root"], packet_root=bindings["roots"]["packet_root"])
        need(canonical_value == expected, "environment_canonical_receipt")
        expected_distributions = sorted(({"project": item["project"], "version": item["version"], "artifact_sha256": item["sha256"]} for item in lock["lanes"][lane]["distributions"]), key=lambda item: item["project"])
        need(canonical_value["distributions"] == expected_distributions and canonical_value["pip_version"] == lock["pip"]["version"], "environment_locked_manifest")
        canonical_values[lane] = canonical_value
    present = json.loads(json.dumps(canonical_values["numpy_present"]))
    absent = json.loads(json.dumps(canonical_values["numpy_absent"]))
    need(present.pop("lane") == "numpy_present" and absent.pop("lane") == "numpy_absent", "environment_lane_labels")
    present.pop("numpy")
    absent_numpy = absent.pop("numpy")
    need(absent_numpy == {"present": False, "version": None, "artifact_sha256": None}, "environment_numpy_absent")
    present["distributions"] = [item for item in present["distributions"] if item["project"] != "numpy"]
    absent["distributions"] = [item for item in absent["distributions"] if item["project"] != "numpy"]
    need(present == absent, "environment_parity")
    return lock


def validate_preregistration_semantics(
    prereg: Mapping[str, Any], *, cases: Mapping[str, Any], p0: Mapping[str, Any],
    config: Mapping[str, Any], expected_hashes: Mapping[str, str],
) -> None:
    exact(config, CAMPAIGN_CONFIG_KEYS, "campaign_config_keys")
    exact(config["lane_interpreters"], ("numpy_present", "numpy_absent"), "campaign_interpreters")
    exact(config["environment_capture_specs"], ("numpy_present", "numpy_absent"), "campaign_capture_specs")
    exact(config["environment_lane_roots"], ("numpy_present", "numpy_absent"), "campaign_environment_roots")
    exact(config["corpora"], ("django", "fastapi", "jcodemunch"), "campaign_corpora")
    exact(config["child_environment"], ("system_root", "temp", "locale", "timezone", "pythonhashseed"), "campaign_child_environment")
    need(isinstance(config["queries"], dict) and len(config["queries"]) == 4 and isinstance(config["worker_timeout_seconds"], int) and not isinstance(config["worker_timeout_seconds"], bool) and 1 <= config["worker_timeout_seconds"] <= 3600, "campaign_config_values")
    for corpus in config["corpora"].values():
        exact(corpus, ("database", "repo_id", "candidate_ids"), "campaign_corpus_keys")
    for query in config["queries"].values():
        exact(query, ("query_text", "query_vector", "query_vector_sha256"), "campaign_query_keys")
        need(isinstance(query["query_vector"], list) and len(query["query_vector"]) == 384 and hashlib.sha256(json.dumps(query["query_vector"], ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=False).encode("utf-8")).hexdigest() == query["query_vector_sha256"], "campaign_query_hash")
    exact(prereg, ("schema", "approved_utc", "design_sha256", "config_sha256", "frozen_cases_sha256", "environment_lock_sha256", "p0_receipt_sha256", "source_inventory_sha256", "run_id", "matrix_rows", "matrix_pairs", "preflight_rows", "preflight_pairs", "claim_ceiling", "p0_claim_ceiling", "p0_does_not_establish", "no_early_stop", "verdict_requires_complete_coverage"), "preregistration_keys")
    need(prereg["schema"] == "arc4.preregistration-inputs/v1" and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", str(prereg["approved_utc"])) is not None, "preregistration_schema")
    need(prereg["design_sha256"] == DESIGN_SHA256, "preregistration_design")
    exact(expected_hashes, ("config_sha256", "frozen_cases_sha256", "environment_lock_sha256", "p0_receipt_sha256", "source_inventory_sha256"), "preregistration_expected_hash_keys")
    need(all(prereg[key] == value for key, value in expected_hashes.items()), "preregistration_hashes")
    need(config.get("schema") == "arc4.campaign-config/v1" and config.get("run_id") == prereg["run_id"] == cases["run_id"], "preregistration_run_identity")
    planned = cases.get("planned_rows")
    need(isinstance(planned, list) and len(planned) == 264, "preregistration_planned_rows")
    matrix = [row for row in planned if row.get("arm") == "matrix"]
    preflight = [row for row in planned if row.get("arm") == "preflight"]
    matrix_pairs = {row.get("pair_id") for row in matrix}
    preflight_pairs = {row.get("pair_id") for row in preflight}
    need(len(matrix) == 240 and len(matrix_pairs) == 120 and len(preflight) == 24 and len(preflight_pairs) == 12, "preregistration_plan_counts")
    need(all(sum(row.get("pair_id") == pair_id for row in matrix) == 2 for pair_id in matrix_pairs) and all(sum(row.get("pair_id") == pair_id for row in preflight) == 2 for pair_id in preflight_pairs), "preregistration_pair_multiplicity")
    need((prereg["matrix_rows"], prereg["matrix_pairs"], prereg["preflight_rows"], prereg["preflight_pairs"]) == (len(matrix), len(matrix_pairs), len(preflight), len(preflight_pairs)) == (240, 120, 24, 12), "preregistration_counts")
    need(prereg["claim_ceiling"] == "fixed_suite_descriptive_only_no_inference" and prereg["p0_claim_ceiling"] == p0["claim_ceiling"] == P0_CLAIM_CEILING and prereg["p0_does_not_establish"] == p0["does_not_establish"] == P0_NONCOVERAGE and prereg["no_early_stop"] is True and prereg["verdict_requires_complete_coverage"] is True, "preregistration_claims")


def verify_preregistration(root: Path, *, cases: Mapping[str, Any], p0: Mapping[str, Any], lock: Mapping[str, Any]) -> None:
    prereg = load(root / "PREREGISTRATION-INPUTS.json")
    config = load(root / "CONFIG.json")
    need(Path(str(config["packet_root"])).resolve() == root.resolve(), "campaign_packet_root")
    canonical_config_paths = {
        "frozen_cases": root / "frozen-cases.json",
        "environment_lock": root / "ENVIRONMENT-LOCK.json",
        "preregistration_inputs": root / "PREREGISTRATION-INPUTS.json",
        "preregistration_commit_receipt": root / "PREREGISTRATION-COMMIT.json",
        "source_build_receipt": root / SOURCE_BUILD_RECEIPT_PATH,
        "source_build_receipt_digest": root / SOURCE_BUILD_DIGEST_PATH,
        "p0_receipt": root / "P0-RECEIPT.json",
    }
    for key, expected in canonical_config_paths.items():
        need(Path(str(config[key])).resolve() == expected.resolve(), "campaign_artifact_path")
    frozen_config = Path(str(config["frozen_config"])).resolve()
    need(frozen_config != (root / "CONFIG.json").resolve() and frozen_config.is_file() and frozen_config.read_bytes() == (root / "CONFIG.json").read_bytes(), "external_frozen_config_bytes")
    capture_specs = config["environment_capture_specs"]
    need(Path(str(capture_specs["numpy_present"])).resolve() == (root / "env" / "raw-numpy-present.json").resolve() and Path(str(capture_specs["numpy_absent"])).resolve() == (root / "env" / "raw-numpy-absent.json").resolve(), "campaign_capture_paths")
    validate_preregistration_semantics(
        prereg, cases=cases, p0=p0, config=config,
        expected_hashes={
            "config_sha256": file_sha(root / "CONFIG.json"),
            "frozen_cases_sha256": file_sha(root / "frozen-cases.json"),
            "environment_lock_sha256": file_sha(root / "ENVIRONMENT-LOCK.json"),
            "p0_receipt_sha256": file_sha(root / "P0-RECEIPT.json"),
            "source_inventory_sha256": file_sha(root / "SOURCE-INVENTORY.json"),
        },
    )
    inventory = load(root / "SOURCE-INVENTORY.json")
    exact(inventory, ("schema", "official_wheel", "p0", "source", "corpora", "query_vectors", "environment", "unreproducible_elements"), "source_inventory_keys")
    exact(inventory["official_wheel"], ("path", "sha256", "pypi_url"), "source_inventory_wheel_keys")
    exact(inventory["p0"], ("path", "sha256", "status", "claim_ceiling"), "source_inventory_p0_keys")
    exact(inventory["source"], ("commit", "build_receipt", "build_receipt_path", "build_receipt_sha256", "build_receipt_digest_path", "build_receipt_digest_sha256", "rebuilt_wheel_sha256"), "source_inventory_source_keys")
    exact(inventory["environment"], ("lock_path", "lock_sha256", "manifest_bindings"), "source_inventory_environment_keys")
    need(isinstance(inventory["corpora"], list) and isinstance(inventory["query_vectors"], list), "source_inventory_lists")
    for item in inventory["corpora"]:
        exact(item, ("name", "working_database_sha256", "candidate_ids_sha256", "candidate_count"), "source_inventory_corpus_keys")
    for item in inventory["query_vectors"]:
        exact(item, ("query_id", "vector", "sha256"), "source_inventory_query_keys")
        need(isinstance(item["vector"], list) and len(item["vector"]) == 384 and hashlib.sha256(json.dumps(item["vector"], ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=False).encode("utf-8")).hexdigest() == item["sha256"], "source_inventory_query_digest")
    need(inventory["schema"] == "arc4.source-inventory/v1" and inventory["official_wheel"]["sha256"] == OFFICIAL_WHEEL_SHA256 and file_sha(root / inventory["official_wheel"]["path"]) == OFFICIAL_WHEEL_SHA256, "source_inventory_wheel")
    need(inventory["official_wheel"]["path"] == "inputs/jcodemunch_mcp-1.108.228-py3-none-any.whl" and isinstance(inventory["official_wheel"]["pypi_url"], str) and inventory["official_wheel"]["pypi_url"].startswith("https://files.pythonhosted.org/"), "source_inventory_wheel_identity")
    need(inventory["p0"] == {"path": "P0-RECEIPT.json", "sha256": file_sha(root / "P0-RECEIPT.json"), "status": "passed", "claim_ceiling": P0_CLAIM_CEILING}, "source_inventory_p0")
    source = inventory["source"]
    build = source["build_receipt"]
    exact(build, ("schema", "source_commit", "git", "python", "build", "produced_wheel", "comparison_tool_sha256", "generator_sha256"), "source_build_receipt_keys")
    exact(build["git"], ("head", "clean", "detached", "core_autocrlf", "status_sha256"), "source_build_git_keys")
    exact(build["python"], ("implementation", "version", "cache_tag", "executable", "executable_sha256"), "source_build_python_keys")
    exact(build["build"], ("backend", "backend_version", "command", "cwd", "environment"), "source_build_command_keys")
    exact(build["produced_wheel"], ("path", "sha256"), "source_build_wheel_keys")
    commit = "8bed872e9436093be9f89d35fb84e0cb58a293af"
    need(build["schema"] == "arc4.source-build-receipt/v2" and source["commit"] == build["source_commit"] == commit and build["git"] == {"head": commit, "clean": True, "detached": True, "core_autocrlf": "false", "status_sha256": hashlib.sha256(b"").hexdigest()}, "source_build_git_state")
    need(build["python"]["implementation"] == "CPython" and build["python"]["version"] == "3.13.7" and build["python"]["cache_tag"] == "cpython-313" and sha256_text(build["python"]["executable_sha256"]), "source_build_python")
    command = build["build"]["command"]
    need(build["build"]["backend"] == "hatchling" and build["build"]["backend_version"] == "1.31.0" and isinstance(command, list) and len(command) >= 8 and command[0] == build["python"]["executable"] and command[1:5] == ["-m", "build", "--wheel", "--no-isolation"] and isinstance(build["build"]["cwd"], str) and bool(build["build"]["cwd"]), "source_build_command")
    environment = build["build"]["environment"]
    need(isinstance(environment, dict) and set(environment) == {"SystemRoot", "ComSpec", "TEMP", "TMP", "USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH", "PATH", "PYTHONNOUSERSITE", "PYTHONHASHSEED", "PYTHONUTF8", "PIP_NO_INDEX"} and environment["PYTHONNOUSERSITE"] == "1" and environment["PIP_NO_INDEX"] == "1", "source_build_environment")
    need(source["rebuilt_wheel_sha256"] == build["produced_wheel"]["sha256"] == p0["rebuilt_sha256"] and build["comparison_tool_sha256"] == build["generator_sha256"] == p0["comparison_tool_sha256"], "source_build_p0_binding")
    need(source["build_receipt_sha256"] == hashlib.sha256(canonical(build)).hexdigest(), "source_build_receipt_hash")
    need(source["build_receipt_path"] == SOURCE_BUILD_RECEIPT_PATH and (root / SOURCE_BUILD_RECEIPT_PATH).read_bytes() == canonical(build), "source_build_receipt_file")
    need(source["build_receipt_digest_path"] == SOURCE_BUILD_DIGEST_PATH and (root / SOURCE_BUILD_DIGEST_PATH).read_bytes() == (source["build_receipt_sha256"] + "\n").encode("ascii"), "source_build_digest_file")
    need(source["build_receipt_digest_sha256"] == file_sha(root / SOURCE_BUILD_DIGEST_PATH), "source_build_digest_hash")
    expected_corpora = [{key: corpus[key] for key in ("name", "working_database_sha256", "candidate_ids_sha256", "candidate_count")} for corpus in cases["corpora"]]
    need(inventory["corpora"] == expected_corpora, "source_inventory_corpora")
    expected_queries = {row["query_id"]: row["query_vector_sha256"] for row in cases["planned_rows"]}
    need([{"query_id": item["query_id"], "sha256": item["sha256"]} for item in inventory["query_vectors"]] == [{"query_id": key, "sha256": expected_queries[key]} for key in sorted(expected_queries)], "source_inventory_queries")
    need(inventory["environment"] == {"lock_path": "ENVIRONMENT-LOCK.json", "lock_sha256": file_sha(root / "ENVIRONMENT-LOCK.json"), "manifest_bindings": lock["manifest_bindings"]} and inventory["unreproducible_elements"] == P0_NONCOVERAGE, "source_inventory_environment")
    commit_receipt = load(root / "PREREGISTRATION-COMMIT.json")
    exact(commit_receipt, ("schema", "commit_sha", "committed", "files"), "prereg_commit_keys")
    need(commit_receipt["schema"] == "arc4.preregistration-commit/v1" and commit_receipt["committed"] is True and isinstance(commit_receipt["commit_sha"], str) and len(commit_receipt["commit_sha"]) == 40 and all(character in "0123456789abcdef" for character in commit_receipt["commit_sha"]), "prereg_commit_status")
    expected_committed = {
        "CONFIG.json": file_sha(root / "CONFIG.json"),
        "ENVIRONMENT-LOCK.json": file_sha(root / "ENVIRONMENT-LOCK.json"),
        "P0-RECEIPT.json": file_sha(root / "P0-RECEIPT.json"),
        "PREREGISTRATION-INPUTS.json": file_sha(root / "PREREGISTRATION-INPUTS.json"),
        "SOURCE-BUILD-RECEIPT.json": file_sha(root / SOURCE_BUILD_RECEIPT_PATH),
        "SOURCE-BUILD-RECEIPT.sha256": file_sha(root / SOURCE_BUILD_DIGEST_PATH),
        "SOURCE-INVENTORY.json": file_sha(root / "SOURCE-INVENTORY.json"),
        "frozen-cases.json": file_sha(root / "frozen-cases.json"),
    }
    need(commit_receipt["files"] == expected_committed, "prereg_commit_files")


def verify_original_matrix(root: Path) -> None:
    declaration = load(root / "ORIGINAL-MATRIX-DECOMPOSITION.json")
    source = Path(str(declaration.get("source_csv_path", "")))
    need(source.is_file() and file_sha(source) == declaration.get("source_csv_sha256"), "original_matrix_source")
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream, strict=True))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise Rejected("original_matrix_csv") from exc
    need(len(rows) == 360, "original_matrix_rows")
    need(len({row.get("row_id") for row in rows}) == 360, "original_matrix_row_ids")
    cases = defaultdict(list)
    pairs = defaultdict(list)
    modes: set[str | None] = set()
    for row in rows:
        cases[row.get("case_id")].append(row)
        pairs[row.get("pair_id")].append(row)
        modes.add(row.get("mode"))
        need(row.get("row_status") == "retained", "original_matrix_status")
    need(len(cases) == 24 and all(len(group) == 15 for group in cases.values()), "original_matrix_cases")
    need(len(pairs) == 120 and all(len(group) == 3 for group in pairs.values()), "original_matrix_pairs")
    need(len(modes) == 3 and all({row.get("mode") for row in group} == modes for group in pairs.values()), "original_matrix_modes")


def validate_rows(rows: Sequence[Mapping[str, Any]], planned: Mapping[str, Mapping[str, Any]], candidates: Mapping[str, set[str]]) -> tuple[int, int, int, int, dict[str, list[Mapping[str, Any]]]]:
    ids: set[str] = set()
    pairs: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    matrix_rows = preflight_rows = 0
    need(len(rows) == len(planned) == 264, "plan_bijection")
    for row in rows:
        need(row.get("row_id") not in ids, "duplicate_row_id")
        ids.add(str(row.get("row_id")))
        need(row.get("arm") in ("matrix", "preflight") and row.get("lane") in ("numpy_present", "numpy_absent"), "row_classification")
        plan = planned.get(str(row.get("row_id")))
        need(plan is not None and all(row.get(field) == plan.get(field) for field in PLAN_FIELDS), "plan_bijection")
        need(isinstance(row.get("case_id"), str) and isinstance(row.get("pair_id"), str), "row_identity")
        need(re.fullmatch(r"[0-9a-f]{64}", str(row.get("query_vector_sha256"))) is not None, "query_vector_hash")
        need(re.fullmatch(r"[0-9a-f]{64}", str(row.get("corpus_sha256"))) is not None, "corpus_hash")
        expected_ids = candidates.get(str(row.get("corpus")))
        need(expected_ids is not None, "row_candidate_corpus")
        validate_row_evidence(row, expected_ids)
        pairs[str(row["pair_id"])].append(row)
        matrix_rows += row["arm"] == "matrix"
        preflight_rows += row["arm"] == "preflight"
    matrix_pairs = preflight_pairs = 0
    for pair in pairs.values():
        need(len(pair) == 2 and {row["lane"] for row in pair} == {"numpy_present", "numpy_absent"}, "pair_lanes")
        need(len({row["case_id"] for row in pair}) == 1 and len({row["arm"] for row in pair}) == 1, "pair_identity")
        matrix_pairs += pair[0]["arm"] == "matrix"
        preflight_pairs += pair[0]["arm"] == "preflight"
    need(ids == set(planned), "plan_bijection")
    matrix = [row for row in rows if row["arm"] == "matrix"]
    need(len({row["problem_id"] for row in matrix}) == 12 and len({row["query_id"] for row in rows}) == 4, "observed_factor_counts")
    need(all(sum(row["problem_id"] == value for row in matrix) == 20 for value in {row["problem_id"] for row in matrix}), "observed_problem_multiplicity")
    need(all(sum(row["query_id"] == value for row in matrix) == 60 for value in {row["query_id"] for row in matrix}), "observed_query_multiplicity")
    need(all(sum(row["lane"] == value for row in matrix) == 120 for value in ("numpy_present", "numpy_absent")), "observed_lane_multiplicity")
    need(all(sum(row["cache_state"] == value for row in matrix) == 120 for value in ("cold_fresh_process", "generation_warm")), "observed_cache_multiplicity")
    need(all(sum(row["repetition"] == value for row in matrix) == 48 for value in range(1, 6)), "observed_repetition_multiplicity")
    return matrix_rows, matrix_pairs, preflight_rows, preflight_pairs, pairs


def validate_m7(rows: Sequence[Mapping[str, Any]]) -> None:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["arm"] == "matrix":
            groups[(row["case_id"], row["lane"])].append(row)
    need(len(groups) == 48 and all(len(group) == 5 for group in groups.values()), "m7_coverage")
    for group in groups.values():
        ordered_group = sorted(group, key=lambda item: int(item["repetition"]))
        reference = ordered_group[0]
        for row in ordered_group[1:]:
            need(row["public_result_ids"] == reference["public_result_ids"], "m7_order")
            need(row["full_depth_ordering_sha256"] == reference["full_depth_ordering_sha256"], "m7_full_depth")
            top_ids = reference["public_result_ids"][: int(reference["top_k"])]
            need([row["final_scores"][symbol_id] for symbol_id in top_ids] == [reference["final_scores"][symbol_id] for symbol_id in top_ids], "m7_top_scores")
            projection = recompute_pair(reference, row)
            need(projection["m1_rank0_difference"] is False and projection["m2_ordered_top_k_difference"] is False and projection["m3_membership_top_k_difference"] is False and projection["m4_exact_tie_difference"] is False, "m7_negative_control")
            need(projection["m5_top_k_inversion_count"] == projection["m5_full_inversion_count"] == projection["m6_top_k_genuine_disagreement_count"] == projection["m6_full_genuine_disagreement_count"] == 0, "m7_negative_control")


CONTROL_EVIDENCE_KEYS = {
    "C1": ("lanes",),
    "C2": ("p0_receipt_sha256", "source_commit", "build_receipt_sha256", "build_wheel_sha256", "comparison_tool_sha256", "checkout_clean", "checkout_detached", "core_autocrlf"),
    "C3": ("rows_checked", "database_unchanged_rows", "wal_unchanged_rows", "embeddings_unchanged_rows", "frozen_originals"),
    "C4": ("rows_checked", "matching_rows", "planned_query_vector_hashes", "observed_query_vector_hashes"),
    "C5": ("rows_checked", "matrix_rows_checked", "numpy_version", "numpy_importable_before", "numpy_helper_non_null_before", "numpy_importable_after", "numpy_helper_non_null_after", "vectorised_matrix_rows", "cache_numpy_rows"),
    "C6": ("rows_checked", "matrix_rows_checked", "numpy_import_failures_before", "find_spec_none_before", "numpy_helper_none_before", "numpy_import_failures_after", "find_spec_none_after", "numpy_helper_none_after", "fallback_matrix_rows", "cache_python_rows"),
    "C7": ("matrix_rows_checked", "expected_provider_calls", "observed_provider_calls", "frozen_text_calls", "frozen_vector_calls", "topup_tripwire_events", "package_unchanged_rows"),
    "C8": ("matrix_rows_checked", "matrix_order_matches", "matrix_rounded_score_matches", "preflight_rows_checked", "preflight_order_matches", "debug_true_rows"),
    "C9": ("deterministic_groups", "deterministic_groups_expected", "seed_subset_row_id", "seeds", "ordering_sha256_by_seed", "seed_observations", "seed_dependence_observed"),
    "C10": ("matrix_numpy_first", "matrix_python_first", "preflight_numpy_first", "preflight_python_first"),
    "C11": ("matrix_rows_checked", "topup_tripwire_events", "database_unchanged_rows", "embedding_count_unchanged_rows"),
    "C12": ("preflight_rows_checked", "get_matrix_called_rows", "cold_rows", "cold_cache_hit_rows", "warm_rows", "warm_cache_hit_rows"),
    "C13": ("manifest_scope", "detached_root_required", "closed_world_required", "self_test_names", "verification_entrypoint"),
    "C14": ("cold_rows_checked", "cold_repos_zero_rows", "warm_rows_checked", "warm_expected_cache_rows", "warm_matrix_stamp_unchanged_rows"),
    "C15": ("rows_checked", "storage_tuning_absent_rows", "home_tuning_absent_rows", "effective_weight_matches_rows"),
    "C16": ("environment_lock_sha256", "raw_manifest_hashes", "canonical_manifest_hashes", "only_declared_difference"),
    "C20": ("matrix_rows_checked", "raw_vectors_checked", "final_vectors_checked", "candidate_set_matches_rows", "ordering_hash_matches_rows"),
    "C21": ("rows_checked", "tripwire_installed_before_config_rows", "tripwire_lifetime_guard_rows", "outbound_attempts", "credentials_absent_rows", "sharing_disabled_rows"),
}


def _control_counts(evidence: Mapping[str, Any], total: int, fields: Sequence[str], code: str) -> None:
    need(all(isinstance(evidence.get(field), int) and not isinstance(evidence.get(field), bool) and evidence[field] == total for field in fields), code)


def verify_external_control_predicate(control_id: str, evidence: Mapping[str, Any]) -> None:
    """Independently enforce the DESIGN section 12 pass predicate after recomputation."""
    exact(evidence, CONTROL_EVIDENCE_KEYS[control_id], f"{control_id.lower()}_evidence_keys")
    if control_id == "C1":
        exact(evidence["lanes"], ("numpy_present", "numpy_absent"), "c1_lanes")
        for lane in ("numpy_present", "numpy_absent"):
            need(evidence["lanes"][lane] == {"wheel_sha256": OFFICIAL_WHEEL_SHA256, "package_version": "1.108.228"}, "c1_predicate")
    elif control_id == "C2":
        need(evidence["source_commit"] == "8bed872e9436093be9f89d35fb84e0cb58a293af" and evidence["checkout_clean"] is True and evidence["checkout_detached"] is True and evidence["core_autocrlf"] == "false", "c2_predicate")
        need(all(sha256_text(evidence[key]) for key in ("p0_receipt_sha256", "build_receipt_sha256", "build_wheel_sha256", "comparison_tool_sha256")), "c2_hashes")
    elif control_id == "C3":
        _control_counts(evidence, 264, ("rows_checked", "database_unchanged_rows", "wal_unchanged_rows", "embeddings_unchanged_rows"), "c3_predicate")
        need(evidence["frozen_originals"]["start"] == evidence["frozen_originals"]["end"], "c3_frozen_mutation")
    elif control_id == "C4":
        _control_counts(evidence, 264, ("rows_checked", "matching_rows"), "c4_predicate")
        need(evidence["planned_query_vector_hashes"] == evidence["observed_query_vector_hashes"] and len(evidence["planned_query_vector_hashes"]) == 4, "c4_hashes")
    elif control_id == "C5":
        _control_counts(evidence, 132, ("rows_checked", "numpy_importable_before", "numpy_helper_non_null_before", "numpy_importable_after", "numpy_helper_non_null_after", "cache_numpy_rows"), "c5_predicate")
        _control_counts(evidence, 120, ("matrix_rows_checked", "vectorised_matrix_rows"), "c5_predicate")
        need(evidence["numpy_version"] == "2.4.4", "c5_predicate")
    elif control_id == "C6":
        _control_counts(evidence, 132, ("rows_checked", "numpy_import_failures_before", "find_spec_none_before", "numpy_helper_none_before", "numpy_import_failures_after", "find_spec_none_after", "numpy_helper_none_after", "cache_python_rows"), "c6_predicate")
        _control_counts(evidence, 120, ("matrix_rows_checked", "fallback_matrix_rows"), "c6_predicate")
    elif control_id == "C7":
        _control_counts(evidence, 240, ("matrix_rows_checked", "package_unchanged_rows"), "c7_predicate")
        need(evidence["expected_provider_calls"] == evidence["observed_provider_calls"] == evidence["frozen_text_calls"] == evidence["frozen_vector_calls"] and evidence["topup_tripwire_events"] == 0, "c7_predicate")
    elif control_id == "C8":
        _control_counts(evidence, 240, ("matrix_rows_checked", "matrix_order_matches", "matrix_rounded_score_matches"), "c8_predicate")
        _control_counts(evidence, 24, ("preflight_rows_checked", "preflight_order_matches"), "c8_predicate")
        _control_counts(evidence, 264, ("debug_true_rows",), "c8_predicate")
    elif control_id == "C10":
        need(evidence == {"matrix_numpy_first": 60, "matrix_python_first": 60, "preflight_numpy_first": 6, "preflight_python_first": 6}, "c10_predicate")
    elif control_id == "C11":
        _control_counts(evidence, 240, ("matrix_rows_checked", "database_unchanged_rows", "embedding_count_unchanged_rows"), "c11_predicate")
        need(evidence["topup_tripwire_events"] == 0, "c11_predicate")
    elif control_id == "C12":
        need(evidence == {"preflight_rows_checked": 24, "get_matrix_called_rows": 0, "cold_rows": 12, "cold_cache_hit_rows": 0, "warm_rows": 12, "warm_cache_hit_rows": 12}, "c12_predicate")
    elif control_id == "C14":
        _control_counts(evidence, 132, ("cold_rows_checked", "cold_repos_zero_rows", "warm_rows_checked", "warm_expected_cache_rows"), "c14_predicate")
        _control_counts(evidence, 120, ("warm_matrix_stamp_unchanged_rows",), "c14_predicate")
    elif control_id == "C15":
        _control_counts(evidence, 264, ("rows_checked", "storage_tuning_absent_rows", "home_tuning_absent_rows", "effective_weight_matches_rows"), "c15_predicate")
    elif control_id == "C16":
        need(sha256_text(evidence["environment_lock_sha256"]) and set(evidence["raw_manifest_hashes"]) == {"numpy_present", "numpy_absent"} and set(evidence["canonical_manifest_hashes"]) == {"numpy_present", "numpy_absent"} and all(sha256_text(value) for group in (evidence["raw_manifest_hashes"], evidence["canonical_manifest_hashes"]) for value in group.values()) and evidence["only_declared_difference"] == "numpy==2.4.4", "c16_predicate")
    elif control_id == "C20":
        _control_counts(evidence, 240, ("matrix_rows_checked", "raw_vectors_checked", "final_vectors_checked", "candidate_set_matches_rows", "ordering_hash_matches_rows"), "c20_predicate")
    elif control_id == "C21":
        _control_counts(evidence, 264, ("rows_checked", "tripwire_installed_before_config_rows", "tripwire_lifetime_guard_rows", "credentials_absent_rows", "sharing_disabled_rows"), "c21_predicate")
        need(evidence["outbound_attempts"] == 0, "c21_predicate")
    else:
        raise Rejected("external_control_id", control_id)


def _db_unchanged(row: Mapping[str, Any]) -> bool:
    before = row.get("database_state_before")
    after = row.get("database_state")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    keys = ("database_sha256", "wal_sha256", "wal_size", "shm_sha256", "shm_size", "logical_embedding_sha256", "embedding_count")
    if set(before) != set(keys) or set(after) != set(keys):
        return False
    if before["database_sha256"] != after["database_sha256"] or before["logical_embedding_sha256"] != after["logical_embedding_sha256"] or before["embedding_count"] != after["embedding_count"]:
        return False
    if before["wal_sha256"] is None:
        return after["wal_sha256"] is None or after["wal_size"] <= 32
    return before["wal_sha256"] == after["wal_sha256"] and before["wal_size"] == after["wal_size"]


def _projection_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()


def verify_synthetic_control(control_id: str, evidence: Mapping[str, Any]) -> None:
    exact(evidence, ("fixtures",), "synthetic_control_keys")
    fixtures = evidence["fixtures"]
    need(isinstance(fixtures, list), "synthetic_control_fixtures")
    expected_names = {
        "C17": {"known_zero"},
        "C18": set(CONTROL_PROJECTION_SHA256) - {"known_zero", "one_ulp_cross"} | {"aggregate_sentinels"},
        "C19": {"one_ulp_cross"},
    }[control_id]
    need({item.get("fixture") for item in fixtures if isinstance(item, dict)} == expected_names and len(fixtures) == len(expected_names), "synthetic_control_fixtures")
    for fixture in fixtures:
        if fixture.get("fixture") == "aggregate_sentinels":
            exact(fixture, ("schema", "fixture", "expected_projection", "observed_projection", "passed"), "synthetic_fixture_keys")
            expected = {"input": ["0x0.0p+0", "0x1.0000000000000p+1", "+inf", "exact_tie"], "eligible": ["0x0.0p+0", "0x1.0000000000000p+1"], "numeric": {"count": 2, "minimum": "0x0.0p+0", "maximum": "0x1.0000000000000p+1", "median": "0x1.0000000000000p+0", "p99_nearest_rank": "0x1.0000000000000p+1"}, "plus_inf": 1, "exact_tie": 1, "finite_zero": 1}
            need(fixture["expected_projection"] == fixture["observed_projection"] == expected and fixture["passed"] is True, "synthetic_aggregate")
            continue
        exact(fixture, ("schema", "fixture", "top_k", "numpy_scores", "python_scores", "expected_projection", "observed_projection", "passed"), "synthetic_fixture_keys")
        name = fixture["fixture"]
        need(name in CONTROL_PROJECTION_SHA256 and isinstance(fixture["top_k"], int) and fixture["top_k"] > 0, "synthetic_fixture_identity")
        for scores in (fixture["numpy_scores"], fixture["python_scores"]):
            need(isinstance(scores, dict) and bool(scores) and all(isinstance(key, str) and float.fromhex(value).hex() == value for key, value in scores.items()), "synthetic_fixture_scores")
        expected = fixture["expected_projection"]
        observed = fixture["observed_projection"]
        exact(expected, PROJECTION_KEYS, "synthetic_projection_keys")
        exact(observed, PROJECTION_KEYS, "synthetic_projection_keys")
        need(_projection_digest(expected) == CONTROL_PROJECTION_SHA256[name], "synthetic_expected_projection")
        left = {"final_scores": fixture["numpy_scores"], "raw_cosine": fixture["numpy_scores"], "top_k": fixture["top_k"]}
        right = {"final_scores": fixture["python_scores"], "raw_cosine": fixture["python_scores"], "top_k": fixture["top_k"]}
        recomputed = control_projection(recompute_pair(left, right))
        need(expected == observed == recomputed and fixture["passed"] is True, "synthetic_projection")


def _expected_controls(root: Path, rows: Sequence[Mapping[str, Any]], cases: Mapping[str, Any], p0: Mapping[str, Any], lock: Mapping[str, Any], manifest_sha: str, manifest_count: int, *, originals: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    matrix = [row for row in rows if row["arm"] == "matrix"]
    preflight = [row for row in rows if row["arm"] == "preflight"]
    present = [row for row in rows if row["lane"] == "numpy_present"]
    absent = [row for row in rows if row["lane"] == "numpy_absent"]
    frozen = {item["name"]: item["working_database_sha256"] for item in cases["corpora"]}
    inventory = load(root / "SOURCE-INVENTORY.json")
    provider_calls = [call for row in matrix for call in row.get("provider_calls", [])]
    frozen_calls = sum(
        isinstance(call, dict) and set(call) == {"texts", "provider", "model", "task_type", "query_vector_sha256"}
        and isinstance(call["texts"], list) and len(call["texts"]) == 1 and call["query_vector_sha256"] == row["query_vector_sha256"]
        for row in matrix for call in row.get("provider_calls", [])
    )
    raw_hashes = {lane: lock["manifest_bindings"]["raw"][lane]["sha256"] for lane in ("numpy_present", "numpy_absent")}
    canonical_hashes = {lane: lock["manifest_bindings"]["canonical"][lane]["sha256"] for lane in ("numpy_present", "numpy_absent")}
    expected_calls = sum(int(row["controls"]["provider_expected_calls"]) for row in matrix)
    if originals is None:
        c3 = load(root / "controls" / "C3.json").get("evidence", {}).get("frozen_originals") if (root / "controls" / "C3.json").is_file() else None
        originals = c3
    need(isinstance(originals, dict), "c3_original_receipts")
    pair_orders: dict[str, tuple[str, str]] = {}
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["pair_id"])].append(row)
    for pair_id, pair in grouped.items():
        need({row.get("pair_invocation_ordinal") for row in pair} == {1, 2}, "c10_observed_ordinals")
        first = next(row for row in pair if row["pair_invocation_ordinal"] == 1)
        declared = str(first["lane_invocation_order"])
        expected_first = "numpy_present" if declared == "numpy_first" else "numpy_absent"
        need(first["lane"] == expected_first, "c10_observed_order")
        pair_orders[pair_id] = (str(first["arm"]), declared)
    build = inventory["source"]["build_receipt"]
    return {
        "C1": {"lanes": {lane: {"wheel_sha256": sorted({row["package_evidence"]["official_wheel_sha256"] for row in rows if row["lane"] == lane})[0] if len({row["package_evidence"]["official_wheel_sha256"] for row in rows if row["lane"] == lane}) == 1 else "__inconsistent__", "package_version": sorted({row["package_evidence"]["installed_version"] for row in rows if row["lane"] == lane})[0] if len({row["package_evidence"]["installed_version"] for row in rows if row["lane"] == lane}) == 1 else "__inconsistent__"} for lane in ("numpy_present", "numpy_absent")}},
        "C2": {"p0_receipt_sha256": file_sha(root / "P0-RECEIPT.json"), "source_commit": inventory["source"]["commit"], "build_receipt_sha256": inventory["source"]["build_receipt_sha256"], "build_wheel_sha256": build["produced_wheel"]["sha256"], "comparison_tool_sha256": build["comparison_tool_sha256"], "checkout_clean": build["git"]["clean"], "checkout_detached": build["git"]["detached"], "core_autocrlf": build["git"]["core_autocrlf"]},
        "C3": {"rows_checked": len(rows), "database_unchanged_rows": sum(_db_unchanged(row) for row in rows), "wal_unchanged_rows": sum(_db_unchanged(row) for row in rows), "embeddings_unchanged_rows": sum(row["database_state_before"].get("logical_embedding_sha256") == row["database_state"].get("logical_embedding_sha256") for row in rows), "frozen_originals": originals},
        "C4": {"rows_checked": len(rows), "matching_rows": sum(row.get("observed_query_vector_sha256") == row["query_vector_sha256"] for row in rows), "planned_query_vector_hashes": sorted({row["query_vector_sha256"] for row in rows}), "observed_query_vector_hashes": sorted({row.get("observed_query_vector_sha256") for row in rows})},
        "C5": {"rows_checked": len(present), "matrix_rows_checked": sum(row["arm"] == "matrix" for row in present), "numpy_version": "2.4.4", "numpy_importable_before": sum(row["lane_evidence"]["numpy_importable_before"] is True for row in present), "numpy_helper_non_null_before": sum(row["lane_evidence"]["numpy_helper_non_null_before"] is True for row in present), "numpy_importable_after": sum(row["lane_evidence"]["numpy_importable_after"] is True for row in present), "numpy_helper_non_null_after": sum(row["lane_evidence"]["numpy_helper_non_null_after"] is True for row in present), "vectorised_matrix_rows": sum(row["lane_evidence"]["matrix_vectorised"] is True for row in present if row["arm"] == "matrix"), "cache_numpy_rows": sum(row["cache_after_public"].get("numpy") is True for row in present)},
        "C6": {"rows_checked": len(absent), "matrix_rows_checked": sum(row["arm"] == "matrix" for row in absent), "numpy_import_failures_before": sum(row["lane_evidence"]["numpy_import_failed_before"] is True for row in absent), "find_spec_none_before": sum(row["lane_evidence"]["numpy_importable_before"] is False for row in absent), "numpy_helper_none_before": sum(row["lane_evidence"]["numpy_helper_non_null_before"] is False for row in absent), "numpy_import_failures_after": sum(row["lane_evidence"]["numpy_import_failed_after"] is True for row in absent), "find_spec_none_after": sum(row["lane_evidence"]["numpy_importable_after"] is False for row in absent), "numpy_helper_none_after": sum(row["lane_evidence"]["numpy_helper_non_null_after"] is False for row in absent), "fallback_matrix_rows": sum(row["lane_evidence"]["matrix_vectorised"] is False for row in absent if row["arm"] == "matrix"), "cache_python_rows": sum(row["cache_after_public"].get("numpy") is False for row in absent)},
        "C7": {"matrix_rows_checked": len(matrix), "expected_provider_calls": expected_calls, "observed_provider_calls": len(provider_calls), "frozen_text_calls": frozen_calls, "frozen_vector_calls": frozen_calls, "topup_tripwire_events": sum(row["controls"]["topup_tripwire_events"] for row in matrix), "package_unchanged_rows": sum(row["controls"]["package_unchanged"] is True and row["package_evidence"]["payload_matches_official_wheel"] is True for row in matrix)},
        "C8": {"matrix_rows_checked": len(matrix), "matrix_order_matches": sum(row["debug_observation"]["order_matches"] is True for row in matrix), "matrix_rounded_score_matches": sum(row["debug_observation"]["rounded_scores_match"] is True for row in matrix), "preflight_rows_checked": len(preflight), "preflight_order_matches": sum(row["debug_observation"]["order_matches"] is True for row in preflight), "debug_true_rows": sum(row["debug_observation"]["debug"] is True for row in rows)},
        "C10": {"matrix_numpy_first": sum(arm == "matrix" and order == "numpy_first" for arm, order in pair_orders.values()), "matrix_python_first": sum(arm == "matrix" and order == "python_first" for arm, order in pair_orders.values()), "preflight_numpy_first": sum(arm == "preflight" and order == "numpy_first" for arm, order in pair_orders.values()), "preflight_python_first": sum(arm == "preflight" and order == "python_first" for arm, order in pair_orders.values())},
        "C11": {"matrix_rows_checked": len(matrix), "topup_tripwire_events": sum(row["controls"]["topup_tripwire_events"] for row in matrix), "database_unchanged_rows": sum(_db_unchanged(row) for row in matrix), "embedding_count_unchanged_rows": sum(row["database_state_before"]["embedding_count"] == row["database_state"]["embedding_count"] for row in matrix)},
        "C12": {"preflight_rows_checked": len(preflight), "get_matrix_called_rows": sum(row["matrix_stamp_after_measurement"] is not None for row in preflight), "cold_rows": sum(row["cache_state"] == "cold_fresh_process" for row in preflight), "cold_cache_hit_rows": sum(row["cache_state"] == "cold_fresh_process" and row["served_from_result_cache"] is True for row in preflight), "warm_rows": sum(row["cache_state"] == "generation_warm" for row in preflight), "warm_cache_hit_rows": sum(row["cache_state"] == "generation_warm" and row["served_from_result_cache"] is True for row in preflight)},
        "C13": {"manifest_scope": "all_packet_files_except_manifest_root_and_generated_verifier_state", "detached_root_required": True, "closed_world_required": True, "self_test_names": list(SELF_TESTS), "verification_entrypoint": "verify_packet"},
        "C14": {"cold_rows_checked": sum(row["cache_state"] == "cold_fresh_process" for row in rows), "cold_repos_zero_rows": sum(row["cache_state"] == "cold_fresh_process" and row["cache_before"].get("repos") == 0 for row in rows), "warm_rows_checked": sum(row["cache_state"] == "generation_warm" for row in rows), "warm_expected_cache_rows": sum(row["cache_state"] == "generation_warm" and row["cache_after_warmup"].get("repos") == (1 if row["arm"] == "matrix" else 0) for row in rows), "warm_matrix_stamp_unchanged_rows": sum(row["cache_state"] == "generation_warm" and row["arm"] == "matrix" and row["matrix_stamp_before_measurement"] == row["matrix_stamp_after_measurement"] and row["matrix_stamp_before_measurement"] is not None for row in rows)},
        "C15": {"rows_checked": len(rows), "storage_tuning_absent_rows": sum(row["controls"]["storage_tuning_absent"] is True for row in rows), "home_tuning_absent_rows": sum(row["controls"]["home_tuning_absent"] is True for row in rows), "effective_weight_matches_rows": sum(row["controls"]["effective_weight_matches"] is True for row in rows)},
        "C16": {"environment_lock_sha256": file_sha(root / "ENVIRONMENT-LOCK.json"), "raw_manifest_hashes": raw_hashes, "canonical_manifest_hashes": canonical_hashes, "only_declared_difference": "numpy==2.4.4"},
        "C20": {"matrix_rows_checked": len(matrix), "raw_vectors_checked": len(matrix), "final_vectors_checked": len(matrix), "candidate_set_matches_rows": sum(row["controls"]["candidate_set_matches"] is True for row in matrix), "ordering_hash_matches_rows": sum(row["full_depth_ordering_sha256"] == order_hash(row["final_scores"]) for row in matrix)},
        "C21": {"rows_checked": len(rows), "tripwire_installed_before_config_rows": sum(row["controls"]["network_tripwire_installed_before_config"] is True for row in rows), "tripwire_lifetime_guard_rows": sum(row["controls"]["network_lifetime_guard_registered"] is True for row in rows), "outbound_attempts": sum(len(row["controls"]["network_attempts"]) for row in rows), "credentials_absent_rows": sum(row["controls"]["credentials_absent"] is True for row in rows), "sharing_disabled_rows": sum(row["controls"]["sharing_disabled"] is True for row in rows)},
    }


def verify_controls(root: Path, controls: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]], cases: Mapping[str, Any], p0: Mapping[str, Any], lock: Mapping[str, Any], manifest_sha: str, manifest_count: int) -> None:
    need(len(controls) == 21 and [item.get("control_id") for item in controls] == [f"C{number}" for number in range(1, 22)], "control_coverage")
    lock_sha = file_sha(root / "ENVIRONMENT-LOCK.json")
    for row in rows:
        package = row["package_evidence"]
        need(package["environment_lock_sha256"] == lock_sha, "package_lock_binding")
        lane_root = Path(lock["manifest_bindings"]["roots"][row["lane"]]["lane_venv"]).resolve()
        package_root = lane_root / "Lib" / "site-packages" / "jcodemunch_mcp"
        for origin in package["module_origins"].values():
            try:
                origin_path = Path(origin)
                need(not origin_path.is_absolute() and ".." not in origin_path.parts, "module_origin_spelling")
                (package_root / origin_path).resolve().relative_to(package_root)
            except ValueError as exc:
                raise Rejected("module_origin_root") from exc
    expected = _expected_controls(root, rows, cases, p0, lock, manifest_sha, manifest_count)
    for record in controls:
        exact(record, ("schema", "control_id", "status", "evidence"), "control_record_keys")
        control_id = record["control_id"]
        need(record["schema"] == "arc4.control/v1" and record["status"] == "passed", "control_status")
        if control_id in ("C17", "C18", "C19"):
            verify_synthetic_control(control_id, record["evidence"])
        elif control_id == "C9":
            evidence = record["evidence"]
            exact(evidence, CONTROL_EVIDENCE_KEYS["C9"], "c9_evidence_keys")
            need(evidence["deterministic_groups"] == evidence["deterministic_groups_expected"] == 48 and evidence["seed_subset_row_id"] in {row["row_id"] for row in rows}, "c9_determinism")
            need(evidence["seeds"] == ["0", "1", "2", "3", "4", "unset"] and isinstance(evidence["ordering_sha256_by_seed"], dict) and set(evidence["ordering_sha256_by_seed"]) == set(evidence["seeds"]), "c9_seed_set")
            need(all(sha256_text(value) for value in evidence["ordering_sha256_by_seed"].values()) and evidence["seed_dependence_observed"] is (len(set(evidence["ordering_sha256_by_seed"].values())) > 1), "c9_seed_evidence")
            observations = evidence["seed_observations"]
            need(isinstance(observations, list) and len(observations) == 6, "c9_seed_observations")
            for index, observation in enumerate(observations):
                exact(observation, ("control_id", "is_control", "seed", "row_id", "lane", "ordering_sha256"), "c9_seed_observation_keys")
                label = evidence["seeds"][index]
                need(observation["control_id"] == "C9" and observation["is_control"] is True and observation["seed"] == (None if label == "unset" else label) and observation["row_id"] == evidence["seed_subset_row_id"] and observation["lane"] in {"numpy_present", "numpy_absent"} and observation["ordering_sha256"] == evidence["ordering_sha256_by_seed"][label], "c9_seed_observation")
        elif control_id == "C13":
            evidence = record["evidence"]
            exact(evidence, CONTROL_EVIDENCE_KEYS["C13"], "c13_evidence_keys")
            need(evidence == expected["C13"], "c13_contract")
        else:
            evidence = record["evidence"]
            exact(evidence, CONTROL_EVIDENCE_KEYS[control_id], f"{control_id.lower()}_evidence_keys")
            verify_external_control_predicate(control_id, evidence)
            need(evidence == expected[control_id], f"{control_id.lower()}_recomputation")
            if control_id == "C3":
                originals = evidence["frozen_originals"]
                need(isinstance(originals, dict) and set(originals) == {"start", "end"} and originals["start"] == originals["end"], "c3_frozen_mutation")
                for receipt in originals["end"].values():
                    exact(receipt, ("database_path", "files"), "c3_receipt_keys")
                    exact(receipt["files"], ("db", "wal", "shm"), "c3_file_set")
                    database = Path(receipt["database_path"])
                    for suffix, path in (("db", database), ("wal", Path(str(database) + "-wal")), ("shm", Path(str(database) + "-shm"))):
                        item = receipt["files"][suffix]
                        exact(item, ("present", "sha256", "size"), "c3_file_keys")
                        if item["present"]:
                            need(path.is_file() and path.stat().st_size == item["size"] and file_sha(path) == item["sha256"], "c3_live_file")
                        else:
                            need(not path.exists() and item == {"present": False, "sha256": None, "size": 0}, "c3_live_absent")


def verify_allowed_packet_files(root: Path, rows: Sequence[Mapping[str, Any]], lock: Mapping[str, Any]) -> None:
    allowed = {
        "CONFIG.json", "ENVIRONMENT-LOCK.json", "FAILURE-JOURNAL.jsonl", "REPAIR-JOURNAL.jsonl", "ORIGINAL-MATRIX-DECOMPOSITION.json",
        "P0-RECEIPT.json", "PREREGISTRATION-COMMIT.json", "PREREGISTRATION-INPUTS.json", "REPORT.md", "SOURCE-BUILD-RECEIPT.json", "SOURCE-BUILD-RECEIPT.sha256", "SOURCE-INVENTORY.json",
        "SUMMARY.json", "frozen-cases.json", "paired.jsonl", "raw/rows.jsonl", "raw/warmups.jsonl",
        "verify.py",
    }
    allowed.update(f"controls/C{number}.json" for number in range(1, 22))
    for family in ("raw", "canonical"):
        for lane in ("numpy_present", "numpy_absent"):
            allowed.add(lock["manifest_bindings"][family][lane]["path"])
    inventory = load(root / "SOURCE-INVENTORY.json")
    allowed.add(inventory["official_wheel"]["path"])
    for row in rows:
        evidence = row.get("full_ranking_evidence")
        if isinstance(evidence, dict):
            for reference in evidence.values():
                if isinstance(reference, dict) and "path" in reference:
                    allowed.add(reference["path"])
    failure_path = root / "FAILURE-JOURNAL.jsonl"
    failures = [] if failure_path.read_bytes() == b"" else load_jsonl(failure_path)
    for failure in failures:
        evidence = failure.get("evidence")
        if failure.get("stage") == "worker" and isinstance(evidence, dict) and isinstance(evidence.get("invocation_evidence_id"), str):
            prefix = f"invocations/{evidence['invocation_evidence_id']}"
            allowed.update(f"{prefix}/{name}" for name in ("invocation-binding.json", "receipt.json", "job-artifact.json", "stdout.log", "stderr.log"))
    actual = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    } - {"MANIFEST.json", "MANIFEST.sha256", *GENERATED_PACKET_FILES}
    need(actual == allowed, "packet_file_set")


def verify_packet(root: Path) -> dict[str, Any]:
    manifest_sha, manifest_count = verify_manifest(root)
    p0 = verify_p0(root)
    cases, planned, candidates = verify_frozen_cases(root)
    lock = verify_environment(root)
    verify_preregistration(root, cases=cases, p0=p0, lock=lock)
    prereg = load(root / "PREREGISTRATION-INPUTS.json")
    config = load(root / "CONFIG.json")
    verify_original_matrix(root)
    rows = [hydrate_row(root, row) for row in load_jsonl(root / "raw" / "rows.jsonl")]
    verify_allowed_packet_files(root, rows, lock)
    matrix_rows, matrix_pairs, preflight_rows, preflight_pairs, pairs = validate_rows(rows, planned, candidates)
    need((matrix_rows, matrix_pairs, preflight_rows, preflight_pairs) == (EXPECTED_MATRIX_ROWS, EXPECTED_MATRIX_PAIRS, EXPECTED_PREFLIGHT_ROWS, EXPECTED_PREFLIGHT_PAIRS), "coverage")
    validate_m7(rows)
    warmups = load_jsonl(root / "raw" / "warmups.jsonl")
    need(len(warmups) == 66 and len({item.get("pair_id") for item in warmups}) == 66, "warmup_coverage")
    need(all(item.get("schema") == "arc4.warmup-pair/v1" and set(item.get("lane_results", {})) == {"numpy_present", "numpy_absent"} for item in warmups), "warmup_lanes")
    paired = load_jsonl(root / "paired.jsonl")
    paired_by_id = {item["pair_id"]: item for item in paired}
    need(len(paired_by_id) == 132 and len(paired_by_id) == len(paired), "paired_coverage")
    for pair_id, pair_rows in pairs.items():
        need(pair_id in paired_by_id, "paired_missing")
        pair_claim = paired_by_id[pair_id]
        exact(pair_claim, ("schema", "pair_id", "problem_id", "case_id", "arm", "row_ids", "attempt", "metrics"), "paired_record_keys")
        need(pair_claim["schema"] == "arc4.paired-comparison/v1" and pair_claim["pair_id"] == pair_id and pair_claim["problem_id"] == pair_rows[0]["problem_id"] and pair_claim["case_id"] == pair_rows[0]["case_id"] and pair_claim["arm"] == pair_rows[0]["arm"], "paired_identity")
        need(pair_claim["row_ids"] == {row["lane"]: row["row_id"] for row in pair_rows}, "paired_row_ids")
        exact(pair_claim["attempt"], ("attempt_n", "methodology", "repair_reason"), "paired_attempt_keys")
        need(all(row.get("attempt_n") == pair_claim["attempt"]["attempt_n"] and row.get("attempt_methodology") == pair_claim["attempt"]["methodology"] and row.get("repair_reason") == pair_claim["attempt"]["repair_reason"] for row in pair_rows), "paired_attempt_provenance")
        if pair_rows[0]["arm"] == "matrix":
            by_lane = {row["lane"]: row for row in pair_rows}
            observed = recompute_pair(by_lane["numpy_present"], by_lane["numpy_absent"])
            claimed = paired_by_id[pair_id].get("metrics", {})
            validate_pair_claim(claimed, observed)
        else:
            need(pair_claim["metrics"] == {"m1_m9_only": True, "public_order_equal": pair_rows[0]["public_result_ids"] == pair_rows[1]["public_result_ids"]}, "paired_preflight_metrics")
    controls = [load(path) for path in sorted((root / "controls").glob("C*.json"), key=lambda path: int(path.stem[1:]))]
    verify_controls(root, controls, rows, cases, p0, lock, manifest_sha, manifest_count)
    summary = load(root / "SUMMARY.json")
    exact(summary, ("schema", "verdict", "matrix_rows_observed", "matrix_pairs_observed", "preflight_rows_observed", "preflight_pairs_observed", "unique_query_vectors", "ranking_problems", "independence", "counts", "m5_top_k_inversions", "m5_full_inversions", "m6_top_k_genuine_disagreements", "m6_full_genuine_disagreements", "m9", "m10", "m11", "m12", "controls_passed", "controls_expected", "claim_ceiling"), "summary_keys")
    need(summary.get("schema") == "arc4.summary/v1" and summary.get("verdict") == "complete", "summary_verdict")
    need((summary.get("matrix_rows_observed"), summary.get("matrix_pairs_observed"), summary.get("preflight_rows_observed"), summary.get("preflight_pairs_observed")) == (matrix_rows, matrix_pairs, preflight_rows, preflight_pairs) == (240, 120, 24, 12), "summary_coverage")
    query_ids = {row["query_id"] for row in rows}
    problem_ids = {row["problem_id"] for row in rows if row["arm"] == "matrix"}
    need(summary.get("unique_query_vectors") == len(query_ids) == 4 and summary.get("ranking_problems") == len(problem_ids) == 12, "summary_units")
    expected_independence = {
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
    }
    need(summary.get("independence") == expected_independence, "summary_independence")
    need(summary.get("controls_passed") == len(controls) == summary.get("controls_expected") == EXPECTED_CONTROLS and summary.get("claim_ceiling") == "fixed_suite_descriptive_only_no_inference", "summary_controls_claim")
    matrix_claims = [item for item in paired if item.get("arm") == "matrix"]
    for metric in ("m1_rank0_difference", "m2_ordered_top_k_difference", "m3_membership_top_k_difference", "m4_exact_tie_difference"):
        by_problem: dict[str, list[bool]] = defaultdict(list)
        for item in matrix_claims:
            if metric != "m1_rank0_difference" or item["metrics"]["m1_status"] == "eligible":
                by_problem[str(item["problem_id"])].append(item["metrics"].get(metric) is True)
        eligible_count = sum(item["metrics"]["m1_status"] == "eligible" for item in matrix_claims) if metric == "m1_rank0_difference" else 120
        expected = {
            "pair_numerator": sum(value for values in by_problem.values() for value in values),
            "pair_denominator": eligible_count,
            "pair_excluded_no_results": 120 - eligible_count if metric == "m1_rank0_difference" else 0,
            "problem_numerator": sum(any(values) for values in by_problem.values()),
            "problem_denominator": len(by_problem),
            "heterogeneous_within_problem": sorted(problem for problem, values in by_problem.items() if len(set(values)) > 1),
        }
        claimed = summary.get("counts", {}).get(metric, {})
        exact(claimed, ("pair_numerator", "pair_denominator", "pair_excluded_no_results", "pair_independence_level", "problem_numerator", "problem_denominator", "problem_independence_level", "heterogeneous_within_problem"), "summary_metric_keys")
        for key, value in expected.items():
            need(claimed.get(key) == value, "summary_metric")
        need(claimed.get("pair_independence_level") == "replicated_pair" and claimed.get("problem_independence_level") == "ranking_problem_not_independent_draw", "summary_metric_independence")
    need(summary.get("m5_top_k_inversions") == sum(item["metrics"]["m5_top_k_inversion_count"] for item in matrix_claims), "summary_m5")
    need(summary.get("m5_full_inversions") == sum(item["metrics"]["m5_full_inversion_count"] for item in matrix_claims), "summary_m5")
    need(summary.get("m6_top_k_genuine_disagreements") == sum(item["metrics"]["m6_top_k_genuine_disagreement_count"] for item in matrix_claims), "summary_m6")
    need(summary.get("m6_full_genuine_disagreements") == sum(item["metrics"]["m6_full_genuine_disagreement_count"] for item in matrix_claims), "summary_m6")
    def m10_aggregate(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        need(bool(items), "summary_m10_coverage")
        return {"pair_count": len(items), "candidate_comparisons": sum(item["candidate_count"] for item in items), "maximum_absolute_delta": max(item["max"] for item in items), "bit_identical": sum(item["bit_identical"] for item in items)}
    raw_m10 = [item["metrics"]["m10_raw_cosine"] for item in matrix_claims]
    hybrid_m10 = [item["metrics"]["m10_hybrid_final"] for item in matrix_claims if "m10_hybrid_final" in item["metrics"]]
    need(len(raw_m10) == 120 and len(hybrid_m10) == 60, "summary_m10_coverage")
    expected_m10 = {"raw_cosine": m10_aggregate(raw_m10), "hybrid_final": m10_aggregate(hybrid_m10)}
    need(summary.get("m10") == expected_m10, "summary_m10")
    failure_path = root / "FAILURE-JOURNAL.jsonl"
    failures = [] if failure_path.read_bytes() == b"" else load_jsonl(failure_path)
    repair_path = root / "REPAIR-JOURNAL.jsonl"
    repairs = [] if repair_path.read_bytes() == b"" else load_jsonl(repair_path)
    categories: list[str] = []
    attempts_by_number: dict[str, int] = defaultdict(int)
    failures_by_pair: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    rowless_failures = 0
    for failure in failures:
        exact(failure, ("schema", "stage", "classification", "error_code", "reason", "attempt_n", "row_identity", "methodology", "evidence"), "failure_record_keys")
        need(failure["schema"] == "arc4.failure/v1" and isinstance(failure["attempt_n"], int) and not isinstance(failure["attempt_n"], bool) and failure["attempt_n"] >= 1, "failure_record")
        exact(failure["row_identity"], ("run_id", "row_id", "pair_id", "case_id", "problem_id", "arm", "lane"), "failure_identity_keys")
        categories.append(failure_category(failure))
        identity = failure["row_identity"]
        need(identity["run_id"] == prereg["run_id"], "failure_run_id")
        if identity["pair_id"] is None:
            need(all(identity[key] is None for key in ("row_id", "case_id", "problem_id", "arm", "lane")), "rowless_failure_identity")
            need(failure["stage"] in {"setup", "p0", "environment", "control", "consolidation", "verification"} and failure["attempt_n"] == 1 and failure["methodology"] == "initial", "rowless_failure_semantics")
            rowless_failures += 1
        else:
            need(identity["pair_id"] in paired_by_id, "failure_unknown_pair")
            if failure["stage"] in {"setup", "worker", "timeout", "commit"}:
                failures_by_pair[str(identity["pair_id"])].append(failure)
    verify_failure_invocations(root, failures, planned, config, lock)
    repair_by_attempt: dict[tuple[str, int], Mapping[str, Any]] = {}
    for repair in repairs:
        exact(repair, ("schema", "run_id", "pair_id", "case_id", "problem_id", "arm", "attempt_n", "repair_reason", "row_ids"), "repair_declaration_keys")
        need(repair["schema"] == "arc4.repair-declaration/v1" and isinstance(repair["attempt_n"], int) and not isinstance(repair["attempt_n"], bool) and repair["attempt_n"] >= 2, "repair_declaration_record")
        need(isinstance(repair["repair_reason"], str) and bool(repair["repair_reason"].strip()), "repair_declaration_reason")
        key = (str(repair["pair_id"]), int(repair["attempt_n"]))
        need(key not in repair_by_attempt, "repair_declaration_duplicate")
        need(key[0] in paired_by_id, "repair_declaration_unknown_pair")
        repair_pair = paired_by_id[key[0]]
        need(repair["run_id"] == prereg["run_id"] and repair["case_id"] == repair_pair["case_id"] and repair["problem_id"] == repair_pair["problem_id"] and repair["arm"] == repair_pair["arm"] and repair["row_ids"] == repair_pair["row_ids"], "repair_declaration_identity")
        repair_by_attempt[key] = repair
    used_repairs: set[tuple[str, int]] = set()
    successful_repair_pairs = 0
    for pair_id, pair_claim in paired_by_id.items():
        success_n = pair_claim["attempt"]["attempt_n"]
        need(isinstance(success_n, int) and not isinstance(success_n, bool) and success_n >= 1, "paired_attempt_n")
        related = failures_by_pair.get(pair_id, [])
        failure_attempts = [item["attempt_n"] for item in related]
        need(all(count == 1 for count in Counter(failure_attempts).values()), "attempt_duplicate")
        need(sorted(failure_attempts) == list(range(1, success_n)), "attempt_sequence")
        for failure in related:
            identity = failure["row_identity"]
            pair_identity = identity["pair_id"] == pair_id and identity["case_id"] == pair_claim["case_id"] and identity["problem_id"] == pair_claim["problem_id"] and identity["arm"] == pair_claim["arm"]
            lane_identity = (identity["lane"] is None and identity["row_id"] is None) or (identity["lane"] in pair_claim["row_ids"] and identity["row_id"] == pair_claim["row_ids"][identity["lane"]])
            need(pair_identity and lane_identity, "failure_pair_identity")
            expected_methodology = "initial" if failure["attempt_n"] == 1 else "explicit_repair"
            need(failure["methodology"] == expected_methodology, "failure_attempt_methodology")
            if failure["attempt_n"] >= 2:
                declaration_key = (pair_id, int(failure["attempt_n"]))
                declaration = repair_by_attempt.get(declaration_key)
                if declaration is None:
                    need(failure["evidence"].get("cause_error_code") == "repair_declaration_persistence" and isinstance(failure["evidence"].get("repair_reason"), str) and bool(failure["evidence"]["repair_reason"].strip()), "failure_repair_declaration")
                else:
                    need(failure["evidence"].get("repair_reason") == declaration["repair_reason"], "failure_repair_declaration")
                    used_repairs.add(declaration_key)
            attempts_by_number[str(failure["attempt_n"])] += 1
        attempts_by_number[str(success_n)] += 1
        if success_n == 1:
            need(pair_claim["attempt"] == {"attempt_n": 1, "methodology": "initial", "repair_reason": None}, "successful_initial_provenance")
        else:
            need(pair_claim["attempt"]["methodology"] == "explicit_repair" and isinstance(pair_claim["attempt"]["repair_reason"], str) and bool(pair_claim["attempt"]["repair_reason"].strip()), "successful_repair_provenance")
            declaration_key = (pair_id, success_n)
            declaration = repair_by_attempt.get(declaration_key)
            need(declaration is not None, "successful_repair_declaration")
            need(declaration["run_id"] == prereg["run_id"] and declaration["case_id"] == pair_claim["case_id"] and declaration["problem_id"] == pair_claim["problem_id"] and declaration["arm"] == pair_claim["arm"] and declaration["row_ids"] == pair_claim["row_ids"] and declaration["repair_reason"] == pair_claim["attempt"]["repair_reason"], "successful_repair_declaration")
            used_repairs.add(declaration_key)
            successful_repair_pairs += 1
    need(used_repairs == set(repair_by_attempt), "repair_declaration_orphan")
    expected_m9 = {key: categories.count(key) for key in M9_CATEGORIES}
    expected_m9.update({"total": len(failures), "attempts_by_number": dict(sorted(attempts_by_number.items(), key=lambda item: int(item[0]))), "successful_repair_pairs": successful_repair_pairs, "repair_declarations": len(repairs), "rowless_failures": rowless_failures, "explicit_repair_failures": sum(item["methodology"] == "explicit_repair" for item in failures)})
    need(summary.get("m9") == expected_m9, "summary_m9")
    expected_m11: dict[str, Any] = {}
    for lane_key in ("m11_numpy_order", "m11_python_order"):
        expected_m11[lane_key] = {}
        for location in ("boundary", "minimum_internal"):
            expected_m11[lane_key][location] = {kind: margin_aggregate(matrix_claims, lane_key, location, kind) for kind in ("observed", "conservative")}
    need(summary.get("m11") == expected_m11, "summary_m11")
    divergences = [item["metrics"]["m12_first_divergence_rank"] for item in matrix_claims]
    expected_m12 = {"none": sum(value is None for value in divergences), "first_divergence_histogram": {str(rank): divergences.count(rank) for rank in sorted({value for value in divergences if value is not None})}}
    need(summary.get("m12") == expected_m12, "summary_m12")
    report_text = (root / "REPORT.md").read_text(encoding="utf-8")
    summary_text = (root / "SUMMARY.json").read_text(encoding="utf-8")
    need(report_text == reconstruct_report(summary), "report_reconstruction")
    need(FORBIDDEN_REPORT.search(report_text) is None and FORBIDDEN_REPORT.search(summary_text) is None, "forbidden_claim")
    need(P0_REPORT_SENTENCE in report_text and FORBIDDEN_P0_CLAIM.search(report_text) is None and FORBIDDEN_P0_CLAIM.search(summary_text) is None, "p0_claim_ceiling")
    return {"manifest_sha256": manifest_sha, "manifest_files_verified": manifest_count, "matrix_rows_observed": matrix_rows, "matrix_pairs_observed": matrix_pairs, "preflight_rows_observed": preflight_rows, "preflight_pairs_observed": preflight_pairs, "controls_passed": len(controls), "verdict": "complete"}


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical(value))


def _write_json_atomic(path: Path, value: Any) -> None:
    temporary = path.with_name(SELF_TEST_PROGRESS_TEMP_NAME)
    try:
        with temporary.open("wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_jsonl(path: Path, values: Sequence[Mapping[str, Any]]) -> None:
    path.write_bytes(b"".join(canonical(value) for value in values))


def _refresh_manifest(root: Path) -> None:
    paths = sorted(
        (path for path in root.rglob("*") if path.is_file()
         and path.relative_to(root).as_posix() not in {"MANIFEST.json", "MANIFEST.sha256", *GENERATED_PACKET_FILES}),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    manifest = {"schema": "arc4.manifest/v1", "files": [
        {"path": path.relative_to(root).as_posix(), "sha256": file_sha(path), "size": path.stat().st_size}
        for path in paths
    ]}
    _write_json(root / "MANIFEST.json", manifest)
    (root / "MANIFEST.sha256").write_text(file_sha(root / "MANIFEST.json") + "\n", encoding="ascii", newline="\n")


def _rebase_self_test_packet(root: Path, frozen_config: Path) -> None:
    config = load(root / "CONFIG.json")
    config["packet_root"] = str(root.resolve())
    config["frozen_cases"] = str((root / "frozen-cases.json").resolve())
    config["environment_lock"] = str((root / "ENVIRONMENT-LOCK.json").resolve())
    config["preregistration_inputs"] = str((root / "PREREGISTRATION-INPUTS.json").resolve())
    config["preregistration_commit_receipt"] = str((root / "PREREGISTRATION-COMMIT.json").resolve())
    config["source_build_receipt"] = str((root / SOURCE_BUILD_RECEIPT_PATH).resolve())
    config["source_build_receipt_digest"] = str((root / SOURCE_BUILD_DIGEST_PATH).resolve())
    config["p0_receipt"] = str((root / "P0-RECEIPT.json").resolve())
    config["frozen_config"] = str(frozen_config.resolve())
    config["environment_capture_specs"] = {
        "numpy_present": str((root / "env" / "raw-numpy-present.json").resolve()),
        "numpy_absent": str((root / "env" / "raw-numpy-absent.json").resolve()),
    }
    rebased_config_sha256 = hashlib.sha256(canonical(config)).hexdigest()
    invocation_root = root / "invocations"
    if invocation_root.is_dir():
        for evidence_root in invocation_root.iterdir():
            if not evidence_root.is_dir():
                continue
            artifact_path = evidence_root / "job-artifact.json"
            binding_path = evidence_root / "invocation-binding.json"
            receipt_path = evidence_root / "receipt.json"
            job = load(artifact_path)
            job["config_path"] = str((root / "CONFIG.json").resolve())
            job["config_sha256"] = rebased_config_sha256
            job["environment_lock_path"] = str((root / "ENVIRONMENT-LOCK.json").resolve())
            job["environment_lock_sha256"] = file_sha(root / "ENVIRONMENT-LOCK.json")
            _write_json(artifact_path, job)
            binding = load(binding_path)
            binding["job"]["sha256"] = file_sha(artifact_path)
            binding["job"]["bytes"] = artifact_path.stat().st_size
            _write_json(binding_path, binding)
            receipt = load(receipt_path)
            receipt["binding"] = {"path": "invocation-binding.json", "sha256": file_sha(binding_path), "bytes": binding_path.stat().st_size}
            receipt["job_after"] = {"present": True, "sha256": file_sha(artifact_path), "bytes": artifact_path.stat().st_size}
            _write_json(receipt_path, receipt)
    _write_json(root / "CONFIG.json", config)
    _write_json(frozen_config, config)
    prereg = load(root / "PREREGISTRATION-INPUTS.json")
    prereg["config_sha256"] = file_sha(root / "CONFIG.json")
    _write_json(root / "PREREGISTRATION-INPUTS.json", prereg)
    _refresh_preregistration_commit_receipt(root)
    _refresh_manifest(root)


def _refresh_preregistration_commit_receipt(root: Path) -> None:
    commit_receipt = load(root / "PREREGISTRATION-COMMIT.json")
    commit_receipt["files"] = {
        name: file_sha(root / name)
        for name in (
            "CONFIG.json", "ENVIRONMENT-LOCK.json", "P0-RECEIPT.json", "PREREGISTRATION-INPUTS.json",
            "SOURCE-BUILD-RECEIPT.json", "SOURCE-BUILD-RECEIPT.sha256", "SOURCE-INVENTORY.json", "frozen-cases.json",
        )
    }
    _write_json(root / "PREREGISTRATION-COMMIT.json", commit_receipt)


def _mutate_self_test(root: Path, name: str) -> None:
    rows_path = root / "raw" / "rows.jsonl"
    if name in {"lane_identity", "case_identity", "pair_identity", "query_vector_hash", "corpus_hash", "ordered_result_ids", "top_k_membership", "full_depth_ordering_hash", "coverage", "arm_assignment", "both_lanes_mutated", "network_attempt", "provider_topup", "incomplete_lane_execution", "debug_truncated", "debug_empty", "query_vector_observation"}:
        rows = load_jsonl(rows_path)
        if name == "lane_identity":
            rows[0]["lane"] = rows[1]["lane"]
        elif name == "case_identity":
            rows[0]["case_id"] = "mutated-case"
        elif name == "pair_identity":
            rows[0]["pair_id"] = "mutated-pair"
        elif name == "query_vector_hash":
            rows[0]["query_vector_sha256"] = "f" * 64
        elif name == "corpus_hash":
            rows[0]["corpus_sha256"] = "e" * 64
        elif name in {"ordered_result_ids", "top_k_membership"}:
            matrix = next(row for row in rows if row["arm"] == "matrix")
            current = list(matrix["public_result_ids"])
            matrix["public_result_ids"] = list(reversed(current)) if len(current) > 1 else ["unlisted-candidate"]
        elif name == "full_depth_ordering_hash":
            next(row for row in rows if row["arm"] == "matrix")["full_depth_ordering_sha256"] = "0" * 64
        elif name == "coverage":
            removed = rows.pop()
            for reference in removed.get("full_ranking_evidence", {}).values():
                if isinstance(reference, dict) and "path" in reference:
                    (root / reference["path"]).unlink()
        elif name == "arm_assignment":
            rows[0]["arm"] = "preflight" if rows[0]["arm"] == "matrix" else "matrix"
        elif name == "both_lanes_mutated":
            pair_id = rows[0]["pair_id"]
            for row in rows:
                if row["pair_id"] == pair_id:
                    row["case_id"] = "mutated-both-lanes"
        elif name == "network_attempt":
            rows[0]["controls"]["network_attempts"] = ["('example.invalid', 443)"]
        elif name == "provider_topup":
            next(row for row in rows if row["arm"] == "matrix")["controls"]["topup_tripwire_events"] = 1
        elif name == "incomplete_lane_execution":
            pair_id = rows[0]["pair_id"]
            for row in rows:
                if row["pair_id"] == pair_id:
                    row["pair_invocation_ordinal"] = 1
        elif name == "debug_truncated":
            row = next(item for item in rows if item["arm"] == "preflight")
            row["debug_observation"]["ordered_ids"].pop()
            row["debug_observation"]["scores"].pop()
        elif name == "debug_empty":
            row = next(item for item in rows if item["arm"] == "preflight")
            row["debug_observation"]["ordered_ids"] = []
            row["debug_observation"]["scores"] = []
        elif name == "query_vector_observation":
            rows[0]["observed_query_vector_sha256"] = "0" * 64
        _write_jsonl(rows_path, rows)
    elif name in {"rank0", "tie_classification"}:
        pairs = load_jsonl(root / "paired.jsonl")
        pair = next(item for item in pairs if item["arm"] == "matrix")
        key = "m1_rank0_difference" if name == "rank0" else "m4_exact_tie_difference"
        pair["metrics"][key] = not bool(pair["metrics"][key])
        _write_jsonl(root / "paired.jsonl", pairs)
    elif name == "paired_extra_metric":
        pairs = load_jsonl(root / "paired.jsonl")
        next(item for item in pairs if item["arm"] == "matrix")["metrics"]["unexpected"] = False
        _write_jsonl(root / "paired.jsonl", pairs)
    elif name == "candidate_domain":
        rows = load_jsonl(rows_path)
        row = next(item for item in rows if item["arm"] == "matrix")
        reference = row["full_ranking_evidence"]["raw_cosine"]
        vector_path = root / reference["path"]
        vector = load_jsonl(vector_path)
        vector.pop()
        _write_jsonl(vector_path, vector)
        reference["sha256"] = file_sha(vector_path)
        reference["size"] = vector_path.stat().st_size
        _write_jsonl(rows_path, rows)
    elif name == "p0_receipt":
        value = load(root / "P0-RECEIPT.json")
        value["official_sha256"] = "0" * 64
        _write_json(root / "P0-RECEIPT.json", value)
    elif name == "environment_binding":
        value = load(root / "ENVIRONMENT-LOCK.json")
        value["manifest_bindings"]["c16"]["status"] = "failed"
        _write_json(root / "ENVIRONMENT-LOCK.json", value)
    elif name == "preregistration_hash":
        value = load(root / "PREREGISTRATION-INPUTS.json")
        value["config_sha256"] = "0" * 64
        _write_json(root / "PREREGISTRATION-INPUTS.json", value)
    elif name == "source_inventory":
        value = load(root / "SOURCE-INVENTORY.json")
        value["source"]["commit"] = "0" * 40
        _write_json(root / "SOURCE-INVENTORY.json", value)
        prereg = load(root / "PREREGISTRATION-INPUTS.json")
        prereg["source_inventory_sha256"] = file_sha(root / "SOURCE-INVENTORY.json")
        _write_json(root / "PREREGISTRATION-INPUTS.json", prereg)
    elif name == "source_build_receipt_file":
        value = load(root / SOURCE_BUILD_RECEIPT_PATH)
        value["generator_sha256"] = "0" * 64
        _write_json(root / SOURCE_BUILD_RECEIPT_PATH, value)
    elif name == "source_build_digest_file":
        (root / SOURCE_BUILD_DIGEST_PATH).write_text("0" * 64 + "\n", encoding="ascii", newline="\n")
    elif name == "campaign_alternate_path":
        config = load(root / "CONFIG.json")
        config["p0_receipt"] = str((root / "alternate" / "P0-RECEIPT.json").resolve())
        _write_json(root / "CONFIG.json", config)
        _write_json(Path(config["frozen_config"]), config)
        prereg = load(root / "PREREGISTRATION-INPUTS.json")
        prereg["config_sha256"] = file_sha(root / "CONFIG.json")
        _write_json(root / "PREREGISTRATION-INPUTS.json", prereg)
    elif name == "campaign_packet_root":
        config = load(root / "CONFIG.json")
        config["packet_root"] = str((root / "alternate-packet-root").resolve())
        _write_json(root / "CONFIG.json", config)
        _write_json(Path(config["frozen_config"]), config)
        prereg = load(root / "PREREGISTRATION-INPUTS.json")
        prereg["config_sha256"] = file_sha(root / "CONFIG.json")
        _write_json(root / "PREREGISTRATION-INPUTS.json", prereg)
    elif name == "synthetic_projection":
        value = load(root / "controls" / "C17.json")
        value["evidence"]["fixtures"][0]["expected_projection"]["m2_ordered_top_k_difference"] = True
        _write_json(root / "controls" / "C17.json", value)
    elif name == "control_status":
        control = load(root / "controls" / "C1.json")
        control["status"] = "failed"
        _write_json(root / "controls" / "C1.json", control)
    elif name == "summary_verdict":
        summary = load(root / "SUMMARY.json")
        summary["verdict"] = "incomplete"
        _write_json(root / "SUMMARY.json", summary)
    elif name == "summary_m10":
        summary = load(root / "SUMMARY.json")
        summary["m10"]["raw_cosine"]["candidate_comparisons"] += 1
        _write_json(root / "SUMMARY.json", summary)
    elif name in {"summary_schema", "summary_preflight_pairs", "summary_query_vectors", "summary_ranking_problems", "summary_control_total", "summary_claim_ceiling", "summary_independence", "summary_denominator", "summary_m9_categories"}:
        summary = load(root / "SUMMARY.json")
        if name == "summary_schema":
            summary["schema"] = "arc4.summary/v0"
        elif name == "summary_preflight_pairs":
            summary["preflight_pairs_observed"] = 24
        elif name == "summary_query_vectors":
            summary["unique_query_vectors"] = 5
        elif name == "summary_ranking_problems":
            summary["ranking_problems"] = 13
        elif name == "summary_control_total":
            summary["controls_expected"] = 20
        elif name == "summary_claim_ceiling":
            summary["claim_ceiling"] = "inferential"
        elif name == "summary_independence":
            summary["independence"]["preflight"]["case_executions"]["count"] = 24
        elif name == "summary_denominator":
            summary["counts"]["m1_rank0_difference"]["pair_denominator"] += 1
        else:
            summary["m9"]["failed_preconditions"] += 1
        _write_json(root / "SUMMARY.json", summary)
    elif name == "p0_claim_ceiling":
        with (root / "REPORT.md").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write("\nP0 establishes a reproducible build.\n")
    elif name == "extra_packet_file":
        (root / "UNLISTED.txt").write_text("unexpected\n", encoding="utf-8", newline="\n")
    elif name == "frozen_sidecar_mutation":
        control = load(root / "controls" / "C3.json")
        control["evidence"]["frozen_originals"]["end"]["django"]["files"]["wal"] = {"present": True, "sha256": "0" * 64, "size": 1}
        _write_json(root / "controls" / "C3.json", control)
    elif name in {"repair_reason_removed", "repair_reason_changed", "repair_attempt_gap", "repair_row_attempt_changed"}:
        rows = load_jsonl(rows_path)
        repaired_pair_id = next(row["pair_id"] for row in rows if int(row.get("attempt_n", 1)) > 1)
        repaired = [row for row in rows if row.get("pair_id") == repaired_pair_id]
        successful_attempt = int(repaired[0]["attempt_n"])
        need(successful_attempt > 1 and all(int(row["attempt_n"]) == successful_attempt for row in repaired), "self_test_fixture")
        if name == "repair_reason_removed":
            for row in repaired:
                row["repair_reason"] = None
        elif name == "repair_reason_changed":
            for row in repaired:
                row["repair_reason"] = "altered repair reason"
            pairs = load_jsonl(root / "paired.jsonl")
            next(pair for pair in pairs if pair["pair_id"] == repaired[0]["pair_id"])["attempt"]["repair_reason"] = "altered repair reason"
            _write_jsonl(root / "paired.jsonl", pairs)
        elif name == "repair_attempt_gap":
            mutated_attempt = successful_attempt + 1
            for row in repaired:
                row["attempt_n"] = mutated_attempt
            pairs = load_jsonl(root / "paired.jsonl")
            next(pair for pair in pairs if pair["pair_id"] == repaired_pair_id)["attempt"]["attempt_n"] = mutated_attempt
            _write_jsonl(root / "paired.jsonl", pairs)
            repairs = load_jsonl(root / "REPAIR-JOURNAL.jsonl")
            next(
                repair for repair in repairs
                if repair["pair_id"] == repaired_pair_id and int(repair["attempt_n"]) == successful_attempt
            )["attempt_n"] = mutated_attempt
            _write_jsonl(root / "REPAIR-JOURNAL.jsonl", repairs)
        else:
            repaired[0]["attempt_n"] = successful_attempt + 1
        _write_jsonl(rows_path, rows)
    elif name == "repair_attempt_duplicate":
        failures = load_jsonl(root / "FAILURE-JOURNAL.jsonl")
        duplicate = json.loads(json.dumps(next(
            failure for failure in failures
            if failure["error_code"] in {"failed_precondition", "infrastructure_failure"}
        )))
        duplicate["stage"] = "setup"
        duplicate["evidence"] = {"cause_error_code": "duplicate_fixture"}
        if duplicate["methodology"] == "explicit_repair":
            duplicate["evidence"]["repair_reason"] = next(
                repair["repair_reason"] for repair in load_jsonl(root / "REPAIR-JOURNAL.jsonl")
                if repair["pair_id"] == duplicate["row_identity"]["pair_id"] and repair["attempt_n"] == duplicate["attempt_n"]
            )
        failures.append(duplicate)
        _write_jsonl(root / "FAILURE-JOURNAL.jsonl", failures)
    elif name == "repair_declaration_missing":
        pairs = load_jsonl(root / "paired.jsonl")
        repaired_pair = next(pair for pair in pairs if int(pair["attempt"]["attempt_n"]) > 1)
        repairs = load_jsonl(root / "REPAIR-JOURNAL.jsonl")
        repairs = [
            repair for repair in repairs
            if not (
                repair["pair_id"] == repaired_pair["pair_id"]
                and int(repair["attempt_n"]) == int(repaired_pair["attempt"]["attempt_n"])
            )
        ]
        _write_jsonl(root / "REPAIR-JOURNAL.jsonl", repairs)
    elif name == "repair_identity_mismatch":
        repairs = load_jsonl(root / "REPAIR-JOURNAL.jsonl")
        repairs[0]["case_id"] = "mutated-case"
        _write_jsonl(root / "REPAIR-JOURNAL.jsonl", repairs)
    elif name == "repair_failure_identity_mismatch":
        failures = load_jsonl(root / "FAILURE-JOURNAL.jsonl")
        failures[0]["row_identity"]["row_id"] = "mutated-row"
        _write_jsonl(root / "FAILURE-JOURNAL.jsonl", failures)
    elif name in {"failure_row_run_id", "failure_rowless_run_id", "failure_bool_attempt", "failure_rowless_repair", "failure_wrong_lane", "failure_wrong_pair_identity", "worker_rejection_m9", "worker_network_address", "worker_invocation_binding", "invocation_opposite_lane_interpreter", "invocation_alternate_interpreter_path", "invocation_source_path", "invocation_artifact_path", "invocation_wrong_namespace", "invocation_stderr_refreshed", "invocation_job_refreshed", "invocation_job_corpus_refreshed", "invocation_job_source_refreshed", "invocation_job_config_refreshed", "invocation_alias", "invocation_orphan", "invocation_extra_file"}:
        failures = load_jsonl(root / "FAILURE-JOURNAL.jsonl")
        failure = failures[0]
        original_evidence_id = failure.get("evidence", {}).get("invocation_evidence_id")
        if name == "failure_row_run_id":
            failure["row_identity"]["run_id"] = "wrong-run"
        elif name == "failure_rowless_run_id":
            failure["row_identity"] = {"run_id": "wrong-run", "row_id": None, "pair_id": None, "case_id": None, "problem_id": None, "arm": None, "lane": None}
            failure["stage"] = "setup"
            failure["evidence"] = {"cause_error_code": "fixture_setup"}
        elif name == "failure_bool_attempt":
            failure["attempt_n"] = True
            failure["stage"] = "setup"
            failure["evidence"] = {"cause_error_code": "fixture_setup"}
        elif name == "failure_rowless_repair":
            failure["row_identity"] = {"run_id": failure["row_identity"]["run_id"], "row_id": None, "pair_id": None, "case_id": None, "problem_id": None, "arm": None, "lane": None}
            failure["attempt_n"] = 2
            failure["methodology"] = "explicit_repair"
            failure["stage"] = "setup"
            failure["evidence"] = {"cause_error_code": "fixture_setup", "repair_reason": "invalid rowless repair"}
        elif name == "failure_wrong_lane":
            failure["row_identity"]["lane"] = "numpy_absent" if failure["row_identity"]["lane"] == "numpy_present" else "numpy_present"
            failure["evidence"]["worker_rejection"]["lane"] = failure["row_identity"]["lane"]
        elif name == "worker_rejection_m9":
            failure["evidence"]["worker_rejection"]["m9_classification"] = "failed_precondition"
        elif name == "worker_network_address":
            failure["evidence"]["worker_rejection"]["network_attempts"][0]["host"] = ""
        elif name == "worker_invocation_binding":
            evidence_root = root / "invocations" / failure["evidence"]["invocation_evidence_id"]
            binding_path = evidence_root / "invocation-binding.json"
            binding = load(binding_path)
            binding["run_id"] = "alternate-run"
            _write_json(binding_path, binding)
            receipt_path = evidence_root / "receipt.json"
            receipt = load(receipt_path)
            receipt["binding"] = {"path": "invocation-binding.json", "sha256": file_sha(binding_path), "bytes": binding_path.stat().st_size}
            _write_json(receipt_path, receipt)
        elif name in {"invocation_opposite_lane_interpreter", "invocation_alternate_interpreter_path", "invocation_source_path", "invocation_artifact_path", "invocation_wrong_namespace", "invocation_stderr_refreshed", "invocation_job_refreshed", "invocation_job_corpus_refreshed", "invocation_job_source_refreshed", "invocation_job_config_refreshed", "invocation_extra_file"}:
            evidence_root = root / "invocations" / failure["evidence"]["invocation_evidence_id"]
            binding_path = evidence_root / "invocation-binding.json"
            receipt_path = evidence_root / "receipt.json"
            artifact_path = evidence_root / "job-artifact.json"
            binding = load(binding_path)
            receipt = load(receipt_path)
            if name == "invocation_opposite_lane_interpreter":
                other = "numpy_absent" if failure["row_identity"]["lane"] == "numpy_present" else "numpy_present"
                config = load(root / "CONFIG.json")
                lock = load(root / "ENVIRONMENT-LOCK.json")
                lane_root = Path(config["environment_lane_roots"][other]["lane_venv"]).resolve()
                interpreter = Path(config["lane_interpreters"][other]).resolve()
                binding["interpreter"] = {"lane_root": str(lane_root), "path": str(interpreter), "sha256": lock["manifest_bindings"]["roots"][other]["python_executable_sha256"], "package_root": str((lane_root / "Lib" / "site-packages" / "jcodemunch_mcp").resolve())}
                binding["command"]["argv"][0] = str(interpreter)
                binding["command"]["sha256"] = hashlib.sha256(json.dumps(binding["command"]["argv"], ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=False).encode("utf-8")).hexdigest()
            elif name == "invocation_alternate_interpreter_path":
                alternate = str((Path(binding["interpreter"]["lane_root"]) / "Scripts" / "same-hash-alternate.exe").resolve())
                binding["interpreter"]["path"] = alternate
                binding["command"]["argv"][0] = alternate
                binding["command"]["sha256"] = hashlib.sha256(json.dumps(binding["command"]["argv"], ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=False).encode("utf-8")).hexdigest()
            elif name == "invocation_source_path":
                binding["job"]["source_path"] = str((Path(binding["job"]["source_path"]).parent / "redirected.json").resolve())
            elif name == "invocation_artifact_path":
                alternate = str((Path(binding["paths"]["attempt_root"]) / "alternate-artifact.json").resolve())
                binding["job"]["artifact_path"] = alternate
                binding["command"]["argv"][-1] = alternate
                binding["command"]["sha256"] = hashlib.sha256(json.dumps(binding["command"]["argv"], ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=False).encode("utf-8")).hexdigest()
            elif name == "invocation_wrong_namespace":
                binding["execution"]["namespace"] = "preflight"
                job = load(artifact_path)
                job["execution_namespace"] = "preflight"
                _write_json(artifact_path, job)
                rejection = failure["evidence"]["worker_rejection"]
                rejection["execution_namespace"] = "preflight"
                failure["reason"] = json.dumps(rejection, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)
                receipt["rejection"] = rejection
                (evidence_root / "stderr.log").write_bytes(canonical(rejection))
                receipt["stderr"] = {"path": "stderr.log", "sha256": file_sha(evidence_root / "stderr.log"), "bytes": (evidence_root / "stderr.log").stat().st_size}
                binding["job"]["sha256"] = file_sha(artifact_path)
                binding["job"]["bytes"] = artifact_path.stat().st_size
                receipt["job_after"] = {"present": True, "sha256": file_sha(artifact_path), "bytes": artifact_path.stat().st_size}
            elif name == "invocation_stderr_refreshed":
                rejection = failure["evidence"]["worker_rejection"]
                rejection["execution_namespace"] = "preflight"
                failure["reason"] = json.dumps(rejection, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)
                receipt["rejection"] = rejection
                (evidence_root / "stderr.log").write_bytes(canonical(rejection))
                receipt["stderr"] = {"path": "stderr.log", "sha256": file_sha(evidence_root / "stderr.log"), "bytes": (evidence_root / "stderr.log").stat().st_size}
            elif name in {"invocation_job_refreshed", "invocation_job_corpus_refreshed", "invocation_job_source_refreshed", "invocation_job_config_refreshed"}:
                job = load(artifact_path)
                if name == "invocation_job_refreshed":
                    job["database"] = str((Path(job["storage_path"]) / "substituted.db").resolve())
                    job["trial_source_files"]["database_path"] = job["database"]
                elif name == "invocation_job_corpus_refreshed":
                    job["repo_id"] = "substituted/repository"
                elif name == "invocation_job_source_refreshed":
                    job["frozen_source_files"]["database_path"] = str((Path(job["frozen_source_files"]["database_path"]).parent / "substituted.db").resolve())
                else:
                    job["config_path"] = str((Path(job["config_path"]).parent / "alternate-CONFIG.json").resolve())
                _write_json(artifact_path, job)
                binding["job"]["sha256"] = file_sha(artifact_path)
                binding["job"]["bytes"] = artifact_path.stat().st_size
                receipt["job_after"] = {"present": True, "sha256": file_sha(artifact_path), "bytes": artifact_path.stat().st_size}
            else:
                (evidence_root / "extra.log").write_bytes(b"extra\n")
            if name != "invocation_extra_file":
                _write_json(binding_path, binding)
                receipt["binding"] = {"path": "invocation-binding.json", "sha256": file_sha(binding_path), "bytes": binding_path.stat().st_size}
                _write_json(receipt_path, receipt)
        elif name == "invocation_alias":
            failures.append(json.loads(json.dumps(failure)))
        elif name == "invocation_orphan":
            source = root / "invocations" / failure["evidence"]["invocation_evidence_id"]
            shutil.copytree(source, root / "invocations" / ("f" * 64))
        else:
            failure["row_identity"]["case_id"] = "wrong-case"
        if name in {"failure_rowless_run_id", "failure_bool_attempt", "failure_rowless_repair"} and isinstance(original_evidence_id, str):
            shutil.rmtree(root / "invocations" / original_evidence_id)
        _write_jsonl(root / "FAILURE-JOURNAL.jsonl", failures)
    elif name in CONTROL_SEMANTIC_SELF_TESTS:
        control_id = name.removeprefix("control_").removesuffix("_semantic").upper()
        control_path = root / "controls" / f"{control_id}.json"
        control = load(control_path)
        evidence = control["evidence"]
        mutations: dict[str, tuple[str, Any]] = {
            "C2": ("checkout_clean", False), "C3": ("database_unchanged_rows", 263),
            "C4": ("matching_rows", 263), "C5": ("numpy_importable_before", 131),
            "C6": ("numpy_import_failures_before", 131), "C7": ("topup_tripwire_events", 1),
            "C8": ("matrix_order_matches", 239), "C9": ("deterministic_groups", 47),
            "C10": ("matrix_numpy_first", 59), "C11": ("topup_tripwire_events", 1),
            "C12": ("cold_cache_hit_rows", 1), "C13": ("closed_world_required", False),
            "C14": ("cold_repos_zero_rows", 131), "C15": ("home_tuning_absent_rows", 263),
            "C16": ("only_declared_difference", "undeclared"), "C20": ("raw_vectors_checked", 239),
            "C21": ("outbound_attempts", 1),
        }
        if control_id == "C1":
            evidence["lanes"]["numpy_present"]["wheel_sha256"] = "0" * 64
        else:
            key, value = mutations[control_id]
            evidence[key] = value
        _write_json(control_path, control)
    else:
        raise Rejected("unknown_self_test", name)
    _refresh_preregistration_commit_receipt(root)
    _refresh_manifest(root)


def _self_test_progress(*, verifier_sha: str, manifest_sha: str, passed_tests: Sequence[str]) -> dict[str, Any]:
    passed = list(passed_tests)
    return {
        "schema": SELF_TEST_PROGRESS_SCHEMA,
        "status": "in_progress",
        "verifier_sha256": verifier_sha,
        "manifest_sha256": manifest_sha,
        "self_tests_passed": len(passed),
        "self_tests_expected": len(SELF_TESTS),
        "passed_tests": passed,
        "next_test": SELF_TESTS[len(passed)] if len(passed) < len(SELF_TESTS) else None,
    }


def _load_self_test_progress(path: Path, *, verifier_sha: str, manifest_sha: str) -> list[str]:
    if not path.exists():
        return []
    try:
        value = load(path)
        keys = (
            "schema", "status", "verifier_sha256", "manifest_sha256", "self_tests_passed",
            "self_tests_expected", "passed_tests", "next_test",
        )
        exact(value, keys, "self_test_progress")
        passed = value["passed_tests"]
        need(value["schema"] == SELF_TEST_PROGRESS_SCHEMA and value["status"] == "in_progress", "self_test_progress")
        need(value["verifier_sha256"] == verifier_sha and value["manifest_sha256"] == manifest_sha, "self_test_progress")
        need(isinstance(value["self_tests_passed"], int) and not isinstance(value["self_tests_passed"], bool), "self_test_progress")
        need(value["self_tests_expected"] == len(SELF_TESTS), "self_test_progress")
        need(isinstance(passed, list) and all(isinstance(name, str) for name in passed), "self_test_progress")
        need(value["self_tests_passed"] == len(passed) and passed == list(SELF_TESTS[:len(passed)]), "self_test_progress")
        expected_next = SELF_TESTS[len(passed)] if len(passed) < len(SELF_TESTS) else None
        need(value["next_test"] == expected_next, "self_test_progress")
        return passed
    except Rejected as exc:
        if exc.code == "self_test_progress":
            raise
        raise Rejected("self_test_progress") from exc


def run_self_tests(
    root: Path,
    *,
    base_result: Mapping[str, Any] | None = None,
    verifier_sha: str | None = None,
    progress_path: Path | None = None,
    deadline: float | None = None,
) -> tuple[int, bool, dict[str, Any]]:
    result = verify_packet(root) if base_result is None else base_result
    manifest_sha = str(result["manifest_sha256"])
    current_verifier_sha = verifier_sha or file_sha(Path(__file__))
    passed_tests = [] if progress_path is None else _load_self_test_progress(
        progress_path, verifier_sha=current_verifier_sha, manifest_sha=manifest_sha,
    )
    snapshot = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() not in GENERATED_PACKET_FILES
    }
    expected_codes = {
        "lane_identity": "plan_bijection", "case_identity": "plan_bijection", "pair_identity": "plan_bijection",
        "query_vector_hash": "plan_bijection", "corpus_hash": "plan_bijection",
        "ordered_result_ids": "ordered_result_ids", "top_k_membership": "ordered_result_ids",
        "rank0": "paired_metric_mismatch", "tie_classification": "paired_metric_mismatch",
        "full_depth_ordering_hash": "full_depth_ordering_hash", "coverage": "plan_bijection",
        "arm_assignment": "plan_bijection", "control_status": "control_status",
        "summary_verdict": "summary_verdict", "both_lanes_mutated": "plan_bijection",
        "candidate_domain": "full_score_vector", "p0_receipt": "p0_hashes",
        "environment_binding": "environment_c16", "preregistration_hash": "preregistration_hashes",
        "source_inventory": "source_build_git_state", "synthetic_projection": "synthetic_expected_projection",
        "p0_claim_ceiling": "report_reconstruction", "extra_packet_file": "packet_file_set",
        "network_attempt": "row_network_control", "provider_topup": "row_provider_control",
        "incomplete_lane_execution": "c10_observed_ordinals", "debug_truncated": "debug_preflight_parity",
        "paired_extra_metric": "paired_metric_keys", "frozen_sidecar_mutation": "c3_frozen_mutation",
        "debug_empty": "debug_preflight_parity", "query_vector_observation": "observed_query_vector_hash",
        "summary_m10": "summary_m10", "summary_schema": "summary_verdict",
        "summary_preflight_pairs": "summary_coverage", "summary_query_vectors": "summary_units",
        "summary_ranking_problems": "summary_units", "summary_control_total": "summary_controls_claim",
        "summary_claim_ceiling": "summary_controls_claim", "summary_independence": "summary_independence",
        "summary_denominator": "summary_metric", "summary_m9_categories": "summary_m9",
        "repair_reason_removed": "row_repair_provenance", "repair_reason_changed": "successful_repair_declaration",
        "repair_attempt_duplicate": "attempt_duplicate", "repair_attempt_gap": "attempt_sequence",
        "repair_declaration_missing": "successful_repair_declaration", "repair_identity_mismatch": "repair_declaration_identity",
        "repair_row_attempt_changed": "paired_attempt_provenance", "repair_failure_identity_mismatch": "failure_worker_invocation_binding",
        "source_build_receipt_file": "source_build_receipt_file", "source_build_digest_file": "source_build_digest_file",
        "campaign_alternate_path": "campaign_artifact_path", "campaign_packet_root": "campaign_packet_root",
        "failure_row_run_id": "failure_run_id",
        "failure_rowless_run_id": "failure_run_id", "failure_bool_attempt": "failure_record",
        "failure_rowless_repair": "rowless_failure_semantics", "failure_wrong_lane": "failure_worker_invocation_binding",
        "failure_wrong_pair_identity": "failure_worker_invocation_binding", "worker_rejection_m9": "failure_worker_rejection_binding",
        "worker_network_address": "failure_worker_network_attempt", "worker_invocation_binding": "failure_worker_invocation_binding",
        "invocation_opposite_lane_interpreter": "failure_invocation_interpreter",
        "invocation_alternate_interpreter_path": "failure_invocation_interpreter",
        "invocation_source_path": "failure_invocation_job_paths",
        "invocation_artifact_path": "failure_invocation_job_paths",
        "invocation_wrong_namespace": "failure_invocation_paths",
        "invocation_stderr_refreshed": "failure_invocation_rejection_execution",
        "invocation_job_refreshed": "failure_invocation_job_trial_paths",
        "invocation_job_corpus_refreshed": "failure_invocation_job_corpus",
        "invocation_job_source_refreshed": "failure_invocation_job_source_receipts",
        "invocation_job_config_refreshed": "failure_invocation_job_config",
        "invocation_alias": "failure_invocation_alias", "invocation_orphan": "packet_file_set",
        "invocation_extra_file": "packet_file_set",
    }
    expected_codes.update({name: f"c{name.removeprefix('control_c').removesuffix('_semantic')}_predicate" for name in CONTROL_SEMANTIC_SELF_TESTS})
    expected_codes["control_c9_semantic"] = "c9_determinism"
    expected_codes["control_c13_semantic"] = "c13_contract"
    for name in SELF_TESTS[len(passed_tests):]:
        if deadline is not None and time.monotonic() >= deadline:
            progress = _self_test_progress(
                verifier_sha=current_verifier_sha, manifest_sha=manifest_sha, passed_tests=passed_tests,
            )
            if progress_path is not None:
                _write_json_atomic(progress_path, progress)
            return len(passed_tests), False, progress
        with tempfile.TemporaryDirectory(prefix=f"arc4-selftest-{name}-") as directory:
            candidate = Path(directory) / "packet"
            candidate.mkdir()
            for relative, payload in snapshot.items():
                target = candidate / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            _rebase_self_test_packet(candidate, Path(directory) / "FROZEN-CONFIG.json")
            _mutate_self_test(candidate, name)
            try:
                verify_packet(candidate)
            except Rejected as exc:
                if exc.code != expected_codes[name]:
                    raise Rejected("self_test_wrong_gate", f"{name}: expected {expected_codes[name]}, observed {exc.code}") from exc
                passed_tests.append(name)
            else:
                raise Rejected("self_test_failure", name)
        progress = _self_test_progress(
            verifier_sha=current_verifier_sha, manifest_sha=manifest_sha, passed_tests=passed_tests,
        )
        if progress_path is not None:
            _write_json_atomic(progress_path, progress)
    need(len(passed_tests) == len(SELF_TESTS), "self_test_failure")
    return len(passed_tests), True, _self_test_progress(
        verifier_sha=current_verifier_sha, manifest_sha=manifest_sha, passed_tests=passed_tests,
    )


def receipt(status: str, *, verifier_sha: str, manifest_sha: str | None = None, result: Mapping[str, Any] | None = None, self_tests: int = 0, errors: Sequence[str] = ()) -> dict[str, Any]:
    result = result or {}
    return {
        "schema": RECEIPT_SCHEMA, "status": status, "verifier_sha256": verifier_sha,
        "manifest_sha256": manifest_sha, "matrix_rows_observed": result.get("matrix_rows_observed"),
        "matrix_rows_expected": EXPECTED_MATRIX_ROWS, "matrix_pairs_observed": result.get("matrix_pairs_observed"),
        "matrix_pairs_expected": EXPECTED_MATRIX_PAIRS, "preflight_rows_observed": result.get("preflight_rows_observed"),
        "preflight_rows_expected": EXPECTED_PREFLIGHT_ROWS, "controls_passed": result.get("controls_passed"),
        "controls_expected": EXPECTED_CONTROLS, "manifest_files_verified": result.get("manifest_files_verified"),
        "self_tests_passed": self_tests, "self_tests_expected": len(SELF_TESTS),
        "verdict": result.get("verdict", "incomplete"), "error_codes": sorted(set(errors)),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--self-test-budget-seconds", type=float)
    parser.add_argument("--write-receipt", action="store_true")
    root = Path(__file__).resolve().parent
    verifier_sha = file_sha(Path(__file__))
    try:
        ns = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        sys.stdout.buffer.write(canonical(receipt("usage_error", verifier_sha=verifier_sha, errors=["invalid_cli"])))
        return 64
    if ns.self_test_budget_seconds is not None and (
        not ns.self_test or not math.isfinite(ns.self_test_budget_seconds) or ns.self_test_budget_seconds <= 0
    ):
        sys.stdout.buffer.write(canonical(receipt("usage_error", verifier_sha=verifier_sha, errors=["invalid_cli"])))
        return 64
    started = time.monotonic()
    self_count = 0
    progress_path = root / SELF_TEST_PROGRESS_NAME
    try:
        if ns.self_test:
            (root / SELF_TEST_PROGRESS_TEMP_NAME).unlink(missing_ok=True)
        result = verify_packet(root)
        if ns.self_test:
            deadline = None if ns.self_test_budget_seconds is None else started + ns.self_test_budget_seconds
            self_count, complete, progress = run_self_tests(
                root,
                base_result=result,
                verifier_sha=verifier_sha,
                progress_path=progress_path,
                deadline=deadline,
            )
            if not complete:
                sys.stdout.buffer.write(canonical(progress))
                return SELF_TEST_PROGRESS_EXIT
        value = receipt("verified", verifier_sha=verifier_sha, manifest_sha=result["manifest_sha256"], result=result, self_tests=self_count)
        code = 0
    except Rejected as exc:
        value = receipt("rejected", verifier_sha=verifier_sha, self_tests=self_count, errors=[exc.code])
        code = 2
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        value = receipt("rejected", verifier_sha=verifier_sha, self_tests=self_count, errors=["packet_io"])
        code = 2
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        value = receipt("internal_error", verifier_sha=verifier_sha, errors=["internal_exception"])
        code = 70
    payload = canonical(value)
    sys.stdout.buffer.write(payload)
    if ns.write_receipt and code == 0:
        (root / "verification.txt").write_bytes(payload)
    if ns.self_test and code == 0:
        progress_path.unlink(missing_ok=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
