# Dataset inventory

The generated queries, screen negatives, failed attempts, raw comparisons, and full rankings are unpacked inside this report package. They are not optional attachments.

## Adversarial dataset

- [All 5,000 balanced generated-text queries](evidence/adversarial-falsification/artifacts/queries/provider-text.jsonl), including the 33 the preliminary filter nominated and the 4,967 it rejected. All 5,000 have since been replayed through both lanes; see the complete replay dataset below.
- [All geometric boundary inputs](evidence/adversarial-falsification/artifacts/queries/geometric.jsonl) supporting 10,002 executed cases, including 10,000 independently generated boundary cases.
- [Screen outputs](evidence/adversarial-falsification/artifacts/screens/), including the preliminary provider-text screen.
- [Confirmed findings](evidence/adversarial-falsification/artifacts/findings/), including replay outputs, minimization evidence, and the public counterexample.
- [Failed or superseded attempts](evidence/adversarial-falsification/artifacts/attempts/), retained as diagnostic evidence rather than positive findings.
- [Chronological journal](evidence/adversarial-falsification/artifacts/JOURNAL.jsonl), [summary](evidence/adversarial-falsification/artifacts/summary.json), [coverage](evidence/adversarial-falsification/artifacts/coverage.json), [provenance](evidence/adversarial-falsification/artifacts/provenance.json), and [original manifest](evidence/adversarial-falsification/artifacts/manifest.json).

## Complete replay dataset, supplemental

- [Per-lane records for all 5,000 queries](evidence/full-suite-replay/raw/), two lanes by three corpora, each holding the ordered top 100, its exact score encodings, and a SHA-256 over the complete ordering.
- [Full-depth scores](evidence/full-suite-replay/raw/) for the 29 queries whose first swap leaves both top-100 lists, so no disagreement is left unclassified.
- [The 114 disagreements](evidence/full-suite-replay/raw/disagreements.jsonl), with both lanes' full top-100 lists and scores.
- [Machine summary](evidence/full-suite-replay/results-summary.json) and [report](evidence/full-suite-replay/REPORT.md).
- [Attested mechanism census](evidence/full-suite-replay/mechanism-census.json), derived from the excluded corpus databases and therefore not gated by the package verifier.

This dataset is supplemental. The comparison the maintainer requested is the comparison-v2 dataset below.

The three corpus databases stay outside the publication boundary. Their SHA-256 digests are in the adversarial provenance record and the harness verifies each before scoring.

## Comparison-v1 dataset

- [All precursor raw ranking outputs](evidence/comparison-v1/artifacts/raw/)
- [All precursor controls](evidence/comparison-v1/artifacts/controls/)
- [Compact paired comparisons](evidence/comparison-v1/artifacts/comparisons.jsonl)

This dataset is retained because rejected and superseded work remains useful evidence. It is supplemental to the authoritative official-package v2 comparison.

## Comparison-v2 dataset

- [All raw rows, warmups, and full rankings](evidence/comparison-v2/packet/raw/)
- [All invocation artifacts](evidence/comparison-v2/packet/invocations/)
- [All controls](evidence/comparison-v2/packet/controls/)
- [Compressed paired full-depth evidence](evidence/comparison-v2/packet/paired.jsonl.gz)
- [Paired-data compression metadata](evidence/comparison-v2/packet/paired.jsonl.gz.json)

The original `paired.jsonl` is 188.48 MiB, above GitHub's ordinary per-file limit. That single file is therefore stored as deterministic gzip, compressed to 19.80 MiB. Decompression reproduces the original 197,630,471 bytes, 132 complete JSONL records, and SHA-256 `bfa58e4dabb95f9a765c1c3514eede5fdbb6d80adf263f8eae3eec19161685ef`.

## Integrity

[SOURCE-HASHES.sha256](SOURCE-HASHES.sha256) records the frozen research-source hashes before publication normalization. [CHECKSUMS.sha256](CHECKSUMS.sha256) covers every published file. The package verifier checks the files, links, public-path hygiene, and lossless decompression of the paired data.
