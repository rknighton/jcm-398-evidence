"""One fresh-process production trial or scorer control."""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
from pathlib import Path

from common import SCHEMA, canonical, sha256_file, write_json


def environment() -> dict:
    try:
        import numpy
        numpy_version = numpy.__version__
    except ImportError:
        numpy_version = None
    freeze = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"], check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
    ).stdout.splitlines()
    return {
        "python_version": platform.python_version(), "python_executable": sys.executable,
        "numpy_version": numpy_version, "sqlite_version": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "cpu_identity": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
        "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
        "pip_freeze": sorted(freeze),
        "pip_freeze_sha256": hashlib.sha256(("\n".join(sorted(freeze)) + "\n").encode()).hexdigest(),
    }


def run_control(args: argparse.Namespace) -> int:
    from jcodemunch_mcp.storage import embedding_matrix as em
    vectors = args.control.read_bytes()
    fixture = json.loads(vectors)
    raw = []
    for row in fixture["vectors"]:
        raw.append((row["id"], array.array("f", row["vector"]).tobytes()))
    matrix = em._build(raw)
    if matrix is None:
        raise RuntimeError("control matrix did not build")
    scores = matrix.score_all(fixture["query"])
    ordered = sorted(scores, key=lambda sid: (-scores[sid], sid))[: fixture["top_k"]]
    print(canonical({"lane": args.lane, "vectorised": matrix.vectorised, "ordered": ordered,
                     "scores": {sid: score.hex() for sid, score in scores.items()}, "environment": environment()}))
    return 0


def adapter(index, matrix, query: dict) -> dict:
    from jcodemunch_mcp.retrieval.signal_fusion import _bm25_score_no_identity
    from jcodemunch_mcp.tools.search_symbols import _compute_bm25, _compute_centrality, _identity_score, _tokenize
    cosines = matrix.score_all(query["vector"])
    if query["semantic_only"]:
        raw = [(sym, 0.0, 0.0, cosines.get(sym["id"], 0.0)) for sym in index.symbols]
        max_lex = max_id = 0.0
    else:
        terms = _tokenize(query["text"])
        idf, avgdl, _ = _compute_bm25(index.symbols)
        centrality = _compute_centrality(index.symbols, index.imports, index.alias_map, getattr(index, "psr4_map", None))
        joined = " ".join(terms)
        raw = [(sym, _bm25_score_no_identity(sym, terms, idf, avgdl, centrality),
                _identity_score(sym, joined, raw_query=query["text"]), cosines.get(sym["id"], 0.0))
               for sym in index.symbols]
        max_lex = max((row[1] for row in raw), default=0.0)
        max_id = max((row[2] for row in raw), default=0.0)
    scores = []
    for sym, lex, identity, cosine in raw:
        lexical = max(lex / max_lex if max_lex > 0 else 0.0, identity / max_id if max_id > 0 else 0.0)
        final = cosine if query["semantic_only"] else (1.0 - query["semantic_weight"]) * lexical + query["semantic_weight"] * cosine
        scores.append({"id": sym["id"], "cosine_hex": cosine.hex(), "final_hex": final.hex()})
    ranked = sorted((row for row in scores if float.fromhex(row["final_hex"]) > 0.0),
                    key=lambda row: (-float.fromhex(row["final_hex"]), row["id"]))
    return {"scores": scores, "ranked_scores": ranked,
            "ordered_positive_ids": [row["id"] for row in ranked]}


