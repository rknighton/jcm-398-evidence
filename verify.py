#!/usr/bin/env python3
"""Recompute every figure quoted in jgravelle/jcodemunch-mcp#398 from the shipped CSVs.

No arguments, no dependencies beyond the standard library, no checkout required.
Reads only the CSVs in this bundle and prints what it derives next to what the
issue claimed, so any disagreement is visible rather than argued.

    python verify.py

Exit code is 0 when every check reproduces, 1 otherwise.
"""
from __future__ import annotations

import collections
import csv
import pathlib
import statistics
import sys

RUNS = pathlib.Path(__file__).resolve().parent / "supporting-data" / "source-runs"
PINNED_SHA = "c2201a55b6e1b0ea38043c514ab7bc3a372bad13"

results: list[tuple[bool, str, str, str]] = []


def check(ok: bool, name: str, claimed: str, found: str) -> None:
    results.append((ok, name, claimed, found))


def rows(name: str) -> list[dict]:
    with (RUNS / name).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def close(a: float, b: float, tol: float = 0.01) -> bool:
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-9)


# ---------------------------------------------------------------- provenance
# One Arc 1 file predates the pin. It is an exploratory architecture probe that
# backs no figure quoted in #398, and it is kept rather than dropped so the
# bundle is not curated to look tidier than the research was.
PRE_PIN = {"generation_boundary_architecture_probe_v1.csv": "6996cc08"}


def provenance() -> None:
    bad = []
    for f in sorted(RUNS.glob("*.csv")):
        shas = {r.get("jcodemunch_source_sha", "") for r in rows(f.name)}
        shas.discard("")
        if not shas:
            continue
        expected = {PRE_PIN[f.name]} if f.name in PRE_PIN else {PINNED_SHA}
        if {s[:8] for s in shas} != {e[:8] for e in expected}:
            bad.append(f"{f.name}: {sorted(s[:8] for s in shas)}")
    check(
        not bad,
        "CSV provenance matches declaration",
        f"{len(list(RUNS.glob('*.csv'))) - len(PRE_PIN)} at c2201a55, {len(PRE_PIN)} declared pre-pin",
        "as declared" if not bad else "; ".join(bad),
    )


# ------------------------------------------------------- Arcs 1-3 headline
def headline() -> None:
    r = rows("generation_safe_hybrid_combined_validation_v3.csv")
    base = {x["tool"]: float(x["wall_ms"]) for x in r if x["mode"] == "baseline_full"}
    cand = {x["tool"]: float(x["wall_ms"]) for x in r if x["mode"] == "generation_safe_hybrid"}
    tb, tc = sum(base.values()), sum(cand.values())
    ratio, saved = tb / tc, 100 * (tb - tc) / tb
    ratios = sorted(base[t] / cand[t] for t in base)
    med = statistics.median(ratios)
    deltas = sorted(((base[t] - cand[t]), t) for t in base)[::-1]
    top1 = 100 * deltas[0][0] / (tb - tc)
    top3 = 100 * sum(d[0] for d in deltas[:3]) / (tb - tc)
    slower = sum(1 for x in ratios if x < 1.0)

    check(len(base) == 38, "38 Django tool cases", "38", str(len(base)))
    check(close(ratio, 3.22), "aggregate throughput", "3.22x", f"{ratio:.4f}x")
    check(close(saved, 68.96), "total wall time saved", "68.96%", f"{saved:.2f}%")
    check(close(med, 1.23, 0.02), "median case ratio", "1.23x", f"{med:.3f}x")
    check(close(top1, 43.1, 0.02), "top tool share of savings", "43.1%", f"{top1:.1f}%")
    check(close(top3, 91.9, 0.02), "top 3 tools share", "91.9%", f"{top3:.1f}%")
    check(slower == 0, "cases slower than baseline", "0", str(slower))

    hashes = collections.defaultdict(set)
    for x in r:
        hashes[x["tool"]].add(x["canonical_response_hash"])
    mism = [t for t, h in hashes.items() if len(h) != 1]
    check(not mism, "canonical response parity", "38 of 38 match", f"{38 - len(mism)} of 38 match")


