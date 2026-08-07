# JCodeMunch v1.108.228 Production-Lane Comparison Plan

Status: active local execution plan. Nothing in this project may be pushed, released, posted, or submitted without explicit user approval after the local evidence packet is complete.

## Objective

Measure whether JCodeMunch v1.108.228's shipped NumPy float32 and NumPy-absent pure-Python float64 embedding-scoring lanes produce different rankings on the same frozen real-embedding corpora and queries.

Report rank-0, ordered top-k, top-k membership, and exact-tie behavior separately. Produce a locally verified evidence packet and draft report. Do not describe this as a rerun of the earlier certification candidate.

## Approved question

The maintainer approved this comparison in the final Arc 4 response:

> Pin v1.108.228, where ties use `(-score, symbol_id)`. Compare the two shipped production lanes and report rank-0, ordered top-k, membership, and exact-tie results separately. Treat it as a new production-lane comparison, not a rerun of the unshipped certified scorer.

Authority: https://github.com/jgravelle/jcodemunch-mcp/issues/398#issuecomment-5177953577

The earlier packet compared its own exact baseline with a local float32 certification candidate. NumPy was present on every row, so it did not run the shipped NumPy-absent lane. This plan closes only that missing production-lane comparison.

## Deliverables

Create these local artifacts under this project directory:

- `harness/`: controller, isolated lane worker, comparison logic, and tests
- `config.json`: frozen sources, cases, environment contract, and expected coverage
- `working/`: disposable source checkout, environments, database copies, and incomplete runs
- `artifacts/raw/`: immutable completed trial records and first-repeat score evidence
- `artifacts/comparisons.jsonl`: one paired comparison per corpus and query
- `artifacts/summary.json`: recomputed aggregate counts and denominators
- `artifacts/manifest.json`: identities and SHA-256 for every retained input and output
- `REPORT.md`: concise findings, limitations, and exact reproduction command
- `verify.py`: standard-library verifier that rejects missing, duplicated, inconsistent, or tampered evidence
- `verification.txt`: captured PASS receipt from the final verifier and tamper self-test

Do not create a publication repository, release archive, GitHub comment, or issue draft during this goal.

## Source of truth

1. Current user instruction and this plan
2. The maintainer's approved comparison quoted above
3. Clean JCodeMunch tag `v1.108.228`, resolved to `8bed872e9436093be9f89d35fb84e0cb58a293af`
4. The frozen Arc 4 configuration and prepared query vectors in `<PUBLIC_EVIDENCE_ROOT>\arc4-real-embedding-certification-v1`
5. The matching local real-embedding databases listed below
6. Harness tests and retained raw evidence
7. Derived summaries and prose reports

The raw trial records are authoritative. Comparisons, summaries, and the report are rebuildable derived artifacts.

## Frozen inputs

### Production source

- Release: `v1.108.228`
- Tag commit: `8bed872e9436093be9f89d35fb84e0cb58a293af`
- Package version in `pyproject.toml`: `1.108.228`
- Production NumPy path: `EmbeddingMatrix._scores_numpy`
- Production fallback: `EmbeddingMatrix._scores_python`
- Production ranking key: `scored.sort(key=lambda x: (-x[0], x[1]["id"]))`

Use one clean detached checkout and build one wheel. Install that same wheel into both lane environments.

### Corpora

Use all three corpora from the earlier fixed suite. Their local database hashes match `prepared-inputs.json` exactly.

| Corpus | Role | Pinned source commit | Vectors | Local database | SHA-256 |
| --- | --- | --- | ---: | --- | --- |
| Django | authoritative | `274a1d494d11d87a1b767340d1f398f197810f93` | 45,561 | `local-django-3eb2e228.db` | `21767e35f79cf051c346389c90562126317fff9871ee9c7e4b33280fe3740529` |
| FastAPI | second point | `95f8322ee1dcda7ceace7b1c4f6c9915b36d748f` | 13,405 | `local-fastapi-c1d6b9c4.db` | `fb0f933f2fff75684a26872b86bc8f7b7301b7d08c54a079630c05ede760e61e` |
| JCodeMunch | control | `c78392cac0d50570d5cf86558d8d3674c0bea068` | 13,960 | `local-arc4-research-v1-upstream-6f37f3de.db` | `9b6a007e9554a7afdb98936180d0abebce8b86693d842841122c72e9093cdc58` |

Local source directory:

`<LOCAL_RESEARCH_ROOT>\candidate-cold-hydration-vetting\arc4-real-embedding-certification-v1\working\indexes`

Never run a trial against these source files. Verify them, then copy each database into trial-local scratch. Preserve the JCodeMunch database locally because its indexed source text is not cleared for redistribution.

### Queries

Reuse the four query strings, query vectors, serialized arguments, top-k values, and SHA-256 values from:

`<PUBLIC_EVIDENCE_ROOT>\arc4-real-embedding-certification-v1\prepared-inputs.json`

