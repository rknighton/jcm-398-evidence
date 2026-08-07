from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from harness.common import canonical_json, canonical_json_bytes, sha256_bytes
from harness.metrics import ordering_sha256
from harness.worker_protocol import PROTOCOL_SELF_TEST_SCHEMA, WIRE_SCHEMA
from harness.environment import OFFICIAL_WHEEL_SHA256


RUN_ID = "arc4-worker-fixture-run"
CANDIDATE_IDS = ["a", "b"]


def source_receipt() -> dict[str, Any]:
    absent = {"present": False, "sha256": None, "size": 0}
    return {"database_path": "C:/arc4-fixture/index.db", "files": {"db": dict(absent), "wal": dict(absent), "shm": dict(absent)}}


def planned_row(*, lane: str = "numpy_present") -> dict[str, Any]:
    serialized = {"query": "fixture", "semantic_only": False, "max_results": 2}
    debug = {**serialized, "debug": True}
    return {
        "arm": "matrix", "problem_id": "problem-fixture", "case_id": "case-fixture",
        "pair_id": "pair-fixture", "corpus": "django", "form_id": "hybrid",
        "query_id": "q1", "cache_state": "cold_fresh_process", "repetition": 1,
        "top_k": 2, "serialized_args": serialized,
        "serialized_args_sha256": sha256_bytes(canonical_json(serialized).encode("utf-8")),
        "debug_observation_args": debug,
        "debug_observation_args_sha256": sha256_bytes(canonical_json(debug).encode("utf-8")),
        "corpus_sha256": "1" * 64,
        "candidate_ids_sha256": sha256_bytes(canonical_json(CANDIDATE_IDS).encode("utf-8")),
        "candidate_count": len(CANDIDATE_IDS), "query_vector_sha256": "2" * 64,
        "lane_invocation_order": "numpy_first", "lane": lane,
        "row_id": f"row-fixture-{lane}",
    }


def successful_result(*, lane: str = "numpy_present") -> dict[str, Any]:
    row = planned_row(lane=lane)
    final = {"a": 0.9, "b": 0.1}
    raw = {"a": 0.8, "b": 0.2}
    source = source_receipt()
    present = lane == "numpy_present"
    scores = [
        {"id": symbol_id, "public_score": round(final[symbol_id], 4), "adapter_rounded": round(final[symbol_id], 4)}
        for symbol_id in ("a", "b")
    ]
    return {
        "schema": WIRE_SCHEMA, **row,
        "attempt_n": 1, "attempt_methodology": "initial", "repair_reason": None,
        "pair_invocation_ordinal": 1 if lane == "numpy_present" else 2, "observed_query_vector_sha256": row["query_vector_sha256"],
        "frozen_source_files": source, "trial_source_files": source,
        "public_result_ids": ["a", "b"],
        "raw_cosine": {key: value.hex() for key, value in raw.items()},
        "final_scores": {key: value.hex() for key, value in final.items()},
        "full_depth_ordering_sha256": ordering_sha256(final), "provider_calls": [],
        "warmup_result": None, "cache_before": {}, "cache_after_public": {},
        "cache_after_warmup": None, "served_from_result_cache": False,
        "database_state_before": {}, "database_state": {},
        "matrix_stamp_before_measurement": [1, 2], "matrix_stamp_after_measurement": [1, 2],
        "wall_ns": 1, "process_cpu_ns": 1,
        "debug_observation": {"debug": True, "ordered_ids": ["a", "b"], "scores": scores, "order_matches": True, "rounded_scores_match": True, "adapter_kind": "final"},
        "package_evidence": {"official_wheel_sha256": OFFICIAL_WHEEL_SHA256, "environment_lock_sha256": "4" * 64, "installed_version": "1.108.228", "payload_file_count": 1, "payload_matches_official_wheel": True, "module_origins": {"jcodemunch_mcp": "__init__.py"}},
        "lane_evidence": {"numpy_version": "2.4.4" if present else None, "numpy_import_failed_before": not present, "numpy_importable_before": present, "numpy_helper_non_null_before": present, "numpy_importable_after": present, "numpy_import_failed_after": not present, "numpy_helper_non_null_after": present, "matrix_vectorised": present},
        "controls": {"network_attempts": [], "network_tripwire_installed_before_config": True, "network_lifetime_guard_registered": True, "credentials_absent": True, "sharing_disabled": True, "package_unchanged": True, "database_unchanged": True, "candidate_set_matches": True, "provider_expected_calls": 0, "provider_observed_calls": 0, "topup_tripwire_events": 0, "storage_tuning_absent": True, "home_tuning_absent": True, "effective_weight_matches": True},
    }


def protocol_job(root: Path, *, lane: str = "numpy_present", action: str = "success", error_code: str | None = None, result: dict[str, Any] | None = None) -> dict[str, Any]:
    row = planned_row(lane=lane)
    source = source_receipt()
    return {
        "schema": PROTOCOL_SELF_TEST_SCHEMA, "planned_row": row,
        "candidate_ids": list(CANDIDATE_IDS),
        "production_context": {"attempt_n": 1, "attempt_methodology": "initial", "repair_reason": None, "pair_invocation_ordinal": 1 if lane == "numpy_present" else 2, "frozen_source_files": source, "trial_source_files": source},
        "fixture_action": action, "fixture_error_code": error_code,
        "fixture_result": deepcopy(successful_result(lane=lane)) if action == "success" and result is None else result,
        "home_path": str((root / "home").resolve()),
    }


def write_protocol_job(root: Path, *, name: str, lane: str = "numpy_present", action: str = "success", error_code: str | None = None, result: dict[str, Any] | None = None) -> tuple[Path, dict[str, Any]]:
    value = protocol_job(root, lane=lane, action=action, error_code=error_code, result=result)
    path = root / f"{name}.json"
    path.write_bytes(canonical_json_bytes(value))
    return path, value
