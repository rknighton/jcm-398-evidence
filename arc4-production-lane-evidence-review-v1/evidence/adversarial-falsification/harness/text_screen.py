"""Bulk differential screen for provider-reachable queries over real corpora.

This is candidate nomination only. It cannot establish a production finding.
"""

from __future__ import annotations

import array
import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE=Path(__file__).resolve().parent.parent
ART=HERE/"artifacts"
DBS={
 "django":Path(r"<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\working\indexes\local-django-3eb2e228.db"),
 "fastapi":Path(r"<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\working\indexes\local-fastapi-c1d6b9c4.db"),
 "jcodemunch":Path(r"<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\working\indexes\local-arc4-research-v1-upstream-6f37f3de.db")}
KS=(1,5,10,25,50,100)

def canonical(v): return json.dumps(v,sort_keys=True,separators=(",",":"))

def load(path):
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro",uri=True) as c:
        rows=c.execute("SELECT symbol_id, embedding FROM symbol_embeddings ORDER BY symbol_id").fetchall()
    ids=np.array([x[0] for x in rows],dtype=object)
    raw=np.vstack([np.frombuffer(x[1],dtype=np.float32) for x in rows])
    n=raw.copy(); norms=np.linalg.norm(n,axis=1); norms[norms==0]=1; n/=norms[:,None]
    norms64=np.sqrt(np.sum(raw.astype(np.float64)**2,axis=1)); norms64[norms64==0]=1
    p=(raw.astype(np.float64)/norms64[:,None]).astype(np.float32).astype(np.float64)
    return ids,n,p

def order_subset(ids,scores,limit=120):
    take=min(limit,len(scores)); idx=np.argpartition(scores,-take)[-take:]
    return sorted(idx,key=lambda i:(-float(scores[i]),str(ids[i])))

def main():
    grouped=defaultdict(list)
    for line in (ART/"queries"/"provider-text.jsonl").read_text(encoding="utf-8").splitlines():
        row=json.loads(line); grouped[row["corpus_seed"]].append(row)
    hits=[]; coverage={}; closest=[]
    for corpus,queries in grouped.items():
        ids,nmat,pmat=load(DBS[corpus]); corpus_hits=0
        for start in range(0,len(queries),64):
            batch=queries[start:start+64]
            q=np.asarray([x["vector"] for x in batch],dtype=np.float64)
            qnorm=np.sqrt(np.sum(q*q,axis=1)); qnorm[qnorm==0]=1; q64=q/qnorm[:,None]; q32=q64.astype(np.float32)
            ns=nmat.dot(q32.T); ps=pmat.dot(q64.T)
            for col,item in enumerate(batch):
                no=order_subset(ids,ns[:,col]); po=order_subset(ids,ps[:,col]); nids=[str(ids[i]) for i in no]; pids=[str(ids[i]) for i in po]
                differences={}
                for k in KS:
                    differences[str(k)]={"rank0":nids[0]!=pids[0],"ordered":nids[:k]!=pids[:k],"membership":set(nids[:k])!=set(pids[:k])}
                nmargin=float(ns[no[0],col])-float(ns[no[1],col]); pmargin=float(ps[po[0],col])-float(ps[po[1],col])
                closest.append({"query_id":item["query_id"],"corpus":corpus,"numpy_margin_hex":nmargin.hex(),"python_margin_hex":pmargin.hex(),"min_abs_margin":min(abs(nmargin),abs(pmargin))})
                if any(v["rank0"] or v["ordered"] or v["membership"] for v in differences.values()):
                    corpus_hits+=1; hits.append({"query":item,"differences":differences,"numpy_top":nids[:100],"python_top":pids[:100],
                                                "numpy_top_scores":[float(ns[i,col]).hex() for i in no[:100]],"python_top_scores":[float(ps[i,col]).hex() for i in po[:100]]})
        coverage[corpus]={"queries":len(queries),"candidate_vectors":len(ids),"screen_hits":corpus_hits}
    closest=sorted(closest,key=lambda x:x["min_abs_margin"])[:100]
    result={"schema_version":"jcm-adversarial-text-screen-v1","status":"screen_only_not_proof","coverage":coverage,"top_k_boundaries":list(KS),
            "hits":hits,"closest_rank0_margins":closest}
    out=ART/"screens"/"provider-text-screen.json"; out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(canonical({"queries":sum(x["queries"] for x in coverage.values()),"hits":len(hits),"coverage":coverage,"sha256":hashlib.sha256(out.read_bytes()).hexdigest()}))
    return 0

if __name__=="__main__": raise SystemExit(main())
