# Adversarial Falsification Methodology

## Experimental posture

This campaign seeks counterexamples, not confirmation. A rank difference is treated as a successful finding. A non-finding is reported only as bounded search coverage. Screening may prioritize inputs, but only execution through the untouched JCodeMunch v1.108.228 shipped scorer implementations can establish a finding.

The validated fixed-suite comparison is a separate prior experiment and is not modified or pooled with this campaign.

## Tools and their roles

- JCodeMunch MCP v1.108.241: source navigation and exact retrieval of the pinned v1.108.228 scorer implementation. It was not the scorer under test.
- Clean JCodeMunch v1.108.228 wheel: system under test in isolated NumPy-present and NumPy-absent environments.
- Python 3.13: deterministic generators, orchestration, evidence serialization, and the pure-Python production lane.
- NumPy 2.4.4: the shipped vectorized production lane and bulk screening support.
- Local ONNX `all-MiniLM-L6-v2`: production query provider used to generate 5,000 provider-reachable text vectors.
- SQLite: read-only extraction of frozen real embedding and symbol identities.
- Wolfram Context: mathematical-method lookup for cosine equality surfaces, precision-dependent normalization, and perturbation design. Its retrieval returned general precision and normalization references, not an empirical conclusion. Production replay remains authoritative.
- `bounded-command.py`: bounded execution and durable raw logs for long-running commands.
- PowerShell: local environment setup and artifact preservation.

## Mathematical targeting

For normalized candidates `a` and `b`, exact equality under cosine ranking lies on the hyperplane `q . (a - b) = 0`. A useful base query is proportional to `a + b` when candidate norms are comparable. Perturbations along `a - b` move controllably across the boundary. The campaign varies:

- dimensions 2, 3, 8, 16, 32, 64, 128, and 384;
- candidate separation scales from approximately `2^-18` through `2^-41`;
- query perturbations around zero from approximately `2^-30` through `2^-49`;
- corpus width, because NumPy matrix multiplication may select width-dependent kernels;
- insertion order, symbol IDs, top-k boundaries, hybrid weights, and Python hash seeds.

Stored candidates are serialized as native float32 blobs because that is the production storage contract. Queries remain valid Python float vectors and are normalized by the shipped scorer.

## Evidence hierarchy

1. Actual isolated shipped-lane replay.
2. Actual public production-tool replay for provider-reachable findings.
3. Full hex score and ordered-ID evidence.
4. Deterministic generator identity and fixture hashes.
5. Screening output, used only to nominate replay candidates.

## Attempt preservation rule

Every material attempt receives an immutable directory under `artifacts/attempts/` containing its inputs, outputs, status, hypothesis, and reason for success or failure. Later refinements never overwrite those records. `artifacts/JOURNAL.jsonl` is the chronological machine-readable index.

## Attempts to date

### Attempt 001: assumed two-candidate minimization

Hypothesis: the NumPy full-corpus winner and fallback full-corpus winner alone would preserve the rank-0 flip.

Method: regenerate the seed-11, dimension-384, 4,000-vector fixture; retain only `symbol-00046` and `symbol-03962`; replay five times per lane across Python hash seeds 0, 1, 2, 11, and 101.

Result: failed to preserve the flip. Both lanes ranked `symbol-03962` first in all 50 replays. This falsified the minimization hypothesis, not the original 4,000-row counterexample.

Diagnostic consequence: candidate scores in the NumPy lane depend on matrix width or the selected matrix multiplication kernel. The next attempt sweeps corpus width while preserving both observed winners.

Raw evidence: `artifacts/attempts/attempt-001-two-candidate-minimization-failed/`.

### Attempt 002: matrix-width sweep

Hypothesis: the failure depends on NumPy matrix width or kernel selection.

Method: preserve both observed winners, sweep declared corpus widths from 2 through 4,000, and replay each width through both actual shipped scorers.

Result: succeeded. Four candidates preserve the rank-0 flip. The retained four-row fixture was replayed five times per lane across five Python hash seeds, producing 50 stable replays.

### Attempt 003: first provider-text allocation

Hypothesis: deterministic stepping through all corpus symbols would naturally distribute 5,000 text queries across all three corpora.

Result: failed coverage design. Django exhausted the global budget before the other corpora were reached. The vectors remain valid, but they do not satisfy the breadth claim.

Correction: preserve the biased manifest, replace implicit allocation with frozen quotas of 1,667 Django, 1,667 FastAPI, and 1,666 JCodeMunch queries, then regenerate before screening.

Raw evidence: `artifacts/attempts/attempt-003-biased-text-allocation/`.

### Attempt 004: balanced provider-text screen and actual replay

Method: freeze 5,000 local-ONNX vectors with explicit corpus quotas, bulk-screen all real candidates at top-k boundaries 1, 5, 10, 25, 50, and 100, then replay every nomination through both full actual shipped scorer lanes.

Result: 33 screen nominations, five actual ordered top-k findings, zero provider-reachable rank-0 or membership changes. All five actual findings reproduced through public `search_symbols` with tool/adapter parity.

### Attempt 005: hybrid amplification

Method: replay the five provider-reachable findings through public hybrid search at semantic weights 0.01, 0.1, 0.25, 0.5, 0.75, 0.9, and 0.99.

Result: 11 ordered differences across 35 cases, with zero membership or rank-0 changes.

### Attempt 006: public geometric counterexample

Method: index a legitimate four-function Python repository with v1.108.228, write the minimized float32 vectors through `EmbeddingStore`, inject the frozen valid query vector at the provider boundary, and invoke public `search_symbols` in both isolated environments.

Result: rank 0 flips with exact tool/adapter parity. NumPy returns `omega_boundary_candidate`; fallback returns `gamma_boundary_candidate`. All 24 candidate insertion orders preserve the flip.

### Attempt 007: provider replay under a newer ONNX Runtime

Hypothesis: v1.108.228's local ONNX provider would reproduce the frozen 5,000 text vectors byte-for-byte under a freshly installed current ONNX Runtime.

Method: install ONNX Runtime 1.28.0 in the isolated target lane, re-encode every frozen text in batches of 128, serialize each result as float32 bytes, and compare SHA-256 digests against both the stored vector and its frozen digest.

Result: failed. All 5,000 freshly encoded vectors differed, while every frozen vector still matched its stored digest. This identified ONNX Runtime version as an unrecorded reproducibility variable. The full mismatch record is preserved under `artifacts/attempts/attempt-007-onnxruntime-1.28-vector-reproduction-failed/`.

### Attempt 008: bounded dependency pin with a relative executable

Method: invoke isolated pip through the bounded runner using a relative interpreter path.

Result: failed before pip execution because the bounded runner requires the explicit executable path in this invocation. The launch-failure log is preserved. The repair used the absolute interpreter path.

### Attempt 009: provider replay under the generation runtime

Method: pin the isolated target lane to ONNX Runtime 1.24.4, the version recorded in the original generation environment, and repeat the complete 5,000-vector float32-byte comparison.

Result: passed. All 5,000 vectors reproduced byte-for-byte at 384 dimensions with zero mismatches. This validates the frozen provider-text suite while documenting that exact reproduction depends on the ONNX Runtime version.

## Provenance controls

`artifacts/provenance.json` records the clean target source commit, wheel digest, all three real-corpus database digests, provider reproduction receipt, and the independently passing original comparison packet manifest and verification receipt. The adversarial product does not modify or replace the original confirmatory packet.
