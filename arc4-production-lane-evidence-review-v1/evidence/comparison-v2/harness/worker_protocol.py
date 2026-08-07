from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .common import canonical_json, exact_keys, require, sha256_bytes
from .metrics import ordering_sha256, ranking


WIRE_SCHEMA = "arc4.row-result/v1"
JOB_SCHEMA = "arc4.worker-job/v1"
INVOCATION_BINDING_SCHEMA = "arc4.worker-invocation-binding/v2"
PROTOCOL_SELF_TEST_SCHEMA = "arc4.worker-protocol-self-test/v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}")

PLANNED_ROW_KEYS = (
    "arm", "problem_id", "case_id", "pair_id", "corpus", "form_id", "query_id", "cache_state",
    "repetition", "top_k", "serialized_args", "serialized_args_sha256", "debug_observation_args",
    "debug_observation_args_sha256", "corpus_sha256", "candidate_ids_sha256", "candidate_count",
    "query_vector_sha256", "lane_invocation_order", "lane", "row_id",
)
JOB_EXTRA_KEYS = (
    "schema", "run_id", "repo_id", "database", "storage_path", "package_root", "treatment_wheel",
    "config_path", "config_sha256",
    "environment_lock_path", "environment_lock_sha256", "candidate_ids", "query_text", "query_vector",
    "pair_invocation_ordinal", "frozen_source_files", "trial_source_files", "home_path", "attempt_n",
    "attempt_methodology", "repair_reason", "python_hash_seed", "embed_model",
    "execution_namespace", "is_control", "control_id",
)
JOB_KEYS = PLANNED_ROW_KEYS + JOB_EXTRA_KEYS
SUCCESS_KEYS = (
    "schema", *PLANNED_ROW_KEYS, "attempt_n", "attempt_methodology", "repair_reason",
    "pair_invocation_ordinal", "observed_query_vector_sha256", "frozen_source_files", "trial_source_files",
    "public_result_ids", "raw_cosine", "final_scores", "full_depth_ordering_sha256", "provider_calls",
    "warmup_result", "cache_before", "cache_after_public", "cache_after_warmup", "served_from_result_cache",
    "database_state_before", "database_state", "matrix_stamp_before_measurement",
    "matrix_stamp_after_measurement", "wall_ns", "process_cpu_ns", "debug_observation",
    "package_evidence", "lane_evidence", "controls",
)
REJECTION_KEYS = (
    "schema", "status", "error_code", "failure_family", "m9_classification",
    "product", "lane", "fallback_state", "embedding_mode", "network_attempts",
    "execution_namespace", "is_control", "control_id",
)
BINDING_KEYS = ("schema", "run_id", "row_identity", "execution", "attempt", "job", "interpreter", "paths", "command")
SELF_TEST_CONTEXT_KEYS = (
    "attempt_n", "attempt_methodology", "repair_reason", "pair_invocation_ordinal",
    "frozen_source_files", "trial_source_files",
)
SELF_TEST_KEYS = (
    "schema", "planned_row", "candidate_ids", "production_context", "fixture_action",
    "fixture_error_code", "fixture_result", "home_path",
)

_PUBLIC_ERRORS = {"public_error", "warmup_error", "debug_public_error", "public_tool_error"}
_LANE_ERRORS = {
    "lane_selection", "numpy_absence", "numpy_present", "numpy_absence_after",
    "numpy_present_after", "cache_lane_before", "cache_lane_after", "lane_mismatch",
}
_FALLBACK_ERRORS = {"fallback_fired", "fallback_firing"}
_EMBED_WRITE_ERRORS = {"provider_topup", "database_mutation", "embed_write_tripwire_firing"}
_NETWORK_ERRORS = {"network_attempt", "network_tripwire"}
_JOB_INFRASTRUCTURE_ERRORS = {
    "invalid_json", "worker_job_keys", "worker_job_schema", "worker_job_identity",
    "worker_job_attempt", "worker_protocol_self_test_keys", "worker_protocol_self_test_schema",
    "worker_job_transport", "worker_binding_transport",
}


