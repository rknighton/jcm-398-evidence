# Arc 4 verification annotation

Recorded on 2026-08-06 in America/New_York after the completed local production-lane observations.

## Scope

This annotation records verifier execution after synthesis. It does not change the frozen design, preregistration, treatment, input data, measured rows, pair records, metrics, or controls. `packet/verification.txt` and the verification-only `packet/self-test-progress.json` are generated verifier state excluded from the manifest to avoid circular identity.

Governing design SHA-256: `4E885E262545660378CA508748AB5A8DF49CF1AA8B2AF96DDA0A6748AFE88FBE`.

> **Publication note.** The digest quoted above is the pre-normalization identity of `DESIGN.md`, recorded in `SOURCE-HASHES.sha256`. The published copy had a machine-specific research root replaced with a placeholder and therefore hashes differently. The design content is unchanged. See PROVENANCE-ANNOTATION.md.

Initial base-verification verifier SHA-256: `DB76B2EBD7C05D4384E870C157007168E08C344880BF06C69ECEA7671F824B94`.

Initial base-verification manifest SHA-256: `FECE0839A779D0F94B028592B21223BB4EC1D6DB7E5228213E64BA9951DCEF0A`.

Current refined verifier SHA-256: `330E38FB2364D80123A4007F16A7A33EA4D36777E0232E0A730D96970CE0590C`.

Current refined manifest SHA-256: `C37C4D350116C744AF42A18920CEFCA703BB425EF726EB91F2E103033CB580A3`.

## Base verification

Command, executed with `packet/` as the working directory:

```text
py -3 verify.py --write-receipt
```

The command completed in 198.136 seconds with child exit code 0. It produced the following canonical receipt and wrote the identical content to `packet/verification.txt`:

```json
{"schema":"arc4.verification-receipt/v1","status":"verified","verifier_sha256":"db76b2ebd7c05d4384e870c157007168e08c344880bf06c69ecea7671f824b94","manifest_sha256":"fece0839a779d0f94b028592b21223bb4ec1d6db7e5228213e64ba9951dcef0a","matrix_rows_observed":240,"matrix_rows_expected":240,"matrix_pairs_observed":120,"matrix_pairs_expected":120,"preflight_rows_observed":24,"preflight_rows_expected":24,"controls_passed":21,"controls_expected":21,"manifest_files_verified":434,"self_tests_passed":0,"self_tests_expected":93,"verdict":"complete","error_codes":[]}
```

Receipt and successful command-log SHA-256: `9A588A0DFF80A42EB29B26B1A7437C440117843B2A05AB365741CF9CF8FFC429`.

Successful command log: `working/logs/attempt-a147e9cc-847f-4591-b188-aeded6fa8bee.log`.

Interpretation: base verification passed at that verifier and manifest identity. The verifier authenticated 434 manifest-listed files and independently accepted the required row, pair, preflight, control, summary, and report content. The receipt records zero self-tests because this invocation did not request the mutation suite.

`packet/verification.txt` was later replaced by another successful base receipt during verification-only refinement. Its current contents remain a valid historical base pass, but they are bound to intermediate verifier SHA-256 `441F75D9F1C4FA025268B16030543C0EC1E3B3C39FE24DCE31705EE0BE67CE95` and manifest SHA-256 `B0217F554F5F64EA15DF93554FF2960C867E65C4D68A1919C3526C779ADCB8DA`, not the final refined hashes above.

## Original mutation self-test attempt

Command, executed with `packet/` as the working directory:

```text
py -3 verify.py --self-test --write-receipt
```

The process remained CPU-active until the bounded runner stopped it at 1,800.028 seconds. The bounded runner reported `exit_reason: timeout` and `runner_exit_code: 240`. The verifier emitted zero bytes, so it produced no canonical receipt and did not replace the successful base `packet/verification.txt`.

Timeout command log: `working/logs/attempt-7943c48e-5ae9-42ce-b9b9-da664c7b5da6.log`.

The timeout log is empty because the verifier writes its canonical JSON only after completing the full run. Empty-log SHA-256: `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`.

Interpretation: the original all-or-nothing invocation did not establish a mutation-suite result. This was a formal acceptance gap, not evidence of a research-result discrepancy.

## Verification-only refinement and stopped run

After explicit user authorization, `VERIFICATION-AMENDMENT.md` added authenticated checkpoint and resume behavior. The amendment changed no measurement, pair record, metric, control, or finding. It also records narrow corrections to mutation fixtures that made assumptions inconsistent with the production packet.

The final-hash run produced these clean checkpoints:

- 21/93: `working/logs/attempt-dad669bd-f0b5-45d2-a65d-ff07b086b511.log`
- 33/93: `working/logs/attempt-f3f88f41-e643-48e6-a846-9bf186b54c1b.log`
- 41/93: `working/logs/attempt-34bae6fc-0d2f-4698-93cf-e48fe38b2055.log`
- 49/93: `working/logs/attempt-80d06d8c-6334-4d34-9f17-f8e026434a72.log`

The next batch authenticated tests 50 through 53 in `packet/self-test-progress.json`. At the user's direction, the active verifier process was then stopped. The retained final checkpoint is 53/93 and names `failure_row_run_id` as the next uncredited mutation. Its batch log, `working/logs/attempt-ba08fd1c-596e-4751-bfbc-dc3fc2194a71.log`, is empty because the process was stopped before it emitted batch output.

The retained progress record is bound to the current refined verifier hash, current refined manifest hash, and exact ordered prefix. It is resumable state only. It is not a canonical success receipt and does not replace `packet/verification.txt`.

Two earlier checkpoints were invalidated by later verifier corrections and are retained only as provenance:

- `working/verification-progress/stale-41-of-93-before-repair-selection-fix.json`
- `working/verification-progress/stale-45-of-93-before-repair-declaration-fix.json`

After the final narrow correction, the focused verifier test suite passed 7 tests in 68.343 seconds. The full 105-test suite had passed before that last correction and was not rerun after it because packet work was stopped.

## Current verification status

- Research rows and findings: complete and directly reconciled.
- Ordinary packet verification: passed in the retained review history.
- Manifest files verified: 434.
- Matrix coverage: 240/240 rows and 120/120 pairs.
- Preflight coverage: 24/24 rows.
- Controls: 21/21 passed.
- Current refined mutation prefix: 53/93.
- Current canonical receipt for the refined verifier: absent.
- Mutation suite completion: not proven.
- Formal design-level acceptance: incomplete.

The research findings remain bounded to the frozen purposive suite and are reported in `RESEARCH-REPORT.md`. `PACKET-STATUS.md` is the current consolidated review status.
