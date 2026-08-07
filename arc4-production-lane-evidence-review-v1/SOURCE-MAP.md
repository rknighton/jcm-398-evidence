# Arc 4 evidence source map

This map separates observations, interpretation, and lifecycle status. The complete unpacked dataset layout is in [DATASET-INVENTORY.md](DATASET-INVENTORY.md).

## Guarded real-embedding candidate

Purpose: test a float32 fast pass with exact boundary rescore or fallback on real embeddings. This is guarded-candidate evidence, not an unguarded comparison of the two shipped lanes.

- [Packet entry point](../arc4-real-embedding-certification-v1/README.md)
- [Report](../arc4-real-embedding-certification-v1/REPORT.md)
- [Measurements](../arc4-real-embedding-certification-v1/measurements.csv)
- [Verifier](../arc4-real-embedding-certification-v1/verify.py)
- [Verification receipt](../arc4-real-embedding-certification-v1/verification.txt)

Lifecycle: verified published packet. Its 360 rows reduce to 12 corpus-query problems repeated across modes, cache states, and runs.

## Adversarial production-lane falsification

Purpose: prove that NumPy-present float32 and NumPy-absent float64 lanes can diverge, then probe severity and reachability.

- [Report](evidence/adversarial-falsification/REPORT.md)
- [Methodology](evidence/adversarial-falsification/METHODOLOGY.md)
- [Plan](evidence/adversarial-falsification/PLAN.md)
- [Summary](evidence/adversarial-falsification/artifacts/summary.json)
- [Coverage](evidence/adversarial-falsification/artifacts/coverage.json)
- [Provenance](evidence/adversarial-falsification/artifacts/provenance.json)
- [Provider-text findings](evidence/adversarial-falsification/artifacts/findings/provider-actual-findings.json)
- [Public rank-0 counterexample metadata](evidence/adversarial-falsification/artifacts/findings/public-counterexample-meta.json)
- [Verifier](evidence/adversarial-falsification/verify.py)
- [Verification receipt](evidence/adversarial-falsification/verification.txt)
- [All 5,000 provider-text queries](evidence/adversarial-falsification/artifacts/queries/provider-text.jsonl)
- [All geometric query inputs](evidence/adversarial-falsification/artifacts/queries/geometric.jsonl)
- [All preserved attempts](evidence/adversarial-falsification/artifacts/attempts/)

Lifecycle: complete and verified as a falsification packet. Adversarial generator yield is not a production rate. The 4,967 provider-text screen negatives were not fully replayed through both lanes.

## Complete generated-suite replay

Purpose: run every frozen generated query through both shipped lanes, closing the gap the adversarial packet left open.

- [Report](evidence/full-suite-replay/REPORT.md)
- [Machine summary](evidence/full-suite-replay/results-summary.json)
- [Per-lane records](evidence/full-suite-replay/raw/)
- [Comparison verifier](evidence/full-suite-replay/harness/compare_lanes.py)
- [Replay harness](evidence/full-suite-replay/harness/full_replay.py)

Lifecycle: complete. Its comparison step re-derives every reported number from the shipped records and reproduces the adversarial packet's five findings as a control. It measures a within-suite rate, not a production rate, and compares the scoring lane rather than a complete tool response.

## Derived severity assessment

Purpose: interpret the practical severity of the adversarial packet. It adds no independent observations.

- [Assessment](evidence/severity-assessment/REPORT.md)
- [Structured synthesis](evidence/severity-assessment/evidence.json)
- [Verifier implementation](evidence/severity-assessment/verify.py)

Lifecycle: derived assessment with no retained verification receipt, and **partly superseded**. It was written when only 33 of the 5,000 queries had been replayed and states rates over the full 5,000 that the synthesis withdrew. Its own header records which of its statements the complete replay overturned. Retained because superseded reasoning stays useful; the adversarial packet and the full-suite replay are the evidence authorities.

## Production-lane comparison v1

Purpose: supplemental precursor comparison on the same 12 fixed problems, using a locally built wheel.

- [Report](evidence/comparison-v1/REPORT.md)
- [Plan](evidence/comparison-v1/PLAN.md)
- [Summary](evidence/comparison-v1/artifacts/summary.json)
- [Paired comparisons](evidence/comparison-v1/artifacts/comparisons.jsonl)
- [Original manifest](evidence/comparison-v1/artifacts/manifest.json)
- [Verifier](evidence/comparison-v1/verify.py)
- [Verification receipt](evidence/comparison-v1/verification.txt)
- [Full supplemental raw evidence](evidence/comparison-v1/artifacts/raw/)
- [Full supplemental controls](evidence/comparison-v1/artifacts/controls/)