def _sha256(value: Any, code: str) -> None:
    require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None, code, str(value))


def _positive_int(value: Any, code: str, *, allow_zero: bool = False) -> None:
    require(isinstance(value, int) and not isinstance(value, bool) and value >= (0 if allow_zero else 1), code, str(value))


def _source_receipt(value: Any, code: str) -> None:
    exact_keys(value, ("database_path", "files"), f"{code}_keys")
    exact_keys(value["files"], ("db", "wal", "shm"), f"{code}_files")
    require(isinstance(value["database_path"], str) and bool(value["database_path"]), code, str(value))
    for name in ("db", "wal", "shm"):
        item = value["files"][name]
        exact_keys(item, ("present", "sha256", "size"), f"{code}_{name}_keys")
        require(isinstance(item["present"], bool), code, str(item))
        _positive_int(item["size"], code, allow_zero=True)
        if item["present"]:
            _sha256(item["sha256"], code)
        else:
            require(item["sha256"] is None and item["size"] == 0, code, str(item))


def _finite_hex_scores(value: Any, expected_ids: set[str], code: str) -> dict[str, float]:
    require(isinstance(value, dict) and set(value) == expected_ids, code, str(value))
    decoded: dict[str, float] = {}
    for symbol_id, text in value.items():
        require(isinstance(symbol_id, str) and isinstance(text, str), code, str(symbol_id))
        try:
            number = float.fromhex(text)
        except ValueError:
            require(False, code, symbol_id)
        require(math.isfinite(number) and text == number.hex(), code, symbol_id)
        decoded[symbol_id] = number
    return decoded


