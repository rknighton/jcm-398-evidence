# Arc 4 production-lane comparison: research report

## Executive finding

On this frozen, purposive suite, JCodeMunch 1.108.228 returned the same public rank-0 result, ordered top-k list, and top-k membership in the NumPy-present and NumPy-absent production lanes for all 120 planned matrix pairs.

That top-k parity does not mean the lanes were equivalent. Every compared candidate's raw cosine score differed at the bit level, 80 of 120 pairs had different exact-tie partitions, and 100 of 120 pairs first diverged somewhere in the full ranking. The earliest full-depth divergence occurred at zero-based rank 1,555. Across the suite there were 820 strict full-depth score inversions and 540 full-depth tie-versus-distinguished disagreements, while both counts were zero within the public top-k.

The supported conclusion is therefore narrow:

> The shipped NumPy-present and NumPy-absent lanes produced the same public top-k results on these 12 frozen ranking problems, while measurably differing in floating-point scores, exact ties, and deep ranking order.

This result does not estimate production incidence, does not establish that top-k divergence is impossible, and does not generalize beyond the frozen suite and environment.

## Research question and scope

The study asks whether the two shipped production execution lanes differ on retained real inputs when all planned non-lane factors are held fixed.

| Item | Frozen scope |
| --- | --- |
| Product | JCodeMunch 1.108.228 |
| Production lanes | NumPy present and NumPy absent |
| Corpora | Django, FastAPI, JCodeMunch |
| Query vectors | 4 researcher-authored vectors |
| Ranking problems | 12 corpus-by-query problems |
| Cache states | 2 per problem |
| Repetitions | 5 per cache state |
| Matrix pairs | 120 |
| Matrix rows | 240 |
| Preflight pairs | 12, excluded from findings denominators |
| Preflight rows | 24 |
| Total executed rows | 264 |

The 120 pair comparisons are replicated executions, not 120 independent research problems. The closest findings-level unit is the set of 12 ranking problems, and even those are not independent draws because four query vectors are reused across three corpora. Cache states and repetitions provide repeatability evidence, not additional query diversity.

## Findings

### Public top-k results

| Metric | Pair result | Problem result | Interpretation |
| --- | ---: | ---: | --- |
| M1 rank-0 difference | 0 / 120 | 0 / 12 | No observed rank-0 difference |
| M2 ordered top-k difference | 0 / 120 | 0 / 12 | No observed ordered-list difference |
| M3 top-k membership difference | 0 / 120 | 0 / 12 | No observed membership difference |
| M4 exact-tie partition difference | 80 / 120 | 8 / 12 | Tie structure differed despite identical top-k output |

There were no no-result exclusions and no within-problem heterogeneity for M1 through M4. Each problem either showed the same finding in every cache-state and repetition pair or showed no finding in every pair.

### Same-lane repeatability

M7 was checked directly across the 48 problem-by-cache-state-by-lane cells. Every cell contained the planned five repetitions. Within every cell, all five public top-k lists were identical and all five full-depth ordering hashes were identical. No same-lane nondeterministic cell was observed in the frozen environment.

### Ordering disagreements

| Metric | Public top-k | Full ranking |
| --- | ---: | ---: |
| M5 strict score inversions | 0 | 820 |
| M6 tie-versus-distinguished disagreements | 0 | 540 |

These findings locate the observed lane effect below the returned top-k boundary in this suite. They establish real arithmetic and ordering divergence on retained inputs. They do not establish how often a production query would encounter such divergence or whether a different query could move it into the public top-k.

### Score differences

Raw cosine comparison covered all 120 matrix pairs and 2,917,040 candidate comparisons. No candidate score was bit-identical between lanes. The maximum absolute raw-cosine delta was `1.0292171037651343e-07`.

Hybrid final-score comparison covered the 60 hybrid matrix pairs and 1,458,520 candidate comparisons. No compared hybrid final score was bit-identical between lanes. The maximum absolute hybrid delta was `5.146085524376787e-08`.

The score deltas were sufficient to change exact ties and deep ordering, but not sufficient to change any public top-k result in the frozen suite.

### Ordering margins

The reported ordering margins are dimensionless score-gap-to-perturbation ratios. Observed margins use the measured local perturbation denominator and treat exact ties as a separate category. Conservative margins use the larger conservative denominator and assign tie cases a value of zero.

| Lane ordering | Boundary minimum, strict cases | Boundary exact ties | Internal top-k minimum, strict cases | Internal exact ties |
| --- | ---: | ---: | ---: | ---: |
| NumPy ordering | 4,388.5527 | 40 / 120 | 7,620.2470 | 80 / 120 |
| Python ordering | 4,389.5527 | 40 / 120 | 7,621.2470 | 80 / 120 |

The conservative boundary distribution therefore contains 40 zeros per lane, and the conservative minimum-internal distribution contains 80 zeros per lane. Those zeros represent exact-tie conditions. They should be read together with M4 and M6, not as ordinary positive-gap cases.

