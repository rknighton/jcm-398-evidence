from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .common import ContractError, atomic_write, canonical_json, canonical_json_bytes, exact_keys, load_json, require, sha256_bytes

SCHEMA = "arc4.frozen-cases/v1"
LANES = ("numpy_present", "numpy_absent")
CACHE_STATES = ("cold_fresh_process", "generation_warm")
QUERY_IDS = (
    "semantic_input_validation",
    "semantic_transaction_persistence",
    "hybrid_authentication_middleware",
    "hybrid_test_client_response",
)
FORMS = (
    ("matrix", "sem_input_validation", QUERY_IDS[0], True, True, 1.0, 10),
    ("matrix", "sem_transaction_persistence", QUERY_IDS[1], True, True, 1.0, 25),
    ("matrix", "hyb_auth_middleware__semantic", QUERY_IDS[2], True, False, 0.5, 10),
    ("matrix", "hyb_test_client__semantic", QUERY_IDS[3], True, False, 0.5, 25),
    ("preflight", "hyb_auth_middleware__verbatim", QUERY_IDS[2], False, False, 0.5, 10),
    ("preflight", "hyb_test_client__verbatim", QUERY_IDS[3], False, False, 0.5, 25),
)
EXECUTION_KEYS = (
    "arm", "problem_id", "case_id", "pair_id", "corpus", "form_id", "query_id", "cache_state",
    "repetition", "top_k", "serialized_args", "serialized_args_sha256", "debug_observation_args",
    "debug_observation_args_sha256", "corpus_sha256", "candidate_ids_sha256", "candidate_count",
    "query_vector_sha256", "lane_invocation_order",
)
ROW_KEYS = EXECUTION_KEYS + ("lane", "row_id")


def _args(form: tuple[Any, ...], query: Mapping[str, Any]) -> dict[str, Any]:
    arm, _form_id, _query_id, semantic, semantic_only, weight, top_k = form
    recorded = query.get("serialized_args")
    require(isinstance(recorded, dict), "recorded_args_missing", str(_query_id))
    require(set(recorded) == {"query", "semantic_only", "semantic_weight", "max_results", "detail_level", "debug"}, "recorded_args_keys", str(_query_id))
    require(recorded["query"] == query["query"], "recorded_query", str(_query_id))
    require(recorded["semantic_only"] is semantic_only and recorded["semantic_weight"] == weight and recorded["max_results"] == top_k, "recorded_args_values", str(_query_id))
    require(recorded["detail_level"] == "compact" and recorded["debug"] is False, "recorded_args_shape", str(_query_id))
    result = dict(recorded)
    if arm == "matrix" and not semantic_only:
        result["semantic"] = True
    require(bool(result.get("query")), "query_text_missing", str(_query_id))
    return result


