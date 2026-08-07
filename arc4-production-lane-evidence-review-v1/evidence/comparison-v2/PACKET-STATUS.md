# Arc 4 packet status

**Lifecycle:** current local review record

**Recorded:** 2026-08-06, America/New_York

## Authority and scope

`DESIGN.md` remains the frozen research contract at SHA-256 `4E885E262545660378CA508748AB5A8DF49CF1AA8B2AF96DDA0A6748AFE88FBE`. This status document is post-execution synthesis. It does not amend the design, observations, pair records, controls, metrics, or findings.

The packet is intentionally stopped at the user's direction. No external issue, comment, repository, release, or other state has been created or changed.

## Research result

The research portion is complete and answers the production-lane question approved in GitHub issue 398 comment 5177953577.

- 264 planned rows and 132 lane pairs are present.
- The matrix contains 240 rows and 120 pairs over 12 frozen ranking problems.
- The preflight contains 24 rows and 12 pairs and is excluded from findings denominators.
- All 21 controls pass.
- Independent reconciliation reproduced the headline metric totals.
- All 240 reconstructed matrix top-k lists match the retained public tool output.
- All 48 same-lane problem-by-cache-state cells contain five identical repetitions for both public top-k and full-depth ordering hash.

The supported conclusion is:

> On this fixed purposive suite, JCodeMunch 1.108.228 produced identical public rank-0, ordered top-k, and top-k membership results in the NumPy-present and NumPy-absent production lanes. The lanes nevertheless differed in floating-point scores, exact-tie partitions, and deep ranking order.

This is descriptive fixed-suite evidence. It does not estimate prevalence, establish impossibility of public top-k divergence, or support timing or memory claims.

## Formal verification status

The research result and literal design acceptance are separate statuses.

- Research findings: complete and independently cross-checked.
- Literal design acceptance: incomplete.
- Current verifier SHA-256: `330E38FB2364D80123A4007F16A7A33EA4D36777E0232E0A730D96970CE0590C`.
- Current manifest SHA-256: `C37C4D350116C744AF42A18920CEFCA703BB425EF726EB91F2E103033CB580A3`.
- Manifest file count: 434.
- Authenticated mutation prefix: 53/93.
- Next uncredited mutation: `failure_row_run_id`.
- The active run was stopped after the 53/93 checkpoint at the user's direction.

The current `packet/self-test-progress.json` is the resumable verifier state. It is bound to the exact current verifier hash, manifest hash, and ordered 53-test prefix. It is not a success receipt and must not be described as 93/93 completion.

`packet/verification.txt` remains an earlier successful base receipt with 0/93 self-tests. It is bound to an intermediate verifier and manifest, not the current verification-only refinement. It remains historical evidence that the packet passed ordinary verification at that stage, but it is not a final receipt for the current verifier identity.

The last code change passed the focused verifier suite: 7 tests in 68.343 seconds. The full 105-test repository suite passed before the final narrow `repair_declaration_missing` correction; it was not rerun afterward because work was stopped. This is an explicitly retained validation gap.

## Verification refinement provenance

`VERIFICATION-AMENDMENT.md` authorizes only post-execution verifier checkpoint and resume behavior. It changes no measurement or finding. Concrete production-packet mutation defects corrected during execution are recorded there.

Final-verifier clean checkpoints:

- 21/93: `working/logs/attempt-dad669bd-f0b5-45d2-a65d-ff07b086b511.log`
- 33/93: `working/logs/attempt-f3f88f41-e643-48e6-a846-9bf186b54c1b.log`
- 41/93: `working/logs/attempt-34bae6fc-0d2f-4698-93cf-e48fe38b2055.log`
- 49/93: `working/logs/attempt-80d06d8c-6334-4d34-9f17-f8e026434a72.log`
- 53/93: authenticated in `packet/self-test-progress.json`; the interrupted batch log is `working/logs/attempt-ba08fd1c-596e-4751-bfbc-dc3fc2194a71.log` and is empty because the process was stopped before batch output.

Invalidated checkpoints are retained only as provenance and must not be resumed or added to the final prefix:

- `working/verification-progress/stale-41-of-93-before-repair-selection-fix.json`
- `working/verification-progress/stale-45-of-93-before-repair-declaration-fix.json`

## Artifact-layout deviations

The evidence is present, but the packet does not literally satisfy every named artifact in DESIGN.md section 15.1:

- `TRANSFER-DECISIONS.json` is absent. The decisions remain in DESIGN.md sections 5.2 and 5.3, with the decomposition in `packet/ORIGINAL-MATRIX-DECOMPOSITION.json`.
- The preregistration is represented by `PLAN.md`, `packet/PREREGISTRATION-INPUTS.json`, and `packet/PREREGISTRATION-COMMIT.json`, rather than `PREREGISTRATION.md`.
- `METHODOLOGY-JOURNAL.jsonl` is retained at the study root rather than inside `packet/`.
- Post-execution review documents are not preregistered or manifest-bound measurement inputs.

These are packaging and formal acceptance gaps. They do not change the retained observations or reconciled metric totals.

## Optional future resumption

No further work is currently requested. If formal acceptance becomes necessary later, the current 53/93 prefix may be resumed only while the verifier and manifest hashes still match the progress record. Any verifier or manifest change invalidates that checkpoint and requires a new run from zero.

## Current claim decision

The packet may be described as complete fixed-suite research with direct reconciliation and ordinary packet verification history. It must not be described as satisfying every literal design acceptance requirement or as having completed 93/93 mutation self-tests.