### First full-depth divergence

Twenty of 120 pairs had no full-depth ordering divergence. The other 100 pairs first diverged at the following ranks:

| First divergent rank, zero-based | Pair count |
| ---: | ---: |
| 1,555 | 10 |
| 1,852 | 10 |
| 1,888 | 10 |
| 2,377 | 10 |
| 3,065 | 10 |
| 3,624 | 10 |
| 4,744 | 10 |
| 4,916 | 10 |
| 5,189 | 10 |
| 7,904 | 10 |
| No divergence | 20 |

The identical count of 10 at each divergent rank reflects the two cache states and five repetitions for a ranking problem. It is repeatability evidence, not ten independent discoveries.

## Execution integrity and corrections

The completed packet reports all 21 planned controls passing. Direct inspection found exactly 21 control files and a `passed` status in every file. The packet reports zero public-tool errors, zero lane-selection mismatches, zero fallback firings, zero embedding-write tripwire firings, and zero infrastructure failures in the accepted observations.

The preserved failure record contains 12 failed precondition attempts. These were research execution and reconstruction problems, not observations that the product lanes failed. They were retained rather than deleted or silently replaced. Two planned pair identities ultimately succeeded after explicit repairs:

- `django:hyb_auth_middleware__verbatim:cold_fresh_process:r01` succeeded on attempt 5 during preflight.
- `django:hyb_auth_middleware__semantic:cold_fresh_process:r01` succeeded on attempt 3 during the matrix.

The main corrections were:

1. Reconstructing the production lexical and hybrid score channels with the shipped formulas rather than a normalized approximation.
2. Matching the public debug-score rounding used by each mode.
3. Correctly representing the unset `PYTHONHASHSEED` state.
4. Separating control failures from the measured pair's repair history.
5. Normalizing retained evidence fields at the packet boundary without discarding the original failure record.

One preflight acceptance check was changed from literal ordered top-k equality at a tied cutoff to score-consistent top-k acceptance, while still requiring agreement between public and debug output. That decision affects preflight contract checking only. Preflight rows are excluded from all findings denominators. The matrix requirement remains exact agreement between public ordered top-k and full-depth reconstruction on every measured row.

## Provenance

| Artifact | Frozen identity |
| --- | --- |
| Governing design | `DESIGN.md` |
| Design SHA-256 | `4E885E262545660378CA508748AB5A8DF49CF1AA8B2AF96DDA0A6748AFE88FBE` |

> **Publication note.** The digest quoted above is the pre-normalization identity of `DESIGN.md`, recorded in `SOURCE-HASHES.sha256`. The published copy had a machine-specific research root replaced with a placeholder and therefore hashes differently. The design content is unchanged. See PROVENANCE-ANNOTATION.md.
| Authorization | GitHub issue 398 comment 5177953577: production-lane comparison approved on the design's terms |
| Treatment version | 1.108.228 |
| Official wheel SHA-256 | `FF74B6344430053C6FAD9064892D6A3904FFBA6265823E3FBA4DFDE78F9A0488` |
| Source commit | `8bed872e9436093be9f89d35fb84e0cb58a293af` |
| Preregistration commit | `78b6cc56f3262ba90b367c889f5646b929dfba6b` |
| Frozen config SHA-256 | `61ed1e53c3da52e743ad0d8161a7ff9077b684421a5939a47e3297466bfd3f08` |
| Prepared-inputs SHA-256 | `623B077E57D0C6C8B0207C5124DD93E05A1A42D9015F92FD6EF0E5161C6E07C0` |
| Original-matrix SHA-256 | `F50451015E4B56522FDBCA84EDDD677ECF3DA77724E054A75C1E2E69005DA303` |

The P0 provenance ceiling is newline-normalized payload equivalence. It does not establish a reproducible build, the publisher's build environment, or end-to-end supply-chain authenticity.

Raw accepted rows, warmups, pair records, full rankings, invocation receipts, environment locks, controls, failure and repair journals, hashes, and the packet verifier are retained under `packet/`. Earlier setup failures remain under `working/failed-stage-*` and in the journals.

### Packet-completeness annotation

The evidence is present, but the final layout does not literally match every filename and location specified in DESIGN.md section 15.1:

- The required standalone `TRANSFER-DECISIONS.json` is absent. The substantive transfer decisions and their effects were frozen in DESIGN.md sections 5.2 and 5.3, and `packet/ORIGINAL-MATRIX-DECOMPOSITION.json` preserves the resulting matrix decomposition. This is a named-artifact completeness defect and should not be retroactively presented as preregistered repair.
- The preregistration is represented by `PLAN.md`, `packet/PREREGISTRATION-INPUTS.json`, and `packet/PREREGISTRATION-COMMIT.json`, rather than the named `PREREGISTRATION.md`.
- `METHODOLOGY-JOURNAL.jsonl` exists at the study root rather than inside `packet/`.
- The generated `packet/REPORT.md` is a short machine-produced summary. This researcher-facing report supplies the fuller interpretation, margin values, corrections, and caveats, but was written after observation and is therefore synthesis rather than a preregistered input.