# ------------------------------------------------------ four-repo control
def control() -> None:
    r = rows("generation_safe_hybrid_e2e_deep_v3.csv")
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for x in r:
        by[(x["repo_name"], x["tool"], x["case"])][x["mode"]].append(float(x["wall_ms"]))

    per_repo = collections.defaultdict(list)
    for (repo, _tool, _case), modes in by.items():
        b, c = sorted(modes["baseline_full"]), sorted(modes["generation_safe_hybrid"])
        if not b or not c:
            continue
        separated = max(b) < min(c) or max(c) < min(b)
        faster = statistics.median(b) > statistics.median(c)
        per_repo[repo.split("-")[0]].append((separated, faster))

    expected = {"express": 3, "gin": 3, "fastapi": 6, "django": 6}
    for repo, want in expected.items():
        cases = per_repo[repo]
        sep_gain = sum(1 for s, f in cases if s and f)
        sep_reg = sum(1 for s, f in cases if s and not f)
        check(len(cases) == 6, f"{repo}: 6 distinct cases", "6", str(len(cases)))
        check(sep_gain == want, f"{repo}: separated gains", str(want), str(sep_gain))
        check(sep_reg == 0, f"{repo}: separated regressions", "0", str(sep_reg))


# ------------------------------------------------------------- Arc 2 split
def arc2() -> None:
    r = rows("generation_safe_hybrid_hydration_trace_screen_v2.csv")
    by = collections.defaultdict(dict)
    for x in r:
        by[(x["repo_name"], x["tool"], x["case"])][x["mode"]] = float(x["wall_ms"])
    per = collections.defaultdict(list)
    for (repo, _t, _c), m in by.items():
        if len(m) == 2:
            per[repo.split("-")[0]].append(m["baseline_full"] / m["generation_safe_hybrid"])
    for repo, claimed in (("django", 5.17), ("fastapi", 2.59)):
        med = statistics.median(per[repo])
        check(close(med, claimed, 0.01), f"Arc 2 {repo} median", f"{claimed}x", f"{med:.3f}x")
    # The claim is specifically: cases that are Express/Gin AND sub-50ms baseline.
    total = sum(1 for m in by.values() if len(m) == 2)
    unresolvable = sum(
        1
        for (repo, _t, _c), m in by.items()
        if len(m) == 2 and repo.split("-")[0] in ("express", "gin") and m["baseline_full"] < 50
    )
    pct = 100 * unresolvable / total
    check(close(pct, 40.3, 0.02), "small-repo sub-50ms share", "~40%", f"{pct:.1f}%")
    stray = sum(
        1
        for (repo, _t, _c), m in by.items()
        if len(m) == 2 and repo.split("-")[0] not in ("express", "gin") and m["baseline_full"] < 50
    )
    check(stray == 0, "sub-50ms cases outside small repos", "0", str(stray))


# ------------------------------------------------------------ file integrity
def integrity() -> None:
    """Every CSV must still hash to what INDEX.json recorded.

    This catches the case where a checkout translated line endings, which would
    silently invalidate every hash in INDEX.json and in the manifests.
    """
    import hashlib
    import json

    index = pathlib.Path(__file__).resolve().parent / "INDEX.json"
    if not index.exists():
        check(False, "INDEX.json present", "present", "missing")
        return
    declared = json.loads(index.read_text(encoding="utf-8"))["data_files"]
    bad = []
    for entry in declared:
        p = pathlib.Path(__file__).resolve().parent / entry["file"]
        if not p.exists():
            bad.append(f"{p.name}: missing")
        elif hashlib.sha256(p.read_bytes()).hexdigest() != entry["sha256"]:
            bad.append(f"{p.name}: hash differs")
    check(
        not bad,
        "CSV bytes match INDEX.json hashes",
        f"{len(declared)} of {len(declared)}",
        f"{len(declared) - len(bad)} of {len(declared)}" + (f" ({bad[0]})" if bad else ""),
    )


def main() -> int:
    integrity()
    provenance()
    headline()
    control()
    arc2()

    width = max(len(n) for _o, n, _c, _f in results)
    print(f"{'CHECK'.ljust(width)}  {'CLAIMED':>16}  {'RECOMPUTED':>16}   ")
    print("-" * (width + 40))
    for ok, name, claimed, found in results:
        print(f"{name.ljust(width)}  {claimed:>16}  {found:>16}   {'ok' if ok else 'MISMATCH'}")
    failed = [r for r in results if not r[0]]
    print("-" * (width + 40))
    print(f"{len(results) - len(failed)} of {len(results)} checks reproduce.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
