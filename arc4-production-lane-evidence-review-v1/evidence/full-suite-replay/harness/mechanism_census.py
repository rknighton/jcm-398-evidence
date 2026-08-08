#!/usr/bin/env python3
"""Attested census of the stored-vector mechanism behind the observed disagreements.

READ THIS BEFORE CITING ITS OUTPUT.

Its output, ../mechanism-census.json, is **attested, not gated**. It is derived
from the three frozen corpus databases, which are deliberately outside the
publication boundary, so a third party cannot recompute it from the shipped
bytes. `verify_package.py` therefore does not check its numbers, and neither
`REPORT.md` nor the issue-comment draft rests any decision-facing claim on them.

What IS derivable from the shipped bytes, and is gated, is the score-relationship
classification in compare_lanes.py: whether the first swapped pair was tied in
one lane and separated in the other. This file answers the different question of
whether those pairs also hold identical stored embeddings, which requires the
databases.

It also states the scope limit that the classification itself carries: it
examines the FIRST differing pair in each disagreeing query. 83 of the 114
disagreements change more than two top-100 positions, so a first-pair result
does not characterise the whole permutation, and this census does not claim to.

Environment: JCM398_INDEX_ROOT, as for full_replay.py.
"""

from __future__ import annotations

import collections
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from full_replay import DBS, DB_SHA, index_root, sha256_file  # noqa: E402

REPLAY_ROOT = HERE.parent
RAW = REPLAY_ROOT / "raw"


def main() -> int:
    disagreements = [
        json.loads(line)
        for line in (RAW / "disagreements.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    blobs: dict[str, dict[str, bytes]] = {}
    corpus_sha: dict[str, str] = {}
    for corpus, name in DBS.items():
        database = index_root() / name
        observed = sha256_file(database)
        if observed != DB_SHA[corpus]:
            raise SystemExit(f"corpus hash mismatch for {corpus}: {observed}")
        corpus_sha[corpus] = observed
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        blobs[corpus] = dict(
            connection.execute("SELECT symbol_id, embedding FROM symbol_embeddings")
        )
        connection.close()

    first_pair = collections.Counter()
    per_query = []
    for row in disagreements:
        first = row["first_changed_position_one_based"] - 1
        a = row["numpy_ordered_top_100"][first]
        b = row["python_ordered_top_100"][first]
        store = blobs[row["corpus"]]
        identical = store[a] == store[b]
        first_pair[(row["first_swap_classification"], identical)] += 1
        per_query.append(
            {
                "query_id": row["query_id"],
                "corpus": row["corpus"],
                "first_changed_position_one_based": row["first_changed_position_one_based"],
                "positions_changed_in_top_100": row["positions_changed_in_top_100"],
                "first_swap_classification": row["first_swap_classification"],
                "first_pair_shares_stored_vector": identical,
                "first_pair_stored_vector_sha256": [
                    hashlib.sha256(store[a]).hexdigest(),
                    hashlib.sha256(store[b]).hexdigest(),
                ],
            }
        )

    groups = 0
    split_numpy = 0
    split_python = 0
    partial = 0
    lanes: dict[tuple[str, str], dict] = {}
    for corpus in DBS:
        for lane in ("numpy", "python"):
            rows = {}
            with (RAW / f"{lane}-{corpus}.jsonl").open(encoding="utf-8") as stream:
                stream.readline()
                for line in stream:
                    record = json.loads(line)
                    rows[record["query_id"]] = record["score_hex"]
            lanes[(lane, corpus)] = rows
    for corpus in DBS:
        store = blobs[corpus]
        numpy_rows = lanes[("numpy", corpus)]
        python_rows = lanes[("python", corpus)]
        for query_id, numpy_scores in numpy_rows.items():
            python_scores = python_rows[query_id]
            by_blob: dict[bytes, list[str]] = collections.defaultdict(list)
            for symbol_id in numpy_scores:
                by_blob[store[symbol_id]].append(symbol_id)
            for members in by_blob.values():
                if len(members) < 2:
                    continue
                groups += 1
                if len({numpy_scores[s] for s in members}) > 1:
                    split_numpy += 1
                seen = [python_scores.get(s) for s in members]
                if None in seen:
                    partial += 1
                elif len(set(seen)) > 1:
                    split_python += 1

    census = {
        "schema": "jcm398.mechanism-census/v1",
        "status": "attested_not_gated",
        "derivation_note": (
            "Derived from the three frozen corpus databases, which are outside the publication "
            "boundary. It cannot be recomputed from the shipped bytes and verify_package.py does "
            "not check it. Reproduce with JCM398_INDEX_ROOT set. No decision-facing claim in "
            "REPORT.md or the issue-comment draft rests on these numbers."
        ),
        "scope_limit": (
            "The per-query entries classify the FIRST differing pair only. 83 of the 114 "
            "disagreements change more than two top-100 positions, so this does not characterise "
            "the whole permutation, and no claim here should be read as doing so."
        ),
        "corpus_sha256": corpus_sha,
        "disagreeing_queries": len(disagreements),
        "first_pair_by_classification_and_stored_vector_identity": {
            f"{label}|identical_stored_vector={identical}": count
            for (label, identical), count in sorted(first_pair.items())
        },
        "duplicate_stored_vector_groups_in_a_numpy_top_100": groups,
        "groups_split_by_numpy_lane": split_numpy,
        "groups_split_by_python_lane": split_python,
        "groups_not_fully_visible_in_the_python_top_100": partial,
        "per_query": per_query,
    }
    out = REPLAY_ROOT / "mechanism-census.json"
    out.write_text(json.dumps(census, indent=2, sort_keys=False) + "\n", encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {k: v for k, v in census.items() if k not in {"per_query", "derivation_note", "scope_limit"}},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
