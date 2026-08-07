# JCodeMunch v1.108.228 Adversarial Production-Lane Falsification Plan

## Objective

Earnestly attempt to falsify ranking equivalence between JCodeMunch v1.108.228's shipped NumPy float32 and NumPy-absent pure-Python float64 scoring lanes by using valid production scoring inputs. Seek reproducible rank-0, ordered top-k, membership, exact-tie, and fresh-process determinism failures. A failure is a successful experimental finding, not a harness failure.

This is a separate product and experiment from `arc4-production-lane-comparison-v1`. Do not edit, merge, or reinterpret that packet. Its fixed 12-case result is prior evidence only.

Keep all artifacts local. Do not push, publish, release, post, or submit anything.

## System under test

- JCodeMunch tag `v1.108.228`
- Commit `8bed872e9436093be9f89d35fb84e0cb58a293af`
- Shipped `EmbeddingMatrix._scores_numpy`
- Shipped `EmbeddingMatrix._scores_python`
- Shipped `search_symbols` semantic and hybrid ranking path
- Shipped `(-score, symbol_id)` ordering

Build one clean wheel and install it into isolated NumPy-present and NumPy-absent environments. A counterexample is reportable only after replay through both actual shipped lane implementations. Public-path claims additionally require parity with the actual production `search_symbols` response.

## Falsification threat model

Search for differences caused by:

1. float32 versus float64 query normalization and dot accumulation;
2. stored-vector normalization differences between lane constructors;
3. near-equal candidates around rank 0 and top-k boundaries;
4. hybrid lexical/semantic mixtures that amplify or cancel small cosine differences;
5. exact ties created, removed, or reordered by one lane;
6. insertion-order and symbol-ID interactions;
7. query text transformations that are valid user inputs: symbol names, signatures, code vocabulary, typos, punctuation, casing, repetition, long text, and ambiguous multi-concept phrases;
8. fresh-process environment variation, including explicitly swept Python hash seeds;
9. top-k boundaries at 1, 5, 10, 25, 50, and 100.

## Input families

### Provider-reachable text queries

Generate deterministic text queries from real symbols in the frozen Django, FastAPI, and JCodeMunch corpora. Embed them with the locally available `local_onnx` `all-MiniLM-L6-v2` production provider. These are the strongest externally reachable tests because an ordinary semantic search can produce them.

### Corpus-derived geometric queries

Construct deterministic vectors from real stored embeddings: exact rows, normalized sums and differences, near-neighbor bisectors, and ULP-scale perturbations around candidate-pair equality boundaries. These probe the scorer contract directly. Label them separately from provider-reachable text and do not imply that every constructed vector is reachable from natural language.

### Hybrid adversarial queries

Use real query text and its provider-produced vector. Sweep semantic weights around production-relevant values and target candidates whose lexical and semantic channels nearly cancel at top-k boundaries.

## Search strategy

1. Verify source, wheel, corpora, provider, and environments.
2. Extract deterministic real-symbol text seeds and generate a broad query corpus before lane results are inspected.
3. Embed text queries once and retain exact vectors and hashes.
4. Use a vectorized differential screen to rank candidate queries and boundaries by minimum cross-lane margin. Screening may use mathematically equivalent bulk calculations for speed, but cannot establish a finding.
5. Replay every screen hit through the actual shipped lane scorers in isolated fresh processes.
6. Replay externally reachable hits through the actual production `search_symbols` path and require tool/adapter parity.
7. Minimize each counterexample while preserving the failure: fewer candidates, shorter query text when applicable, smallest top-k, and stable identities.
8. Repeat each counterexample at least five times per lane and across a declared Python hash-seed sweep.
9. Continue searching after the first failure to classify distinct failure modes.

## Required coverage

The run is incomplete until it has attempted all of the following:

- all three frozen real corpora;
- at least 5,000 provider-reachable text queries total;
- at least 10,000 corpus-derived geometric queries total;
- semantic-only and hybrid production paths;
- every top-k boundary in `{1, 5, 10, 25, 50, 100}`;
- Python hash seeds `{0, 1, 2, 11, 101}`;
- the known deterministic near-tied positive control;
- at least five actual-lane repetitions for each retained counterexample.

Coverage targets are floors, not stopping rules when the search is still finding new failure classes.

## Findings and non-findings

A retained finding must include:

- exact input text and/or vector bytes and SHA-256;
- corpus and candidate identities;
- lane-selected proof;
- full relevant scores as `float.hex()`;
- rank-0, ordered top-k, membership, and exact-tie classification;
- actual shipped-scorer replay;
- production-tool replay when the input is provider-reachable;
- minimization result;
- five-repeat and hash-seed reproducibility matrix.

If no provider-reachable failure is found, report only the exact searched domain and coverage. Do not claim equivalence or safety. Geometric failures remain valid scorer counterexamples but must be labeled as geometric unless provider reachability is demonstrated.

## Deliverables

- `harness/`: generators, screen, isolated replay worker, minimizer, tests
- `config.json`: frozen identities, generation seeds, coverage floors
- `working/`: disposable environments, source, database copies, incomplete runs
- `artifacts/queries/`: frozen text and geometric query manifests
- `artifacts/screens/`: immutable screening results
- `artifacts/findings/`: complete counterexample evidence
- `artifacts/coverage.json`: attempted coverage and denominators
- `artifacts/summary.json`: failure classes and counts
- `artifacts/manifest.json`: SHA-256 inventory
- `REPORT.md`: adversarial findings, non-findings, limits, reproduction
- `verify.py`: standard-library fail-closed verifier
- `verification.txt`: normal and tamper-test PASS receipt

## Acceptance criteria

- The comparison packet remains byte-for-byte untouched.
- Frozen source and corpus identities match.
- The text-query provider is the recorded local production provider.
- Coverage floors are met without silently omitting failures.
- Screening is never used as final proof.
- Every finding reproduces through actual shipped lanes.
- Every provider-reachable finding also reproduces through the production tool path.
- Counterexamples are minimized and repeated as specified.
- The verifier recomputes coverage and findings and rejects score, query, lane, coverage, and summary tampering.
- The report distinguishes provider-reachable, geometric, hybrid, determinism, and control findings.
- Nothing is published.

## Stop condition

Stop after a verified local handoff for user review. If the same genuine blocker survives three materially different repairs, stop without an equivalence verdict and report the attempts, evidence, likely cause, and exact unblocker.
