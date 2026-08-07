#!/usr/bin/env python3
"""Capture full-depth scores for a named set of queries, so no swap goes unclassified.

compare_lanes.py classifies each disagreement's first swap from the two lanes'
top-100 score tables. For 29 of the 114 disagreements the swapped-in symbol sits
outside the other lane's top 100, so those tables cannot answer the question.
Rather than record those cases as unknown, this captures every score for exactly
those queries. Same environment contract as full_replay.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from full_replay import DBS, DB_SHA, PINNED_VERSION, index_root, sha256_file  # noqa: E402

PACKAGE_ROOT = HERE.parents[2]
DEFAULT_QUERIES = (
    PACKAGE_ROOT
    / "evidence/adversarial-falsification/artifacts/queries/provider-text.jsonl"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lane", required=True, choices=("numpy", "python"))
    parser.add_argument("--corpus", required=True, choices=tuple(DBS))
    parser.add_argument("--ids", required=True, help="comma-separated query ids")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        import numpy

        numpy_version = numpy.__version__
    except ImportError:
        numpy_version = None
    if (args.lane == "numpy") != (numpy_version is not None):
        raise SystemExit(f"lane mismatch: --lane={args.lane}")

    import jcodemunch_mcp
    from jcodemunch_mcp.storage import embedding_matrix as em

    installed = getattr(jcodemunch_mcp, "__version__", None)
    if installed != PINNED_VERSION:
        raise SystemExit(f"expected jcodemunch-mcp {PINNED_VERSION}, found {installed}")

    database = index_root() / DBS[args.corpus]
    observed = sha256_file(database)
    if observed != DB_SHA[args.corpus]:
        raise SystemExit(f"corpus hash mismatch for {args.corpus}: {observed}")

    wanted = {value for value in args.ids.split(",") if value}
    queries_path = Path(os.environ.get("JCM398_QUERIES", DEFAULT_QUERIES))
    selected = []
    with queries_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["query_id"] in wanted and row["corpus_seed"] == args.corpus:
                selected.append(row)
    if not selected:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("", encoding="utf-8", newline="\n")
        print(json.dumps({"corpus": args.corpus, "lane": args.lane, "queries": 0}))
        return 0

    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
        raw = connection.execute(
            "SELECT symbol_id, embedding FROM symbol_embeddings ORDER BY symbol_id"
        ).fetchall()
    matrix = em._build(raw)
    if matrix.vectorised != (args.lane == "numpy"):
        raise SystemExit("matrix selection mismatch")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as out:
        for item in selected:
            scores = matrix.score_all(item["vector"])
            out.write(
                json.dumps(
                    {
                        "query_id": item["query_id"],
                        "corpus": args.corpus,
                        "lane": args.lane,
                        "scores_hex": {k: v.hex() for k, v in scores.items()},
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
    print(json.dumps({"corpus": args.corpus, "lane": args.lane, "queries": len(selected)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
