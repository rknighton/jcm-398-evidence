from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import math
import os
import socket
import sqlite3
import struct
import sys
import time
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping, Sequence

from .common import ContractError, canonical_json, ensure_finite_scores, exact_keys, load_json, require, sha256_bytes, sha256_file, tree_hashes
from .controls import NetworkAttemptError, OutboundSocketTripwire
from .environment import OFFICIAL_WHEEL_SHA256, normalize_project_name, validate_environment_lock
from .metrics import ordering_sha256, ranking
from .invocation import command_receipt, reject_reparse_or_escape, validate_canonical_job_bytes, validate_production_job_campaign_binding
from .worker_protocol import (
    PROTOCOL_SELF_TEST_SCHEMA, WIRE_SCHEMA, build_worker_rejection,
    expected_success_job_from_artifact, validate_protocol_self_test_job,
    validate_invocation_binding, validate_worker_job, validate_worker_success,
)

SCHEMA = WIRE_SCHEMA
PROTOCOL_SELF_TEST_ENV = "ARC4_WORKER_PROTOCOL_SELF_TEST"
NETWORK_PROBE_ENV = "ARC4_WORKER_NETWORK_PROBE"


def query_vector_sha256(vector: Sequence[float]) -> str:
    return hashlib.sha256(canonical_json(list(vector)).encode("utf-8")).hexdigest()


def logical_embedding_identity(database: Path) -> tuple[str, int]:
    digest = hashlib.sha256(b"arc4.symbol-embeddings/v1\n")
    count = 0
    uri = f"file:{database.as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        cursor = connection.execute("SELECT symbol_id, embedding FROM symbol_embeddings ORDER BY symbol_id COLLATE BINARY")
        prior: str | None = None
        for symbol_id, embedding in cursor:
            require(isinstance(symbol_id, str) and symbol_id and symbol_id != prior, "embedding_id", str(symbol_id))
            require(isinstance(embedding, bytes), "embedding_blob", symbol_id)
            encoded_id = symbol_id.encode("utf-8")
            digest.update(struct.pack(">Q", len(encoded_id)))
            digest.update(encoded_id)
            digest.update(struct.pack(">Q", len(embedding)))
            digest.update(embedding)
            prior = symbol_id
            count += 1
    return digest.hexdigest(), count


def _database_state(database: Path) -> dict[str, Any]:
    wal = database.with_name(database.name + "-wal")
    shm = database.with_name(database.name + "-shm")
    logical_sha, count = logical_embedding_identity(database)
    return {
        "database_sha256": sha256_file(database),
        "wal_sha256": sha256_file(wal) if wal.exists() else None,
        "wal_size": wal.stat().st_size if wal.exists() else 0,
        "shm_sha256": sha256_file(shm) if shm.exists() else None,
        "shm_size": shm.stat().st_size if shm.exists() else 0,
        "logical_embedding_sha256": logical_sha,
        "embedding_count": count,
    }