def generate_frozen_cases(
    *, run_id: str, corpora: Sequence[Mapping[str, Any]], queries: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    require(bool(run_id) and run_id.strip() == run_id, "run_id", "run_id must be a nonempty canonical string")
    require(len(corpora) == 3, "corpus_count", "exactly three corpora are required")
    names = [item.get("name") for item in corpora]
    require(set(names) == {"django", "fastapi", "jcodemunch"}, "corpus_names", "the three frozen corpus names must match exactly")
    corpus_by_name = {str(item["name"]): item for item in corpora}
    ordered_corpora = [corpus_by_name[name] for name in ("django", "fastapi", "jcodemunch")]
    frozen_corpora: list[dict[str, Any]] = []
    for corpus in ordered_corpora:
        exact_keys(corpus, ("name", "working_database_sha256", "candidate_ids"), "corpus_input_keys")
        candidate_ids = corpus["candidate_ids"]
        require(isinstance(candidate_ids, list) and candidate_ids and all(isinstance(item, str) and item for item in candidate_ids), "candidate_ids", str(corpus["name"]))
        require(candidate_ids == sorted(set(candidate_ids)), "candidate_ids_canonical", str(corpus["name"]))
        candidate_sha = sha256_bytes(canonical_json(candidate_ids).encode("utf-8"))
        frozen_corpora.append({
            "name": corpus["name"],
            "working_database_sha256": corpus["working_database_sha256"],
            "candidate_ids_sha256": candidate_sha,
            "candidate_count": len(candidate_ids),
            "candidate_ids": candidate_ids,
        })
    require(set(queries) == set(QUERY_IDS), "query_set", "the four frozen query IDs must match exactly")
    executions: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for arm in ("matrix", "preflight"):
        forms = [item for item in FORMS if item[0] == arm]
        repetitions = range(1, 6) if arm == "matrix" else range(1, 2)
        case_ordinal = 0
        for corpus in ordered_corpora:
            corpus_name = str(corpus["name"])
            corpus_sha = str(corpus["working_database_sha256"])
            require(re.fullmatch(r"[0-9a-f]{64}", corpus_sha) is not None, "corpus_hash", corpus_name)
            for form in forms:
                _, form_id, query_id, _semantic, _semantic_only, _weight, top_k = form
                query = queries[query_id]
                query_sha = str(query["query_embedding_sha256"])
                require(re.fullmatch(r"[0-9a-f]{64}", query_sha) is not None, "query_hash", query_id)
                serialized_args = _args(form, query)
                args_sha = sha256_bytes(canonical_json(serialized_args).encode("utf-8"))
                debug_args = {**serialized_args, "debug": True}
                debug_args_sha = sha256_bytes(canonical_json(debug_args).encode("utf-8"))
                frozen_corpus = next(item for item in frozen_corpora if item["name"] == corpus_name)
                for cache_state in CACHE_STATES:
                    case_id = f"{corpus_name}:{form_id}:{cache_state}"
                    problem_id = f"{corpus_name}__{form_id}"
                    for repetition in repetitions:
                        pair_id = f"{case_id}:r{repetition:02d}"
                        lane_order = "numpy_first" if (case_ordinal + repetition) % 2 == 0 else "python_first"
                        execution = {
                            "arm": arm,
                            "problem_id": problem_id,
                            "case_id": case_id,
                            "pair_id": pair_id,
                            "corpus": corpus_name,
                            "form_id": form_id,
                            "query_id": query_id,
                            "cache_state": cache_state,
                            "repetition": repetition,
                            "top_k": top_k,
                            "serialized_args": serialized_args,
                            "serialized_args_sha256": args_sha,
                            "debug_observation_args": debug_args,
                            "debug_observation_args_sha256": debug_args_sha,
                            "corpus_sha256": corpus_sha,
                            "candidate_ids_sha256": frozen_corpus["candidate_ids_sha256"],
                            "candidate_count": frozen_corpus["candidate_count"],
                            "query_vector_sha256": query_sha,
                            "lane_invocation_order": lane_order,
                        }
                        executions.append(execution)
                        for lane in LANES:
                            identity = canonical_json([run_id, pair_id, lane]).encode("utf-8")
                            rows.append({**execution, "lane": lane, "row_id": sha256_bytes(identity)[:24]})
                    case_ordinal += 1
    result = {"schema": SCHEMA, "run_id": run_id, "corpora": frozen_corpora, "case_executions": executions, "planned_rows": rows}
    validate_frozen_cases(result)
    return result


def validate_frozen_cases(value: Mapping[str, Any]) -> None:
    exact_keys(value, ("schema", "run_id", "corpora", "case_executions", "planned_rows"), "cases_keys")
    require(value.get("schema") == SCHEMA, "cases_schema", "unexpected frozen-case schema")
    require(isinstance(value.get("run_id"), str) and bool(value["run_id"]), "cases_run_id", "nonempty run ID required")
    corpora = value.get("corpora")
    executions = value.get("case_executions")
    rows = value.get("planned_rows")
    require(isinstance(corpora, list) and isinstance(executions, list) and isinstance(rows, list), "cases_shape", "lists required")
    require([item.get("name") for item in corpora] == ["django", "fastapi", "jcodemunch"], "cases_corpora", "exact ordered corpora required")
    corpus_map: dict[str, Mapping[str, Any]] = {}
    for corpus in corpora:
        exact_keys(corpus, ("name", "working_database_sha256", "candidate_ids_sha256", "candidate_count", "candidate_ids"), "cases_corpus_keys")
        candidate_ids = corpus["candidate_ids"]
        require(isinstance(candidate_ids, list) and candidate_ids == sorted(set(candidate_ids)) and bool(candidate_ids), "cases_candidate_ids", str(corpus["name"]))
        require(corpus["candidate_count"] == len(candidate_ids), "cases_candidate_count", str(corpus["name"]))
        require(corpus["candidate_ids_sha256"] == sha256_bytes(canonical_json(candidate_ids).encode("utf-8")), "cases_candidate_hash", str(corpus["name"]))
        require(re.fullmatch(r"[0-9a-f]{64}", str(corpus["working_database_sha256"])) is not None, "cases_database_hash", str(corpus["name"]))
        corpus_map[str(corpus["name"])] = corpus
    require(len(executions) == 132 and len(rows) == 264, "cases_coverage", f"executions={len(executions)} rows={len(rows)}")
    require(len({row["row_id"] for row in rows}) == 264, "duplicate_row_id", "row IDs must be unique")
    pairs: dict[str, set[str]] = {}
    for row in rows:
        exact_keys(row, ROW_KEYS, "planned_row_keys")
        corpus = corpus_map.get(str(row["corpus"]))
        require(corpus is not None, "planned_row_corpus", str(row["corpus"]))
        require(row["corpus_sha256"] == corpus["working_database_sha256"] and row["candidate_ids_sha256"] == corpus["candidate_ids_sha256"] and row["candidate_count"] == corpus["candidate_count"], "planned_row_corpus_identity", str(row["row_id"]))
        require(row["debug_observation_args"] == {**row["serialized_args"], "debug": True}, "debug_observation_args", str(row["row_id"]))
        require(row["debug_observation_args_sha256"] == sha256_bytes(canonical_json(row["debug_observation_args"]).encode("utf-8")), "debug_observation_hash", str(row["row_id"]))
        pairs.setdefault(row["pair_id"], set()).add(row["lane"])
    for execution in executions:
        exact_keys(execution, EXECUTION_KEYS, "case_execution_keys")
    require(len(pairs) == 132 and all(lanes == set(LANES) for lanes in pairs.values()), "pair_lanes", "every pair requires both lanes")
    matrix = [row for row in rows if row["arm"] == "matrix"]
    preflight = [row for row in rows if row["arm"] == "preflight"]
    require(len(matrix) == 240 and len(preflight) == 24, "arm_counts", "expected 240 matrix and 24 preflight rows")
    require(len({row["problem_id"] for row in matrix}) == 12, "matrix_problem_count", "exactly 12 matrix problem IDs required")
    require({row["query_id"] for row in rows} == set(QUERY_IDS), "query_id_count", "exactly four query IDs required")
    require(all(sum(row["problem_id"] == problem for row in matrix) == 20 for problem in {row["problem_id"] for row in matrix}), "matrix_problem_multiplicity", "each matrix problem requires 20 rows")
    require(all(sum(row["query_id"] == query_id for row in matrix) == 60 for query_id in QUERY_IDS), "matrix_query_multiplicity", "each query requires 60 matrix rows")
    require(all(sum(row["lane"] == lane for row in matrix) == 120 for lane in LANES), "matrix_lane_multiplicity", "each lane requires 120 matrix rows")
    require(all(sum(row["cache_state"] == state for row in matrix) == 120 for state in CACHE_STATES), "matrix_cache_multiplicity", "each cache state requires 120 matrix rows")
    require(all(sum(row["repetition"] == repetition for row in matrix) == 48 for repetition in range(1, 6)), "matrix_repetition_multiplicity", "each repetition requires 48 matrix rows")
    firsts = [item["lane_invocation_order"] for item in executions if item["arm"] == "matrix"]
    require(firsts.count("numpy_first") == 60 and firsts.count("python_first") == 60, "matrix_order_balance", str({x:firsts.count(x) for x in set(firsts)}))
    pre = [item["lane_invocation_order"] for item in executions if item["arm"] == "preflight"]
    require(pre.count("numpy_first") == 6 and pre.count("python_first") == 6, "preflight_order_balance", str({x:pre.count(x) for x in set(pre)}))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--corpora", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    ns = parser.parse_args(argv)
    try:
        corpora_value = load_json(ns.corpora)
        queries_value = load_json(ns.queries)
        value = generate_frozen_cases(run_id=ns.run_id, corpora=corpora_value, queries=queries_value)
        atomic_write(ns.output, canonical_json_bytes(value), allowed_root=Path.cwd())
    except ContractError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
