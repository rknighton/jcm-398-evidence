"""Prepare and replay the minimized geometric rank-0 failure through public search."""
from __future__ import annotations
import argparse,base64,json,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent.parent
META=HERE/"artifacts"/"findings"/"public-counterexample-meta.json"
def canonical(v):return json.dumps(v,sort_keys=True,separators=(",",":"))
def prepare():
 from jcodemunch_mcp.tools.index_folder import index_folder
 from jcodemunch_mcp.storage import IndexStore
 from jcodemunch_mcp.storage.embedding_store import EmbeddingStore
 root=HERE/"working"/"public-counterexample-base";root.mkdir(parents=True,exist_ok=True)
 result=index_folder(str(HERE/"working"/"public-counterexample-source"),use_ai_summaries=False,storage_path=str(root),identity_mode="local",context_providers=False)
 if result.get("error"):raise RuntimeError(result)
 repo=result["repo"];owner,name=repo.split("/",1);store=IndexStore(base_path=root);index=store.load_index(owner,name)
 if index is None or len(index.symbols)!=4:raise RuntimeError(f"expected four indexed symbols: {len(index.symbols) if index else None}")
 fixture=json.loads((HERE/"artifacts"/"queries"/"minimal-rank0.jsonl").read_text())
 candidate_by_old={c["id"]:c for c in fixture["candidates"]}
 old_order=["symbol-04000","symbol-03999","symbol-03962","symbol-00046"]
 symbols=sorted(s["id"] for s in index.symbols)
 mapping={symbols[i]:candidate_by_old[old_order[i]] for i in range(4)}
 vectors={sid:list(__import__("array").array("f",base64.b64decode(c["blob_b64"]))) for sid,c in mapping.items()}
 db=store._sqlite._db_path(owner,name);emb=EmbeddingStore(db);emb.set_dimension(384,"all-MiniLM-L6-v2");emb.set_task_type("");emb.set_many(vectors)
 META.parent.mkdir(parents=True,exist_ok=True);META.write_text(json.dumps({"repo":repo,"database_name":db.name,"query":fixture["query"],"symbol_mapping":{sid:mapping[sid]["id"] for sid in symbols}},indent=2,sort_keys=True)+"\n",encoding="utf-8")
 print(canonical({"status":"prepared","repo":repo,"symbols":symbols,"database":str(db)}))
def replay(lane,output):
 meta=json.loads(META.read_text());base=HERE/"working"/"public-counterexample-base";root=HERE/"working"/f"public-counterexample-{lane}"
 if root.exists():shutil.rmtree(root)
 shutil.copytree(base,root)
 try:
  import numpy
  nv=numpy.__version__
 except ImportError:nv=None
 if (lane=="numpy")!=(nv is not None):raise RuntimeError("lane mismatch")
 import jcodemunch_mcp.tools.embed_repo as emb
 from jcodemunch_mcp.tools.search_symbols import search_symbols
 from jcodemunch_mcp.storage import IndexStore
 from jcodemunch_mcp.storage import embedding_matrix as em
 emb._detect_provider=lambda:("local_onnx","all-MiniLM-L6-v2");emb.embed_texts=lambda texts,provider,model,task_type=None:[meta["query"] for _ in texts]
 result=search_symbols(repo=meta["repo"],query="adversarial rank zero boundary",max_results=4,detail_level="compact",semantic=True,semantic_only=True,semantic_weight=1.0,storage_path=str(root))
 if result.get("error"):raise RuntimeError(result["error"])
 owner,name=meta["repo"].split("/",1);store=IndexStore(base_path=root);matrix=em.get_matrix(store._sqlite._db_path(owner,name));scores=matrix.score_all(meta["query"]);adapter=sorted(scores,key=lambda sid:(-scores[sid],sid))
 tool=[x["id"] for x in result["results"]]
 if tool!=adapter:raise RuntimeError("public counterexample tool/adapter mismatch")
 row={"lane":lane,"repo":meta["repo"],"query_text":"adversarial rank zero boundary","query_vector":meta["query"],"tool_ids":tool,"adapter_ids":adapter,"parity":True,"scores":{sid:scores[sid].hex() for sid in adapter},"mapped_original_ids":[meta["symbol_mapping"][sid] for sid in tool],"vectorised":matrix.vectorised,"numpy":nv}
 output.write_text(json.dumps(row,indent=2,sort_keys=True)+"\n",encoding="utf-8");print(canonical({"lane":lane,"top":tool[0],"mapped_top":row["mapped_original_ids"][0],"parity":True}))
def main():
 p=argparse.ArgumentParser();p.add_argument("command",choices=("prepare","replay"));p.add_argument("--lane");p.add_argument("--output",type=Path);a=p.parse_args()
 if a.command=="prepare":prepare()
 else:replay(a.lane,a.output)
if __name__=="__main__":main()
