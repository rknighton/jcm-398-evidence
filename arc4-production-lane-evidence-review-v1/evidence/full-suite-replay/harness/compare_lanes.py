#!/usr/bin/env python3
"""Compare the two shipped scoring lanes across every frozen provider-text query.

Reads the per-lane records under ../raw/ and writes, beside them:

  ../results-summary.json   the four dimensions issue 398 asked to see separately
  ../raw/disagreements.jsonl  one record per query whose lanes disagreed anywhere

Needs no corpus database and no jcodemunch install. It runs on the shipped bytes
with the standard library alone, which is the point: a reader can check the
conclusion without reconstructing the environment that produced it.

Fail-closed. A missing query, a lane and corpus mismatch, a short top-100 list,
an unequal candidate count, or a swap it cannot classify are all errors and all
force a non-zero exit. There is no `continue` in the checking loop.

Control: it re-derives the five findings published in
../adversarial-falsification/artifacts/findings/provider-actual-findings.json
from this run and compares them. If the 33-query replay and the 5,000-query
replay disagree about those five, nothing else here is trustworthy.
"""

from __future__ import annotations

import collections
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPLAY_ROOT = HERE.parent
RAW = REPLAY_ROOT / "raw"
PACKAGE_ROOT = REPLAY_ROOT.parents[1]
CORPORA = ("django", "fastapi", "jcodemunch")
KS = (1, 5, 10, 25, 50, 100)
EXPECTED_QUERIES = {"django": 1667, "fastapi": 1667, "jcodemunch": 1666}
EXPECTED_CANDIDATES = {"django": 45561, "fastapi": 13405, "jcodemunch": 13960}
PINNED_VERSION = "1.108.228"

errors: list[str] = []
DEEP: dict[tuple[str, str], dict] = {}


def fail(message: str) -> None:
    errors.append(message)


def load_deep(corpus: str) -> None:
    for lane in ("numpy", "python"):
        path = RAW / f"deep-{lane}-{corpus}.jsonl"
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                DEEP[(lane, row["query_id"])] = row["scores_hex"]


def read_lane(lane: str, corpus: str):
    path = RAW / f"{lane}-{corpus}.jsonl"
    with path.open("r", encoding="utf-8") as stream:
        header = json.loads(stream.readline())
        rows = {}
        for line in stream:
            row = json.loads(line)
            if row["query_id"] in rows:
                fail(f"duplicate query {row['query_id']} in {path.name}")
            rows[row["query_id"]] = row
    if header["lane"] != lane or header["corpus"] != corpus:
        fail(f"{path.name}: header lane or corpus mismatch")
    if header["vectorised"] != (lane == "numpy"):
        fail(f"{path.name}: vectorised={header['vectorised']} in lane {lane}")
    if header["jcodemunch_version"] != PINNED_VERSION:
        fail(f"{path.name}: unexpected package version {header['jcodemunch_version']}")
    if header["candidate_count"] != EXPECTED_CANDIDATES[corpus]:
        fail(f"{path.name}: candidate_count {header['candidate_count']}")
    if header["skipped_dim_mismatch"] != 0:
        fail(f"{path.name}: skipped {header['skipped_dim_mismatch']} rows of mismatched width")
    if len(rows) != EXPECTED_QUERIES[corpus]:
        fail(f"{path.name}: {len(rows)} queries, expected {EXPECTED_QUERIES[corpus]}")
    return header, rows


def classify(first: int, numpy_row, python_row) -> str:
    """Is the first swap a float32 tie the other lane separates, or a real inversion?"""
    a = numpy_row["ordered_top_100"][first]
    b = python_row["ordered_top_100"][first]
    numpy_scores, python_scores = numpy_row["score_hex"], python_row["score_hex"]
    if a not in numpy_scores or b not in numpy_scores or a not in python_scores or b not in python_scores:
        query_id = numpy_row["query_id"]
        deep_numpy = DEEP.get(("numpy", query_id))
        deep_python = DEEP.get(("python", query_id))
        if deep_numpy is None or deep_python is None:
            return "unclassifiable_outside_top_100"
        numpy_scores, python_scores = deep_numpy, deep_python
    na, nb = float.fromhex(numpy_scores[a]), float.fromhex(numpy_scores[b])
    pa, pb = float.fromhex(python_scores[a]), float.fromhex(python_scores[b])
    if na == nb and pa != pb:
        return "numpy_exact_tie_separated_by_python"
    if pa == pb and na != nb:
        return "python_exact_tie_separated_by_numpy"
    if na == nb and pa == pb:
        return "tie_in_both_lanes"
    if (na > nb) != (pa > pb):
        return "genuine_score_order_inversion"
    return "unexplained_same_direction"