def _database_content_unchanged(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    if before["database_sha256"] != after["database_sha256"]:
        return False
    if before["logical_embedding_sha256"] != after["logical_embedding_sha256"] or before["embedding_count"] != after["embedding_count"]:
        return False
    if before["wal_sha256"] is None:
        return after["wal_sha256"] is None or after["wal_size"] <= 32
    return before["wal_sha256"] == after["wal_sha256"] and before["wal_size"] == after["wal_size"]


def _source_file_receipts(database: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"database_path": str(database.resolve()), "files": {}}
    for suffix, path in (("db", database), ("wal", Path(str(database) + "-wal")), ("shm", Path(str(database) + "-shm"))):
        result["files"][suffix] = (
            {"present": True, "sha256": sha256_file(path), "size": path.stat().st_size}
            if path.exists() else {"present": False, "sha256": None, "size": 0}
        )
    return result


def _package_payload_hashes(package_root: Path) -> dict[str, str]:
    return {
        key: value for key, value in tree_hashes(package_root).items()
        if "/__pycache__/" not in f"/{key}" and not key.endswith((".pyc", ".pyo"))
    }


def _wheel_package_payload_hashes(wheel: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        with zipfile.ZipFile(wheel) as archive:
            for info in archive.infolist():
                if not info.filename.startswith("jcodemunch_mcp/") or info.is_dir():
                    continue
                relative = info.filename[len("jcodemunch_mcp/"):]
                require(relative and "\\" not in relative and ".." not in Path(relative).parts, "wheel_package_path", info.filename)
                require(relative not in result, "wheel_package_duplicate", relative)
                result[relative] = sha256_bytes(archive.read(info))
    except (OSError, zipfile.BadZipFile) as exc:
        raise ContractError("wheel_package_read", str(wheel)) from exc
    require(bool(result), "wheel_package_empty", str(wheel))
    return result


def _module_origin(module: Any, package_root: Path) -> str:
    origin = getattr(module, "__file__", None)
    require(isinstance(origin, str) and bool(origin), "module_origin_missing", str(getattr(module, "__name__", module)))
    resolved = Path(origin).resolve()
    try:
        relative = resolved.relative_to(package_root).as_posix()
    except ValueError as exc:
        raise ContractError("module_origin_escape", f"{resolved} outside {package_root}") from exc
    return relative


def _installed_distribution_versions() -> dict[str, str]:
    result: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        project = normalize_project_name(str(distribution.metadata["Name"]))
        require(project not in result, "installed_distribution_duplicate", project)
        result[project] = distribution.version
    return result


def _lexical_scores(index: Any, query: str) -> dict[str, float]:
    search_module = importlib.import_module("jcodemunch_mcp.tools.search_symbols")
    query_terms = search_module._tokenize(query) or [query.lower()]
    query_terms = [term for term in query_terms if term]
    idf, avgdl, _inverted = search_module._compute_bm25(index.symbols)
    centrality = search_module._compute_centrality(index.symbols, index.imports, index.alias_map, getattr(index, "psr4_map", None))
    result = {
        symbol["id"]: search_module._bm25_score(
            symbol,
            query_terms,
            idf,
            avgdl,
            centrality,
            raw_query=query,
        )
        for symbol in index.symbols
    }
    ensure_finite_scores(result)
    return result


def _semantic_lexical_channel(index: Any, query: str) -> dict[str, float]:
    search_module = importlib.import_module("jcodemunch_mcp.tools.search_symbols")
    fusion = importlib.import_module("jcodemunch_mcp.retrieval.signal_fusion")
    query_terms = search_module._tokenize(query) or [query.lower()]
    query_terms = [term for term in query_terms if term]
    idf, avgdl, _inverted = search_module._compute_bm25(index.symbols)
    centrality = search_module._compute_centrality(index.symbols, index.imports, index.alias_map, getattr(index, "psr4_map", None))
    joined = " ".join(query_terms)
    raw: list[tuple[str, float, float]] = []
    max_lex = max_identity = 0.0
    for symbol in index.symbols:
        symbol_id = symbol["id"]
        lex = fusion._bm25_score_no_identity(symbol, query_terms, idf, avgdl, centrality)
        identity = search_module._identity_score(symbol, joined, raw_query=query)
        require(math.isfinite(lex) and math.isfinite(identity), "adapter_nonfinite", symbol_id)
        max_lex = max(max_lex, lex)
        max_identity = max(max_identity, identity)
        raw.append((symbol_id, lex, identity))
    result = {
        symbol_id: max(lex / max_lex if max_lex > 0.0 else 0.0, identity / max_identity if max_identity > 0.0 else 0.0)
        for symbol_id, lex, identity in raw
    }
    ensure_finite_scores(result)
    return result


def _require_score_consistent_top_k(
    observed_ids: Sequence[Any], scores: Mapping[str, float], limit: int, code: str
) -> None:
    positive_ids = [symbol_id for symbol_id, score in scores.items() if float(score) > 0.0]
    expected_length = min(limit, len(positive_ids))
    require(len(observed_ids) == expected_length, code, "public result length differs from positive-score top-k")
    require(len(set(observed_ids)) == len(observed_ids), code, "public result IDs are not unique")
    require(all(isinstance(symbol_id, str) and symbol_id in scores for symbol_id in observed_ids), code, "public result contains an unknown ID")
    observed_scores = [float(scores[str(symbol_id)]) for symbol_id in observed_ids]
    require(all(score > 0.0 for score in observed_scores), code, "public result contains a non-positive score")
    require(
        all(left >= right for left, right in zip(observed_scores, observed_scores[1:])),
        code,
        "public results are not ordered by non-increasing score",
    )
    if observed_scores:
        observed_set = set(observed_ids)
        cutoff = observed_scores[-1]
        excluded_max = max(
            (float(score) for symbol_id, score in scores.items() if symbol_id not in observed_set),
            default=float("-inf"),
        )
        require(excluded_max <= cutoff, code, "an excluded result has a greater score than the public cutoff")


def _reconstruct(index: Any, matrix: Any, query: str, query_vector: list[float], semantic_only: bool, weight: float) -> tuple[dict[str, float], dict[str, float]]:
    cosine = matrix.score_all(query_vector)
    ensure_finite_scores(cosine)
    if semantic_only:
        return cosine, dict(cosine)
    lexical = _semantic_lexical_channel(index, query)
    require(set(lexical) == set(cosine), "adapter_candidate_set", "lexical and semantic candidates differ")
    final = {symbol_id: (1.0 - weight) * lexical[symbol_id] + weight * float(cosine[symbol_id]) for symbol_id in lexical}
    ensure_finite_scores(final)
    return cosine, final


def execute_job(job: Mapping[str, Any], *, network: OutboundSocketTripwire) -> dict[str, Any]:
    require(network.installed and network.lifetime_guard_registered, "network_lifetime_guard", "process-lifetime tripwire must be installed before job execution")
    lane = job.get("lane")
    require(lane in ("numpy_present", "numpy_absent"), "worker_lane", str(lane))
    require(isinstance(job.get("attempt_n"), int) and not isinstance(job.get("attempt_n"), bool) and job["attempt_n"] >= 1, "worker_attempt", str(job.get("attempt_n")))
    require(job.get("attempt_methodology") in ("initial", "explicit_repair"), "worker_attempt_methodology", str(job.get("attempt_methodology")))
    require((job["attempt_methodology"] == "initial" and job["attempt_n"] == 1 and job.get("repair_reason") is None) or (job["attempt_methodology"] == "explicit_repair" and job["attempt_n"] >= 2 and isinstance(job.get("repair_reason"), str) and bool(job["repair_reason"].strip())), "worker_repair_provenance", str(job.get("repair_reason")))
    vector = job.get("query_vector")
    require(isinstance(vector, list) and len(vector) == 384, "query_vector", "384 values required")
    require(query_vector_sha256(vector) == job.get("query_vector_sha256"), "query_vector_hash", "frozen vector hash mismatch")
    candidate_ids = job.get("candidate_ids")
    require(isinstance(candidate_ids, list) and candidate_ids == sorted(set(candidate_ids)) and bool(candidate_ids), "candidate_ids", "sorted unique frozen candidate IDs required")
    require(sha256_bytes(canonical_json(candidate_ids).encode("utf-8")) == job.get("candidate_ids_sha256") and len(candidate_ids) == job.get("candidate_count"), "candidate_identity", "candidate set differs from frozen evidence")
    storage_path = Path(str(job["storage_path"])).resolve()
    home_path = Path(str(job["home_path"])).resolve()
    require(Path.home().resolve() == home_path and Path(os.environ.get("USERPROFILE", "")).resolve() == home_path, "worker_home", f"expected {home_path}, observed {Path.home()}")
    package_root = Path(str(job["package_root"])).resolve()
    database = Path(str(job["database"])).resolve()
    require(job.get("trial_source_files") == _source_file_receipts(database), "trial_source_receipt", str(database))
    args = dict(job["serialized_args"])
    args.setdefault("repo", job["repo_id"])
    require(str(args.get("query")) == job.get("query_text"), "query_text", "serialized query differs")
    require(not (storage_path / "tuning.jsonc").exists() and not (Path.home() / ".code-index" / "tuning.jsonc").exists(), "tuning_override", str(storage_path))
    expected_environment = {
        "PYTHONHASHSEED": None if job["python_hash_seed"] is None else str(job["python_hash_seed"]), "PYTHONNOUSERSITE": "1",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        "JCODEMUNCH_EMBED_MATRIX_CACHE": None, "JCODEMUNCH_SHARE_SAVINGS": "0",
    }
    require({key: os.environ.get(key) for key in expected_environment} == expected_environment, "worker_environment", str({key: os.environ.get(key) for key in expected_environment}))
    credentials = ("OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "COHERE_API_KEY")
    require(not any(os.environ.get(key) for key in credentials), "embedding_credentials", "embedding API credential inherited")
    treatment_wheel = Path(str(job["treatment_wheel"])).resolve()
    before_treatment_sha = sha256_file(treatment_wheel)
    require(before_treatment_sha == OFFICIAL_WHEEL_SHA256, "treatment_wheel", str(treatment_wheel))
    environment_lock_path = Path(str(job["environment_lock_path"])).resolve()
    require(sha256_file(environment_lock_path) == job.get("environment_lock_sha256"), "environment_lock_hash", str(environment_lock_path))
    environment_lock = load_json(environment_lock_path)
    validate_environment_lock(environment_lock, require_bound=True)
    expected_distributions = {item["project"]: item["version"] for item in environment_lock["lanes"][lane]["distributions"]}
    require(_installed_distribution_versions() == expected_distributions, "installed_distribution_set", str(_installed_distribution_versions()))
    require(importlib.metadata.version("jcodemunch-mcp") == "1.108.228", "installed_version", importlib.metadata.version("jcodemunch-mcp"))
    before_package = _package_payload_hashes(package_root)
    require(before_package == _wheel_package_payload_hashes(treatment_wheel), "installed_payload", "installed package differs from locked official wheel")
    provider_calls: list[dict[str, Any]] = []
    unexpected_provider_call = False
    package = importlib.import_module("jcodemunch_mcp")
    module_origins = {"jcodemunch_mcp": _module_origin(package, package_root)}
    config = importlib.import_module("jcodemunch_mcp.config")
    module_origins["jcodemunch_mcp.config"] = _module_origin(config, package_root)
    try:
        config.load_config(storage_path=str(storage_path))
        require(config.get("share_savings") is False, "share_config", "share_savings must be false")
        require(config.get("perf_telemetry_enabled") is False, "telemetry_config", "perf telemetry must be false")
        require(config.get("embed_model") == job.get("embed_model"), "embed_model", "sentinel differs")
        storage_module = importlib.import_module("jcodemunch_mcp.storage")
        module_origins["jcodemunch_mcp.storage"] = _module_origin(storage_module, package_root)
        from jcodemunch_mcp.storage import IndexStore
        owner, name = str(job["repo_id"]).split("/", 1)
        store = IndexStore(base_path=str(storage_path))
        index = store.load_index(owner, name)
        require(index is not None, "index_load", str(job["repo_id"]))
        index_candidate_ids = sorted(str(symbol["id"]) for symbol in index.symbols)
        require(index_candidate_ids == candidate_ids, "index_candidate_set", "loaded index differs from frozen candidate IDs")
        actual_database = Path(store._sqlite._db_path(owner, name)).resolve()
        require(actual_database == database, "database_path", f"expected {database}, observed {actual_database}")
        before_database = _database_state(database)
        embed_repo = importlib.import_module("jcodemunch_mcp.tools.embed_repo")
        module_origins["jcodemunch_mcp.tools.embed_repo"] = _module_origin(embed_repo, package_root)
        original_embed = embed_repo.embed_texts
        def frozen_embed(texts: list[str], provider: str, model: str, **kwargs: Any) -> list[list[float]]:
            nonlocal unexpected_provider_call
            provider_calls.append({"texts": list(texts), "provider": provider, "model": model, "task_type": kwargs.get("task_type"), "query_vector_sha256": job["query_vector_sha256"]})
            if texts != [job["query_text"]]:
                unexpected_provider_call = True
                raise RuntimeError("unexpected_provider_call")
            require(query_vector_sha256(vector) == job["query_vector_sha256"], "provider_vector_hash", "vector changed")
            return [list(vector)]
        embed_repo.embed_texts = frozen_embed
        try:
            embedding_matrix = importlib.import_module("jcodemunch_mcp.storage.embedding_matrix")
            module_origins["jcodemunch_mcp.storage.embedding_matrix"] = _module_origin(embedding_matrix, package_root)
            if lane == "numpy_absent":
                try:
                    importlib.import_module("numpy")
                except ModuleNotFoundError:
                    numpy_import_failed_before = True
                else:
                    numpy_import_failed_before = False
                numpy_importable_before = importlib.util.find_spec("numpy") is not None
                numpy_helper_before = embedding_matrix._numpy() is not None
                require(numpy_import_failed_before and not numpy_importable_before and not numpy_helper_before, "numpy_absence", "NumPy is importable")
                numpy_version = None
            else:
                numpy = importlib.import_module("numpy")
                numpy_import_failed_before = False
                numpy_importable_before = True
                numpy_helper_before = embedding_matrix._numpy() is not None
                numpy_version = numpy.__version__
                require(numpy_version == "2.4.4" and numpy_helper_before, "numpy_present", "NumPy 2.4.4 required")
            cache_before = embedding_matrix.cache_stats()
            require(cache_before["numpy"] is (lane == "numpy_present"), "cache_lane_before", str(cache_before))
            search_module = importlib.import_module("jcodemunch_mcp.tools.search_symbols")
            module_origins["jcodemunch_mcp.tools.search_symbols"] = _module_origin(search_module, package_root)
            fusion_module = importlib.import_module("jcodemunch_mcp.retrieval.signal_fusion")
            module_origins["jcodemunch_mcp.retrieval.signal_fusion"] = _module_origin(fusion_module, package_root)
            warmup = None
            cache_after_warmup = None
            matrix_stamp_before_measurement = None
            if job["cache_state"] == "generation_warm":
                warmup = search_module.search_symbols(**args, storage_path=str(storage_path))
                require(not warmup.get("error"), "warmup_error", str(warmup.get("error")))
                cache_after_warmup = embedding_matrix.cache_stats()
                require(cache_after_warmup["repos"] == (1 if job["arm"] == "matrix" else 0), "warm_cache", "unexpected cache state")
                if job["arm"] == "matrix":
                    warm_matrix = embedding_matrix.get_matrix(database)
                    matrix_stamp_before_measurement = embedding_matrix._stamp(database)
                    require(matrix_stamp_before_measurement is not None, "warm_matrix_stamp", "matrix stamp is unavailable")
            else:
                require(cache_before["repos"] == 0, "cold_cache", "cold worker started with cached matrix")
            started_cpu = time.process_time_ns()
            started_wall = time.perf_counter_ns()
            public = search_module.search_symbols(**args, storage_path=str(storage_path))
            wall_ns = time.perf_counter_ns() - started_wall
            cpu_ns = time.process_time_ns() - started_cpu
            require(not public.get("error"), "public_error", str(public.get("error")))
            cache_after_public = embedding_matrix.cache_stats()
            require(cache_after_public["numpy"] is (lane == "numpy_present"), "cache_lane_after", str(cache_after_public))
            served_from_result_cache = bool(public.get("_meta", {}).get("cache_hit", False))
            if job["arm"] == "matrix":
                require(cache_after_public["repos"] == 1 and not served_from_result_cache, "matrix_cache_path", str(cache_after_public))
                matrix = embedding_matrix.get_matrix(database)
                require(matrix is not None, "lane_selection", lane)
                if lane == "numpy_present":
                    require(matrix.vectorised is True, "fallback_firing", "NumPy lane executed the Python fallback")
                else:
                    require(matrix.vectorised is False, "lane_mismatch", "fallback lane executed the NumPy path")
                matrix_stamp_after_measurement = embedding_matrix._stamp(database)
                require(matrix_stamp_after_measurement is not None, "matrix_stamp", "matrix stamp is unavailable")
                if matrix_stamp_before_measurement is not None:
                    require(matrix_stamp_after_measurement == matrix_stamp_before_measurement, "warm_matrix_stamp_changed", "matrix stamp changed between calls")
                cosine, final = _reconstruct(index, matrix, str(job["query_text"]), vector, bool(args.get("semantic_only")), float(args.get("semantic_weight", 0.5)))
                require(set(cosine) == set(final) == set(candidate_ids), "matrix_candidate_set", "score vectors differ from frozen candidates")
                public_adapter_scores = final
            else:
                cosine, final = {}, {}
                matrix_stamp_after_measurement = None
                require(cache_after_public["repos"] == 0, "preflight_matrix_path", "preflight loaded the embedding matrix")
                require(served_from_result_cache == (job["cache_state"] == "generation_warm"), "preflight_result_cache", str(served_from_result_cache))
                public_adapter_scores = _lexical_scores(index, str(job["query_text"]))
            public_results = public.get("results", [])
            require(isinstance(public_results, list), "public_result_shape", "results list required")
            public_ids = [item.get("id") for item in public_results if isinstance(item, dict)]
            expected_public_ids = ranking(public_adapter_scores)[: int(job["top_k"])]
            try:
                _require_score_consistent_top_k(public_ids, public_adapter_scores, int(job["top_k"]), "adapter_public_parity")
            except ContractError:
                diagnostic = {
                    "schema": "arc4.adapter-public-parity-diagnostic/v1",
                    "public_ids": public_ids,
                    "expected_public_ids": expected_public_ids,
                    "public_only": [symbol_id for symbol_id in public_ids if symbol_id not in expected_public_ids],
                    "expected_only": [symbol_id for symbol_id in expected_public_ids if symbol_id not in public_ids],
                }
                (home_path / "adapter-public-parity-diagnostic.json").write_bytes(
                    (canonical_json(diagnostic) + "\n").encode("utf-8")
                )
                raise
            debug_args = dict(job["debug_observation_args"])
            require(debug_args.get("debug") is True and sha256_bytes(canonical_json(debug_args).encode("utf-8")) == job.get("debug_observation_args_sha256"), "debug_observation_args", "debug observation was not preregistered")
            debug_args.setdefault("repo", job["repo_id"])
            debug_public = search_module.search_symbols(**debug_args, storage_path=str(storage_path))
            require(not debug_public.get("error"), "debug_public_error", str(debug_public.get("error")))
            debug_results = debug_public.get("results", [])
            require(isinstance(debug_results, list), "debug_result_shape", "results list required")
            debug_ids = [item.get("id") for item in debug_results if isinstance(item, dict)]
            adapter_scores = final if job["arm"] == "matrix" else _lexical_scores(index, str(job["query_text"]))
            require(set(adapter_scores) == set(candidate_ids), "debug_candidate_set", "debug adapter differs from frozen candidates")
            _require_score_consistent_top_k(debug_ids, adapter_scores, int(debug_args["max_results"]), "debug_adapter_order")
            require(debug_ids == public_ids, "debug_public_parity", "debug and non-debug public result IDs differ")
            debug_scores: list[dict[str, Any]] = []
            for item in debug_results:
                require(isinstance(item, dict) and set(item) >= {"id", "score"}, "debug_result_item", str(item))
                public_score = item.get("score")
                expected_score = round(float(adapter_scores[item["id"]]), 4 if job["arm"] == "matrix" else 3)
                require(isinstance(public_score, (int, float)) and float(public_score) == expected_score, "debug_adapter_score", str(item["id"]))
                debug_scores.append({"id": item["id"], "public_score": float(public_score), "adapter_rounded": expected_score})
            require(not unexpected_provider_call, "provider_topup", "unexpected embed_texts call occurred")
            expected_calls = (3 if job["cache_state"] == "generation_warm" else 2) if job["arm"] == "matrix" else 0
            require(len(provider_calls) == expected_calls, "provider_call_count", f"expected {expected_calls}, observed {len(provider_calls)}")
            if lane == "numpy_absent":
                try:
                    importlib.import_module("numpy")
                except ModuleNotFoundError:
                    numpy_import_failed_after = True
                else:
                    numpy_import_failed_after = False
                numpy_importable_after = importlib.util.find_spec("numpy") is not None
                numpy_helper_after = embedding_matrix._numpy() is not None
                require(numpy_import_failed_after and not numpy_importable_after and not numpy_helper_after, "numpy_absence_after", "NumPy became importable")
            else:
                numpy_import_failed_after = False
                numpy_importable_after = importlib.util.find_spec("numpy") is not None
                numpy_helper_after = embedding_matrix._numpy() is not None
                require(numpy_importable_after and numpy_helper_after, "numpy_present_after", "NumPy lane changed")
        finally:
            embed_repo.embed_texts = original_embed
    finally:
        pass
    after_database = _database_state(database)
    require(_database_content_unchanged(before_database, after_database), "database_mutation", "database, WAL, or embeddings changed")
    require(before_package == _package_payload_hashes(package_root), "package_mutation", "installed package bytes changed")
    require(sha256_file(treatment_wheel) == before_treatment_sha, "treatment_wheel_mutation", str(treatment_wheel))
    require(not network.attempts, "network_attempt", str(network.attempts))
    return {
        "schema": SCHEMA,
        **{key: job[key] for key in (
            "problem_id", "case_id", "pair_id", "corpus", "form_id", "query_id", "cache_state",
            "repetition", "top_k", "serialized_args", "serialized_args_sha256", "debug_observation_args",
            "debug_observation_args_sha256", "corpus_sha256", "candidate_ids_sha256", "candidate_count",
            "query_vector_sha256", "lane_invocation_order", "row_id", "arm",
        )},
        "lane": lane,
        "attempt_n": job["attempt_n"],
        "attempt_methodology": job["attempt_methodology"], "repair_reason": job["repair_reason"],
        "pair_invocation_ordinal": job["pair_invocation_ordinal"],
        "observed_query_vector_sha256": query_vector_sha256(vector),
        "frozen_source_files": job["frozen_source_files"], "trial_source_files": job["trial_source_files"],
        "public_result_ids": [item["id"] for item in public.get("results", [])],
        "raw_cosine": {key: float(value).hex() for key, value in sorted(cosine.items())},
        "final_scores": {key: float(value).hex() for key, value in sorted(final.items())},
        "full_depth_ordering_sha256": ordering_sha256(final) if final else None,
        "provider_calls": provider_calls, "warmup_result": warmup,
        "cache_before": cache_before, "cache_after_public": cache_after_public,
        "cache_after_warmup": cache_after_warmup,
        "served_from_result_cache": served_from_result_cache, "database_state_before": before_database,
        "database_state": after_database,
        "matrix_stamp_before_measurement": list(matrix_stamp_before_measurement) if matrix_stamp_before_measurement is not None else None,
        "matrix_stamp_after_measurement": list(matrix_stamp_after_measurement) if matrix_stamp_after_measurement is not None else None,
        "wall_ns": wall_ns, "process_cpu_ns": cpu_ns,
        "debug_observation": {
            "debug": True, "ordered_ids": debug_ids, "scores": debug_scores,
            "order_matches": True, "rounded_scores_match": True,
            "adapter_kind": "final" if job["arm"] == "matrix" else "bm25_identity",
        },
        "package_evidence": {
            "official_wheel_sha256": before_treatment_sha,
            "environment_lock_sha256": job["environment_lock_sha256"],
            "installed_version": "1.108.228",
            "payload_file_count": len(before_package),
            "payload_matches_official_wheel": True,
            "module_origins": dict(sorted(module_origins.items())),
        },
        "lane_evidence": {
            "numpy_version": numpy_version,
            "numpy_import_failed_before": numpy_import_failed_before,
            "numpy_importable_before": numpy_importable_before,
            "numpy_helper_non_null_before": numpy_helper_before,
            "numpy_importable_after": numpy_importable_after,
            "numpy_import_failed_after": numpy_import_failed_after,
            "numpy_helper_non_null_after": numpy_helper_after,
            "matrix_vectorised": matrix.vectorised if job["arm"] == "matrix" else None,
        },
        "controls": {
            "network_attempts": [], "network_tripwire_installed_before_config": True,
            "network_lifetime_guard_registered": True, "credentials_absent": True,
            "sharing_disabled": True, "package_unchanged": True, "database_unchanged": True,
            "candidate_set_matches": True, "provider_expected_calls": expected_calls,
            "provider_observed_calls": len(provider_calls), "topup_tripwire_events": 0,
            "storage_tuning_absent": True, "home_tuning_absent": True,
            "effective_weight_matches": True,
        },
    }


def _execute_protocol_self_test(job: Mapping[str, Any], *, network: OutboundSocketTripwire) -> dict[str, Any]:
    validate_protocol_self_test_job(job)
    action = job["fixture_action"]
    if action == "network_connect":
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.connect(("127.0.0.1", 9))
        raise ContractError("network_tripwire_bypass", "socket connect unexpectedly returned")
    error_code = job["fixture_error_code"]
    if action == "error":
        raise ContractError(error_code, "deterministic worker protocol self-test")
    require(isinstance(job["fixture_result"], dict), "worker_protocol_self_test_result", "success fixture required")
    return dict(job["fixture_result"])


def _load_bound_job(binding_path: Path, job_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        binding_bytes = binding_path.read_bytes()
    except OSError as exc:
        raise ContractError("worker_binding_transport", str(exc)) from exc
    binding = validate_canonical_job_bytes(binding_bytes)
    validate_invocation_binding(binding)
    attempt_root = Path(binding["paths"]["attempt_root"])
    require(binding_path.resolve() == Path(binding["paths"]["binding"]).resolve(), "worker_binding_path", str(binding_path))
    require(job_path.resolve() == Path(binding["job"]["artifact_path"]).resolve(), "worker_binding_job_path", str(job_path))
    reject_reparse_or_escape(binding_path, attempt_root, "worker_binding_reparse")
    reject_reparse_or_escape(job_path, attempt_root, "worker_job_reparse")
    try:
        payload = job_path.read_bytes()
    except OSError as exc:
        raise ContractError("worker_job_transport", str(exc)) from exc
    require(len(payload) == binding["job"]["bytes"] and sha256_bytes(payload) == binding["job"]["sha256"], "worker_job_binding_hash", str(job_path))
    job = validate_canonical_job_bytes(payload)
    self_test = os.environ.get(PROTOCOL_SELF_TEST_ENV) == "1"
    if self_test:
        validate_protocol_self_test_job(job)
        plan = job["planned_row"]
        attempt = job["production_context"]
    else:
        validate_worker_job(job)
        plan = job
        attempt = job
    expected_identity = {key: plan[key] for key in ("row_id", "pair_id", "case_id", "problem_id", "arm", "lane")}
    require(binding["row_identity"] == expected_identity, "worker_binding_job_identity", str(expected_identity))
    expected_execution = {"namespace": "preflight", "is_control": False, "control_id": None, "python_hash_seed": os.environ.get("PYTHONHASHSEED")} if self_test else {"namespace": job["execution_namespace"], "is_control": job["is_control"], "control_id": job["control_id"], "python_hash_seed": job["python_hash_seed"]}
    require(binding["execution"] == expected_execution, "worker_binding_job_execution", str(plan["row_id"]))
    require(binding["attempt"] == {"attempt_n": attempt["attempt_n"], "methodology": attempt["attempt_methodology"], "repair_reason": attempt["repair_reason"]}, "worker_binding_job_attempt", str(plan["row_id"]))
    require(Path(sys.executable).resolve() == Path(binding["interpreter"]["path"]).resolve() and sha256_file(Path(sys.executable)) == binding["interpreter"]["sha256"], "worker_interpreter_identity", sys.executable)
    if not self_test:
        require(Path(job["package_root"]).resolve() == Path(binding["interpreter"]["package_root"]).resolve(), "worker_package_root_binding", str(job["package_root"]))
        validate_production_job_campaign_binding(job, binding=binding)
    expected_command = [str(Path(sys.executable).resolve()), "-m", "harness.worker", "--binding", str(binding_path.resolve()), str(job_path.resolve())]
    require(binding["command"] == command_receipt(expected_command), "worker_command_identity", str(binding["command"]))
    observed_seed = os.environ.get("PYTHONHASHSEED")
    require(observed_seed == binding["execution"]["python_hash_seed"], "worker_hash_seed", f"declared={binding['execution']['python_hash_seed']!r} observed={observed_seed!r}")
    return binding, job


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("job", type=Path)
    ns = parser.parse_args(argv)
    network = OutboundSocketTripwire().install(process_lifetime=True)
    job: Mapping[str, Any] | None = None
    try:
        _binding, loaded = _load_bound_job(ns.binding, ns.job)
        self_test = os.environ.get(PROTOCOL_SELF_TEST_ENV) == "1"
        if self_test:
            validate_protocol_self_test_job(loaded)
        else:
            validate_worker_job(loaded)
        job = loaded
        selected_executor = _execute_protocol_self_test if self_test else execute_job
        if not self_test and os.environ.get(NETWORK_PROBE_ENV) == "1":
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.connect(("127.0.0.1", 9))
        result = selected_executor(job, network=network)
        require(isinstance(result, dict), "worker_success_type", str(type(result).__name__))
        expected_job = expected_success_job_from_artifact(job)
        validate_worker_success(result, expected_job=expected_job)
        from .verify import Rejected, validate_row_evidence
        try:
            validate_row_evidence(result, set(expected_job["candidate_ids"]))
        except Rejected as exc:
            raise ContractError(f"worker_success_{exc.code}", str(exc)) from exc
        sys.stdout.buffer.write(("ARC4_RESULT " + canonical_json(result) + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
        return 0
    except ContractError as exc:
        attempts = exc.attempts if isinstance(exc, NetworkAttemptError) else []
        rejection = build_worker_rejection(exc.code, job, network_attempts=attempts)
        sys.stderr.buffer.write((canonical_json(rejection) + "\n").encode("utf-8"))
        sys.stderr.buffer.flush()
        if isinstance(exc, NetworkAttemptError):
            network.mark_retained(attempts)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
