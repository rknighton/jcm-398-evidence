"""Generate, execute, classify, and minimize the adversarial campaign."""

from __future__ import annotations

import argparse
import array
import base64
import hashlib
import json
import math
import os
import random
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ART = HERE / "artifacts"
GEOMETRIC_COUNT = 10000
TEXT_COUNT = 5000
SEEDS = (0, 1, 2, 11, 101)
DBS = {
    "django": Path(r"<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\working\indexes\local-django-3eb2e228.db"),
    "fastapi": Path(r"<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\working\indexes\local-fastapi-c1d6b9c4.db"),
    "jcodemunch": Path(r"<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\working\indexes\local-arc4-research-v1-upstream-6f37f3de.db"),
}


def canonical(value): return json.dumps(value, sort_keys=True, separators=(",", ":"))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def blob(values): return base64.b64encode(array.array("f", values).tobytes()).decode("ascii")


def known_fixture(seed=11, dimension=384, count=4000):
    rng = random.Random(seed)
    query = [rng.uniform(-1, 1) for _ in range(dimension)]
    norm = math.sqrt(sum(x*x for x in query)); query = [x/norm for x in query]
    vectors = []
    for index in range(count):
        noise = 1e-6 * (index - count / 2) / count
        row = [x + noise * rng.uniform(-1, 1) for x in query]
        vectors.append((f"symbol-{count-index:05d}", row))
    return query, vectors


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def generate_geometric():
    rng = random.Random(398228)
    query0, known = known_fixture()
    cases = [{"case_id": "known-4000-rank0", "family": "known_near_tied", "query": query0,
              "candidates": [{"id": sid, "blob_b64": blob(row)} for sid, row in known]}]
    winners = {sid: row for sid, row in known if sid in ("symbol-00046", "symbol-03962")}
    cases.append({"case_id": "known-minimal-two-candidate", "family": "minimized_known", "query": query0,
                  "candidates": [{"id": sid, "blob_b64": blob(winners[sid])} for sid in sorted(winners)]})
    dimensions = (2, 3, 8, 16, 32, 64, 128, 384)
    while len(cases) < GEOMETRIC_COUNT + 2:
        index = len(cases) - 2; dim = dimensions[index % len(dimensions)]
        base = [rng.uniform(-1, 1) for _ in range(dim)]
        norm = math.sqrt(sum(x*x for x in base)); base = [x/norm for x in base]
        scale = 2.0 ** (-(18 + index % 24))
        direction = [rng.uniform(-1, 1) for _ in range(dim)]
        a = [x + scale*d for x, d in zip(base, direction)]
        b = [x - scale*d for x, d in zip(base, direction)]
        perturb = (-1, 0, 1)[index % 3] * 2.0 ** (-(30 + index % 20))
        query = [x + perturb*d for x, d in zip(base, direction)]
        cases.append({"case_id": f"boundary-{index:05d}", "family": "boundary_sweep", "dimension": dim,
                      "scale_hex": scale.hex(), "perturb_hex": perturb.hex(), "query": query,
                      "candidates": [{"id": "candidate-a", "blob_b64": blob(a)}, {"id": "candidate-b", "blob_b64": blob(b)}]})
    path = ART / "queries" / "geometric.jsonl"
    path.write_text("".join(canonical(c)+"\n" for c in cases), encoding="utf-8", newline="\n")
    return {"cases": len(cases), "sha256": sha(path), "known_full": 1, "known_minimized": 1, "boundary_sweep": GEOMETRIC_COUNT}