def validate_worker_job(value: Mapping[str, Any]) -> None:
    exact_keys(value, JOB_KEYS, "worker_job_keys")
    require(value["schema"] == JOB_SCHEMA, "worker_job_schema", str(value["schema"]))
    require(isinstance(value["run_id"], str) and bool(value["run_id"]), "worker_job_identity", str(value["run_id"]))
    require(value["lane"] in {"numpy_present", "numpy_absent"} and value["arm"] in {"matrix", "preflight"}, "worker_job_identity", str(value["lane"]))
    require(value["lane_invocation_order"] in {"numpy_first", "python_first"}, "worker_job_identity", str(value["lane_invocation_order"]))
    require(all(isinstance(value[key], str) and bool(value[key]) for key in ("row_id", "pair_id", "case_id", "problem_id", "corpus", "form_id", "query_id")), "worker_job_identity", str(value.get("row_id")))
    require(all(isinstance(value[key], str) and bool(value[key]) for key in ("repo_id", "database", "storage_path", "package_root", "treatment_wheel", "config_path", "environment_lock_path", "query_text", "home_path", "embed_model")), "worker_job_paths", str(value.get("row_id")))
    require(value["execution_namespace"] in {"measured", "preflight", "repair", "control"} and isinstance(value["is_control"], bool), "worker_job_execution", str(value.get("execution_namespace")))
    if value["is_control"]:
        require(value["execution_namespace"] == "control" and value["control_id"] == "C9", "worker_job_control", str(value.get("control_id")))
        require(value["python_hash_seed"] is None or value["python_hash_seed"] in {"0", "1", "2", "3", "4"}, "worker_job_seed", str(value.get("python_hash_seed")))
    else:
        require(value["execution_namespace"] in {"measured", "preflight", "repair"} and value["control_id"] is None and isinstance(value["python_hash_seed"], str) and bool(value["python_hash_seed"]), "worker_job_control", str(value.get("control_id")))
    for key in ("repetition", "top_k", "candidate_count"):
        _positive_int(value[key], "worker_job_identity")
    _positive_int(value["attempt_n"], "worker_job_attempt")
    require(
        (value["attempt_methodology"] == "initial" and value["attempt_n"] == 1 and value["repair_reason"] is None)
        or (value["attempt_methodology"] == "explicit_repair" and value["attempt_n"] >= 2 and isinstance(value["repair_reason"], str) and bool(value["repair_reason"].strip())),
        "worker_job_attempt", str(value["attempt_n"]),
    )
    _positive_int(value["pair_invocation_ordinal"], "worker_job_identity")
    require(value["pair_invocation_ordinal"] in {1, 2}, "worker_job_identity", str(value["pair_invocation_ordinal"]))
    require(isinstance(value["candidate_ids"], list) and all(isinstance(item, str) and bool(item) for item in value["candidate_ids"]), "worker_job_candidates", str(value["candidate_ids"]))
    require(value["candidate_ids"] == sorted(set(value["candidate_ids"])) and len(value["candidate_ids"]) == value["candidate_count"], "worker_job_candidates", str(value["candidate_ids"]))
    require(sha256_bytes(canonical_json(value["candidate_ids"]).encode("utf-8")) == value["candidate_ids_sha256"], "worker_job_candidates", str(value["candidate_ids_sha256"]))
    for key in ("serialized_args_sha256", "debug_observation_args_sha256", "corpus_sha256", "candidate_ids_sha256", "query_vector_sha256", "config_sha256", "environment_lock_sha256"):
        _sha256(value[key], "worker_job_hash")
    require(isinstance(value["serialized_args"], dict) and isinstance(value["debug_observation_args"], dict), "worker_job_args", str(value.get("serialized_args")))
    require(sha256_bytes(canonical_json(value["serialized_args"]).encode("utf-8")) == value["serialized_args_sha256"], "worker_job_args", str(value["row_id"]))
    require(sha256_bytes(canonical_json(value["debug_observation_args"]).encode("utf-8")) == value["debug_observation_args_sha256"], "worker_job_args", str(value["row_id"]))
    require(isinstance(value["query_vector"], list) and len(value["query_vector"]) == 384 and all(isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(float(item)) for item in value["query_vector"]), "worker_job_vector", str(value["row_id"]))
    require(sha256_bytes(canonical_json(value["query_vector"]).encode("utf-8")) == value["query_vector_sha256"], "worker_job_vector", str(value["row_id"]))
    _source_receipt(value["frozen_source_files"], "worker_job_frozen_source")
    _source_receipt(value["trial_source_files"], "worker_job_trial_source")


