"""Classify actual full-corpus provider-text replays."""
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent.parent
lanes={}
for lane in ("numpy","python"):
 lanes[lane]={r["query_id"]:r for r in map(json.loads,(HERE/"artifacts"/"findings"/f"provider-replay-{lane}.jsonl").read_text().splitlines())}
findings=[]
for qid,n in lanes["numpy"].items():
 p=lanes["python"][qid];dims={}
 for k in (1,5,10,25,50,100):dims[str(k)]={"rank0":n["ordered_top_100"][0]!=p["ordered_top_100"][0],"ordered":n["ordered_top_100"][:k]!=p["ordered_top_100"][:k],"membership":set(n["ordered_top_100"][:k])!=set(p["ordered_top_100"][:k])}
 if any(x["rank0"] or x["ordered"] or x["membership"] for x in dims.values()):findings.append({"query_id":qid,"query_text":n["query_text"],"corpus":n["corpus"],"dimensions":dims,"numpy":n,"python":p})
out=HERE/"artifacts"/"findings"/"provider-actual-findings.json";out.write_text(json.dumps(findings,indent=2,sort_keys=True)+"\n",encoding="utf-8")
print(json.dumps({"screen_replays":len(lanes["numpy"]),"actual_findings":len(findings),"rank0_flips":sum(f["dimensions"]["1"]["rank0"] for f in findings)},sort_keys=True))