| Query ID | Mode | Top-k |
| --- | --- | ---: |
| `semantic_input_validation` | semantic-only | 10 |
| `semantic_transaction_persistence` | semantic-only | 25 |
| `hybrid_authentication_middleware` | hybrid, semantic weight 0.5 | 10 |
| `hybrid_test_client_response` | hybrid, semantic weight 0.5 | 25 |

Do not regenerate embeddings or alter the query suite after inspecting lane results.

## Measurement design

### Unit and coverage

The primary unit is one paired case: one corpus and one frozen query scored once by each production lane.

- 3 corpora x 4 queries = 12 paired cases
- 2 lanes per case
- 2 independent fresh-process repetitions per lane
- Expected raw trial coverage: 48 lane trials
- Statistical denominator: 12 paired cases, never 48 trials

The second repetition is a determinism check. It does not increase the evidentiary sample size. If repetitions disagree within a lane, report nondeterminism and do not average or select a preferred repetition.

### Environments

Create two isolated virtual environments from the same Python executable and install the same locally built v1.108.228 wheel plus identical common dependencies.

`numpy` lane:

- Install and record NumPy explicitly, initially matching the earlier host at `2.4.4` when compatible with the selected Python.
- Prove `EmbeddingMatrix.vectorised is True` for every trial.
- Record NumPy version, Python version, platform, CPU identity, and `pip freeze` hash.

`python` lane:

- Do not install NumPy or any extra that brings it in.
- Prove `import numpy` fails before every batch.
- Prove `EmbeddingMatrix.vectorised is False` for every trial.
- Record Python version, platform, CPU identity, and `pip freeze` hash.

Build the wheel once. Record its SHA-256. Reject a run if source identity, wheel identity, Python major/minor, or common dependency manifests differ across lanes beyond the declared NumPy difference.

### Query injection

The query embedding must be byte-for-byte the frozen vector from `prepared-inputs.json`. Do not invoke an embedding provider during measurement.

Inside the isolated worker, replace only the provider detection and query-embedding call needed to return the frozen vector. The worker must then run the actual v1.108.228 search path, including:

- Production database loading
- Production `EmbeddingMatrix` construction
- Production lane-specific `score_all`
- Production hybrid score combination where applicable
- Production `(-score, symbol_id)` ordering
- Production top-k result creation

Before calling the tool, assert that every indexed candidate expected by the case already has an embedding. Refuse the case if production code would top up or write missing embeddings.

### Raw-score adapter

The public tool response does not expose full-precision candidate scores. Add a measurement adapter that uses the production matrix scorer and production lexical helpers to retain each candidate's cosine and final ranking score.

The adapter is acceptable only if its ordered top-k IDs exactly equal the actual production tool response for every lane trial. A mismatch invalidates the trial and blocks reporting.

Persist floating-point values as `float.hex()` strings. Decimal renderings are derived display values only.

For each case, retain the full candidate-score evidence from the first repetition. For the second repetition, retain the full evidence hash and top-k result. If it differs, retain the full second evidence file for diagnosis.

### Isolation and ordering

- Start a fresh subprocess for every lane trial.
- Copy the frozen database into a unique trial directory.
- Run one measured query in that subprocess.
- Use a deterministic, precomputed lane order balanced across cases so one lane is not always first.
- Do not make timing or performance claims. Timing may be retained only as diagnostic metadata.
- Never reuse an `EmbeddingMatrix` across cases or repetitions.

## Required metrics

For each of the 12 paired cases, calculate:

### Rank 0

- NumPy top ID
- Python top ID
- Exact equality boolean

### Ordered top-k

- Ordered IDs from each lane
- Exact ordered-list equality boolean
- First differing rank, or null
- Count and identities of rank positions that differ

### Membership

- Exact set equality boolean
- NumPy-only IDs
- Python-only IDs
- Symmetric-difference count

### Exact ties

Define an exact tie as bit-exact equality of final production ranking scores within one lane. Do not apply an epsilon to this category.

Report separately for each lane:

- Full-ranking exact-tie group count and participant count
- Exact ties intersecting the returned top-k
- Exact ties crossing the top-k boundary
- The symbol-ID order used inside each relevant tie group

For every cross-lane ranking disagreement, report whether the involved candidates participate in an exact tie in either lane. Do not classify an unequal near tie as an exact tie.

### Diagnostic numeric differences

Retain but do not headline:

- Maximum and median absolute cosine-score difference
- Maximum and median absolute final-score difference
- Candidate IDs at the largest differences

These diagnostics explain scale. They are not a substitute for ranking comparisons.

## Controls

### Positive divergence control

Before running the real corpora, prove that the comparator can detect a real lane difference. Use the deterministic near-tied fixture described by v1.108.228's regression evidence, starting with seed 11, dimension 384, and the 4,000-vector form cited by the maintainer.

The control must produce and correctly classify at least one rank-0 or ordered top-k divergence between the actual production lane scorers. If that exact fixture no longer produces a divergence on the pinned environment, make up to three deterministic, documented fixture refinements before declaring the comparator non-vacuous. Freeze the successful control and its hash before inspecting real-corpus comparisons.

This is a diagnostic positive control, not part of the 12-case real-corpus denominator.