def validate_protocol_self_test_job(value: Mapping[str, Any]) -> None:
    exact_keys(value, SELF_TEST_KEYS, "worker_protocol_self_test_keys")
    require(value["schema"] == PROTOCOL_SELF_TEST_SCHEMA, "worker_protocol_self_test_schema", str(value.get("schema")))
    planned = value["planned_row"]
    exact_keys(planned, PLANNED_ROW_KEYS, "worker_protocol_self_test_plan_keys")
    require(planned["lane"] in {"numpy_present", "numpy_absent"}, "worker_protocol_self_test_lane", str(planned.get("lane")))
    require(all(isinstance(planned[key], str) and bool(planned[key]) for key in ("row_id", "pair_id", "case_id", "problem_id")), "worker_protocol_self_test_identity", str(planned))
    candidates = value["candidate_ids"]
    require(isinstance(candidates, list) and candidates == sorted(set(candidates)) and len(candidates) == planned["candidate_count"], "worker_protocol_self_test_candidates", str(candidates))
    require(sha256_bytes(canonical_json(candidates).encode("utf-8")) == planned["candidate_ids_sha256"], "worker_protocol_self_test_candidates", str(candidates))
    context = value["production_context"]
    exact_keys(context, SELF_TEST_CONTEXT_KEYS, "worker_protocol_self_test_context_keys")
    _positive_int(context["attempt_n"], "worker_protocol_self_test_attempt")
    _positive_int(context["pair_invocation_ordinal"], "worker_protocol_self_test_ordinal")
    require(context["pair_invocation_ordinal"] in {1, 2}, "worker_protocol_self_test_ordinal", str(context["pair_invocation_ordinal"]))
    require(
        (context["attempt_methodology"] == "initial" and context["attempt_n"] == 1 and context["repair_reason"] is None)
        or (context["attempt_methodology"] == "explicit_repair" and context["attempt_n"] >= 2 and isinstance(context["repair_reason"], str) and bool(context["repair_reason"].strip())),
        "worker_protocol_self_test_attempt", str(context),
    )
    _source_receipt(context["frozen_source_files"], "worker_protocol_self_test_frozen_source")
    _source_receipt(context["trial_source_files"], "worker_protocol_self_test_trial_source")
    require(value["fixture_action"] in {"success", "error", "network_connect"}, "worker_protocol_self_test_action", str(value["fixture_action"]))
    require(value["fixture_error_code"] is None or isinstance(value["fixture_error_code"], str), "worker_protocol_self_test_error", str(value["fixture_error_code"]))
    require((value["fixture_action"] == "error") == (isinstance(value["fixture_error_code"], str) and bool(value["fixture_error_code"])), "worker_protocol_self_test_error", str(value["fixture_error_code"]))
    require(value["fixture_result"] is None or isinstance(value["fixture_result"], dict), "worker_protocol_self_test_result", str(type(value["fixture_result"]).__name__))
    require(isinstance(value["home_path"], str) and bool(value["home_path"]), "worker_protocol_self_test_home", str(value["home_path"]))


