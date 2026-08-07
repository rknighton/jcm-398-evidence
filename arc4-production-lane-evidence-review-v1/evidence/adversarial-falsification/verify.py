"""Standard-library verifier for the adversarial falsification packet."""
import argparse,hashlib,json,os,shutil,tempfile
from collections import Counter
from pathlib import Path
HERE=Path(__file__).resolve().parent
class Failure(RuntimeError):pass
def req(v,m):
 if not v:raise Failure(m)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text(encoding="utf-8"))
def lines(p):return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x]
def verify(root=HERE):
 required=("PLAN.md","METHODOLOGY.md","config.json","REPORT.md","artifacts/JOURNAL.jsonl","artifacts/coverage.json","artifacts/summary.json","artifacts/manifest.json","artifacts/provenance.json","artifacts/controls/provider-vector-reproduction.json","artifacts/findings/minimal-reproduction-matrix.json","artifacts/findings/public-counterexample-numpy.json","artifacts/findings/public-counterexample-python.json")
 for x in required:req((root/x).is_file(),f"missing {x}")
 c=load(root/"config.json");s=load(root/"artifacts/summary.json");cov=load(root/"artifacts/coverage.json")
 req(c["target"]["commit"]=="8bed872e9436093be9f89d35fb84e0cb58a293af","target mismatch")
 geo=lines(root/"artifacts/queries/geometric.jsonl");req(len(geo)==10002,"geometric coverage")
 gn=lines(root/"artifacts/screens/geometric-numpy.jsonl");gp=lines(root/"artifacts/screens/geometric-python.jsonl");req(len(gn)==len(gp)==len(geo),"geometric lane coverage");req([x["case_id"] for x in gn]==[x["case_id"] for x in gp]==[x["case_id"] for x in geo],"geometric identity mismatch")
 diffs=sum(n["ordered"][0]!=p["ordered"][0] for n,p in zip(gn,gp));req(diffs==s["geometric"]["rank0_flips"]==3211,"geometric finding mismatch")
 texts=lines(root/"artifacts/queries/provider-text.jsonl");req(len(texts)==5000,"text coverage");counts=Counter(x["corpus_seed"] for x in texts);req(dict(counts)==c["generation"]["text_quotas"],"text quota mismatch")
 screen=load(root/"artifacts/screens/provider-text-screen.json");req(sum(x["queries"] for x in screen["coverage"].values())==5000 and len(screen["hits"])==33,"screen coverage mismatch")
 actual=load(root/"artifacts/findings/provider-actual-findings.json");req(len(actual)==5 and not any(x["dimensions"]["1"]["rank0"] for x in actual),"provider finding mismatch")
 rep=load(root/"artifacts/findings/minimal-reproduction-matrix.json");req(rep["stable"] and len(rep["runs"])==50,"reproduction mismatch");req(all(x["top"]==rep["expected"][x["lane"]] for x in rep["runs"]),"replay top mismatch")
 perms=load(root/"artifacts/findings/permutation-summary.json");req(len(perms)==24 and all(x["rank0_flip"] for x in perms),"permutation mismatch")
 n=load(root/"artifacts/findings/public-counterexample-numpy.json");p=load(root/"artifacts/findings/public-counterexample-python.json");req(n["parity"] and p["parity"] and n["tool_ids"][0]!=p["tool_ids"][0],"public rank0 proof failed")
 req(n["mapped_original_ids"][0]=="symbol-00046" and p["mapped_original_ids"][0]=="symbol-03962","public mapping mismatch")
 hybrid=load(root/"artifacts/findings/hybrid-findings.json");req(len(hybrid)==11,"hybrid mismatch")
 provenance=load(root/"artifacts/provenance.json");provider=load(root/"artifacts/controls/provider-vector-reproduction.json")
 req(provenance["target"]["source_clean"] and provenance["target"]["source_commit"]==c["target"]["commit"],"source provenance mismatch")
 req(provenance["target"]["wheel_sha256"]==c["wheel_sha256"],"wheel provenance mismatch")
 req(provider["status"]=="PASS" and provider["queries"]==provider["reproduced"]==5000 and provider["mismatch_count"]==0 and provider["dimensions"]==[384],"provider reproduction mismatch")
 req(provenance["provider_reproduction"]==provider and provenance["baseline_packet"]["verification_status"]=="PASS","control provenance mismatch")
 expected_dbs={"django":"21767e35f79cf051c346389c90562126317fff9871ee9c7e4b33280fe3740529","fastapi":"fb0f933f2fff75684a26872b86bc8f7b7301b7d08c54a079630c05ede760e61e","jcodemunch":"9b6a007e9554a7afdb98936180d0abebce8b86693d842841122c72e9093cdc58"};req({k:v["sha256"] for k,v in provenance["corpora"].items()}==expected_dbs,"corpus provenance mismatch")
 req(all((root/"artifacts/attempts"/name).is_dir() for name in ("attempt-001-two-candidate-minimization-failed","attempt-003-biased-text-allocation","attempt-007-onnxruntime-1.28-vector-reproduction-failed","attempt-008-relative-interpreter-launch-failed")),"failed attempts missing")
 req(s["conclusion"]=="rank_0_equivalence_falsified" and s["publication_state"]=="local_only","summary verdict mismatch")
 manifest=load(root/"artifacts/manifest.json");req(manifest["publication_state"]=="local_only","manifest publication state")
 for rel,digest in manifest["file_sha256"].items():req(sha(root/rel)==digest,f"manifest mismatch {rel}")
 req("Rank-0 equivalence is falsified." in (root/"REPORT.md").read_text(),"report verdict missing")
 return {"status":"PASS","geometric_rank0_flips":diffs,"provider_actual_findings":len(actual),"provider_vectors_reproduced":provider["reproduced"],"public_rank0_flip":True,"manifest_sha256":sha(root/"artifacts/manifest.json")}
