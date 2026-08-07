import itertools,json,os,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent.parent
case=json.loads((HERE/"artifacts"/"queries"/"minimal-rank0.jsonl").read_text())
cases=[]
for i,order in enumerate(itertools.permutations(case["candidates"])):
 row=dict(case);row["case_id"]=f"permutation-{i:02d}";row["family"]="insertion_order";row["candidates"]=list(order);cases.append(row)
source=HERE/"artifacts"/"queries"/"minimal-permutations.jsonl";source.write_text("".join(json.dumps(x,sort_keys=True,separators=(",",":"))+"\n" for x in cases),encoding="utf-8")
results={}
for lane in ("numpy","python"):
 py=HERE/"working"/f"venv-{lane}"/"Scripts"/"python.exe";out=HERE/"artifacts"/"findings"/f"permutations-{lane}.jsonl";env=os.environ.copy();env["PYTHONHASHSEED"]="0"
 subprocess.run([str(py),str(HERE/"harness"/"lane_worker.py"),"--input",str(source),"--output",str(out),"--lane",lane],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
 results[lane]=list(map(json.loads,out.read_text().splitlines()))
summary=[]
for n,p in zip(results["numpy"],results["python"]):summary.append({"case_id":n["case_id"],"numpy_top":n["ordered"][0],"python_top":p["ordered"][0],"rank0_flip":n["ordered"][0]!=p["ordered"][0]})
out=HERE/"artifacts"/"findings"/"permutation-summary.json";out.write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",encoding="utf-8")
print(json.dumps({"permutations":len(summary),"rank0_flips":sum(x["rank0_flip"] for x in summary),"distinct_numpy_tops":sorted(set(x["numpy_top"] for x in summary)),"distinct_python_tops":sorted(set(x["python_top"] for x in summary))},sort_keys=True))