def expected_success_job_from_artifact(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema") == JOB_SCHEMA:
        validate_worker_job(value)
        return dict(value)
    validate_protocol_self_test_job(value)
    return {**dict(value["planned_row"]), "candidate_ids": list(value["candidate_ids"]), **dict(value["production_context"])}


def validate_invocation_binding(value: Mapping[str, Any]) -> None:
    exact_keys(value, BINDING_KEYS, "worker_binding_keys")
    require(value["schema"] == INVOCATION_BINDING_SCHEMA and isinstance(value["run_id"], str) and bool(value["run_id"]), "worker_binding_schema", str(value))
    identity = value["row_identity"]
    exact_keys(identity, ("row_id", "pair_id", "case_id", "problem_id", "arm", "lane"), "worker_binding_identity_keys")
    require(all(isinstance(identity[key], str) and bool(identity[key]) for key in ("row_id", "pair_id", "case_id", "problem_id", "arm")) and identity["lane"] in {"numpy_present", "numpy_absent"}, "worker_binding_identity", str(identity))
    execution = value["execution"]
    exact_keys(execution, ("namespace", "is_control", "control_id", "python_hash_seed"), "worker_binding_execution_keys")
    require(execution["namespace"] in {"measured", "preflight", "repair", "control"} and isinstance(execution["is_control"], bool), "worker_binding_execution", str(execution))
    if execution["is_control"]:
        require(execution["namespace"] == "control" and execution["control_id"] == "C9" and (execution["python_hash_seed"] is None or execution["python_hash_seed"] in {"0", "1", "2", "3", "4"}), "worker_binding_execution", str(execution))
    else:
        require(execution["namespace"] != "control" and execution["control_id"] is None and isinstance(execution["python_hash_seed"], str) and bool(execution["python_hash_seed"]), "worker_binding_execution", str(execution))
    attempt = value["attempt"]
    exact_keys(attempt, ("attempt_n", "methodology", "repair_reason"), "worker_binding_attempt_keys")
    _positive_int(attempt["attempt_n"], "worker_binding_attempt")
    require((attempt["methodology"] == "initial" and attempt["attempt_n"] == 1 and attempt["repair_reason"] is None) or (attempt["methodology"] == "explicit_repair" and attempt["attempt_n"] >= 2 and isinstance(attempt["repair_reason"], str) and bool(attempt["repair_reason"].strip())), "worker_binding_attempt", str(attempt))
    job = value["job"]
    exact_keys(job, ("source_path", "publication_path", "artifact_path", "sha256", "bytes"), "worker_binding_job_keys")
    require(all(isinstance(job[key], str) and Path(job[key]).is_absolute() for key in ("source_path", "publication_path", "artifact_path")), "worker_binding_job", str(job))
    _sha256(job["sha256"], "worker_binding_job")
    _positive_int(job["bytes"], "worker_binding_job")
    interpreter = value["interpreter"]
    exact_keys(interpreter, ("lane_root", "path", "sha256", "package_root"), "worker_binding_interpreter_keys")
    require(all(isinstance(interpreter[key], str) and Path(interpreter[key]).is_absolute() for key in ("lane_root", "path", "package_root")), "worker_binding_interpreter", str(interpreter))
    _sha256(interpreter["sha256"], "worker_binding_interpreter")
    paths = value["paths"]
    exact_keys(paths, ("attempt_root", "binding", "receipt", "stdout", "stderr"), "worker_binding_path_keys")
    require(all(isinstance(path, str) and Path(path).is_absolute() for path in paths.values()), "worker_binding_paths", str(paths))
    command = value["command"]
    exact_keys(command, ("argv", "sha256"), "worker_binding_command_keys")
    require(isinstance(command["argv"], list) and len(command["argv"]) >= 2 and all(isinstance(item, str) and bool(item) for item in command["argv"]), "worker_binding_command", str(command))
    require(command["sha256"] == sha256_bytes(canonical_json(command["argv"]).encode("utf-8")), "worker_binding_command", str(command["sha256"]))


def validate_worker_success(value: Mapping[str, Any], *, expected_job: Mapping[str, Any]) -> None:
    exact_keys(value, SUCCESS_KEYS, "worker_success_keys")
    require(value["schema"] == WIRE_SCHEMA and "status" not in value, "worker_success_schema", str(value.get("schema")))
    for key in PLANNED_ROW_KEYS:
        require(value[key] == expected_job[key], "worker_success_identity", f"{key}:{value.get(key)!r}")
    for key in ("attempt_n", "attempt_methodology", "repair_reason", "pair_invocation_ordinal", "frozen_source_files", "trial_source_files"):
        require(value[key] == expected_job[key], "worker_success_identity", f"{key}:{value.get(key)!r}")
    _positive_int(value["attempt_n"], "worker_success_attempt")
    _positive_int(value["wall_ns"], "worker_success_metrics", allow_zero=True)
    _positive_int(value["process_cpu_ns"], "worker_success_metrics", allow_zero=True)
    require(value["observed_query_vector_sha256"] == value["query_vector_sha256"], "worker_success_query_vector", str(value["row_id"]))
    expected_ids = set(expected_job["candidate_ids"])
    public_ids = value["public_result_ids"]
    require(isinstance(public_ids, list) and len(public_ids) == len(set(public_ids)) and all(item in expected_ids for item in public_ids), "worker_success_public_ids", str(public_ids))
    require(len(public_ids) == min(value["top_k"], len(expected_ids)), "worker_success_public_ids", str(len(public_ids)))
    require(isinstance(value["provider_calls"], list) and isinstance(value["cache_before"], dict) and isinstance(value["cache_after_public"], dict), "worker_success_introspection", str(value["row_id"]))
    require(value["warmup_result"] is None or isinstance(value["warmup_result"], dict), "worker_success_introspection", str(value["warmup_result"]))
    require(value["cache_after_warmup"] is None or isinstance(value["cache_after_warmup"], dict), "worker_success_introspection", str(value["cache_after_warmup"]))
    require(isinstance(value["served_from_result_cache"], bool) and isinstance(value["database_state_before"], dict) and isinstance(value["database_state"], dict), "worker_success_introspection", str(value["row_id"]))
    require(value["matrix_stamp_before_measurement"] is None or isinstance(value["matrix_stamp_before_measurement"], list), "worker_success_introspection", str(value["matrix_stamp_before_measurement"]))
    require(value["matrix_stamp_after_measurement"] is None or isinstance(value["matrix_stamp_after_measurement"], list), "worker_success_introspection", str(value["matrix_stamp_after_measurement"]))
    debug = value["debug_observation"]
    exact_keys(debug, ("debug", "ordered_ids", "scores", "order_matches", "rounded_scores_match", "adapter_kind"), "worker_success_debug_keys")
    require(debug["debug"] is True and debug["order_matches"] is True and debug["rounded_scores_match"] is True and debug["ordered_ids"] == public_ids, "worker_success_debug", str(debug))
    require(isinstance(debug["scores"], list) and len(debug["scores"]) == len(public_ids), "worker_success_debug", str(debug))
    for index, item in enumerate(debug["scores"]):
        exact_keys(item, ("id", "public_score", "adapter_rounded"), "worker_success_debug_score_keys")
        require(item["id"] == public_ids[index] and isinstance(item["public_score"], (int, float)) and not isinstance(item["public_score"], bool) and isinstance(item["adapter_rounded"], (int, float)) and not isinstance(item["adapter_rounded"], bool), "worker_success_debug_score", str(item))
        require(math.isfinite(float(item["public_score"])) and math.isfinite(float(item["adapter_rounded"])) and float(item["public_score"]) == float(item["adapter_rounded"]) == round(float(item["adapter_rounded"]), 4), "worker_success_debug_score", str(item))
    package = value["package_evidence"]
    exact_keys(package, ("official_wheel_sha256", "environment_lock_sha256", "installed_version", "payload_file_count", "payload_matches_official_wheel", "module_origins"), "worker_success_package_keys")
    _sha256(package["official_wheel_sha256"], "worker_success_package")
    _sha256(package["environment_lock_sha256"], "worker_success_package")
    _positive_int(package["payload_file_count"], "worker_success_package")
    require(package["installed_version"] == "1.108.228" and package["payload_matches_official_wheel"] is True and isinstance(package["module_origins"], dict) and bool(package["module_origins"]), "worker_success_package", str(package))
    lane = value["lane_evidence"]
    exact_keys(lane, ("numpy_version", "numpy_import_failed_before", "numpy_importable_before", "numpy_helper_non_null_before", "numpy_importable_after", "numpy_import_failed_after", "numpy_helper_non_null_after", "matrix_vectorised"), "worker_success_lane_keys")
    require(lane["numpy_version"] is None or isinstance(lane["numpy_version"], str), "worker_success_lane", str(lane["numpy_version"]))
    for key in ("numpy_import_failed_before", "numpy_importable_before", "numpy_helper_non_null_before", "numpy_importable_after", "numpy_import_failed_after", "numpy_helper_non_null_after"):
        require(isinstance(lane[key], bool), "worker_success_lane", f"{key}:{lane[key]!r}")
    require(lane["matrix_vectorised"] is None or isinstance(lane["matrix_vectorised"], bool), "worker_success_lane", str(lane["matrix_vectorised"]))
    if value["lane"] == "numpy_present":
        require(all(lane[key] is True for key in ("numpy_importable_before", "numpy_helper_non_null_before", "numpy_importable_after", "numpy_helper_non_null_after")) and lane["numpy_import_failed_before"] is False and lane["numpy_import_failed_after"] is False, "worker_success_lane", str(lane))
    else:
        require(all(lane[key] is False for key in ("numpy_importable_before", "numpy_helper_non_null_before", "numpy_importable_after", "numpy_helper_non_null_after")) and lane["numpy_import_failed_before"] is True and lane["numpy_import_failed_after"] is True, "worker_success_lane", str(lane))
    require(lane["matrix_vectorised"] == ((value["lane"] == "numpy_present") if value["arm"] == "matrix" else None), "worker_success_lane", str(lane["matrix_vectorised"]))
    controls = value["controls"]
    exact_keys(controls, ("network_attempts", "network_tripwire_installed_before_config", "network_lifetime_guard_registered", "credentials_absent", "sharing_disabled", "package_unchanged", "database_unchanged", "candidate_set_matches", "provider_expected_calls", "provider_observed_calls", "topup_tripwire_events", "storage_tuning_absent", "home_tuning_absent", "effective_weight_matches"), "worker_success_control_keys")
    require(controls["network_attempts"] == [] and all(controls[key] is True for key in ("network_tripwire_installed_before_config", "network_lifetime_guard_registered", "credentials_absent", "sharing_disabled", "package_unchanged", "database_unchanged", "candidate_set_matches", "storage_tuning_absent", "home_tuning_absent", "effective_weight_matches")), "worker_success_controls", str(controls))
    require(controls["provider_expected_calls"] == controls["provider_observed_calls"] and controls["topup_tripwire_events"] == 0, "worker_success_controls", str(controls))
    for key in ("provider_expected_calls", "provider_observed_calls", "topup_tripwire_events"):
        _positive_int(controls[key], "worker_success_controls", allow_zero=True)
    if value["arm"] == "matrix":
        raw = _finite_hex_scores(value["raw_cosine"], expected_ids, "worker_success_raw_scores")
        final = _finite_hex_scores(value["final_scores"], expected_ids, "worker_success_final_scores")
        require(public_ids == ranking(final)[: value["top_k"]] and value["full_depth_ordering_sha256"] == ordering_sha256(final), "worker_success_ranking", str(value["row_id"]))
        require(debug["adapter_kind"] == "final", "worker_success_debug", str(debug["adapter_kind"]))
        for item in debug["scores"]:
            require(float(item["public_score"]) == round(final[item["id"]], 4), "worker_success_debug_score", str(item))
        require(set(raw) == set(final), "worker_success_scores", str(value["row_id"]))
    else:
        require(value["raw_cosine"] == {} and value["final_scores"] == {} and value["full_depth_ordering_sha256"] is None, "worker_success_preflight_scores", str(value["row_id"]))
        require(debug["adapter_kind"] == "bm25_identity", "worker_success_debug", str(debug["adapter_kind"]))


def m9_classification_for_worker_error(error_code: str) -> str:
    require(isinstance(error_code, str) and bool(error_code), "worker_rejection_error_code", str(error_code))
    if error_code in _PUBLIC_ERRORS:
        return "public_tool_error"
    if error_code in _LANE_ERRORS:
        return "lane_mismatch"
    if error_code in _FALLBACK_ERRORS:
        return "fallback_firing"
    if error_code in _EMBED_WRITE_ERRORS:
        return "embed_write_tripwire_firing"
    if error_code in _NETWORK_ERRORS or error_code in _JOB_INFRASTRUCTURE_ERRORS or error_code.startswith("worker_job_") or error_code.startswith("worker_binding_") or error_code.startswith("worker_protocol_self_test_"):
        return "infrastructure_failure"
    return "failed_precondition"


def metadata_free_worker_error(error_code: str) -> bool:
    return error_code in _JOB_INFRASTRUCTURE_ERRORS or error_code.startswith("worker_job_") or error_code.startswith("worker_binding_") or error_code.startswith("worker_protocol_self_test_")


def _job_metadata(job: Mapping[str, Any] | None) -> tuple[str | None, str | None, str | None, bool, str | None]:
    if not isinstance(job, Mapping):
        return None, None, None, False, None
    source = job.get("planned_row") if isinstance(job.get("planned_row"), Mapping) else job
    lane = source.get("lane")
    if lane not in {"numpy_present", "numpy_absent"}:
        lane = None
    serialized = source.get("serialized_args")
    embedding_mode: str | None = None
    if isinstance(serialized, Mapping) and isinstance(serialized.get("semantic_only"), bool):
        embedding_mode = "semantic_only" if serialized["semantic_only"] else "hybrid"
    namespace = source.get("execution_namespace")
    is_control = source.get("is_control") is True
    control_id = source.get("control_id") if is_control else None
    return lane, embedding_mode, namespace if isinstance(namespace, str) else None, is_control, control_id if isinstance(control_id, str) else None


def validate_network_attempts(value: Any, *, required: bool) -> None:
    require(isinstance(value, list) and len(value) <= 8 and (bool(value) if required else not value), "worker_rejection_network_attempts", str(value))
    for item in value:
        exact_keys(item, ("host", "port"), "worker_network_attempt_keys")
        require(isinstance(item["host"], str) and 0 < len(item["host"]) <= 255, "worker_network_attempt_host", str(item["host"]))
        require(isinstance(item["port"], int) and not isinstance(item["port"], bool) and 0 <= item["port"] <= 65535, "worker_network_attempt_port", str(item["port"]))


def build_worker_rejection(
    error_code: str, job: Mapping[str, Any] | None, *, network_attempts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    m9 = m9_classification_for_worker_error(error_code)
    lane, embedding_mode, namespace, is_control, control_id = _job_metadata(job)
    rejection = {
        "schema": WIRE_SCHEMA, "status": "rejected", "error_code": error_code,
        "failure_family": m9, "m9_classification": m9, "product": "jcodemunch_mcp",
        "lane": lane, "fallback_state": "fired" if m9 == "fallback_firing" else "not_observed",
        "embedding_mode": embedding_mode, "network_attempts": [dict(item) for item in network_attempts],
        "execution_namespace": namespace, "is_control": is_control, "control_id": control_id,
    }
    validate_worker_rejection(rejection)
    return rejection


def validate_worker_rejection(value: Mapping[str, Any]) -> None:
    exact_keys(value, REJECTION_KEYS, "worker_rejection_keys")
    require(value["schema"] == WIRE_SCHEMA and value["status"] == "rejected", "worker_rejection_schema", str(value))
    expected = m9_classification_for_worker_error(value["error_code"])
    require(value["failure_family"] == expected and value["m9_classification"] == expected, "worker_rejection_classification", str(value))
    require(value["product"] == "jcodemunch_mcp", "worker_rejection_product", str(value["product"]))
    require(value["lane"] is None or value["lane"] in {"numpy_present", "numpy_absent"}, "worker_rejection_lane", str(value["lane"]))
    require(value["embedding_mode"] is None or value["embedding_mode"] in {"semantic_only", "hybrid"}, "worker_rejection_embedding_mode", str(value["embedding_mode"]))
    require(value["execution_namespace"] is None or value["execution_namespace"] in {"measured", "preflight", "repair", "control"}, "worker_rejection_execution", str(value["execution_namespace"]))
    require(isinstance(value["is_control"], bool) and ((value["is_control"] and value["execution_namespace"] == "control" and value["control_id"] == "C9") or (not value["is_control"] and value["control_id"] is None)), "worker_rejection_control", str(value["control_id"]))
    expected_fallback = "fired" if expected == "fallback_firing" else "not_observed"
    require(value["fallback_state"] == expected_fallback, "worker_rejection_fallback", str(value["fallback_state"]))
    validate_network_attempts(value["network_attempts"], required=value["error_code"] == "network_attempt")
    if metadata_free_worker_error(value["error_code"]):
        require(value["lane"] is None and value["embedding_mode"] is None, "worker_rejection_untrusted_job_metadata", str(value))


def worker_journal_classification(rejection: Mapping[str, Any]) -> str:
    validate_worker_rejection(rejection)
    return "infrastructure" if rejection["m9_classification"] == "infrastructure_failure" else "product_lane"
