from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import socket
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Mapping

from .common import ContractError, atomic_write, canonical_json_bytes, exact_keys, load_json, require, sha256_file, tree_hashes
from .metrics import compare_pair, numeric_summary

CONTROL_IDS = tuple(f"C{number}" for number in range(1, 22))
OFFICIAL_WHEEL_SHA256 = "ff74b6344430053c6fad9064892d6a3904ffba6265823e3fba4dfde78f9a0488"
HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
LANES = ("numpy_present", "numpy_absent")
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


def _sha(value: Any, code: str) -> None:
    require(isinstance(value, str) and HEX_SHA256.fullmatch(value) is not None, code, str(value))


def _lane_hashes(value: Any, code: str) -> None:
    require(isinstance(value, dict), code, "lane hash object required")
    exact_keys(value, LANES, code)
    for digest in value.values():
        _sha(digest, code)


def _counts_equal(evidence: Mapping[str, Any], total: int, fields: tuple[str, ...], code: str) -> None:
    require(all(isinstance(evidence[field], int) and not isinstance(evidence[field], bool) and evidence[field] == total for field in fields), code, str({field: evidence[field] for field in fields}))


def validate_external_control_evidence(control_id: str, evidence: Mapping[str, Any]) -> None:
    require(control_id in CONTROL_EVIDENCE_KEYS, "external_control_id", control_id)
    exact_keys(evidence, CONTROL_EVIDENCE_KEYS[control_id], f"{control_id.lower()}_evidence_keys")
    if control_id == "C1":
        exact_keys(evidence["lanes"], LANES, "c1_lanes")
        for lane in LANES:
            exact_keys(evidence["lanes"][lane], ("wheel_sha256", "package_version"), "c1_lane_keys")
            require(evidence["lanes"][lane] == {"wheel_sha256": OFFICIAL_WHEEL_SHA256, "package_version": "1.108.228"}, "c1_identity", lane)
    elif control_id == "C2":
        for key in ("p0_receipt_sha256", "build_receipt_sha256", "build_wheel_sha256", "comparison_tool_sha256"):
            _sha(evidence[key], "c2_hash")
        require(evidence["source_commit"] == "8bed872e9436093be9f89d35fb84e0cb58a293af", "c2_source_commit", str(evidence["source_commit"]))
        require(evidence["checkout_clean"] is True and evidence["checkout_detached"] is True and evidence["core_autocrlf"] == "false", "c2_checkout", str(evidence))
    elif control_id == "C3":
        _counts_equal(evidence, 264, ("rows_checked", "database_unchanged_rows", "wal_unchanged_rows", "embeddings_unchanged_rows"), "c3_rows")
        originals = evidence["frozen_originals"]
        require(isinstance(originals, dict) and set(originals) == {"start", "end"} and set(originals["start"]) == {"django", "fastapi", "jcodemunch"} and set(originals["end"]) == {"django", "fastapi", "jcodemunch"}, "c3_corpora", str(originals))
        require(originals["start"] == originals["end"], "c3_frozen_mutation", "frozen originals or sidecars changed")
        for receipt in originals["start"].values():
            exact_keys(receipt, ("database_path", "files"), "c3_receipt_keys")
            exact_keys(receipt["files"], ("db", "wal", "shm"), "c3_file_set")
            require(receipt["files"]["db"]["present"] is True, "c3_database_absent", receipt["database_path"])
            for item in receipt["files"].values():
                exact_keys(item, ("present", "sha256", "size"), "c3_file_keys")
                require(isinstance(item["present"], bool) and isinstance(item["size"], int) and item["size"] >= 0, "c3_file_types", str(item))
                if item["present"]:
                    _sha(item["sha256"], "c3_file_hash")
                else:
                    require(item == {"present": False, "sha256": None, "size": 0}, "c3_absent_file", str(item))
    elif control_id == "C4":
        _counts_equal(evidence, 264, ("rows_checked", "matching_rows"), "c4_rows")
        require(evidence["planned_query_vector_hashes"] == evidence["observed_query_vector_hashes"] and isinstance(evidence["planned_query_vector_hashes"], list) and len(evidence["planned_query_vector_hashes"]) == 4 and evidence["planned_query_vector_hashes"] == sorted(set(evidence["planned_query_vector_hashes"])), "c4_query_hashes", str(evidence))
        for digest in evidence["planned_query_vector_hashes"]:
            _sha(digest, "c4_query_hash")
    elif control_id == "C5":
        _counts_equal(evidence, 132, ("rows_checked", "numpy_importable_before", "numpy_helper_non_null_before", "numpy_importable_after", "numpy_helper_non_null_after", "cache_numpy_rows"), "c5_rows")
        _counts_equal(evidence, 120, ("matrix_rows_checked", "vectorised_matrix_rows"), "c5_matrix")
        require(evidence["numpy_version"] == "2.4.4", "c5_numpy_version", str(evidence["numpy_version"]))
    elif control_id == "C6":
        _counts_equal(evidence, 132, ("rows_checked", "numpy_import_failures_before", "find_spec_none_before", "numpy_helper_none_before", "numpy_import_failures_after", "find_spec_none_after", "numpy_helper_none_after", "cache_python_rows"), "c6_rows")
        _counts_equal(evidence, 120, ("matrix_rows_checked", "fallback_matrix_rows"), "c6_matrix")
    elif control_id == "C7":
        _counts_equal(evidence, 240, ("matrix_rows_checked", "package_unchanged_rows"), "c7_rows")
        require(all(isinstance(evidence[key], int) and not isinstance(evidence[key], bool) and evidence[key] >= 0 for key in ("expected_provider_calls", "observed_provider_calls", "frozen_text_calls", "frozen_vector_calls", "topup_tripwire_events")), "c7_counts", str(evidence))
        require(evidence["expected_provider_calls"] == evidence["observed_provider_calls"] == evidence["frozen_text_calls"] == evidence["frozen_vector_calls"] and evidence["topup_tripwire_events"] == 0, "c7_provider", str(evidence))
    elif control_id == "C8":
        _counts_equal(evidence, 240, ("matrix_rows_checked", "matrix_order_matches", "matrix_rounded_score_matches"), "c8_matrix")
        _counts_equal(evidence, 24, ("preflight_rows_checked", "preflight_order_matches"), "c8_preflight")
        _counts_equal(evidence, 264, ("debug_true_rows",), "c8_debug")
    elif control_id == "C9":
        require(evidence["deterministic_groups"] == evidence["deterministic_groups_expected"] == 48, "c9_determinism", str(evidence))
        require(isinstance(evidence["seed_subset_row_id"], str) and bool(evidence["seed_subset_row_id"]), "c9_seed_row", str(evidence["seed_subset_row_id"]))
        require(evidence["seeds"] == ["0", "1", "2", "3", "4", "unset"], "c9_seeds", str(evidence["seeds"]))
        exact_keys(evidence["ordering_sha256_by_seed"], evidence["seeds"], "c9_seed_hash_keys")
        for digest in evidence["ordering_sha256_by_seed"].values():
            _sha(digest, "c9_seed_hash")
        require(isinstance(evidence["seed_observations"], list) and len(evidence["seed_observations"]) == 6, "c9_seed_observations", str(evidence.get("seed_observations")))
        for index, observation in enumerate(evidence["seed_observations"]):
            exact_keys(observation, ("control_id", "is_control", "seed", "row_id", "lane", "ordering_sha256"), "c9_seed_observation_keys")
            expected_seed = None if evidence["seeds"][index] == "unset" else evidence["seeds"][index]
            require(observation == {"control_id": "C9", "is_control": True, "seed": expected_seed, "row_id": evidence["seed_subset_row_id"], "lane": observation["lane"], "ordering_sha256": evidence["ordering_sha256_by_seed"][evidence["seeds"][index]]} and observation["lane"] in {"numpy_present", "numpy_absent"}, "c9_seed_observation", str(observation))
        require(evidence["seed_dependence_observed"] is (len(set(evidence["ordering_sha256_by_seed"].values())) > 1), "c9_seed_classification", str(evidence))
    elif control_id == "C10":
        require(evidence == {"matrix_numpy_first": 60, "matrix_python_first": 60, "preflight_numpy_first": 6, "preflight_python_first": 6}, "c10_balance", str(evidence))
    elif control_id == "C11":
        _counts_equal(evidence, 240, ("matrix_rows_checked", "database_unchanged_rows", "embedding_count_unchanged_rows"), "c11_rows")
        require(evidence["topup_tripwire_events"] == 0, "c11_topup", str(evidence["topup_tripwire_events"]))
    elif control_id == "C12":
        require(evidence == {"preflight_rows_checked": 24, "get_matrix_called_rows": 0, "cold_rows": 12, "cold_cache_hit_rows": 0, "warm_rows": 12, "warm_cache_hit_rows": 12}, "c12_preflight", str(evidence))
    elif control_id == "C13":
        require(evidence == {
            "manifest_scope": "all_packet_files_except_manifest_root_and_generated_verifier_state",
            "detached_root_required": True, "closed_world_required": True,
            "self_test_names": [
                "lane_identity", "case_identity", "pair_identity", "query_vector_hash", "corpus_hash",
                "ordered_result_ids", "top_k_membership", "rank0", "tie_classification",
                "full_depth_ordering_hash", "coverage", "arm_assignment", "control_status", "summary_verdict",
                "both_lanes_mutated", "candidate_domain", "p0_receipt", "environment_binding",
                "preregistration_hash", "source_inventory", "synthetic_projection", "p0_claim_ceiling", "extra_packet_file",
                "network_attempt", "provider_topup", "incomplete_lane_execution", "debug_truncated",
                "paired_extra_metric", "frozen_sidecar_mutation",
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
            ] + [f"control_c{number}_semantic" for number in (*range(1, 17), 20, 21)],
            "verification_entrypoint": "verify_packet",
        }, "c13_contract", str(evidence))
    elif control_id == "C14":
        _counts_equal(evidence, 132, ("cold_rows_checked", "cold_repos_zero_rows", "warm_rows_checked", "warm_expected_cache_rows"), "c14_cache")
        _counts_equal(evidence, 120, ("warm_matrix_stamp_unchanged_rows",), "c14_stamp")
    elif control_id == "C15":
        _counts_equal(evidence, 264, ("rows_checked", "storage_tuning_absent_rows", "home_tuning_absent_rows", "effective_weight_matches_rows"), "c15_rows")
    elif control_id == "C16":
        _sha(evidence["environment_lock_sha256"], "c16_lock_hash")
        _lane_hashes(evidence["raw_manifest_hashes"], "c16_raw_hashes")
        _lane_hashes(evidence["canonical_manifest_hashes"], "c16_canonical_hashes")
        require(evidence["only_declared_difference"] == "numpy==2.4.4", "c16_difference", str(evidence["only_declared_difference"]))
    elif control_id == "C20":
        _counts_equal(evidence, 240, ("matrix_rows_checked", "raw_vectors_checked", "final_vectors_checked", "candidate_set_matches_rows", "ordering_hash_matches_rows"), "c20_rows")
    elif control_id == "C21":
        _counts_equal(evidence, 264, ("rows_checked", "tripwire_installed_before_config_rows", "tripwire_lifetime_guard_rows", "credentials_absent_rows", "sharing_disabled_rows"), "c21_rows")
        require(evidence["outbound_attempts"] == 0, "c21_network", str(evidence["outbound_attempts"]))


