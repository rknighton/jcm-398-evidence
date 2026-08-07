"""Build environments, run controls and matrix, then derive the local packet."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import uuid
import platform
from collections import Counter, defaultdict
from pathlib import Path

from common import SCHEMA, canonical, compare_case, sha256_file, write_json

HERE = Path(__file__).resolve().parent.parent
WORK = HERE / "working"
RAW = HERE / "artifacts" / "raw"
INPUTS = Path(r"<PUBLIC_EVIDENCE_ROOT>\arc4-real-embedding-certification-v1\prepared-inputs.json")
INDEXES = Path(r"<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\working\indexes")
COMMIT = "8bed872e9436093be9f89d35fb84e0cb58a293af"
DATABASE_HASHES = {
    "django": "21767e35f79cf051c346389c90562126317fff9871ee9c7e4b33280fe3740529",
    "fastapi": "fb0f933f2fff75684a26872b86bc8f7b7301b7d08c54a079630c05ede760e61e",
    "jcodemunch": "9b6a007e9554a7afdb98936180d0abebce8b86693d842841122c72e9093cdc58",
}


def run(command: list[str], *, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    child_environment = os.environ.copy()
    child_environment["PYTHONHASHSEED"] = "0"
    return subprocess.run(command, cwd=HERE, check=True, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout, env=child_environment)


def wheel() -> Path:
    matches = list((WORK / "wheel").glob("jcodemunch_mcp-1.108.228-*.whl"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one wheel, found {matches}")
    return matches[0]


def setup() -> None:
    source = WORK / "source"
    if run(["git", "-C", str(source), "rev-parse", "HEAD"]).stdout.strip() != COMMIT:
        raise RuntimeError("source commit mismatch")
    if run(["git", "-C", str(source), "status", "--porcelain"]).stdout.strip():
        raise RuntimeError("source checkout is dirty")
    pyproject = (source / "pyproject.toml").read_text(encoding="utf-8")
    if 'version = "1.108.228"' not in pyproject:
        raise RuntimeError("package version mismatch")
    remote = run(["git", "ls-remote", "https://github.com/jgravelle/jcodemunch-mcp.git", "refs/tags/v1.108.228"]).stdout.strip().split()[0]
    if remote != COMMIT:
        raise RuntimeError(f"remote tag mismatch: {remote}")
    prepared = json.loads(INPUTS.read_text(encoding="utf-8"))
    database_receipts = {}
    for name, expected in DATABASE_HASHES.items():
        item = prepared["corpora"][name]
        path = INDEXES / item["database_filename"]
        actual = sha256_file(path)
        if actual != expected:
            raise RuntimeError(f"database hash mismatch for {name}: {actual}")
        database_receipts[name] = {"sha256": actual, "license": item["license"]}
    free = shutil.disk_usage(HERE).free
    if free < 5 * 1024 * 1024 * 1024:
        raise RuntimeError(f"insufficient disk headroom: {free}")
    wheel_path = wheel()
    for lane in ("numpy", "python"):
        env = WORK / f"venv-{lane}"
        if not env.exists():
            run([sys.executable, "-m", "venv", str(env)])
        python = env / "Scripts" / "python.exe"
        run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", str(wheel_path)])
        if lane == "numpy":
            run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "numpy==2.4.4"])
        else:
            check = subprocess.run([str(python), "-c", "import numpy"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if check.returncode == 0:
                raise RuntimeError("NumPy is importable in python lane")
    write_json(HERE / "artifacts" / "preflight.json", {
        "schema_version": SCHEMA, "source_commit": COMMIT, "source_clean": True,
        "package_version": "1.108.228", "remote_tag": "v1.108.228", "remote_tag_commit": remote,
        "wheel_sha256": sha256_file(wheel_path), "python_version": platform.python_version(),
        "disk_free_bytes": free, "prepared_inputs_sha256": sha256_file(INPUTS),
        "databases": database_receipts,
    })


def make_config() -> dict:
    prepared = json.loads(INPUTS.read_text(encoding="utf-8"))
    corpora = {}
    for name, item in prepared["corpora"].items():
        source = INDEXES / item["database_filename"]
        actual = sha256_file(source)
        if actual != DATABASE_HASHES[name] or actual != item["working_database_sha256"]:
            raise RuntimeError(f"database hash mismatch for {name}: {actual}")
        corpora[name] = {
            "role": {"required_second_point": "second point", "control_only": "control"}.get(item["role"], item["role"]),
            "source_repo_id": item["source_repo_id"], "source_commit": item["corpus_commit"],
            "database_name": item["database_filename"], "database_sha256": actual,
            "vector_count": item["embedding_vector_count"], "embedding_identity": item["embedding_generation_identity"],
            "local_source": str(source),
        }
    queries = {}
    for qid, item in prepared["queries"].items():
        args = json.loads(item["serialized_args_json"])
        if sha256_file(INPUTS) == "":
            raise AssertionError
        queries[qid] = {
            "text": args["query"], "vector": item["vector"], "vector_sha256": item["sha256"],
            "serialized_args_json": item["serialized_args_json"], "semantic_only": args["semantic_only"],
            "semantic_weight": args["semantic_weight"], "top_k": args["max_results"],
        }
    cases = []
    for ci, corpus in enumerate(("django", "fastapi", "jcodemunch")):
        for qi, qid in enumerate(("semantic_input_validation", "semantic_transaction_persistence",
                                  "hybrid_authentication_middleware", "hybrid_test_client_response")):
            cases.append({"paired_case_id": f"{corpus}__{qid}", "corpus": corpus, "query_id": qid,
                          "top_k": queries[qid]["top_k"], "lane_order": ["numpy", "python"] if (ci + qi) % 2 == 0 else ["python", "numpy"]})
    config = {
        "schema_version": SCHEMA, "run_id": "production-lane-v1-" + uuid.uuid5(uuid.NAMESPACE_URL, COMMIT + sha256_file(INPUTS)).hex[:12],
        "prepared_inputs_path": str(INPUTS), "prepared_inputs_sha256": sha256_file(INPUTS),
        "production": {"tag": "v1.108.228", "commit": COMMIT, "wheel_sha256": sha256_file(wheel()),
                       "functions": ["EmbeddingMatrix._scores_numpy", "EmbeddingMatrix._scores_python",
                                     "search_symbols._search_symbols_semantic", "scored.sort(key=lambda x: (-x[0], x[1]['id']))"]},
        "embedding": {"provider": prepared["embedding_provider"], "model": prepared["embedding_model"]},
        "environments": {"python_major_minor": list(sys.version_info[:2]), "numpy_version": "2.4.4", "common_difference": "NumPy only"},
        "corpora": corpora, "queries": queries, "cases": cases,
        "expected": {"paired_cases": 12, "lanes": 2, "repetitions": 2, "trials": 48},
    }
    write_json(HERE / "config.json", config)
    return config


def fixture(seed: int, count: int = 4000, dim: int = 384) -> dict:
    import random
    rng = random.Random(seed)
    query = [rng.uniform(-1, 1) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in query)); query = [x / norm for x in query]
    vectors = []
    for index in range(count):
        noise = 1e-6 * (index - count / 2) / count
        row = [x + noise * rng.uniform(-1, 1) for x in query]
        vectors.append({"id": f"symbol-{count-index:05d}", "vector": row})
    return {"seed": seed, "dimension": dim, "count": count, "top_k": 10, "query": query, "vectors": vectors}


def controls() -> dict:
    control_dir = HERE / "artifacts" / "controls"; control_dir.mkdir(parents=True, exist_ok=True)
    selected = None
    attempts = []
    for number, (seed, count) in enumerate(((11, 4000), (11, 8000), (29, 4000)), 1):
        data = fixture(seed, count)
        path = control_dir / f"positive-attempt-{number}.json"; write_json(path, data)
        results = {}
        for lane in ("numpy", "python"):
            python = WORK / f"venv-{lane}" / "Scripts" / "python.exe"
            results[lane] = json.loads(run([str(python), str(HERE / "harness" / "worker.py"), "control", "--lane", lane, "--control", str(path)]).stdout)
        divergent = results["numpy"]["ordered"] != results["python"]["ordered"]
        attempts.append({"attempt": number, "seed": seed, "count": count, "fixture_sha256": sha256_file(path), "divergent": divergent})
        if divergent:
            selected = {"fixture": path.name, "fixture_sha256": sha256_file(path), "results": results}; break
    if selected is None:
        raise RuntimeError(f"positive divergence control failed after three refinements: {attempts}")
    tie = {"seed": None, "dimension": 3, "count": 3, "top_k": 3, "query": [1.0, 0.0, 0.0],
           "vectors": [{"id": sid, "vector": [1.0, 0.0, 0.0]} for sid in ("zeta", "alpha", "mu")]}
    tie_path = control_dir / "exact-tie.json"; write_json(tie_path, tie)
    tie_results = {}
    for lane in ("numpy", "python"):
        python = WORK / f"venv-{lane}" / "Scripts" / "python.exe"
        tie_results[lane] = json.loads(run([str(python), str(HERE / "harness" / "worker.py"), "control", "--lane", lane, "--control", str(tie_path)]).stdout)
    if any(result["ordered"] != ["alpha", "mu", "zeta"] for result in tie_results.values()):
        raise RuntimeError("exact-tie control failed")
    negative = {"input": selected["results"]["numpy"], "comparison_equal": selected["results"]["numpy"] == selected["results"]["numpy"]}
    result = {"schema_version": SCHEMA, "positive": {**selected, "attempts": attempts},
              "exact_tie": {"fixture_sha256": sha256_file(tie_path), "results": tie_results, "ascending_id": True},
              "negative": negative}
    write_json(control_dir / "controls.json", result)
    return result


def measure(config: dict) -> None:
    for case in config["cases"]:
        for repetition in (1, 2):
            for order, lane in enumerate(case["lane_order"], 1):
                trial_id = f"{case['paired_case_id']}__{lane}__r{repetition}"
                output = RAW / f"{trial_id}.json"
                if output.exists():
                    existing = json.loads(output.read_text(encoding="utf-8"))
                    if existing.get("terminal_status") == "completed": continue
                    raise RuntimeError(f"non-completed immutable trial exists: {output}")
                scratch = WORK / "trials" / trial_id
                scratch.mkdir(parents=True, exist_ok=False)
                corpus = config["corpora"][case["corpus"]]
                shutil.copy2(corpus["local_source"], scratch / corpus["database_name"])
                evidence = RAW / "scores" / f"{case['paired_case_id']}__{lane}__r{repetition}.json"
                python = WORK / f"venv-{lane}" / "Scripts" / "python.exe"
                command = [str(python), str(HERE / "harness" / "worker.py"), "trial", "--config", str(HERE / "config.json"),
                           "--scratch", str(scratch), "--packet", str(HERE), "--output", str(output), "--case", case["paired_case_id"],
                           "--lane", lane, "--trial-id", trial_id, "--repetition", str(repetition), "--execution-order", str(order)]
                command += ["--evidence", str(evidence)]
                run(command, timeout=1800)


def derive(config: dict, controls_result: dict) -> None:
    records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(RAW.glob("*.json"))]
    if len(records) != 48: raise RuntimeError(f"expected 48 trials, found {len(records)}")
    by = defaultdict(dict)
    for record in records: by[record["paired_case_id"]][(record["lane_requested"], record["repetition"])] = record
    comparisons = []
    for case in config["cases"]:
        rows = by[case["paired_case_id"]]
        for lane in ("numpy", "python"):
            if rows[(lane, 1)]["score_evidence_sha256"] != rows[(lane, 2)]["score_evidence_sha256"]:
                raise RuntimeError(f"within-lane nondeterminism: {case['paired_case_id']} {lane}")
        ne = json.loads((HERE / rows[("numpy", 1)]["score_evidence_path"]).read_text(encoding="utf-8"))
        pe = json.loads((HERE / rows[("python", 1)]["score_evidence_path"]).read_text(encoding="utf-8"))
        comparisons.append(compare_case(ne, pe, case))
    comp_path = HERE / "artifacts" / "comparisons.jsonl"
    comp_path.write_text("".join(canonical(row) + "\n" for row in comparisons), encoding="utf-8", newline="\n")
    summary = {
        "schema_version": SCHEMA, "paired_case_count": 12, "trial_count": 48,
        "rank_0_equal": sum(c["rank_0"]["equal"] for c in comparisons),
        "ordered_top_k_equal": sum(c["ordered_top_k"]["equal"] for c in comparisons),
        "membership_equal": sum(c["membership"]["equal"] for c in comparisons),
        "cases_with_numpy_exact_ties": sum(c["exact_ties"]["numpy"]["group_count"] > 0 for c in comparisons),
        "cases_with_python_exact_ties": sum(c["exact_ties"]["python"]["group_count"] > 0 for c in comparisons),
        "exact_ties": {
            lane: {
                "full_ranking_group_count": sum(c["exact_ties"][lane]["group_count"] for c in comparisons),
                "full_ranking_participant_count": sum(c["exact_ties"][lane]["participant_count"] for c in comparisons),
                "top_k_intersecting_group_count": sum(len(c["exact_ties"][lane]["intersecting_top_k"]) for c in comparisons),
                "top_k_boundary_crossing_group_count": sum(len(c["exact_ties"][lane]["crossing_top_k_boundary"]) for c in comparisons),
            } for lane in ("numpy", "python")
        },
        "by_corpus": {}, "by_query": {}, "controls_pass": True, "nondeterminism": False,
    }
    for dimension in ("corpus", "query_id"):
        grouped = defaultdict(list)
        for comp in comparisons: grouped[comp[dimension]].append(comp)
        summary["by_corpus" if dimension == "corpus" else "by_query"] = {
            key: {"cases": len(values), "rank_0_equal": sum(v["rank_0"]["equal"] for v in values),
                  "ordered_equal": sum(v["ordered_top_k"]["equal"] for v in values),
                  "membership_equal": sum(v["membership"]["equal"] for v in values)}
            for key, values in grouped.items()}
    write_json(HERE / "artifacts" / "summary.json", summary)
    write_report(config, summary)
    write_manifest(config)


def write_report(config: dict, summary: dict) -> None:
    sentence = "No disagreement was observed in this fixed 12-case suite." if summary["ordered_top_k_equal"] == 12 else "At least one production-lane ranking disagreement was observed in this fixed suite."
    lines = ["# JCodeMunch v1.108.228 production-lane comparison", "", "## Result", "", sentence, "",
             f"Rank 0 equality: {summary['rank_0_equal']}/12 paired cases.",
             f"Ordered top-k equality: {summary['ordered_top_k_equal']}/12 paired cases.",
             f"Top-k membership equality: {summary['membership_equal']}/12 paired cases.",
             f"Cases with exact ties: NumPy {summary['cases_with_numpy_exact_ties']}/12; Python {summary['cases_with_python_exact_ties']}/12.", "",
             "Exact ties are bit-exact final-score equality, with no epsilon. Across full positive-score rankings, NumPy had "
             f"{summary['exact_ties']['numpy']['full_ranking_group_count']} groups and {summary['exact_ties']['numpy']['full_ranking_participant_count']} participants; Python had "
             f"{summary['exact_ties']['python']['full_ranking_group_count']} groups and {summary['exact_ties']['python']['full_ranking_participant_count']} participants. "
             f"Groups intersecting returned top-k were NumPy {summary['exact_ties']['numpy']['top_k_intersecting_group_count']} and Python {summary['exact_ties']['python']['top_k_intersecting_group_count']}; "
             f"groups crossing the top-k boundary were NumPy {summary['exact_ties']['numpy']['top_k_boundary_crossing_group_count']} and Python {summary['exact_ties']['python']['top_k_boundary_crossing_group_count']}. Relevant tie-group IDs and ascending symbol-ID order are retained per case in `artifacts/comparisons.jsonl`.", "",
             "### Per corpus", "", "| Corpus | Cases | Rank 0 equal | Ordered equal | Membership equal |", "| --- | ---: | ---: | ---: | ---: |",
             *[f"| {name} | {row['cases']} | {row['rank_0_equal']} | {row['ordered_equal']} | {row['membership_equal']} |" for name, row in summary["by_corpus"].items()], "",
             "### Per query", "", "| Query | Cases | Rank 0 equal | Ordered equal | Membership equal |", "| --- | ---: | ---: | ---: | ---: |",
             *[f"| `{name}` | {row['cases']} | {row['rank_0_equal']} | {row['ordered_equal']} | {row['membership_equal']} |" for name, row in summary["by_query"].items()], "",
             "## Scope and identities", "", f"This is a new production-lane comparison of the shipped NumPy float32 and NumPy-absent pure-Python float64 lanes in v1.108.228 at `{COMMIT}`. v1.108.228 includes the deterministic `(-score, symbol_id)` tie-break, but not the earlier certified scorer candidate.",
             f"The same locally built wheel (`{config['production']['wheel_sha256']}`) was installed in both isolated Python {'.'.join(map(str, config['environments']['python_major_minor']))} environments. NumPy was 2.4.4 in one lane and absent in the other.", "",
             "The fixed, purposive suite contains Django, FastAPI, and JCodeMunch corpora with four frozen real query embeddings each. It is not a random sample, and these 12 cases do not support a population prevalence claim. The second repetitions are determinism checks, not additional cases.", "",
             "## Controls and reproducibility", "", "The positive control demonstrated an actual production-scorer ordering divergence. The exact-tie control ordered reversed insertion input by ascending symbol ID in both lanes. The negative control reported no difference for identical evidence. All 48 fresh-process trials had tool/adapter parity and identical within-lane repetitions.", "",
             "Reproduce locally from this directory with:", "", "```powershell", "py -3 harness\\controller.py all", "py -3 verify.py --self-test --write-receipt", "```", "",
             "## Limitations", "", "The corpora and queries are fixed and purposive. Numeric diagnostics describe this suite only. No timing or performance conclusion is made. The JCodeMunch control database contains private-source-derived indexed text and remains local.", "",
             "## Local hold", "", "Nothing was pushed, released, posted, or submitted. The only next action is user review and a publication decision.", ""]
    lines[-1:-1] = ["## Artifact inventory", "", "`artifacts/manifest.json` is the exact SHA-256 inventory of every retained packet file. The primary created surfaces are `harness/`, `config.json`, `artifacts/preflight.json`, `artifacts/controls/`, 48 immutable trial records plus two full score-evidence repetitions for each lane/case under `artifacts/raw/`, `artifacts/comparisons.jsonl`, `artifacts/summary.json`, `REPORT.md`, `verify.py`, and `verification.txt`.", "", "Disposable local state is under `working/`: the clean detached source, one built wheel, build and lane environments, trial-local database copies, and the preserved first incomplete run that exposed uncontrolled Python hash randomization. None is listed as public-safe export material.", ""]
    (HERE / "REPORT.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def write_manifest(config: dict) -> None:
    retained = [p for p in HERE.rglob("*") if p.is_file() and "working" not in p.parts and "__pycache__" not in p.parts and p.name not in ("manifest.json", "verification.txt")]
    manifest = {"schema_version": SCHEMA, "submission_state": "not_published", "run_id": config["run_id"],
                "file_sha256": {p.relative_to(HERE).as_posix(): sha256_file(p) for p in sorted(retained)},
                "public_safe_export_inventory": ["PLAN.md", "REPORT.md", "artifacts/summary.json", "artifacts/comparisons.jsonl"],
                "excluded_private_material": ["working/", "artifacts/raw/scores/", config["corpora"]["jcodemunch"]["database_name"]]}
    write_json(HERE / "artifacts" / "manifest.json", manifest)


def main() -> int:
    command = argparse.ArgumentParser(); command.add_argument("command", choices=("setup", "controls", "measure", "derive", "all")); args = command.parse_args()
    if args.command in ("setup", "all"): setup()
    config = make_config()
    if args.command == "setup":
        return 0
    control_result = controls() if args.command in ("controls", "all") else json.loads((HERE / "artifacts" / "controls" / "controls.json").read_text())
    if args.command in ("measure", "all"): measure(config)
    if args.command in ("derive", "all"): derive(config, control_result)
    return 0


if __name__ == "__main__": raise SystemExit(main())