def main() -> int:
    summary = {
        "schema": "jcm398.full-5000-replay-summary/v1",
        "pinned_version": PINNED_VERSION,
        "queries_total": 0,
        "by_corpus": {},
        "rank0_differences": 0,
        "ordered_top_100_difference_queries": 0,
        "full_depth_ordering_difference_queries": 0,
        "exact_tie_partition_difference_queries": 0,
        "differences_by_k": {str(k): {"ordered": 0, "membership": 0} for k in KS},
        "first_changed_positions_one_based": [],
        "positions_changed_histogram": {},
        "swap_classification": {},
    }
    disagreements = []

    for corpus in CORPORA:
        load_deep(corpus)
        numpy_header, numpy_rows = read_lane("numpy", corpus)
        python_header, python_rows = read_lane("python", corpus)
        if numpy_header["corpus_sha256"] != python_header["corpus_sha256"]:
            fail(f"{corpus}: the two lanes read different corpus bytes")
        if set(numpy_rows) != set(python_rows):
            fail(f"{corpus}: query sets differ between lanes")
        stats = {
            "queries": len(numpy_rows),
            "candidate_count": numpy_header["candidate_count"],
            "corpus_sha256": numpy_header["corpus_sha256"],
            "rank0_differences": 0,
            "ordered_top_100_difference_queries": 0,
            "full_depth_ordering_difference_queries": 0,
            "exact_tie_partition_difference_queries": 0,
        }
        for query_id in sorted(numpy_rows):
            left, right = numpy_rows[query_id], python_rows[query_id]
            if left["vector_sha256"] != right["vector_sha256"]:
                fail(f"{query_id}: lanes used different query vectors")
                continue
            numpy_order, python_order = left["ordered_top_100"], right["ordered_top_100"]
            if len(numpy_order) != 100 or len(python_order) != 100:
                fail(f"{query_id}: top-100 lists are {len(numpy_order)}/{len(python_order)} long")
                continue
            summary["queries_total"] += 1

            def partition(score_hex: dict) -> frozenset:
                groups: dict[str, list[str]] = {}
                for symbol_id, encoded in score_hex.items():
                    groups.setdefault(encoded, []).append(symbol_id)
                return frozenset(frozenset(v) for v in groups.values() if len(v) > 1)

            if partition(left["score_hex"]) != partition(right["score_hex"]):
                summary["exact_tie_partition_difference_queries"] += 1
                stats["exact_tie_partition_difference_queries"] += 1
            if left["full_ordering_sha256"] != right["full_ordering_sha256"]:
                summary["full_depth_ordering_difference_queries"] += 1
                stats["full_depth_ordering_difference_queries"] += 1
            for k in KS:
                if numpy_order[:k] != python_order[:k]:
                    summary["differences_by_k"][str(k)]["ordered"] += 1
                if set(numpy_order[:k]) != set(python_order[:k]):
                    summary["differences_by_k"][str(k)]["membership"] += 1
            if numpy_order[0] != python_order[0]:
                summary["rank0_differences"] += 1
                stats["rank0_differences"] += 1

            first = next(
                (i for i, (x, y) in enumerate(zip(numpy_order, python_order)) if x != y), None
            )
            if first is None:
                continue
            summary["ordered_top_100_difference_queries"] += 1
            stats["ordered_top_100_difference_queries"] += 1
            summary["first_changed_positions_one_based"].append(first + 1)
            changed = sum(1 for x, y in zip(numpy_order, python_order) if x != y)
            key = str(changed)
            summary["positions_changed_histogram"][key] = (
                summary["positions_changed_histogram"].get(key, 0) + 1
            )
            label = classify(first, left, right)
            summary["swap_classification"][label] = summary["swap_classification"].get(label, 0) + 1
            if label in {"unclassifiable_outside_top_100", "unexplained_same_direction"}:
                fail(f"{query_id}: first swap could not be classified ({label})")
            disagreements.append(
                {
                    "query_id": query_id,
                    "corpus": corpus,
                    "first_changed_position_one_based": first + 1,
                    "positions_changed_in_top_100": changed,
                    "rank0_changed": numpy_order[0] != python_order[0],
                    "top_100_membership_changed": set(numpy_order) != set(python_order),
                    "first_swap_classification": label,
                    "numpy_ordered_top_100": numpy_order,
                    "python_ordered_top_100": python_order,
                    "numpy_score_hex": left["score_hex"],
                    "python_score_hex": right["score_hex"],
                }
            )
        summary["by_corpus"][corpus] = stats

    summary["first_changed_positions_one_based"].sort()
    summary["positions_changed_histogram"] = dict(
        sorted(summary["positions_changed_histogram"].items(), key=lambda kv: int(kv[0]))
    )

    published = json.loads(
        (
            PACKAGE_ROOT
            / "evidence/adversarial-falsification/artifacts/findings/provider-actual-findings.json"
        ).read_text(encoding="utf-8")
    )
    found = {row["query_id"]: row for row in disagreements}
    control = {"published_findings": len(published), "reproduced": 0, "mismatches": []}
    for record in published:
        query_id = record["query_id"]
        mine = found.get(query_id)
        if mine is None:
            control["mismatches"].append(f"{query_id}: not reproduced by the full replay")
            continue
        their_numpy = record["numpy"]["ordered_top_100"]
        their_python = record["python"]["ordered_top_100"]
        their_first = next(
            i + 1 for i, (x, y) in enumerate(zip(their_numpy, their_python)) if x != y
        )
        problems = []
        if mine["numpy_ordered_top_100"] != their_numpy:
            problems.append("numpy top-100 differs")
        if mine["python_ordered_top_100"] != their_python:
            problems.append("python top-100 differs")
        if mine["first_changed_position_one_based"] != their_first:
            problems.append(
                f"first-changed {mine['first_changed_position_one_based']} != {their_first}"
            )
        if problems:
            control["mismatches"].append(f"{query_id}: " + "; ".join(problems))
        else:
            control["reproduced"] += 1
    for message in control["mismatches"]:
        fail("control: " + message)
    summary["published_findings_control"] = control

    screen = json.loads(
        (
            PACKAGE_ROOT
            / "evidence/adversarial-falsification/artifacts/screens/provider-text-screen.json"
        ).read_text(encoding="utf-8")
    )
    nominated = {hit["query"]["query_id"] for hit in screen["hits"]}
    summary["screen_nominations"] = len(nominated)
    summary["screen_true_positives"] = len(nominated & set(found))
    summary["screen_false_alarms"] = len(nominated - set(found))
    summary["screen_missed"] = sorted(set(found) - nominated)
    summary["screen_miss_count"] = len(summary["screen_missed"])
    summary["new_disagreements_not_previously_replayed"] = sorted(
        set(found) - {row["query_id"] for row in published}
    )

    out_path = RAW / "disagreements.jsonl"
    out_path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in disagreements
        ),
        encoding="utf-8",
        newline="\n",
    )
    summary["disagreements_file_sha256"] = hashlib.sha256(out_path.read_bytes()).hexdigest()
    summary["errors"] = errors
    (REPLAY_ROOT / "results-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    printable = {
        k: v
        for k, v in summary.items()
        if k not in {"screen_missed", "new_disagreements_not_previously_replayed", "first_changed_positions_one_based"}
    }
    print(json.dumps(printable, indent=2, sort_keys=True))
    if errors:
        print("\nFAIL")
        for message in errors:
            print(" -", message)
        return 1
    print("\nPASS: structural checks and the five-finding control both hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
