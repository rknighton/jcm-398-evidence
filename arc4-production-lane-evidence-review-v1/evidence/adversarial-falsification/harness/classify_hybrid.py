import json
from pathlib import Path
HERE=Path(__file__).resolve().parent.parent
def load(lane):return {(r["query_id"],r["semantic_weight"]):r for r in map(json.loads,(HERE/"artifacts"/"findings"/f"hybrid-{lane}.jsonl").read_text().splitlines())}
n,p=load("numpy"),load("python");findings=[]
for key,nr in n.items():
 pr=p[key];dims={}
 for k in (1,5,10,25,50,100):dims[str(k)]={"rank0":nr["tool_ids"][0]!=pr["tool_ids"][0],"ordered":nr["tool_ids"][:k]!=pr["tool_ids"][:k],"membership":set(nr["tool_ids"][:k])!=set(pr["tool_ids"][:k])}
 if any(any(v.values()) for v in dims.values()):findings.append({"query_id":key[0],"weight":key[1],"query_text":nr["query_text"],"corpus":nr["corpus"],"dimensions":dims,"numpy_ids":nr["tool_ids"],"python_ids":pr["tool_ids"]})
out=HERE/"artifacts"/"findings"/"hybrid-findings.json";out.write_text(json.dumps(findings,indent=2,sort_keys=True)+"\n",encoding="utf-8")
print(json.dumps({"hybrid_cases":len(n),"findings":len(findings),"rank0_flips":sum(f["dimensions"]["1"]["rank0"] for f in findings),"membership_changes":sum(any(v["membership"] for v in f["dimensions"].values()) for f in findings)},sort_keys=True))
