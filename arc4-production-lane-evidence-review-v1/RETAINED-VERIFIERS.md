# Retained verifiers: what runs here and what does not

`verify_package.py` is the release gate for this published layout. It passes.

The four verifiers retained from the original experiment packets **do not run in this layout, and none of them is expected to.** They are kept as provenance and as research tooling, so that a reader can see exactly what each packet checked and how. Each one authenticates its own frozen local packet, and publication deliberately removed or normalised files those manifests list. Their failure is a documented consequence of the publication boundary described in [PROVENANCE-ANNOTATION.md](PROVENANCE-ANNOTATION.md), not a sign that the evidence is damaged.

The observed behaviour is recorded here so that nobody has to discover it by surprise.

| Verifier | Exit | What it reports | Why |
| --- | ---: | --- | --- |
| `evidence/adversarial-falsification/verify.py` | 1 | `{"status": "FAIL", "error": "manifest mismatch artifacts/logs/attempt-797a8667-...log"}` | Its frozen manifest lists 240 files. All 240 are published, but 6 were rewritten by publication normalization: two attempt logs and four harness scripts, each of which had a machine-specific research root replaced with a placeholder. It stops at the first. |
| `evidence/comparison-v1/verify.py` | 1 | unhandled `FileNotFoundError` on `.pytest_cache/.gitignore` | Its frozen manifest lists 114 files including four generated pytest-cache entries, which publication excludes as caches. Two further files carry normalization differences. It raises rather than reporting. |
| `evidence/comparison-v2/packet/verify.py` | 2 | `{"status": "rejected", ..., "error_codes": ["manifest_file_hash"]}` | Its frozen manifest lists 434 files. Two are absent by design: the oversized `paired.jsonl`, replaced by a verified single-file gzip, and `inputs/jcodemunch_mcp-1.108.228-py3-none-any.whl`, excluded as a third-party binary. |
| `evidence/severity-assessment/verify.py` | 1 | unhandled `FileNotFoundError` on `evidence/arc4-production-lane-adversarial-falsification-v1/artifacts/summary.json` | Line 7 resolves the adversarial packet by its original local sibling directory name. In this package that directory is `evidence/adversarial-falsification/`, so the path cannot resolve. It is layout-bound and was not rewritten, because rewriting it would change a retained research artifact. |

## What replaces them

Everything those verifiers checked that still applies to the published bytes is covered by `verify_package.py`, which recomputes the decision-facing counts from raw records rather than reading them from summaries. Run:

```powershell
py -3 -B verify_package.py
py -3 -B -m unittest -v test_verify_package.py
```

The verifier prints the set it recomputes, the set it cross-checks between documents, and the set it does not cover. Read that output rather than assuming the three sets are one.

`evidence/full-suite-replay/harness/compare_lanes.py` is a read-only reproducer for the supplemental replay, not the release gate. It re-derives that packet's four reported dimensions from the shipped per-lane records using the standard library alone, needs no corpus database and no jcodemunch install, compares its output byte for byte against the committed artifacts, and exits non-zero on any structural failure, a five-finding control failure, or drift. Pass `--regenerate` only when the per-lane records have themselves changed. It does not derive the attested stored-vector census in `mechanism-census.json`.

## Reconciling a retained verifier by hand

Each frozen manifest is published beside its packet, so the difference between what a packet expected and what this publication contains is inspectable:

| Packet | Frozen manifest | Entries | Absent here | Hash-changed here |
| --- | --- | ---: | ---: | ---: |
| adversarial-falsification | `artifacts/manifest.json` | 240 | 0 | 6 |
| comparison-v1 | `artifacts/manifest.json` | 114 | 4 | 2 |
| comparison-v2 | `packet/MANIFEST.json` | 434 | 2 | 0 |

[SOURCE-HASHES.sha256](SOURCE-HASHES.sha256) records every copied file's pre-normalization digest, so a hash-changed file can be identified precisely rather than guessed at.
