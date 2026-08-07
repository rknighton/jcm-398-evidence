"""Freeze the adversarial packet's derived summary, report, and manifest."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent.parent;ART=HERE/"artifacts"
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,indent=2,sort_keys=True)+"\n",encoding="utf-8")
def lines(p):return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x]
geo=lines(ART/"queries"/"geometric.jsonl");gn=lines(ART/"screens"/"geometric-numpy.jsonl");gp=lines(ART/"screens"/"geometric-python.jsonl")
gfind=json.loads((ART/"findings"/"geometric-disagreements.json").read_text());texts=lines(ART/"queries"/"provider-text.jsonl")
screen=json.loads((ART/"screens"/"provider-text-screen.json").read_text());pfind=json.loads((ART/"findings"/"provider-actual-findings.json").read_text())
hfind=json.loads((ART/"findings"/"hybrid-findings.json").read_text());repro=json.loads((ART/"findings"/"minimal-reproduction-matrix.json").read_text())
perms=json.loads((ART/"findings"/"permutation-summary.json").read_text());minim=json.loads((ART/"findings"/"minimization.json").read_text())
pubn=json.loads((ART/"findings"/"public-counterexample-numpy.json").read_text());pubp=json.loads((ART/"findings"/"public-counterexample-python.json").read_text())
provenance=json.loads((ART/"provenance.json").read_text());provider_reproduction=provenance["provider_reproduction"]
config={"schema_version":"jcm-adversarial-falsification-v1","target":{"tag":"v1.108.228","commit":"8bed872e9436093be9f89d35fb84e0cb58a293af"},
 "wheel_sha256":sha(HERE/"working"/"wheel"/"jcodemunch_mcp-1.108.228-py3-none-any.whl"),"numpy_version":"2.4.4","provider":{"name":"local_onnx","model":"all-MiniLM-L6-v2","generation_onnxruntime":"1.24.4"},
 "generation":{"geometric_seed":398228,"known_seed":11,"dimensions":[2,3,8,16,32,64,128,384],"text_quotas":{"django":1667,"fastapi":1667,"jcodemunch":1666}},
 "coverage_floors":{"provider_text":5000,"geometric_boundary":10000,"top_k":[1,5,10,25,50,100],"hash_seeds":[0,1,2,11,101],"repetitions_per_lane_seed":5}}
write(HERE/"config.json",config)
summary={"schema_version":config["schema_version"],"conclusion":"rank_0_equivalence_falsified","publication_state":"local_only",
 "geometric":{"executed":len(geo),"independent_boundary_cases":10000,"rank0_flips":sum(x["rank0_flip"] for x in gfind),"all_disagreements":len(gfind),"dimensions":config["generation"]["dimensions"]},
 "minimal":{"candidate_count":minim["smallest_tested_flip"]["candidate_count"],"numpy_top":"symbol-00046","python_top":"symbol-03962","fresh_process_replays":len(repro["runs"]),"stable":repro["stable"],"permutations":len(perms),"permutation_flips":sum(x["rank0_flip"] for x in perms)},
 "provider_text":{"generated":len(texts),"quotas":config["generation"]["text_quotas"],"screen_hits":len(screen["hits"]),"actual_shipped_scorer_findings":len(pfind),"rank0_flips":sum(x["dimensions"]["1"]["rank0"] for x in pfind),"public_path_parity_findings":len(lines(ART/"findings"/"public-numpy.jsonl"))},
 "hybrid":{"public_cases":len(lines(ART/"findings"/"hybrid-numpy.jsonl")),"findings":len(hfind),"rank0_flips":sum(x["dimensions"]["1"]["rank0"] for x in hfind),"membership_changes":sum(any(v["membership"] for v in x["dimensions"].values()) for x in hfind)},
 "public_geometric_counterexample":{"rank0_flip":pubn["tool_ids"][0]!=pubp["tool_ids"][0],"numpy_top":pubn["tool_ids"][0],"python_top":pubp["tool_ids"][0],"numpy_mapped_top":pubn["mapped_original_ids"][0],"python_mapped_top":pubp["mapped_original_ids"][0],"tool_adapter_parity":pubn["parity"] and pubp["parity"]},
 "controls":{"provider_vectors_reproduced":provider_reproduction["reproduced"],"provider_vector_mismatches":provider_reproduction["mismatch_count"],"baseline_packet_status":provenance["baseline_packet"]["verification_status"],"target_source_clean":provenance["target"]["source_clean"]},
 "failed_attempts_preserved":["attempt-001-two-candidate-minimization-failed","attempt-003-biased-text-allocation","attempt-007-onnxruntime-1.28-vector-reproduction-failed","attempt-008-relative-interpreter-launch-failed"]}
write(ART/"coverage.json",{"geometric_cases":len(geo),"provider_text_queries":len(texts),"text_by_corpus":{c:sum(x["corpus_seed"]==c for x in texts) for c in config["generation"]["text_quotas"]},"top_k_boundaries":config["coverage_floors"]["top_k"],"hybrid_weights":[0.01,0.1,0.25,0.5,0.75,0.9,0.99],"hash_seeds":config["coverage_floors"]["hash_seeds"]})
write(ART/"summary.json",summary)
report=f'''# JCodeMunch v1.108.228 adversarial production-lane falsification

## Verdict

Rank-0 equivalence is falsified.

A valid four-symbol JCodeMunch repository, valid float32 stored embeddings, and a valid 384-dimensional query vector produce different first results through the untouched public `search_symbols` path:

- NumPy 2.4.4 lane: `{summary['public_geometric_counterexample']['numpy_top']}` (`symbol-00046`)
- NumPy-absent lane: `{summary['public_geometric_counterexample']['python_top']}` (`symbol-03962`)

Both tool responses exactly equal independent adapter rankings. The failure survives all 24 insertion orders and 50 fresh-process replays across Python hash seeds 0, 1, 2, 11, and 101.

## Breadth

- 10,000 independently generated boundary cases plus the full and minimized known fixtures were executed through both shipped scorers.
- {summary['geometric']['rank0_flips']:,} geometric cases flipped rank 0.
- 5,000 production-provider text queries were frozen before screening: 1,667 Django, 1,667 FastAPI, and 1,666 JCodeMunch.
- 33 provider-text screens were replayed against full real corpora through both actual shipped scorers.
- Five ordinary text queries produced actual ordered top-k differences. One appears by top 50 and all five by top 100. None changed membership or rank 0.
- Those five findings reproduced through public `search_symbols` with tool/adapter parity.
- Seven hybrid weights over those five queries produced 35 public-path cases and 11 ordered differences, with no membership or rank-0 change.
- Top-k boundaries 1, 5, 10, 25, 50, and 100 were classified.
- All 5,000 frozen provider vectors reproduced byte-for-byte under the recorded ONNX Runtime 1.24.4 generation runtime. A deliberate 1.28.0 replay changed all 5,000 hashes and is preserved as a failed attempt and reproducibility warning.

## Why the four-row case matters

The initial 4,000-row seed-11 corpus flipped rank 0. An assumed two-row minimization failed: both lanes selected the fallback winner. Width sweeping then found that four rows are sufficient. With four rows, NumPy scores `symbol-00046` as `{pubn['scores'][pubn['tool_ids'][0]]}` and selects it first; the fallback selects `symbol-03962` with `{pubp['scores'][pubp['tool_ids'][0]]}`.

This is not malformed input or monkeypatching the scorer. The corpus is indexed normally, embeddings are written through JCodeMunch's embedding store, the query vector satisfies the production dimensional contract, and both lanes run their shipped matrix construction, scoring, and ranking code. Query-provider injection only supplies the frozen vector, exactly as a provider would.

## Methodology and failed attempts

The complete process, mathematical targeting, tools, and evidence hierarchy are in `METHODOLOGY.md`. The chronological machine-readable record is `artifacts/JOURNAL.jsonl`. Failed attempts are retained under `artifacts/attempts/`, including the invalid two-candidate minimization and the first text generator that accidentally allocated all queries to Django.

`artifacts/provenance.json` binds the findings to the clean v1.108.228 source commit, wheel digest, three frozen corpus digests, provider reproduction control, and independently passing original comparison packet.

## Limits

The four-row rank-0 counterexample is geometric. It proves the shipped tool can produce environment-dependent first results for theoretically valid production inputs, but does not show that the local text provider emits that exact vector. The 5,000 provider-reachable text queries found real ordered differences but no rank-0 or membership change. Search coverage is broad and adversarial, not exhaustive.

## Local hold

Nothing was pushed, released, posted, or submitted. The next action is user review.
'''
(HERE/"REPORT.md").write_text(report,encoding="utf-8",newline="\n")
files=[p for p in HERE.rglob("*") if p.is_file() and "working" not in p.parts and "__pycache__" not in p.parts and p.name not in ("manifest.json","verification.txt")]
write(ART/"manifest.json",{"schema_version":config["schema_version"],"publication_state":"local_only","file_sha256":{p.relative_to(HERE).as_posix():sha(p) for p in sorted(files)}})
print(json.dumps(summary,indent=2,sort_keys=True))