def symbol_texts():
    texts = []
    quotas = {"django": 1667, "fastapi": 1667, "jcodemunch": 1666}
    for corpus, path in DBS.items():
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
            rows = connection.execute("SELECT symbol_id FROM symbol_embeddings ORDER BY symbol_id").fetchall()
        corpus_texts=[]
        for offset in range(0, len(rows), max(1, len(rows)//400)):
            sid = rows[offset][0]
            tail = sid.rsplit("::", 1)[-1].replace("#", " ").replace("_", " ").replace(".", " ")
            variants = (tail, tail.lower(), f"find {tail}", f"implementation of {tail}", f"{tail} error validation response")
            for variant in variants:
                corpus_texts.append({"corpus_seed": corpus, "symbol_id": sid, "text": variant})
                if len(corpus_texts) >= quotas[corpus]: break
            if len(corpus_texts) >= quotas[corpus]: break
        if len(corpus_texts) < quotas[corpus]: raise RuntimeError(f"text quota shortfall for {corpus}")
        texts.extend(corpus_texts)
    return texts


def generate_text():
    texts = symbol_texts()
    if len(texts) != TEXT_COUNT: raise RuntimeError(f"generated only {len(texts)} text queries")
    from jcodemunch_mcp.tools.embed_repo import _detect_provider, embed_texts
    provider = _detect_provider()
    if provider != ("local_onnx", "all-MiniLM-L6-v2"): raise RuntimeError(f"provider mismatch: {provider}")
    records = []
    for start in range(0, len(texts), 128):
        batch = texts[start:start+128]
        vectors = embed_texts([x["text"] for x in batch], *provider)
        for index, (item, vector) in enumerate(zip(batch, vectors), start):
            records.append({"query_id": f"text-{index:05d}", **item, "vector": vector,
                            "vector_sha256": hashlib.sha256(array.array("f", vector).tobytes()).hexdigest()})
    path = ART / "queries" / "provider-text.jsonl"
    path.write_text("".join(canonical(r)+"\n" for r in records), encoding="utf-8", newline="\n")
    return {"queries": len(records), "provider": provider[0], "model": provider[1], "sha256": sha(path)}


def execute_geometric():
    source = ART / "queries" / "geometric.jsonl"
    receipts = {}
    for lane in ("numpy", "python"):
        python = HERE / "working" / f"venv-{lane}" / "Scripts" / "python.exe"
        output = ART / "screens" / f"geometric-{lane}.jsonl"
        env = os.environ.copy(); env["PYTHONHASHSEED"] = "0"
        result = subprocess.run([str(python), str(HERE/"harness"/"lane_worker.py"), "--input", str(source), "--output", str(output), "--lane", lane],
                                check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800, env=env)
        receipts[lane] = json.loads(result.stdout)
    return receipts


def compare_geometric():
    lanes = {}
    for lane in ("numpy", "python"):
        lanes[lane] = {r["case_id"]: r for r in map(json.loads, (ART/"screens"/f"geometric-{lane}.jsonl").read_text().splitlines())}
    findings = []
    for case_id in lanes["numpy"]:
        n, p = lanes["numpy"][case_id], lanes["python"][case_id]
        if n["ordered"] != p["ordered"]:
            findings.append({"case_id": case_id, "rank0_flip": n["ordered"][0] != p["ordered"][0],
                             "numpy": n, "python": p})
    path = ART / "findings" / "geometric-disagreements.json"
    write_json(path, findings)
    return {"disagreements": len(findings), "rank0_flips": sum(f["rank0_flip"] for f in findings),
            "finding_sha256": sha(path), "first_ids": [f["case_id"] for f in findings[:20]]}


def _run_fixture_file(source, stem, seed=0):
    rows = {}
    for lane in ("numpy", "python"):
        python = HERE/"working"/f"venv-{lane}"/"Scripts"/"python.exe"
        output = ART/"findings"/"minimization"/f"{stem}-{lane}.jsonl"; output.parent.mkdir(parents=True, exist_ok=True)
        env=os.environ.copy(); env["PYTHONHASHSEED"]=str(seed)
        subprocess.run([str(python),str(HERE/"harness"/"lane_worker.py"),"--input",str(source),"--output",str(output),"--lane",lane],
                       check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=180,env=env)
        rows[lane]=json.loads(output.read_text())
    return rows


def minimize_known():
    query, vectors = known_fixture()
    winner_ids={"symbol-00046","symbol-03962"}
    sizes=(2,4,8,16,32,64,128,256,512,1024,1536,2048,2560,3000,3500,3750,3875,3938,3969,3985,3993,3997,3999,4000)
    attempts=[]; best=None
    for size in sizes:
        selected=[]
        for item in vectors:
            if item[0] in winner_ids or len(selected) < size-len(winner_ids): selected.append(item)
        selected_ids={sid for sid,_ in selected}
        for item in vectors:
            if item[0] in winner_ids and item[0] not in selected_ids: selected.append(item)
        selected=selected[:size]
        case={"case_id":f"width-{size}","family":"width_minimization","query":query,
              "candidates":[{"id":sid,"blob_b64":blob(row)} for sid,row in selected]}
        source=ART/"findings"/"minimization"/f"width-{size}.jsonl"; source.parent.mkdir(parents=True,exist_ok=True)
        source.write_text(canonical(case)+"\n",encoding="utf-8")
        rows=_run_fixture_file(source,f"width-{size}")
        flip=rows["numpy"]["ordered"][0] != rows["python"]["ordered"][0]
        attempt={"candidate_count":size,"rank0_flip":flip,"numpy_top":rows["numpy"]["ordered"][0],"python_top":rows["python"]["ordered"][0],
                 "numpy_top_score":rows["numpy"]["scores"][rows["numpy"]["ordered"][0]],"python_top_score":rows["python"]["scores"][rows["python"]["ordered"][0]],"fixture_sha256":sha(source)}
        attempts.append(attempt)
        if flip and best is None: best={"source":source,"attempt":attempt}
    if best is None: raise RuntimeError("width minimization did not preserve rank-0 flip")
    retained=ART/"queries"/"minimal-rank0.jsonl"; retained.write_bytes(best["source"].read_bytes())
    result={"strategy":"declared width sweep with winner preservation","attempts":attempts,"smallest_tested_flip":best["attempt"],"retained_sha256":sha(retained)}
    write_json(ART/"findings"/"minimization.json",result)
    return result


def repeat_minimal():
    source = ART/"queries"/"minimal-rank0.jsonl"
    baseline=_run_fixture_file(source,"retained-baseline")
    expected={lane:baseline[lane]["ordered"][0] for lane in ("numpy","python")}
    if expected["numpy"]==expected["python"]: raise RuntimeError("retained minimized fixture is not a rank-0 flip")
    matrix = []
    for seed in SEEDS:
        for repetition in range(1, 6):
            for lane in ("numpy", "python"):
                python = HERE/"working"/f"venv-{lane}"/"Scripts"/"python.exe"
                output = ART/"findings"/"replays"/f"seed-{seed}-{lane}-r{repetition}.jsonl"; output.parent.mkdir(parents=True, exist_ok=True)
                env = os.environ.copy(); env["PYTHONHASHSEED"] = str(seed)
                subprocess.run([str(python), str(HERE/"harness"/"lane_worker.py"), "--input", str(source), "--output", str(output), "--lane", lane],
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60, env=env)
                row = json.loads(output.read_text())
                matrix.append({"seed": seed, "repetition": repetition, "lane": lane, "top": row["ordered"][0], "scores": row["scores"], "sha256": sha(output)})
    stable = all(row["top"] == expected[row["lane"]] for row in matrix)
    write_json(ART/"findings"/"minimal-reproduction-matrix.json", {"stable": stable, "expected": expected, "runs": matrix})
    if not stable: raise RuntimeError("minimal rank-0 counterexample did not reproduce")
    return {"runs": len(matrix), "hash_seeds": list(SEEDS), "repetitions_per_lane_seed": 5, "stable": stable}


def write_config_and_summary(parts):
    config = {"schema_version": "jcm-adversarial-falsification-v1", "target": {"tag":"v1.108.228","commit":"8bed872e9436093be9f89d35fb84e0cb58a293af"},
              "coverage_floors": {"provider_text":TEXT_COUNT,"geometric":GEOMETRIC_COUNT,"top_k":[1,5,10,25,50,100],"hash_seeds":list(SEEDS)},
              "wheel_sha256": sha(HERE/"working"/"wheel"/"jcodemunch_mcp-1.108.228-py3-none-any.whl")}
    write_json(HERE/"config.json", config)
    summary = {"schema_version":config["schema_version"], **parts, "conclusion":"rank_0_equivalence_falsified",
               "publication_state":"local_only"}
    write_json(ART/"summary.json", summary)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("command",choices=("generate","text","execute","all")); args=parser.parse_args()
    parts={}
    if args.command in ("generate","all"):
        parts["geometric_generation"]=generate_geometric(); parts["text_generation"]=generate_text()
    if args.command == "text":
        print(canonical(generate_text()))
    if args.command in ("execute","all"):
        parts["geometric_execution"]=execute_geometric(); parts["geometric_findings"]=compare_geometric(); parts["minimization"]=minimize_known(); parts["minimal_reproduction"]=repeat_minimal()
    if args.command=="all": write_config_and_summary(parts)
    return 0


if __name__=="__main__": raise SystemExit(main())