def selftest():
 rejected=[]
 def packet(target):
  for source in HERE.rglob("*"):
   if not source.is_file() or "working" in source.parts or "__pycache__" in source.parts:continue
   dest=target/source.relative_to(HERE);dest.parent.mkdir(parents=True,exist_ok=True);os.link(source,dest)
 def detach(path):
  data=path.read_bytes();path.unlink();path.write_bytes(data)
 def mutate_json(path,action):
  detach(path);data=load(path);action(data);path.write_text(json.dumps(data,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 def mutate_query(path):
  detach(path);rows=lines(path);rows[1]["query"][0]+=0.25;path.write_text("".join(json.dumps(x,sort_keys=True,separators=(",",":"))+"\n" for x in rows),encoding="utf-8")
 mutations=(
  ("score",lambda r:mutate_json(r/"artifacts/findings/public-counterexample-numpy.json",lambda d:d["scores"].update({d["tool_ids"][0]:"0x0.0p+0"}))),
  ("query",lambda r:mutate_query(r/"artifacts/queries/geometric.jsonl")),
  ("lane",lambda r:mutate_json(r/"artifacts/findings/public-counterexample-numpy.json",lambda d:d.update(lane="python"))),
  ("coverage",lambda r:mutate_json(r/"artifacts/coverage.json",lambda d:d.update(geometric_cases=10001))),
  ("summary",lambda r:mutate_json(r/"artifacts/summary.json",lambda d:d.update(conclusion="equivalence_not_falsified"))),)
 with tempfile.TemporaryDirectory(prefix="jcm-adversarial-tamper-") as name:
  base=Path(name)
  for label,mutation in mutations:
   root=base/label;packet(root);mutation(root)
   try:verify(root)
   except Failure:rejected.append(label)
 req(set(rejected)=={x[0] for x in mutations},f"tamper self-test mismatch {rejected}");return rejected
def main():
 p=argparse.ArgumentParser();p.add_argument("--self-test",action="store_true");p.add_argument("--write-receipt",action="store_true");a=p.parse_args();r=verify()
 if a.self_test:r["tamper_rejections"]=selftest();r["self_test"]="PASS"
 text=json.dumps(r,indent=2,sort_keys=True)+"\n"
 if a.write_receipt:(HERE/"verification.txt").write_text(text,encoding="utf-8",newline="\n")
 print(text,end="")
if __name__=="__main__":
 try:main()
 except Failure as e:print(json.dumps({"status":"FAIL","error":str(e)}));raise SystemExit(1)