def run_trial(args: argparse.Namespace) -> int:
    config = json.loads(args.config.read_text(encoding="utf-8"))
    case = next(item for item in config["cases"] if item["paired_case_id"] == args.case)
    corpus = config["corpora"][case["corpus"]]
    query = config["queries"][case["query_id"]]
    env = environment()
    if args.lane == "numpy" and env["numpy_version"] != config["environments"]["numpy_version"]:
        raise RuntimeError(f"NumPy lane mismatch: {env['numpy_version']}")
    if args.lane == "python" and env["numpy_version"] is not None:
        raise RuntimeError(f"NumPy unexpectedly importable: {env['numpy_version']}")

    from jcodemunch_mcp.storage import IndexStore
    from jcodemunch_mcp.storage import embedding_matrix as em
    from jcodemunch_mcp.tools import embed_repo as embed_module
    from jcodemunch_mcp.tools.search_symbols import search_symbols
    owner, name = corpus["source_repo_id"].split("/", 1)
    store = IndexStore(base_path=args.scratch)
    index = store.load_index(owner, name)
    if index is None:
        raise RuntimeError("production index load failed")
    db_path = store._sqlite._db_path(owner, name)
    matrix = em.get_matrix(db_path)
    if matrix is None:
        raise RuntimeError("production matrix load failed")
    missing = [sym["id"] for sym in index.symbols if sym["id"] not in matrix.id_set]
    if missing:
        raise RuntimeError(f"missing embeddings: {len(missing)} first={missing[:3]}")
    expected_vectorised = args.lane == "numpy"
    if matrix.vectorised is not expected_vectorised:
        raise RuntimeError(f"selected lane mismatch: vectorised={matrix.vectorised}")

    embed_module._detect_provider = lambda: (config["embedding"]["provider"], config["embedding"]["model"])
    embed_module.embed_texts = lambda texts, provider, model, task_type=None: [query["vector"] for _ in texts]
    response = search_symbols(
        repo=corpus["source_repo_id"], query=query["text"], max_results=query["top_k"],
        detail_level="compact", semantic=True, semantic_only=query["semantic_only"],
        semantic_weight=query["semantic_weight"], storage_path=str(args.scratch),
    )
    if response.get("error"):
        raise RuntimeError(f"production tool failed: {response['error']}")
    tool_ids = [row["id"] for row in response["results"]]
    evidence = adapter(index, matrix, query)
    adapter_ids = evidence["ordered_positive_ids"][: query["top_k"]]
    if tool_ids != adapter_ids:
        raise RuntimeError(f"tool/adapter mismatch: {tool_ids} != {adapter_ids}")
    evidence_bytes = (canonical(evidence) + "\n").encode()
    evidence_hash = hashlib.sha256(evidence_bytes).hexdigest()
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        if args.evidence.exists():
            raise FileExistsError(args.evidence)
        args.evidence.write_bytes(evidence_bytes)
    record = {
        "schema_version": SCHEMA, "run_id": config["run_id"], "trial_id": args.trial_id,
        "paired_case_id": case["paired_case_id"], "repetition": args.repetition,
        "execution_order": args.execution_order, "corpus": case["corpus"], "role": corpus["role"],
        "source_commit": corpus["source_commit"], "database_name": corpus["database_name"],
        "database_sha256": corpus["database_sha256"], "vector_count": corpus["vector_count"],
        "embedding_identity": corpus["embedding_identity"], "query_id": case["query_id"],
        "query_text": query["text"], "query_vector_sha256": query["vector_sha256"],
        "semantic_only": query["semantic_only"], "semantic_weight": query["semantic_weight"],
        "top_k": query["top_k"], "tag": config["production"]["tag"],
        "source_commit_jcodemunch": config["production"]["commit"],
        "wheel_sha256": config["production"]["wheel_sha256"], "source_clean": True,
        "production_functions": config["production"]["functions"], "lane_requested": args.lane,
        "lane_selected": "numpy" if matrix.vectorised else "python", "environment": env,
        "tool_ordered_top_k_ids": tool_ids, "adapter_ordered_top_k_ids": adapter_ids,
        "adapter_parity": True, "score_evidence_path": str(args.evidence.relative_to(args.packet)) if args.evidence else None,
        "score_evidence_sha256": evidence_hash, "terminal_status": "completed", "failure_reason": None,
    }
    write_json(args.output, record)
    print(canonical(record))
    return 0


def parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    control = sub.add_parser("control")
    control.add_argument("--lane", choices=("numpy", "python"), required=True)
    control.add_argument("--control", type=Path, required=True)
    trial = sub.add_parser("trial")
    for name in ("config", "scratch", "packet", "output"):
        trial.add_argument(f"--{name}", type=Path, required=True)
    trial.add_argument("--evidence", type=Path)
    trial.add_argument("--case", required=True); trial.add_argument("--lane", required=True)
    trial.add_argument("--trial-id", required=True); trial.add_argument("--repetition", type=int, required=True)
    trial.add_argument("--execution-order", type=int, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse()
    raise SystemExit(run_control(arguments) if arguments.command == "control" else run_trial(arguments))