Lifecycle: verified supplemental precursor. It is not an independent replication of v2 and carries no timing claim in this synthesis.

## Production-lane comparison v2

Purpose: compare the two official package lanes on frozen real inputs while holding planned non-lane factors fixed.

- [Lifecycle authority](evidence/comparison-v2/PACKET-STATUS.md)
- [Research report](evidence/comparison-v2/RESEARCH-REPORT.md)
- [Frozen design](evidence/comparison-v2/DESIGN.md)
- [Binding plan](evidence/comparison-v2/PLAN.md)
- [Machine summary](evidence/comparison-v2/packet/SUMMARY.json)
- [Formal packet report](evidence/comparison-v2/packet/REPORT.md)
- [Frozen cases](evidence/comparison-v2/packet/frozen-cases.json)
- [Configuration](evidence/comparison-v2/packet/CONFIG.json)
- [Original manifest](evidence/comparison-v2/packet/MANIFEST.json)
- [Provenance receipt](evidence/comparison-v2/packet/P0-RECEIPT.json)
- [Historical ordinary-verification receipt](evidence/comparison-v2/packet/verification.txt)
- [Current mutation progress](evidence/comparison-v2/packet/self-test-progress.json)
- [Acceptance audit](evidence/comparison-v2/ACCEPTANCE-AUDIT.md)
- [Verification annotation](evidence/comparison-v2/VERIFICATION-ANNOTATION.md)
- [Compressed paired full-depth evidence](evidence/comparison-v2/packet/paired.jsonl.gz)
- [Paired-data compression metadata](evidence/comparison-v2/packet/paired.jsonl.gz.json)
- [All raw rows and full rankings](evidence/comparison-v2/packet/raw/)

Lifecycle: findings complete and independently reconciled, but literal design acceptance is incomplete. The authenticated mutation campaign stopped at 53 of 93 tests. The final verifier has no canonical success receipt. The historical receipt belongs to earlier verifier and manifest identities.

## External decision context

Authors named, because the thread contains both sides and three of these are the reporter's.

- [Issue 398](https://github.com/jgravelle/jcodemunch-mcp/issues/398), the umbrella proposal. Closed 2026-08-01 under the maintainer's one-issue-one-verdict rule; the thread has continued in comments since.
- [Issue 403](https://github.com/jgravelle/jcodemunch-mcp/issues/403), the Arc 4 real-embedding certification evidence issue. Closed 2026-08-03 as completed.
- [Issue 399](https://github.com/jgravelle/jcodemunch-mcp/issues/399), where Arc 4's lane 1 actually shipped, in v1.108.223.
- Maintainer, [comment 5172823848](https://github.com/jgravelle/jcodemunch-mcp/issues/398#issuecomment-5172823848): the synthetic rank-0 disagreement, and lane 3 parked on a changed premise.
- Maintainer, [comment 5167882069 on #403](https://github.com/jgravelle/jcodemunch-mcp/issues/403#issuecomment-5167882069): the Arc 4 gate verdict.
- Reporter, [comment 5175071271](https://github.com/jgravelle/jcodemunch-mcp/issues/398#issuecomment-5175071271): retracting the earlier zero because it never exercised the NumPy-absent lane, and offering exactly the comparison this package now contains.
- Maintainer, [comment 5177953577](https://github.com/jgravelle/jcodemunch-mcp/issues/398#issuecomment-5177953577): accepting the retraction and agreeing to the production-lane comparison on the terms this package follows.

One consequence worth flagging to the maintainer rather than leaving for him to find. `ROADMAP.md` on `main` still records, in its Arc 4 section, that "the hazard is real in principle and does not fire in practice on Django, FastAPI or jcm", and that the v1.108.228 tie-break shipped on the strength of that. That sentence rests on the zero retracted on 2026-08-04, and the roadmap has not been edited since 2026-08-03. The complete replay here restores a narrower version of it on valid grounds: rank 0 held in all 5,000, while ordering, membership and tie partitions did not.

These links provide decision context. The retained experiment artifacts remain the evidence authority.