### Exact-tie control

Use identical vectors with deliberately reversed insertion order. Prove both lanes order exact ties by ascending symbol ID and classify the tie separately from numeric lane disagreement.

### Negative control

Run identical lane evidence through the comparator and prove that it reports no rank, order, membership, or score difference.

## Artifact schema

Each raw trial record must include:

- Schema version
- Run ID, trial ID, paired-case ID, repetition, and execution order
- Corpus name, role, source commit, database name, database SHA-256, vector count, and embedding identity
- Query ID, exact text, query-vector SHA-256, semantic mode, weight, and top-k
- JCodeMunch tag, source commit, wheel SHA-256, source cleanliness, and production-function identities
- Lane requested and lane actually selected
- Python, NumPy or explicit absence, SQLite, platform, CPU, and dependency-manifest identity
- Actual tool ordered top-k IDs
- Adapter ordered top-k IDs and parity result
- Score-evidence path and SHA-256
- Terminal status and exact failure reason when incomplete

Never write a success row for an incomplete or unclassified trial.

## Harness workflow

1. **Preflight:** Verify all local sources, hashes, licenses, disk space, Python availability, and the v1.108.228 remote tag identity.
2. **Build:** Create a clean detached local source checkout, build one wheel, and create the two isolated lane environments.
3. **Freeze:** Generate `config.json` from the existing prepared inputs and fixed identities before any real-corpus lane result is inspected.
4. **Test:** Run unit tests plus positive-divergence, exact-tie, and negative controls.
5. **Screen:** Run one paired case from each query mode and verify true lane selection, tool/adapter parity, and evidence completeness.
6. **Measure:** Run the complete 48-trial matrix. Resume by immutable trial identity; never overwrite a completed trial.
7. **Compare:** Pair first repetitions, check second-repetition identity, and derive all required metrics.
8. **Verify:** Enforce coverage, schema, source identity, hashes, pairability, non-vacuity, and recomputation from raw evidence.
9. **Report:** Write the fixed-suite result with exact denominators, limitations, and no population claim.
10. **Hold locally:** Stop after the validated local handoff. Await explicit approval before any publication action.

## Verification contract

`verify.py` must use only the Python standard library and fail closed on:

- Unknown schema or column names
- Missing or duplicate cases, lanes, or repetitions
- Any row count other than the expected 48 completed lane trials
- Any paired-case count other than 12
- Source, wheel, database, query, environment, or artifact hash mismatch
- A requested lane not matching the selected production lane
- Tool output differing from the raw-score adapter
- Repetitions differing without an explicit nondeterminism failure state
- Summary or report claims not reproducible from raw records
- A positive control that did not demonstrate comparator non-vacuity
- Exact-tie controls not ordered by symbol ID
- Paths or private source material in a public-safe export inventory

Run a tamper self-test on disposable copies that changes one score, removes one trial, changes one lane label, and alters one summary value. Every mutation must be detected.

## Reporting rules

- Report exact counts as `x/12 paired cases`, plus per-corpus and per-query tables.
- State that the suite is fixed and purposive, not a random sample.
- Do not calculate or imply population prevalence from the 12 cases.
- Do not count the second repetitions as additional cases.
- If no disagreement is observed, write: `No disagreement was observed in this fixed 12-case suite.`
- Never write that divergence is impossible or that the hazard does not occur in practice generally.
- If disagreement is observed, distinguish rank-0, ordered-only, membership, and exact-tie-associated cases.
- Separate observed facts from explanations and hypotheses.
- State that v1.108.228 includes the deterministic tie-break but not the earlier certified scorer candidate.
- State that this is a new production-lane comparison.

## Acceptance criteria

The local project is complete only when:

- All frozen input identities match their recorded sources.
- Both isolated environments use the same wheel and select the intended production lane.
- Controls prove divergence detection, exact-tie handling, and no-difference handling.
- All 48 trials complete with no missing or duplicated identity.
- All 12 paired comparisons are reproducible from retained raw evidence.
- Every actual tool top-k equals its adapter top-k.
- Within-lane repetitions are identical, or the project reports nondeterminism and does not issue a ranking verdict.
- `verify.py` passes normally and rejects every tamper self-test.
- `REPORT.md` uses only claims supported by verified artifacts.
- No artifact has been pushed, released, or posted.

## Stopping and escalation

Ordinary test failures, environment setup problems, or surprising results are not reasons to weaken the measurement.

If the same genuine blocker remains after three materially different repair attempts, stop without issuing a verdict. Record each attempt, the evidence inspected, the likely cause, and the exact capability or decision needed to continue.

Do not substitute the earlier certification harness, approximate a missing lane, regenerate the corpus, omit failing cases, or publish partial results.

## Final handoff

Report locally:

- The exact question answered
- Source, corpus, query, environment, and harness identities
- Coverage and control results
- Rank-0, ordered top-k, membership, and exact-tie findings
- Reproducibility and verifier results
- Limitations and unresolved risks
- Every created or changed local file
- Confirmation that nothing was published
- The single next action: user review and publication decision
