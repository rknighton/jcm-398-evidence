# Arc 4 production-lane evidence review

This is the review entry point for the retained Arc 4 research packets. It is a curated publication copy, not a claim that every original design acceptance item completed.

## Start here

1. Read [REPORT.md](REPORT.md) for the decision-facing judgment.
2. Use [SOURCE-MAP.md](SOURCE-MAP.md) to inspect the evidence behind each claim.
3. Use [CLAIM-LEDGER.csv](CLAIM-LEDGER.csv) for the minimum provable claims and their limits.
4. Use [DATASET-INVENTORY.md](DATASET-INVENTORY.md) to locate the complete generated-query and full-ranking datasets.
5. Use [DATA-DICTIONARY.md](DATA-DICTIONARY.md) for plain-language definitions of each main record type and comparison term.
6. Use [INDEX.json](INDEX.json) for the machine-readable package map and claimed counts.
7. Read [PROVENANCE-ANNOTATION.md](PROVENANCE-ANNOTATION.md) before comparing public copies with the frozen local originals.

## Verify the package

From this directory:

```powershell
py -3 -B verify_package.py
py -3 -B -m unittest -v test_verify_package.py
```

The verifier checks the package checksum inventory, local Markdown links, maximum repository-file size, publication-hygiene rules, and lossless decompression of the paired dataset. It also recomputes the report's headline counts and ranking comparisons from the shipped data instead of trusting the summaries. `VALIDATION.txt` records the release-candidate run.

The original experiment verifiers are retained as provenance and research tooling. The v2 verifier expects the original uncompressed `paired.jsonl`; the publication package stores that one oversized file as deterministic gzip. `verify_package.py` is the release gate for the published layout.

## Publication boundary

Included here are the synthesis, all claim-bearing generated and comparison data, methods, harnesses, lifecycle records, and verifiers. Excluded are working environments, caches, cloned sources, dependency wheelhouses, nested Git metadata, and the superseded web output.

The raw datasets are unpacked and organized under `evidence/`. Only the 188.48 MiB paired JSONL required special handling: that single file is compressed by itself to 19.80 MiB. The guarded-candidate packet already lives at [arc4-real-embedding-certification-v1](../arc4-real-embedding-certification-v1/README.md).

## License

The authored contents of this package are released under [MIT-0](LICENSE). No third-party dependency wheels or source checkouts are redistributed here. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
