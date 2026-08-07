# Arc 4 production-lane evidence review

This is the review entry point for the retained Arc 4 research packets. It is a curated publication copy, not a claim that every original design acceptance item completed.

It answers the production-lane comparison the maintainer agreed to in [issue 398 comment 5177953577](https://github.com/jgravelle/jcodemunch-mcp/issues/398#issuecomment-5177953577): pin v1.108.228, report rank 0, ordered top-k, membership and exact ties separately, treat it as a new comparison rather than a rerun.

## Start here

1. Read [REPORT.md](REPORT.md) for the decision-facing judgment.
2. Read [evidence/full-suite-replay/REPORT.md](evidence/full-suite-replay/REPORT.md) for the complete 5,000-query two-lane replay, which is the newest and largest result here.
3. Use [SOURCE-MAP.md](SOURCE-MAP.md) to inspect the evidence behind each claim.
4. Use [CLAIM-LEDGER.csv](CLAIM-LEDGER.csv) for the minimum provable claims and their limits.
5. Use [DATASET-INVENTORY.md](DATASET-INVENTORY.md) to locate the complete datasets.
6. Use [DATA-DICTIONARY.md](DATA-DICTIONARY.md) for plain-language definitions of each record type and comparison term.
7. Use [INDEX.json](INDEX.json) for the machine-readable package map and claimed counts.
8. Read [PROVENANCE-ANNOTATION.md](PROVENANCE-ANNOTATION.md) and [LOCAL-PATH-DISCLOSURE.json](LOCAL-PATH-DISCLOSURE.json) before comparing public copies with the frozen local originals.
9. Read [RETAINED-VERIFIERS.md](RETAINED-VERIFIERS.md) before running any verifier other than the package one.

The two drafts prepared for publication are [ISSUE-398-COMMENT-DRAFT.md](ISSUE-398-COMMENT-DRAFT.md) and [FOLLOW-UP-5000.md](FOLLOW-UP-5000.md). The first is the reply intended for the issue thread; the second is the follow-up specification, now marked complete by the replay above.

## Verify the package

From this directory:

```powershell
py -3 -B verify_package.py
py -3 -B -m unittest -v test_verify_package.py
```

The verifier distinguishes two kinds of check and prints both sets, because conflating them is how an evidence pack overstates itself.

**Recomputed from raw shipped records.** The 5,000 query records, the 33 nominations, the 5 complete-replay findings with their positions and rank-0, top-25 and top-100 membership outcomes, the 3,211 geometric rank-0 changes derived by pairing the two shipped geometric lane outputs, the 10,002 geometric cases, the preserved attempt and raw-file counts, the full-suite replay's four reported dimensions derived from its per-lane records, lossless reconstruction of the one gzip-stored dataset, every file against its manifest digest, and the local-path disclosure in both directions.

**Cross-checked between independently authored surfaces.** Each experiment summary against `INDEX.json`, every numeric claim in `INDEX.json` against the surface that owns it, the comparison-v1 and comparison-v2 headline counts against their experiment summaries, every `CLAIM-LEDGER.csv` evidence pointer against the filesystem, plus local Markdown links, publication hygiene and the repository file-size gate.

**Not covered.** Comparison-v2's `m5`, `m6`, `m10`, `m11` and `m12` are reproducible from `packet/raw/full-rankings/` but are not re-derived by this verifier; `VALIDATION.txt` records an external run that did reproduce `m1` to `m6`, `m10` and `m12`. Nothing resting on material outside the publication boundary is covered, including the corpus databases, the dependency wheel, and the `working/` artifacts cited in `PACKET-STATUS.md` and `ACCEPTANCE-AUDIT.md`.

Do not describe this verifier, or this repository, as recomputing every published figure. It does not, and the covered set is the list above.

The unit tests exercise the verifier's machinery on synthetic packages: tampering, private-path detection in both raw and JSON-escaped form, a false-positive guard, gzip reconstruction, and headline-schema rejection. They do not run the headline recomputation against this package's real data; `verify_package.py` itself does that.

`VALIDATION.txt` records the release-candidate run. [RETAINED-VERIFIERS.md](RETAINED-VERIFIERS.md) records why the four original experiment verifiers do not run in this layout.

## Publication boundary

Included here are the synthesis, all claim-bearing generated and comparison data, methods, harnesses, lifecycle records, and verifiers. Excluded are working environments, caches, cloned sources, dependency wheelhouses, nested Git metadata, and the superseded web output.

The raw datasets are unpacked under `evidence/`. Only the 188.48 MiB paired JSONL required special handling: that single file is compressed by itself to 19.80 MiB. The guarded-candidate packet already lives at [arc4-real-embedding-certification-v1](../arc4-real-embedding-certification-v1/README.md).

Raw provenance, configuration and log records retain the machine-specific research root they were written with. Rewriting them would invalidate the content-addressed packet identities they are bound into, so they are disclosed instead: [LOCAL-PATH-DISCLOSURE.json](LOCAL-PATH-DISCLOSURE.json) names every such file and the verifier fails if a local path appears anywhere else.

## License

The authored contents of this package are released under [MIT-0](LICENSE). No third-party dependency wheels or source checkouts are redistributed here. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
