# Arc 4 verification-only amendment

## Status and authorization

This is a post-execution verification-only amendment recorded on 2026-08-06 after restrictions on refinement were lifted.

It does not amend the frozen measurements, row identities, pair identities, treatment, environments, controls, metrics, findings, claim ceiling, or issue 398 publication boundary. DESIGN.md remains frozen at SHA-256 `4E885E262545660378CA508748AB5A8DF49CF1AA8B2AF96DDA0A6748AFE88FBE`.

> **Publication note.** The digest quoted above is the pre-normalization identity of `DESIGN.md`, recorded in `SOURCE-HASHES.sha256`. The published copy had a machine-specific research root replaced with a placeholder and therefore hashes differently. The design content is unchanged. See PROVENANCE-ANNOTATION.md.

## Observed blocker

The unchanged command `py -3 verify.py --self-test --write-receipt` performs all 93 mutation tests in one process and emits its canonical receipt only after the entire suite finishes. The first combined attempt exceeded 900 seconds. A direct attempt remained CPU-active until a bounded runner stopped it at 1,800.028 seconds. It emitted no partial result.

Source inspection established that every mutation test copies the packet into a temporary directory and invokes the complete packet verifier. The all-or-nothing CLI has no supported checkpoint, resume, selection, or progress mode.

## Authorized refinement

The verifier may add one optional argument:

```text
--self-test-budget-seconds POSITIVE_NUMBER
```

The option is valid only with `--self-test`. When omitted, the original all-tests behavior remains unchanged.

When supplied, the budget covers the full verifier invocation. The verifier checks the deadline only between mutation tests. It never interrupts a mutation test after that test begins.

After every correctly rejected mutation, the verifier atomically writes `self-test-progress.json` in the packet root. The progress record is excluded from the manifest and packet closed-world inventories in the same narrow manner as the generated `verification.txt` receipt.

The atomic writer uses the exact temporary name `.self-test-progress.json.tmp`. A self-test invocation removes only that exact stale temporary file before base verification. This permits recovery if a process is interrupted during the atomic write without creating a general cleanup mechanism or excluding temporary files from closed-world verification.

Control C13's derived manifest-scope label is correspondingly updated from `all_packet_files_except_manifest_root_and_verification_receipt` to `all_packet_files_except_manifest_root_and_generated_verifier_state`. The control remains passed and its closed-world requirement is not weakened.

The progress record is accepted on resume only when all of the following hold:

- its schema and exact key set are valid;
- its verifier SHA-256 equals the currently executing verifier;
- its manifest SHA-256 equals the currently verified packet manifest;
- its expected count equals the current frozen self-test count;
- its passed-test list is the exact ordered prefix of the frozen 93-test sequence;
- its numeric count equals the length of that prefix.

Malformed, stale, reordered, skipped, foreign-verifier, or foreign-manifest progress fails closed before another mutation test runs.

If the budget is reached before all tests finish, the verifier atomically preserves progress, prints one canonical `arc4.self-test-progress/v1` JSON record, returns exit code 75, does not write or replace `verification.txt`, and may be invoked again with the same command.

When all 93 tests pass, the verifier produces the original `arc4.verification-receipt/v1` result with `self_tests_passed: 93`, writes `verification.txt` when requested, and then removes the progress record. A completed progress record remains valid if an interruption occurs in the narrow interval between the last checkpoint and final receipt commit.

## Invariants

- `SELF_TESTS` names and ordering remain unchanged.
- Every expected rejection code remains unchanged.
- The pre-existing `repair_attempt_duplicate` mutation is corrected to remain inside attempt accounting and reach its declared `attempt_duplicate` gate. Its former `control` stage excluded it from that accounting and caused the mutation to reach `summary_m9` instead. This correction changes no packet measurement or research finding.
- The pre-existing repair-row mutations are corrected to select an observed successful repair attempt greater than 1 instead of assuming the successful attempt is exactly 2. The production packet's successful repaired rows occur at attempts 3 and 5, so the old hard-coded selection changed no row and caused `repair_reason_removed` to fail as a self-test rather than exercise its declared gate. Dynamic selection changes no packet measurement or finding.
- The pre-existing `repair_declaration_missing` mutation is corrected to remove only the declaration for an observed successful repaired pair. Erasing the entire repair journal also removed declarations for failed explicit-repair attempts, allowing the earlier `failure_repair_declaration` gate to fire before the mutation's declared `successful_repair_declaration` target. The narrowed mutation changes no packet measurement or finding.
- `verify_packet` remains the authority for packet acceptance.
- Each newly executed mutation test still operates on a fresh temporary packet candidate.
- No passed test may be inferred from elapsed time, process state, filename, or count alone.
- Resume authority comes only from the exact verifier, manifest, ordered prefix, and atomic progress record.
- Exit 0 remains reserved for a completed verified receipt.
- Exit 75 means resumable self-test progress only and cannot be interpreted as verification success.
- The ordinary `py -3 verify.py --write-receipt` path retains its prior behavior.

## Required validation

1. Existing mutation tests still fail closed at their preregistered rejection codes.
2. A bounded run writes ordered progress and returns 75 without replacing the prior receipt.
3. A resumed run skips only the authenticated ordered prefix.
4. Corrupt, stale, reordered, skipped, or mismatched progress is rejected.
5. Completion produces the original receipt schema and exactly 93/93 self-tests.
6. The final progress file is absent after the completed receipt is committed.
7. Base packet verification still passes after the verifier and manifest are refreshed.

This amendment exists to complete the frozen assurance work without rerunning or altering the research data.
