# Arc 4 run acceptance audit

This post-execution audit evaluates the current local study against DESIGN.md section 17. It is synthesis for review, not a preregistered input and not a manifest-bound measurement artifact.

## Overall status

**Research result status:** complete and directly cross-checked.

**Ordinary packet verification status:** passed in the retained review history. The current refined verifier has no final canonical receipt.

**Literal DESIGN.md run acceptance status:** incomplete. The final refined mutation run was intentionally stopped at an authenticated 53/93 prefix. Artifact-layout deviations are also disclosed below.

## Section 17 run criteria

| Requirement | Status | Authoritative evidence |
| --- | --- | --- |
| 240/240 matrix rows | Proven | `packet/verification.txt` reports 240 observed and 240 expected; independent stream reconciliation found 240 unique matrix rows |
| 120/120 matrix pairs | Proven | `packet/verification.txt` reports 120 observed and 120 expected; independent reconciliation found 120 complete matrix pairs |
| 24/24 preflight rows | Proven | `packet/verification.txt` reports 24 observed and 24 expected |
| 12/12 preflight pairs | Proven | Independent reconciliation found 12 complete preflight pairs; `packet/SUMMARY.json` reports 12 |
| P0 provenance gate passed | Proven | `packet/P0-RECEIPT.json` has `status: passed`; claim ceiling remains newline-normalized payload equivalence only |
| C1 through C21 all pass | Proven | `packet/verification.txt` reports 21/21; direct parsing found exactly 21 control files and every status was `passed` |
| Verifier passes | Proven in ordinary-verification history | Successful base receipts authenticated 434 manifest files with no error codes. The retained receipt is bound to an intermediate verification-only identity, not the current refined verifier |
| Verifier passes including self-tests | Not proven | Current authenticated progress is 53/93, next `failure_row_run_id`; the user directed that the active batch stop before a 93/93 receipt existed |
| No unrepaired failed `pair_id` | Proven | Seven failure records reference three pair IDs; all three occur in the final 132 successful pair records. Five additional failure records are rowless. No failed pair ID lacks a successful final pair record |
| M1 through M4 reported separately | Proven | `packet/SUMMARY.json`, `packet/REPORT.md`, and `RESEARCH-REPORT.md` retain separate rank-0, ordered top-k, membership, and exact-tie results |
| M10 through M12 reported | Proven | Exact score-delta totals, ordering margins, and first full-depth divergence ranks appear in `packet/SUMMARY.json` and `RESEARCH-REPORT.md` |

## Independent synthesis checks

The following read-only checks were performed outside the packet verifier:

- Recovered 264 unique rows and 132 unique two-lane pairs.
- Recovered 12 matrix ranking problems with exactly 10 replicated pairs per problem.
- Reproduced M1 through M6 totals, M10 candidate totals and maxima, and the complete M12 histogram.
- Found no disagreement between each matrix pair's public ordered-result comparison and its M2 flag.
- Reconstructed every matrix row's full ordering from retained exact score vectors and confirmed 240/240 exact public top-k matches.
- Confirmed all 48 problem-by-cache-state-by-lane cells contained five repetitions with one public top-k sequence and one full-depth ordering hash per cell.
- Parsed all 21 control files and confirmed every control status was `passed`.

The principal reconciliation logs are:

- `working/logs/attempt-e7987eab-ed37-4ac5-9716-24637deffe9c.log`
- `working/logs/attempt-ce4bb293-806a-4ed7-a3ce-471aec87e93b.log`
- `working/logs/attempt-90cac9bd-3157-4235-b1de-81783d9f9ff4.log`
- `working/logs/attempt-3b0aa691-4ab3-4c82-ba51-80e44275eab4.log`
- `working/logs/attempt-c1bc29f9-2f5f-45d9-9496-01347d811c07.log`

## Verification commands, refinement, and receipts

Successful base command:

```text
py -3 verify.py --write-receipt
```

Result: exit 0 in 198.136 seconds. The then-current canonical receipt authenticated 434 files with no errors. Command log: `working/logs/attempt-a147e9cc-847f-4591-b188-aeded6fa8bee.log`.

Uncompleted combined command:

```text
py -3 verify.py --self-test --write-receipt
```

Result: bounded timeout after 1,800.028 seconds, runner exit code 240, zero verifier output, no replacement receipt. Command log at `working/logs/attempt-7943c48e-5ae9-42ce-b9b9-da664c7b5da6.log`.

After explicit user authorization, `VERIFICATION-AMENDMENT.md` added verifier-only authenticated checkpoint and resume behavior. It changes no measurements or findings. The final refined verifier SHA-256 is `330E38FB2364D80123A4007F16A7A33EA4D36777E0232E0A730D96970CE0590C`; the corresponding 434-file manifest SHA-256 is `C37C4D350116C744AF42A18920CEFCA703BB425EF726EB91F2E103033CB580A3`.

The final-hash run reached these clean batch checkpoints: 21/93, 33/93, 41/93, and 49/93. The next batch authenticated a 53/93 prefix in `packet/self-test-progress.json`. The user then directed that work stop, and the exact active process tree was terminated. The next uncredited mutation is `failure_row_run_id`.

Final-hash checkpoint logs:

- `working/logs/attempt-dad669bd-f0b5-45d2-a65d-ff07b086b511.log`
- `working/logs/attempt-f3f88f41-e643-48e6-a846-9bf186b54c1b.log`
- `working/logs/attempt-34bae6fc-0d2f-4698-93cf-e48fe38b2055.log`
- `working/logs/attempt-80d06d8c-6334-4d34-9f17-f8e026434a72.log`
- `working/logs/attempt-ba08fd1c-596e-4751-bfbc-dc3fc2194a71.log` is empty because the 53/93 batch was stopped before output; its credited prefix is in the authenticated progress record.

The final narrow verifier correction passed the 7-test focused verifier suite in 68.343 seconds. The full 105-test suite passed before that correction and was not rerun afterward. If work resumes later, the exact 53/93 checkpoint may be used only while its verifier and manifest hashes still match. No resumption is currently requested.

## Artifact-layout audit

The retained evidence is sufficient to reproduce the material research claims, but the literal section 15.1 layout has these deviations:

- `TRANSFER-DECISIONS.json` is absent. The frozen decisions remain in DESIGN.md sections 5.2 and 5.3, with the resulting machine-readable decomposition in `packet/ORIGINAL-MATRIX-DECOMPOSITION.json`.
- The preregistration is represented by `PLAN.md`, `packet/PREREGISTRATION-INPUTS.json`, and `packet/PREREGISTRATION-COMMIT.json`, rather than `PREREGISTRATION.md`.
- `METHODOLOGY-JOURNAL.jsonl` is retained at the study root rather than inside `packet/`.
- `RESEARCH-REPORT.md`, `VERIFICATION-ANNOTATION.md`, and this audit are post-execution review documents and are intentionally not described as preregistered or manifest-bound inputs.

## Claim decision

The results may be described as complete fixed-suite research findings with direct reconciliation and successful ordinary-verification history. They must not be described as satisfying every literal design acceptance requirement because the refined mutation run stopped at 53/93, no final refined-verifier receipt exists, and the named-artifact layout has documented deviations.

No external state was changed.
