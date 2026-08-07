#!/usr/bin/env python3
"""Replay every frozen provider-text query against one full corpus in ONE shipped lane.

This is the bounded follow-up specified in ../../FOLLOW-UP-5000.md. It is adapted
from ../../adversarial-falsification/harness/real_replay.py, which consumed only
the 33 screen nominations. Every result-determining line is unchanged: the same
row query, the same jcodemunch_mcp.storage.embedding_matrix._build, the same
EmbeddingMatrix.score_all, and the same descending-score ascending-symbol-id
ordering that v1.108.228 ships in retrieval/signal_fusion.py. What changed is the
input set and what is recorded.

The lane is selected by which interpreter runs this file: an environment with
NumPy importable takes the NumPy lane, one without takes the pure-Python lane.

Required environment:

  JCM398_INDEX_ROOT   directory holding the three frozen corpus databases

Optional:

  JCM398_QUERIES      path to provider-text.jsonl; defaults to the copy in this package

Run once per (lane, corpus). Deliberately no default for the index root: the
databases are outside the publication boundary, so a wrong guess would be worse
than an explicit failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE_ROOT = HERE.parents[2]
DEFAULT_QUERIES = (
    PACKAGE_ROOT
    / "evidence/adversarial-falsification/artifacts/queries/provider-text.jsonl"
)
DBS = {
    "django": "local-django-3eb2e228.db",
    "fastapi": "local-fastapi-c1d6b9c4.db",
    "jcodemunch": "local-arc4-research-v1-upstream-6f37f3de.db",
}
# From evidence/adversarial-falsification/artifacts/provenance.json, corpora.*.sha256.
DB_SHA = {
    "django": "21767e35f79cf051c346389c90562126317fff9871ee9c7e4b33280fe3740529",
    "fastapi": "fb0f933f2fff75684a26872b86bc8f7b7301b7d08c54a079630c05ede760e61e",
    "jcodemunch": "9b6a007e9554a7afdb98936180d0abebce8b86693d842841122c72e9093cdc58",
}
PINNED_VERSION = "1.108.228"


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def index_root() -> Path:
    raw = os.environ.get("JCM398_INDEX_ROOT")
    if not raw:
        raise SystemExit(
            "JCM398_INDEX_ROOT is not set. Point it at the directory holding "
            + ", ".join(sorted(DBS.values()))
            + ". Those databases are outside this package; their SHA-256 digests are "
            "recorded in evidence/adversarial-falsification/artifacts/provenance.json "
            "and are checked before any query runs."
        )
    root = Path(raw)
    if not root.is_dir():
        raise SystemExit(f"JCM398_INDEX_ROOT is not a directory: {root}")
    return root


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lane", required=True, choices=("numpy", "python"))
    parser.add_argument("--corpus", required=True, choices=tuple(DBS))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="debug only; truncates the suite")
    args = parser.parse_args()

    try:
        import numpy

        numpy_version = numpy.__version__
    except ImportError:
        numpy_version = None
    if (args.lane == "numpy") != (numpy_version is not None):
        raise SystemExit(
            f"lane mismatch: --lane={args.lane} but numpy is "
            + ("present" if numpy_version else "absent")
        )

    import jcodemunch_mcp
    from jcodemunch_mcp.storage import embedding_matrix as em

    installed = getattr(jcodemunch_mcp, "__version__", None)
    if installed != PINNED_VERSION:
        raise SystemExit(f"expected jcodemunch-mcp {PINNED_VERSION}, found {installed}")

    database = index_root() / DBS[args.corpus]
    if not database.is_file():
        raise SystemExit(f"corpus database not found: {database}")
    observed_sha = sha256_file(database)
    if observed_sha != DB_SHA[args.corpus]:
        raise SystemExit(
            f"corpus hash mismatch for {args.corpus}: {observed_sha} != {DB_SHA[args.corpus]}"
        )

    queries_path = Path(os.environ.get("JCM398_QUERIES", DEFAULT_QUERIES))
    if not queries_path.is_file():
        raise SystemExit(f"query file not found: {queries_path}")
    queries = []
    with queries_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["corpus_seed"] == args.corpus:
                queries.append(row)
    if not queries:
        raise SystemExit(f"no queries for corpus {args.corpus} in {queries_path}")
    if args.limit:
        queries = queries[: args.limit]

    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        raw = connection.execute(
            "SELECT symbol_id, embedding FROM symbol_embeddings ORDER BY symbol_id"
        ).fetchall()
    build_started = time.perf_counter()
    matrix = em._build(raw)
    build_seconds = time.perf_counter() - build_started
    if matrix is None:
        raise SystemExit("matrix build returned None")
    if matrix.vectorised != (args.lane == "numpy"):
        raise SystemExit(
            f"matrix selection mismatch: vectorised={matrix.vectorised} in lane {args.lane}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    written = 0
    with args.output.open("w", encoding="utf-8", newline="\n") as out:
        out.write(
            canonical(
                {
                    "schema": "jcm398.full-replay-header/v1",
                    "lane": args.lane,
                    "corpus": args.corpus,
                    "corpus_sha256": observed_sha,
                    "candidate_count": len(matrix),
                    "dim": matrix.dim,
                    "skipped_dim_mismatch": matrix.skipped_dim_mismatch,
                    "vectorised": matrix.vectorised,
                    "numpy_version": numpy_version,
                    "python_version": sys.version.split()[0],
                    "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
                    "jcodemunch_version": installed,
                    "queries": len(queries),
                    "build_seconds": round(build_seconds, 3),
                }
            )
            + "\n"
        )
        for item in queries:
            scores = matrix.score_all(item["vector"])
            if len(scores) != len(matrix):
                raise SystemExit(
                    f"score_all returned {len(scores)} scores for {len(matrix)} candidates "
                    f"on {item['query_id']}"
                )
            ordered = sorted(scores, key=lambda symbol_id: (-scores[symbol_id], symbol_id))
            digest = hashlib.sha256()
            for symbol_id in ordered:
                digest.update(symbol_id.encode("utf-8"))
                digest.update(b"\n")
            out.write(
                canonical(
                    {
                        "query_id": item["query_id"],
                        "vector_sha256": item["vector_sha256"],
                        "ordered_top_100": ordered[:100],
                        "score_hex": {sid: scores[sid].hex() for sid in ordered[:100]},
                        "full_ordering_sha256": digest.hexdigest(),
                    }
                )
                + "\n"
            )
            written += 1
            if written % 50 == 0:
                elapsed = time.perf_counter() - started
                remaining = elapsed / written * (len(queries) - written)
                print(
                    f"{args.lane}/{args.corpus} {written}/{len(queries)} "
                    f"{elapsed:.1f}s eta {remaining:.0f}s",
                    flush=True,
                )
    print(
        canonical(
            {
                "lane": args.lane,
                "corpus": args.corpus,
                "replayed": written,
                "seconds": round(time.perf_counter() - started, 1),
                "output_sha256": sha256_file(args.output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
