"""Replay nominated provider-text hits against full real corpora in one shipped lane."""

from __future__ import annotations
import argparse,json,os,sqlite3
from pathlib import Path

HERE=Path(__file__).resolve().parent.parent
DBS={
 "django":Path(r"<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\working\indexes\local-django-3eb2e228.db"),
 "fastapi":Path(r"<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\working\indexes\local-fastapi-c1d6b9c4.db"),
 "jcodemunch":Path(r"<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\working\indexes\local-arc4-research-v1-upstream-6f37f3de.db")}
def canonical(v):return json.dumps(v,sort_keys=True,separators=(",",":"))
def main():
 p=argparse.ArgumentParser();p.add_argument("--lane",required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
 try:
  import numpy
  nv=numpy.__version__
 except ImportError:nv=None
 if (a.lane=="numpy")!=(nv is not None):raise RuntimeError("lane mismatch")
 from jcodemunch_mcp.storage import embedding_matrix as em
 screen=json.loads((HERE/"artifacts"/"screens"/"provider-text-screen.json").read_text())
 grouped={c:[h for h in screen["hits"] if h["query"]["corpus_seed"]==c] for c in DBS}
 output=[]
 for corpus,hits in grouped.items():
  if not hits:continue
  with sqlite3.connect(f"file:{DBS[corpus].as_posix()}?mode=ro",uri=True) as c: raw=c.execute("SELECT symbol_id, embedding FROM symbol_embeddings ORDER BY symbol_id").fetchall()
  matrix=em._build(raw)
  if matrix is None or matrix.vectorised!=(a.lane=="numpy"):raise RuntimeError("matrix selection mismatch")
  for hit in hits:
   scores=matrix.score_all(hit["query"]["vector"]);ordered=sorted(scores,key=lambda sid:(-scores[sid],sid))
   output.append({"query_id":hit["query"]["query_id"],"query_text":hit["query"]["text"],"corpus":corpus,"lane":a.lane,
                  "candidate_count":len(scores),"ordered_top_100":ordered[:100],"score_hex":{sid:scores[sid].hex() for sid in ordered[:100]},
                  "vectorised":matrix.vectorised,"numpy_version":nv,"python_hash_seed":os.environ.get("PYTHONHASHSEED")})
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text("".join(canonical(r)+"\n" for r in output),encoding="utf-8",newline="\n")
 print(canonical({"lane":a.lane,"replayed":len(output)}));return 0
if __name__=="__main__":raise SystemExit(main())
