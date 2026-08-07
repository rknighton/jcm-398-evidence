"""Replay confirmed provider-reachable findings through public search_symbols."""
from __future__ import annotations
import argparse,json,os,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent.parent
DBS={
 "django":Path(r"<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\working\indexes\local-django-3eb2e228.db"),
 "fastapi":Path(r"<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\working\indexes\local-fastapi-c1d6b9c4.db"),
 "jcodemunch":Path(r"<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\working\indexes\local-arc4-research-v1-upstream-6f37f3de.db")}
REPOS={"django":"local/django-3eb2e228","fastapi":"local/fastapi-c1d6b9c4","jcodemunch":"local/arc4-research-v1-upstream-6f37f3de"}
def canonical(v):return json.dumps(v,sort_keys=True,separators=(",",":"))
def main():
 p=argparse.ArgumentParser();p.add_argument("--lane",required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--hybrid",action="store_true");a=p.parse_args()
 try:
  import numpy
  nv=numpy.__version__
 except ImportError:nv=None
 if (a.lane=="numpy")!=(nv is not None):raise RuntimeError("lane mismatch")
 from jcodemunch_mcp.storage import IndexStore
 from jcodemunch_mcp.storage import embedding_matrix as em
 import jcodemunch_mcp.tools.embed_repo as emb
 from jcodemunch_mcp.tools.search_symbols import search_symbols
 findings=json.loads((HERE/"artifacts"/"findings"/"provider-actual-findings.json").read_text())
 vectors={r["query_id"]:r for r in map(json.loads,(HERE/"artifacts"/"queries"/"provider-text.jsonl").read_text().splitlines())}
 root=HERE/"working"/f"public-{a.lane}";root.mkdir(parents=True,exist_ok=True)
 for corpus,path in DBS.items():
  target=root/path.name
  if not target.exists():shutil.copy2(path,target)
 output=[]
 for finding in findings:
  item=vectors[finding["query_id"]];corpus=finding["corpus"]
  emb._detect_provider=lambda:("local_onnx","all-MiniLM-L6-v2")
  emb.embed_texts=lambda texts,provider,model,task_type=None,v=item["vector"]:[v for _ in texts]
  weights=(0.01,0.1,0.25,0.5,0.75,0.9,0.99) if a.hybrid else (1.0,)
  for weight in weights:
   result=search_symbols(repo=REPOS[corpus],query=item["text"],max_results=100,detail_level="compact",semantic=True,semantic_only=not a.hybrid,semantic_weight=weight,storage_path=str(root))
   if result.get("error"):raise RuntimeError(result["error"])
   ids=[x["id"] for x in result["results"]]
   store=IndexStore(base_path=root);owner,name=REPOS[corpus].split("/",1);matrix=em.get_matrix(store._sqlite._db_path(owner,name))
   if matrix is None or matrix.vectorised!=(a.lane=="numpy"):raise RuntimeError("public lane mismatch")
   parity=True
   if not a.hybrid:
    scores=matrix.score_all(item["vector"]);adapter=sorted(scores,key=lambda sid:(-scores[sid],sid))[:100]
    if ids!=adapter:raise RuntimeError(f"tool adapter mismatch {item['query_id']}")
   else:adapter=None
   output.append({"query_id":item["query_id"],"query_text":item["text"],"corpus":corpus,"lane":a.lane,"semantic_weight":weight,"hybrid":a.hybrid,"tool_ids":ids,"adapter_ids":adapter,"parity":parity,"numpy":nv,"vectorised":matrix.vectorised})
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text("".join(canonical(x)+"\n" for x in output),encoding="utf-8",newline="\n")
 print(canonical({"lane":a.lane,"public_replays":len(output),"all_parity":all(x["parity"] for x in output)}));return 0
if __name__=="__main__":raise SystemExit(main())