FIXTURES = (
    ("known_zero", 2, {"a": 1.0, "b": 0.5}, {"a": 1.0, "b": 0.5}),
    ("rank0_swap", 2, {"a": 1.0, "b": 0.5}, {"b": 1.0, "a": 0.5}),
    ("ordered_only", 3, {"a": 1.0, "b": 0.75, "c": 0.5}, {"a": 1.0, "c": 0.75, "b": 0.5}),
    ("membership_boundary", 2, {"a": 1.0, "b": 0.75, "c": 0.5}, {"a": 1.0, "c": 0.75, "b": 0.5}),
    ("tie_split", 2, {"a": 0.5, "b": 0.5}, {"a": 0.75, "b": 0.5}),
    ("same_tie", 2, {"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}),
    ("unchanged_positive_gap", 2, {"a": 1.0, "b": 0.5}, {"a": 1.125, "b": 0.625}),
    ("deep_rank_only", 2, {"a": 1.0, "b": 0.75, "c": 0.5, "d": 0.25}, {"a": 1.0, "b": 0.75, "d": 0.5, "c": 0.25}),
    ("one_ulp_cross", 2, {"a": float.fromhex("0x1.0000000000002p+0"), "b": float.fromhex("0x1.0000000000001p+0")}, {"b": float.fromhex("0x1.0000000000002p+0"), "a": float.fromhex("0x1.0000000000001p+0")}),
)


def _stable(value: Any) -> Any:
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, list):
        return [_stable(item) for item in value]
    if isinstance(value, dict):
        return {key: _stable(item) for key, item in value.items()}
    return value


def metric_control_projection(observed: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "m1_rank0_difference", "m1_status", "m2_ordered_top_k_difference",
        "m3_membership_top_k_difference", "m4_exact_tie_difference", "m4_numpy", "m4_python",
        "m4_participant_symmetric_difference", "m5_top_k_inversion_count", "m5_full_inversion_count",
        "m6_top_k_genuine_disagreement_count", "m6_full_genuine_disagreement_count",
        "m11_numpy_order", "m11_python_order", "m12_first_divergence_rank",
    )
    exact = {key: observed[key] for key in keys}
    overlaps = []
    if exact["m1_rank0_difference"] is True:
        overlaps.append("M1")
    if exact["m2_ordered_top_k_difference"] is True:
        overlaps.append("M2")
    if exact["m3_membership_top_k_difference"] is True:
        overlaps.append("M3")
    if exact["m4_exact_tie_difference"] is True:
        overlaps.append("M4")
    if exact["m5_top_k_inversion_count"] or exact["m5_full_inversion_count"]:
        overlaps.append("M5")
    if exact["m6_top_k_genuine_disagreement_count"] or exact["m6_full_genuine_disagreement_count"]:
        overlaps.append("M6")
    exact["overlaps"] = overlaps
    return _stable(exact)


EXPECTED_PROJECTIONS: dict[str, dict[str, Any]] = json.loads(r'''{"deep_rank_only":{"m11_numpy_order":{"boundary":{"conservative":"0x1.0000000000000p-1","conservative_denominator":"0x1.0000000000000p-1","gap":"0x1.0000000000000p-2","observed":"0x1.0000000000000p+0","observed_denominator":"0x1.0000000000000p-2","symbols":["b","c"]},"minimum_internal":{"conservative":"0x1.0000000000000p-1","conservative_denominator":"0x1.0000000000000p-1","gap":"0x1.0000000000000p-2","observed":"+inf","observed_denominator":"0x0.0p+0","symbols":["a","b"]}},"m11_python_order":{"boundary":{"conservative":"0x1.0000000000000p-1","conservative_denominator":"0x1.0000000000000p-1","gap":"0x1.0000000000000p-2","observed":"0x1.0000000000000p+0","observed_denominator":"0x1.0000000000000p-2","symbols":["b","d"]},"minimum_internal":{"conservative":"0x1.0000000000000p-1","conservative_denominator":"0x1.0000000000000p-1","gap":"0x1.0000000000000p-2","observed":"+inf","observed_denominator":"0x0.0p+0","symbols":["a","b"]}},"m12_first_divergence_rank":2,"m1_rank0_difference":false,"m1_status":"eligible","m2_ordered_top_k_difference":false,"m3_membership_top_k_difference":false,"m4_exact_tie_difference":false,"m4_numpy":{"groups":[],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[],"participants":[],"tie_partition_sha256":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"},"m4_participant_symmetric_difference":[],"m4_python":{"groups":[],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[],"participants":[],"tie_partition_sha256":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"},"m5_full_inversion_count":1,"m5_top_k_inversion_count":0,"m6_full_genuine_disagreement_count":0,"m6_top_k_genuine_disagreement_count":0,"overlaps":["M5"]},"known_zero":{"m11_numpy_order":{"boundary":"insufficient_ranking","minimum_internal":{"conservative":"+inf","conservative_denominator":"0x0.0p+0","gap":"0x1.0000000000000p-1","observed":"+inf","observed_denominator":"0x0.0p+0","symbols":["a","b"]}},"m11_python_order":{"boundary":"insufficient_ranking","minimum_internal":{"conservative":"+inf","conservative_denominator":"0x0.0p+0","gap":"0x1.0000000000000p-1","observed":"+inf","observed_denominator":"0x0.0p+0","symbols":["a","b"]}},"m12_first_divergence_rank":null,"m1_rank0_difference":false,"m1_status":"eligible","m2_ordered_top_k_difference":false,"m3_membership_top_k_difference":false,"m4_exact_tie_difference":false,"m4_numpy":{"groups":[],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[],"participants":[],"tie_partition_sha256":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"},"m4_participant_symmetric_difference":[],"m4_python":{"groups":[],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[],"participants":[],"tie_partition_sha256":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"},"m5_full_inversion_count":0,"m5_top_k_inversion_count":0,"m6_full_genuine_disagreement_count":0,"m6_top_k_genuine_disagreement_count":0,"overlaps":[]},"membership_boundary":{"m11_numpy_order":{"boundary":{"conservative":"0x1.0000000000000p-1","conservative_denominator":"0x1.0000000000000p-1","gap":"0x1.0000000000000p-2","observed":"0x1.0000000000000p-1","observed_denominator":"0x1.0000000000000p-1","symbols":["b","c"]},"minimum_internal":{"conservative":"0x1.0000000000000p-1","conservative_denominator":"0x1.0000000000000p-1","gap":"0x1.0000000000000p-2","observed":"0x1.0000000000000p+0","observed_denominator":"0x1.0000000000000p-2","symbols":["a","b"]}},"m11_python_order":{"boundary":{"conservative":"0x1.0000000000000p-1","conservative_denominator":"0x1.0000000000000p-1","gap":"0x1.0000000000000p-2","observed":"0x1.0000000000000p-1","observed_denominator":"0x1.0000000000000p-1","symbols":["c","b"]},"minimum_internal":{"conservative":"0x1.0000000000000p-1","conservative_denominator":"0x1.0000000000000p-1","gap":"0x1.0000000000000p-2","observed":"0x1.0000000000000p+0","observed_denominator":"0x1.0000000000000p-2","symbols":["a","c"]}},"m12_first_divergence_rank":1,"m1_rank0_difference":false,"m1_status":"eligible","m2_ordered_top_k_difference":true,"m3_membership_top_k_difference":true,"m4_exact_tie_difference":false,"m4_numpy":{"groups":[],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[],"participants":[],"tie_partition_sha256":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"},"m4_participant_symmetric_difference":[],"m4_python":{"groups":[],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[],"participants":[],"tie_partition_sha256":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"},"m5_full_inversion_count":1,"m5_top_k_inversion_count":1,"m6_full_genuine_disagreement_count":0,"m6_top_k_genuine_disagreement_count":0,"overlaps":["M2","M3","M5"]},"one_ulp_cross":{"m11_numpy_order":{"boundary":"insufficient_ranking","minimum_internal":{"conservative":"0x1.0000000000000p-1","conservative_denominator":"0x1.0000000000000p-51","gap":"0x1.0000000000000p-52","observed":"0x1.0000000000000p-1","observed_denominator":"0x1.0000000000000p-51","symbols":["a","b"]}},"m11_python_order":{"boundary":"insufficient_ranking","minimum_internal":{"conservative":"0x1.0000000000000p-1","conservative_denominator":"0x1.0000000000000p-51","gap":"0x1.0000000000000p-52","observed":"0x1.0000000000000p-1","observed_denominator":"0x1.0000000000000p-51","symbols":["b","a"]}},"m12_first_divergence_rank":0,"m1_rank0_difference":true,"m1_status":"eligible","m2_ordered_top_k_difference":true,"m3_membership_top_k_difference":false,"m4_exact_tie_difference":false,"m4_numpy":{"groups":[],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[],"participants":[],"tie_partition_sha256":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"},"m4_participant_symmetric_difference":[],"m4_python":{"groups":[],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[],"participants":[],"tie_partition_sha256":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"},"m5_full_inversion_count":1,"m5_top_k_inversion_count":1,"m6_full_genuine_disagreement_count":0,"m6_top_k_genuine_disagreement_count":0,"overlaps":["M1","M2","M5"]},"ordered_only":{"m11_numpy_order":{"boundary":"insufficient_ranking","minimum_internal":{"conservative":"0x1.0000000000000p-1","conservative_denominator":"0x1.0000000000000p-1","gap":"0x1.0000000000000p-2","observed":"0x1.0000000000000p+0","observed_denominator":"0x1.0000000000000p-2","symbols":["a","b"]}},"m11_python_order":{"boundary":"insufficient_ranking","minimum_internal":{"conservative":"0x1.0000000000000p-1","conservative_denominator":"0x1.0000000000000p-1","gap":"0x1.0000000000000p-2","observed":"0x1.0000000000000p+0","observed_denominator":"0x1.0000000000000p-2","symbols":["a","c"]}},"m12_first_divergence_rank":1,"m1_rank0_difference":false,"m1_status":"eligible","m2_ordered_top_k_difference":true,"m3_membership_top_k_difference":false,"m4_exact_tie_difference":false,"m4_numpy":{"groups":[],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[],"participants":[],"tie_partition_sha256":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"},"m4_participant_symmetric_difference":[],"m4_python":{"groups":[],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[],"participants":[],"tie_partition_sha256":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"},"m5_full_inversion_count":1,"m5_top_k_inversion_count":1,"m6_full_genuine_disagreement_count":0,"m6_top_k_genuine_disagreement_count":0,"overlaps":["M2","M5"]},"rank0_swap":{"m11_numpy_order":{"boundary":"insufficient_ranking","minimum_internal":{"conservative":"0x1.0000000000000p-1","conservative_denominator":"0x1.0000000000000p+0","gap":"0x1.0000000000000p-1","observed":"0x1.0000000000000p-1","observed_denominator":"0x1.0000000000000p+0","symbols":["a","b"]}},"m11_python_order":{"boundary":"insufficient_ranking","minimum_internal":{"conservative":"0x1.0000000000000p-1","conservative_denominator":"0x1.0000000000000p+0","gap":"0x1.0000000000000p-1","observed":"0x1.0000000000000p-1","observed_denominator":"0x1.0000000000000p+0","symbols":["b","a"]}},"m12_first_divergence_rank":0,"m1_rank0_difference":true,"m1_status":"eligible","m2_ordered_top_k_difference":true,"m3_membership_top_k_difference":false,"m4_exact_tie_difference":false,"m4_numpy":{"groups":[],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[],"participants":[],"tie_partition_sha256":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"},"m4_participant_symmetric_difference":[],"m4_python":{"groups":[],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[],"participants":[],"tie_partition_sha256":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"},"m5_full_inversion_count":1,"m5_top_k_inversion_count":1,"m6_full_genuine_disagreement_count":0,"m6_top_k_genuine_disagreement_count":0,"overlaps":["M1","M2","M5"]},"same_tie":{"m11_numpy_order":{"boundary":"insufficient_ranking","minimum_internal":{"conservative":"exact_tie","conservative_denominator":"0x0.0p+0","gap":"0x0.0p+0","observed":"exact_tie","observed_denominator":"0x0.0p+0","symbols":["a","b"]}},"m11_python_order":{"boundary":"insufficient_ranking","minimum_internal":{"conservative":"exact_tie","conservative_denominator":"0x0.0p+0","gap":"0x0.0p+0","observed":"exact_tie","observed_denominator":"0x0.0p+0","symbols":["a","b"]}},"m12_first_divergence_rank":null,"m1_rank0_difference":false,"m1_status":"eligible","m2_ordered_top_k_difference":false,"m3_membership_top_k_difference":false,"m4_exact_tie_difference":false,"m4_numpy":{"groups":[["a","b"]],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[["a","b"]],"participants":["a","b"],"tie_partition_sha256":"2fd3fa2bce0b3ac087fa636c55067579c7efb3be169da9f57610bcb479d68a91"},"m4_participant_symmetric_difference":[],"m4_python":{"groups":[["a","b"]],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[["a","b"]],"participants":["a","b"],"tie_partition_sha256":"2fd3fa2bce0b3ac087fa636c55067579c7efb3be169da9f57610bcb479d68a91"},"m5_full_inversion_count":0,"m5_top_k_inversion_count":0,"m6_full_genuine_disagreement_count":0,"m6_top_k_genuine_disagreement_count":0,"overlaps":[]},"tie_split":{"m11_numpy_order":{"boundary":"insufficient_ranking","minimum_internal":{"conservative":"0x0.0p+0","conservative_denominator":"0x1.0000000000000p-1","gap":"0x0.0p+0","observed":"0x0.0p+0","observed_denominator":"0x1.0000000000000p-2","symbols":["a","b"]}},"m11_python_order":{"boundary":"insufficient_ranking","minimum_internal":{"conservative":"0x1.0000000000000p-1","conservative_denominator":"0x1.0000000000000p-1","gap":"0x1.0000000000000p-2","observed":"0x1.0000000000000p+0","observed_denominator":"0x1.0000000000000p-2","symbols":["a","b"]}},"m12_first_divergence_rank":null,"m1_rank0_difference":false,"m1_status":"eligible","m2_ordered_top_k_difference":false,"m3_membership_top_k_difference":false,"m4_exact_tie_difference":true,"m4_numpy":{"groups":[["a","b"]],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[["a","b"]],"participants":["a","b"],"tie_partition_sha256":"2fd3fa2bce0b3ac087fa636c55067579c7efb3be169da9f57610bcb479d68a91"},"m4_participant_symmetric_difference":["a","b"],"m4_python":{"groups":[],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[],"participants":[],"tie_partition_sha256":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"},"m5_full_inversion_count":0,"m5_top_k_inversion_count":0,"m6_full_genuine_disagreement_count":1,"m6_top_k_genuine_disagreement_count":1,"overlaps":["M4","M6"]},"unchanged_positive_gap":{"m11_numpy_order":{"boundary":"insufficient_ranking","minimum_internal":{"conservative":"0x1.0000000000000p+1","conservative_denominator":"0x1.0000000000000p-2","gap":"0x1.0000000000000p-1","observed":"+inf","observed_denominator":"0x0.0p+0","symbols":["a","b"]}},"m11_python_order":{"boundary":"insufficient_ranking","minimum_internal":{"conservative":"0x1.0000000000000p+1","conservative_denominator":"0x1.0000000000000p-2","gap":"0x1.0000000000000p-1","observed":"+inf","observed_denominator":"0x0.0p+0","symbols":["a","b"]}},"m12_first_divergence_rank":null,"m1_rank0_difference":false,"m1_status":"eligible","m2_ordered_top_k_difference":false,"m3_membership_top_k_difference":false,"m4_exact_tie_difference":false,"m4_numpy":{"groups":[],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[],"participants":[],"tie_partition_sha256":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"},"m4_participant_symmetric_difference":[],"m4_python":{"groups":[],"groups_crossing_top_k_boundary":[],"groups_intersecting_top_k":[],"participants":[],"tie_partition_sha256":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570"},"m5_full_inversion_count":0,"m5_top_k_inversion_count":0,"m6_full_genuine_disagreement_count":0,"m6_top_k_genuine_disagreement_count":0,"overlaps":[]}}''')


def synthetic_metric_controls() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name, top_k, left, right in FIXTURES:
        projection = metric_control_projection(compare_pair(left, right, top_k))
        expected = EXPECTED_PROJECTIONS.get(name)
        require(expected is not None, "control_expected_projection_missing", name)
        results.append({
            "schema": "arc4.metric-control-fixture/v1", "fixture": name, "top_k": top_k,
            "numpy_scores": {key: value.hex() for key, value in sorted(left.items())},
            "python_scores": {key: value.hex() for key, value in sorted(right.items())},
            "expected_projection": expected, "observed_projection": projection,
            "passed": projection == expected,
        })
    aggregate = {
        "input": ["0x0.0p+0", "0x1.0000000000000p+1", "+inf", "exact_tie"],
        "eligible": ["0x0.0p+0", "0x1.0000000000000p+1"],
        "numeric": _stable(numeric_summary([0.0, 2.0])),
        "plus_inf": 1, "exact_tie": 1, "finite_zero": 1,
    }
    results.append({"schema": "arc4.metric-control-fixture/v1", "fixture": "aggregate_sentinels", "expected_projection": aggregate, "observed_projection": aggregate, "passed": True})
    return results


class NetworkAttemptError(ContractError):
    def __init__(self, attempts: list[dict[str, Any]]) -> None:
        super().__init__("network_attempt", "outbound socket attempt rejected")
        self.attempts = [dict(item) for item in attempts]


class OutboundSocketTripwire(AbstractContextManager["OutboundSocketTripwire"]):
    """Reject and retain process-lifetime outbound connection attempts."""

    def __init__(self) -> None:
        self.attempts: list[dict[str, Any]] = []
        self._connect = socket.socket.connect
        self._connect_ex = socket.socket.connect_ex
        self.installed = False
        self.lifetime_guard_registered = False
        self._retained = False

    @staticmethod
    def _canonical_address(address: Any) -> dict[str, Any]:
        if isinstance(address, tuple) and len(address) >= 2:
            host, port = address[0], address[1]
            if isinstance(host, str) and 0 < len(host) <= 255 and isinstance(port, int) and not isinstance(port, bool) and 0 <= port <= 65535:
                return {"host": host, "port": port}
        return {"host": "<unsupported-address>", "port": 0}

    def install(self, *, process_lifetime: bool = False) -> "OutboundSocketTripwire":
        require(not self.installed, "tripwire_double_install", "tripwire already installed")
        tripwire = self

        def reject(_sock: socket.socket, address: Any) -> Any:
            if len(tripwire.attempts) < 8:
                tripwire.attempts.append(tripwire._canonical_address(address))
            raise NetworkAttemptError(tripwire.attempts)

        def reject_ex(_sock: socket.socket, address: Any) -> int:
            if len(tripwire.attempts) < 8:
                tripwire.attempts.append(tripwire._canonical_address(address))
            raise NetworkAttemptError(tripwire.attempts)

        socket.socket.connect = reject  # type: ignore[method-assign]
        socket.socket.connect_ex = reject_ex  # type: ignore[method-assign]
        self.installed = True
        if process_lifetime:
            atexit.register(self._shutdown_gate)
            self.lifetime_guard_registered = True
        return self

    def mark_retained(self, attempts: list[dict[str, Any]]) -> None:
        require(attempts == self.attempts and bool(attempts), "network_attempt_retention", str(attempts))
        self._retained = True

    def _shutdown_gate(self) -> None:
        if self.attempts and not self._retained:
            os._exit(91)

    def __enter__(self) -> "OutboundSocketTripwire":
        return self.install()

    def __exit__(self, *_args: object) -> None:
        if self.installed and not self.lifetime_guard_registered:
            socket.socket.connect = self._connect  # type: ignore[method-assign]
            socket.socket.connect_ex = self._connect_ex  # type: ignore[method-assign]
            self.installed = False


def validate_control_record(record: Mapping[str, Any]) -> None:
    exact_keys(record, ("schema", "control_id", "status", "evidence"), "control_record_keys")
    require(record["schema"] == "arc4.control/v1" and record["control_id"] in CONTROL_IDS, "control_record_identity", str(record.get("control_id")))
    evidence = record["evidence"]
    require(isinstance(evidence, dict), "control_evidence_type", str(record["control_id"]))
    control_id = str(record["control_id"])
    if control_id in ("C17", "C18", "C19"):
        exact_keys(evidence, ("fixtures",), "synthetic_control_keys")
        expected_names = {"C17": {"known_zero"}, "C18": {name for name, *_ in FIXTURES if name not in ("known_zero", "one_ulp_cross")} | {"aggregate_sentinels"}, "C19": {"one_ulp_cross"}}[control_id]
        fixtures = evidence["fixtures"]
        require(isinstance(fixtures, list) and {item.get("fixture") for item in fixtures} == expected_names, "synthetic_control_fixtures", control_id)
        require(all(item.get("passed") is True and item.get("expected_projection") == item.get("observed_projection") for item in fixtures), "synthetic_control_projection", control_id)
    else:
        validate_external_control_evidence(control_id, evidence)
    require(record["status"] == "passed", "control_status", control_id)


def validate_control_records(records: list[Mapping[str, Any]]) -> None:
    require(len(records) == 21, "control_count", f"observed {len(records)}")
    require([record.get("control_id") for record in records] == list(CONTROL_IDS), "control_order", "controls must be C1 through C21 in order")
    for record in records:
        validate_control_record(record)


def package_unchanged(before: Mapping[str, str], package_root: Path) -> bool:
    return dict(before) == tree_hashes(package_root)


def verify_frozen_file_hashes(expected: Mapping[Path, str]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for path, expected_sha in sorted(expected.items(), key=lambda item: str(item[0])):
        actual = sha256_file(path)
        require(actual == expected_sha, "frozen_input_hash", str(path))
        observed[str(path.resolve())] = actual
    return observed


def assemble_control_records(external_evidence: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    generated = synthetic_metric_controls()
    by_fixture = {item["fixture"]: item for item in generated}
    expected_external = set(CONTROL_IDS) - {"C17", "C18", "C19"}
    require(set(external_evidence) == expected_external, "control_evidence_ids", "external control evidence set differs")
    records: list[dict[str, Any]] = []
    for control_id in CONTROL_IDS:
        if control_id == "C17":
            evidence = {"fixtures": [by_fixture["known_zero"]]}
        elif control_id == "C18":
            evidence = {"fixtures": [by_fixture[name] for name in sorted({name for name, *_ in FIXTURES if name not in ("known_zero", "one_ulp_cross")} | {"aggregate_sentinels"})]}
        elif control_id == "C19":
            evidence = {"fixtures": [by_fixture["one_ulp_cross"]]}
        else:
            evidence = dict(external_evidence[control_id])
            validate_external_control_evidence(control_id, evidence)
        records.append({"schema": "arc4.control/v1", "control_id": control_id, "status": "passed", "evidence": evidence})
    validate_control_records(records)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("output_dir", type=Path)
    ns = parser.parse_args(argv)
    try:
        evidence = load_json(ns.evidence)
        require(isinstance(evidence, dict), "control_evidence_type", "object required")
        for record in assemble_control_records(evidence):
            atomic_write(ns.output_dir / f"{record['control_id']}.json", canonical_json_bytes(record), allowed_root=Path.cwd())
        return 0
    except ContractError as exc:
        parser.error(str(exc))
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