These differences do not change the retained row values or the independently reconciled metric totals. They do prevent an unqualified claim that the review packet exactly matches every section 15.1 artifact requirement.

## Compatibility with issue 398

The work stays within the issue 398 authorization as recorded in the frozen provenance: it is the approved production-lane comparison, uses the design's stated local research scope, and does not push, publish, comment, or otherwise mutate external state. The results are held locally for review.

## Claim ceiling and limitations

This is a descriptive census of a fixed purposive suite. No p-values, confidence intervals, hypothesis tests, prevalence estimates, timing conclusions, or memory conclusions are supported.

Required limitations are:

- Four researcher-authored query vectors are reused across three corpora.
- The 12 ranking problems are not independent random draws.
- NumPy-lane results can depend on the frozen BLAS and environment.
- Full-depth hybrid evidence relies on a reconstruction adapter whose matrix top-k parity must be verified against public output.
- The private-source-derived control corpus remains local.
- The study measures one frozen product version and one frozen environment.
- Zero public top-k differences in this suite do not establish that divergence cannot occur elsewhere.
- Non-zero deep-ranking findings establish possibility on retained real inputs, not prevalence.

## Verification status

All 264 planned rows and all 132 paired records are present, and the generated summary reports a complete verdict. A separate read-only reconciliation recovered 240 matrix rows, 24 preflight rows, 120 matrix pairs, 12 preflight pairs, 12 ranking problems, and exactly 10 matrix pairs per problem. It independently reproduced the reported M1 through M6 and M10 through M12 totals, found no public-pair metric mismatches, and found no within-problem heterogeneity in M1 through M4.

A second direct check reconstructed the final ranking from each retained matrix score vector using descending score and symbol-ID tie-breaking. All 240 reconstructed ordered top-k lists exactly matched the public tool output, with zero mismatches across all four matrix forms.

A third direct check grouped matrix rows into 48 problem-by-cache-state-by-lane cells. Every cell contained five repetitions, and no cell differed in either public top-k output or full-depth ordering hash.

The original combined campaign finalization reached its 900-second execution bound without producing a receipt. Ordinary verification was then run directly using the packet verifier:

`py -3 verify.py --write-receipt`

That invocation completed in 198.136 seconds with exit code 0 and wrote `packet/verification.txt`. The receipt reported `status: verified`, `verdict: complete`, 240/240 matrix rows, 120/120 matrix pairs, 24/24 preflight rows, 21/21 controls, 434 verified manifest files, and no error codes. Because the invocation omitted the mutation suite, it recorded 0/93 self-tests.

The original all-or-nothing mutation invocation was then run directly:

`py -3 verify.py --self-test --write-receipt`

It remained CPU-active until the bounded runner stopped it at 1,800.028 seconds. It emitted no verifier output and did not replace the successful base receipt. The exact bounded-command logs are `working/logs/attempt-a147e9cc-847f-4591-b188-aeded6fa8bee.log` for successful base verification and `working/logs/attempt-7943c48e-5ae9-42ce-b9b9-da664c7b5da6.log` for the self-test timeout.

After explicit user authorization, `VERIFICATION-AMENDMENT.md` added verifier-only authenticated checkpoint and resume behavior without changing measurements or findings. Concrete production-packet mutation defects were corrected as they surfaced. The final refined verifier is identical in `harness/verify.py` and `packet/verify.py` at SHA-256 `330E38FB2364D80123A4007F16A7A33EA4D36777E0232E0A730D96970CE0590C`; the corresponding 434-file manifest is SHA-256 `C37C4D350116C744AF42A18920CEFCA703BB425EF726EB91F2E103033CB580A3`.

The final-hash mutation run reached an authenticated 53/93 prefix. The next uncredited test is `failure_row_run_id`. The user then directed that packet work stop, so the active batch was terminated and the checkpoint retained. The current `packet/self-test-progress.json` is resumable state, not a success receipt. `packet/verification.txt` remains an earlier base receipt bound to an intermediate verifier and manifest and must not be presented as final verification of the refined verifier.

The current consolidated packet status, clean checkpoint logs, invalidated checkpoint provenance, validation limits, and optional future resumption rule are recorded in `PACKET-STATUS.md`.

The completed data and headline findings have been independently reconciled as described above. The appropriate current status is: **research findings complete and directly cross-checked; ordinary packet verification passed in the review history; formal packet acceptance remains incomplete because the mutation suite stopped at 53/93, the current refined verifier has no final receipt, and the named-artifact layout has documented gaps.**
