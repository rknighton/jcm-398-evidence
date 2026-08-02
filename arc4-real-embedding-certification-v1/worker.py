"""Fresh-process worker for embedding preparation and retained measurements."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from arc4lib import canonical_json, execute_mode, fractions, score_case, sha256_file


def _emit(payload: dict[str, Any]) -> None:
    print("ARC4_RESULT " + canonical_json(payload), flush=True)


def _activate_root(root: Path) -> dict[str, Any]:
    source = (root / "src").resolve()
    sys.path.insert(0, str(source))
    importlib.invalidate_caches()
    module = importlib.import_module("jcodemunch_mcp.tools.search_symbols")
    imported = Path(module.__file__).resolve()
    if source not in imported.parents:
        raise RuntimeError(f"import root mismatch: expected {source}, imported {imported}")
    return {"source": source, "module": module, "imported": imported}


def _git_identity(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        return completed.stdout

    head = run("rev-parse", "HEAD").strip()
    status = [line for line in run("status", "--porcelain=v1").splitlines() if line]
    diff = subprocess.run(
        ["git", "-C", str(root), "diff", "--no-ext-diff", "--binary", "HEAD"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=30,
    ).stdout
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    version = "unknown"
    for line in pyproject.splitlines():
        stripped = line.strip()
        if stripped.startswith("version") and "=" in stripped:
            version = stripped.split("=", 1)[1].strip().strip('"')
            break
    return {
        "source_sha": head,
        "dirty_paths": status,
        "diff_sha256": hashlib.sha256(diff).hexdigest(),
        "version": version,
    }


def _copy_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    source_uri = f"file:{source.as_posix()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
        dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _embedding_identity(database: Path) -> dict[str, Any]:
    uri = f"file:{database.as_posix()}?mode=ro&immutable=1"
    digest = hashlib.sha256()
    with sqlite3.connect(uri, uri=True) as connection:
        count = connection.execute("SELECT COUNT(*) FROM symbol_embeddings").fetchone()[0]
        for symbol_id, blob in connection.execute(
            "SELECT symbol_id, embedding FROM symbol_embeddings ORDER BY symbol_id"
        ):
            encoded = symbol_id.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            digest.update(len(blob).to_bytes(8, "big"))
            digest.update(blob)
        meta = dict(
            connection.execute(
                "SELECT key, value FROM meta WHERE key LIKE 'embed_%' ORDER BY key"
            ).fetchall()
        )
    return {"vector_count": count, "identity": digest.hexdigest(), "meta": meta}


def _prepare(args: argparse.Namespace) -> int:
    config = json.loads(args.config.read_text(encoding="utf-8"))
    root_info = _activate_root(args.baseline_root)
    from jcodemunch_mcp.tools.embed_repo import _detect_provider, embed_repo, embed_texts

    detected = _detect_provider()
    expected = config["embedding"]
    if detected != (expected["provider"], expected["model"]):
        raise RuntimeError(f"embedding provider mismatch: expected {expected}, detected {detected}")

    args.work_index_root.mkdir(parents=True, exist_ok=True)
    corpus_records: dict[str, Any] = {}
    for corpus in config["corpora"]:
        source_database = args.source_index_root / corpus["source_database"]
        working_database = args.work_index_root / corpus["source_database"]
        if not working_database.exists():
            _copy_database(source_database, working_database)
        result = embed_repo(
            corpus["source_repo_id"],
            batch_size=args.batch_size,
            force=True,
            storage_path=str(args.work_index_root),
        )
        if result.get("error"):
            raise RuntimeError(f"embedding failed for {corpus['name']}: {result}")
        identity = _embedding_identity(working_database)
        if identity["vector_count"] <= 0:
            raise RuntimeError(f"no embeddings produced for {corpus['name']}")
        corpus_records[corpus["name"]] = {
            "source_database": str(source_database),
            "working_database": str(working_database),
            "source_database_sha256": sha256_file(source_database),
            "working_database_sha256": sha256_file(working_database),
            "embedding_vector_count": identity["vector_count"],
            "embedding_generation_identity": identity["identity"],
            "embedding_meta": identity["meta"],
            "embed_result": result,
        }

    query_records: dict[str, Any] = {}
    for query in config["queries"]:
        vector = embed_texts(
            [query["query"]],
            expected["provider"],
            expected["model"],
            task_type=expected.get("query_task_type") or None,
        )[0]
        if len(vector) != expected["dimension"]:
            raise RuntimeError(f"query dimension mismatch for {query['query_id']}")
        encoded = canonical_json(vector).encode("utf-8")
        query_records[query["query_id"]] = {
            "vector": vector,
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "serialized_args_json": canonical_json(
                {
                    "query": query["query"],
                    "semantic_only": query["semantic_only"],
                    "semantic_weight": query["semantic_weight"],
                    "max_results": query["top_k"],
                    "detail_level": "compact",
                    "debug": False,
                }
            ),
        }

    payload = {
        "status": "prepared",
        "baseline_root": str(args.baseline_root.resolve()),
        "baseline_import_root": str(root_info["imported"]),
        "baseline_identity": _git_identity(args.baseline_root),
        "embedding_provider": detected[0],
        "embedding_model": detected[1],
        "corpora": corpus_records,
        "queries": query_records,
    }
    _emit(payload)
    return 0


class _PeakRss:
    def __init__(self, interval: float) -> None:
        self.interval = interval
        self.peak = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _rss(self) -> int:
        try:
            import psutil

            return int(psutil.Process().memory_info().rss)
        except Exception:
            return 0

    def _sample(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, self._rss())
            self._stop.wait(self.interval)

    def __enter__(self) -> "_PeakRss":
        self.peak = self._rss()
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.peak = max(self.peak, self._rss())


def _load_case(
    *,
    index_root: Path,
    repo_id: str,
    query_text: str,
    query_vector: list[float],
    semantic_only: bool,
    semantic_weight: float,
) -> dict[str, Any]:
    import numpy as np
    from jcodemunch_mcp.retrieval.signal_fusion import _bm25_score_no_identity
    from jcodemunch_mcp.storage import IndexStore
    from jcodemunch_mcp.storage.embedding_store import EmbeddingStore
    from jcodemunch_mcp.tools.search_symbols import (
        _compute_bm25,
        _compute_centrality,
        _identity_score,
        _tokenize,
    )

    owner, name = repo_id.split("/", 1)
    store = IndexStore(base_path=index_root)
    index = store.load_index(owner, name)
    if index is None:
        raise RuntimeError(f"could not load index {repo_id} from {index_root}")
    database = store._sqlite._db_path(owner, name)
    embedding_store = EmbeddingStore(database)
    embeddings = embedding_store.get_all_readonly()
    symbols = [symbol for symbol in index.symbols if symbol["id"] in embeddings]
    if not symbols:
        raise RuntimeError(f"index {repo_id} has no matching embeddings")
    symbol_ids = [symbol["id"] for symbol in symbols]
    matrix = np.asarray([embeddings[symbol_id] for symbol_id in symbol_ids], dtype=np.float32)

    if semantic_only:
        lexical_base = [0.0] * len(symbols)
    else:
        query_terms = _tokenize(query_text)
        idf, avgdl, _ = _compute_bm25(index.symbols)
        centrality = _compute_centrality(
            index.symbols,
            index.imports,
            index.alias_map,
            getattr(index, "psr4_map", None),
        )
        query_joined = " ".join(query_terms)
        lexical: list[float] = []
        identity: list[float] = []
        for symbol in symbols:
            lexical.append(
                _bm25_score_no_identity(symbol, query_terms, idf, avgdl, centrality)
            )
            identity.append(_identity_score(symbol, query_joined, raw_query=query_text))
        max_lexical = max(lexical, default=0.0)
        max_identity = max(identity, default=0.0)
        lexical_base = [
            (1.0 - semantic_weight)
            * max(
                score / max_lexical if max_lexical > 0.0 else 0.0,
                identity[index] / max_identity if max_identity > 0.0 else 0.0,
            )
            for index, score in enumerate(lexical)
        ]
    return {
        "index": index,
        "database": database,
        "symbol_ids": symbol_ids,
        "matrix": matrix,
        "lexical_base": lexical_base,
        "query_vector": query_vector,
    }


def _measure(args: argparse.Namespace) -> int:
    config = json.loads(args.config.read_text(encoding="utf-8"))
    preparation = json.loads(args.preparation.read_text(encoding="utf-8"))
    corpus = next(item for item in config["corpora"] if item["name"] == args.corpus)
    query = next(item for item in config["queries"] if item["query_id"] == args.query_id)
    query_record = preparation["queries"][args.query_id]
    root_info = _activate_root(args.candidate_root)
    candidate_identity = _git_identity(args.candidate_root)
    baseline_identity = _git_identity(args.baseline_root)

    rss_sampler = _PeakRss(config["measurement"]["peak_rss_poll_seconds"])
    rss_before = rss_sampler._rss()
    loaded: dict[str, Any] | None = None
    if args.cache_state == "generation_warm":
        loaded = _load_case(
            index_root=args.work_index_root,
            repo_id=corpus["source_repo_id"],
            query_text=query["query"],
            query_vector=query_record["vector"],
            semantic_only=query["semantic_only"],
            semantic_weight=query["semantic_weight"],
        )
        for _ in range(config["measurement"]["warmups"]):
            execute_mode(
                matrix=loaded["matrix"],
                query=loaded["query_vector"],
                symbol_ids=loaded["symbol_ids"],
                lexical_base=loaded["lexical_base"],
                semantic_weight=query["semantic_weight"],
                top_k=query["top_k"],
                mode=args.mode,
                max_rescore_fraction=config["measurement"]["max_rescore_fraction"],
            )

    cpu_start = time.process_time_ns()
    wall_start = time.perf_counter_ns()
    with rss_sampler:
        if loaded is None:
            loaded = _load_case(
                index_root=args.work_index_root,
                repo_id=corpus["source_repo_id"],
                query_text=query["query"],
                query_vector=query_record["vector"],
                semantic_only=query["semantic_only"],
                semantic_weight=query["semantic_weight"],
            )
        scoring_start = time.perf_counter_ns()
        timed = execute_mode(
            matrix=loaded["matrix"],
            query=loaded["query_vector"],
            symbol_ids=loaded["symbol_ids"],
            lexical_base=loaded["lexical_base"],
            semantic_weight=query["semantic_weight"],
            top_k=query["top_k"],
            mode=args.mode,
            max_rescore_fraction=config["measurement"]["max_rescore_fraction"],
        )
        scoring_ns = time.perf_counter_ns() - scoring_start
    wall_ns = time.perf_counter_ns() - wall_start
    process_cpu_ns = time.process_time_ns() - cpu_start
    rss_after = rss_sampler._rss()

    classified = score_case(
        matrix=loaded["matrix"],
        query=loaded["query_vector"],
        symbol_ids=loaded["symbol_ids"],
        lexical_base=loaded["lexical_base"],
        semantic_weight=query["semantic_weight"],
        top_k=query["top_k"],
        mode=args.mode,
        max_rescore_fraction=config["measurement"]["max_rescore_fraction"],
    )
    if timed["top"] != [
        loaded["symbol_ids"].index(symbol_id)
        for symbol_id in classified["diagnostic"]["selected_top_ids"]
    ]:
        raise RuntimeError("timed and independently classified results differ")

    corpus_prep = preparation["corpora"][args.corpus]
    denominator = classified["candidate_count"]
    fraction_values = fractions(classified, denominator)
    import numpy as np

    try:
        import psutil

        total_memory = int(psutil.virtual_memory().total)
    except Exception:
        total_memory = 0
    index = loaded["index"]
    payload = {
        **classified,
        **fraction_values,
        "wall_ns": wall_ns,
        "scoring_ns": scoring_ns,
        "process_cpu_ns": process_cpu_ns,
        "rss_before_bytes": rss_before,
        "rss_after_bytes": rss_after,
        "peak_rss_bytes": rss_sampler.peak,
        "corpus_commit": getattr(index, "git_head", "") or "",
        "index_generation": getattr(index, "indexed_at", "") or "",
        "baseline_identity": baseline_identity,
        "candidate_identity": candidate_identity,
        "baseline_import_root": str((args.baseline_root / "src").resolve()),
        "candidate_import_root": str(root_info["imported"]),
        "source_database_sha256": corpus_prep["source_database_sha256"],
        "working_database_sha256": corpus_prep["working_database_sha256"],
        "embedding_vector_count": corpus_prep["embedding_vector_count"],
        "embedding_generation_identity": corpus_prep["embedding_generation_identity"],
        "query_embedding_sha256": query_record["sha256"],
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "sqlite_version": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "cpu_identity": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
        "total_memory_bytes": total_memory,
    }
    _emit(payload)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--config", type=Path, required=True)
    prepare.add_argument("--baseline-root", type=Path, required=True)
    prepare.add_argument("--source-index-root", type=Path, required=True)
    prepare.add_argument("--work-index-root", type=Path, required=True)
    prepare.add_argument("--batch-size", type=int, default=128)

    measure = sub.add_parser("measure")
    measure.add_argument("--config", type=Path, required=True)
    measure.add_argument("--preparation", type=Path, required=True)
    measure.add_argument("--baseline-root", type=Path, required=True)
    measure.add_argument("--candidate-root", type=Path, required=True)
    measure.add_argument("--work-index-root", type=Path, required=True)
    measure.add_argument("--corpus", required=True)
    measure.add_argument("--query-id", required=True)
    measure.add_argument("--mode", required=True)
    measure.add_argument("--cache-state", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "prepare":
        return _prepare(args)
    return _measure(args)


if __name__ == "__main__":
    raise SystemExit(main())
