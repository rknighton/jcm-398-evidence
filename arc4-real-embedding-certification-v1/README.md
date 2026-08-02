# Arc 4 real-embedding certification v1

This is the versioned Arc 4 evidence bundle requested from the
[`jcodemunch-mcp#398`](https://github.com/jgravelle/jcodemunch-mcp/issues/398)
roadmap discussion. The measured verdict is pass
<!-- claim:roadmap_verdict=pass -->.

In plain language, the exact certification work touched only 0.1591% of Django's
embedded candidates against a 10% pass ceiling, while the warm candidate scorer was
30.55 times faster than the exact baseline. FastAPI independently measured 0.1809%
and 37.96 times faster. All 360 authoritative rows preserved ordered-result parity,
and no genuine float32-versus-exact top-k disagreement was observed.

## Verify the evidence

From this directory:

```powershell
py -3 verify.py --self-test
py -3 -m unittest -v test_arc4lib.py test_release_asset.py
```

The verifier uses only the Python standard library. It checks the complete
three-corpus measurement matrix, row identities, exact fractions, claim markers,
artifact hashes, release manifest, and deliberate tamper rejection.

## What is included

| File | Purpose |
| --- | --- |
| `measurements.csv` | All 360 authoritative raw rows, with only two machine-local path fields replaced by documented placeholders. |
| `screen_measurements.csv` | All 72 preliminary screen rows under the same public path policy. |
| `REPORT.md` | Methods, results, thresholds, limitations, and verdict. |
| `claims.json` | Machine-checkable values displayed in the report. |
| `research_config.json` | Frozen measurement design with portable source-root placeholders. |
| `prepared-inputs.json` | Query vectors, embedding identities, corpus commits, database hashes, and release coverage. |
| `arc4lib.py`, `worker.py`, `run_research.py` | Reusable measurement harness. |
| `release_asset.py` | Prepared-index archive builder, verifier, safety audit, and installer. |
| `INDEX.json` | Public artifact hashes and exact source-to-public transformations. |

`INDEX.json` preserves the SHA-256 identity of the original canonical CSV and frozen
config. The public CSV changes only `baseline_import_root` and
`candidate_import_root`; row IDs, timing data, result hashes, classifications, and all
other measured fields remain unchanged.

## Prepared embedding indexes

The matching release convention is:

- Tag: `arc4-real-embedding-certification-v1`
- Asset: `arc4-real-embedding-indexes-v1.zip`
- Checksum: `arc4-real-embedding-indexes-v1.sha256`
- Manifest: `arc4-real-embedding-indexes-v1.manifest.json`

Verify and install a downloaded asset without trusting the prose:

```powershell
py -3 release_asset.py verify --archive <downloaded-asset-path>
py -3 release_asset.py install --archive <downloaded-asset-path>
```

The public asset contains the two load-bearing gate indexes, Django and FastAPI, with
58,966 real 384-dimensional vectors. This avoids roughly 23 minutes of embedding work
on the measured host. The JCodeMunch control index and its 13,960 vectors are not in the
public asset because the pinned custom license requires written permission for a
repackaged derivative containing indexed source text. Its raw measurement rows remain
in `measurements.csv`. See `RELEASE-ASSET.md` and `THIRD-PARTY-NOTICES.md`.

## Reproduce without the release asset

The full harness can create isolated database copies and generate embeddings without
mutating source JCodeMunch indexes:

```powershell
py -3 run_research.py prepare --baseline-root <baseline-checkout> --source-index-root <index-directory> --batch-size 128
py -3 run_research.py screen --baseline-root <baseline-checkout> --candidate-root <candidate-checkout>
py -3 run_research.py authoritative --baseline-root <baseline-checkout> --candidate-root <candidate-checkout>
```

`working/` is ignored by Git and contains resumable run state. Use a clean copy if you
intend to regenerate `measurements.csv`.

## Publication boundary

The evidence repository and its Arc 4 release are published. The focused upstream
follow-up issue remains a local draft and has not been submitted. Nothing in this
bundle posts, pushes, publishes, creates a release, or submits an issue by itself.
