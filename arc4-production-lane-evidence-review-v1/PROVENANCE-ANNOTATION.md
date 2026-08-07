# Provenance annotation

The frozen local research directories remain unchanged. This publication directory contains selected copies.

`SOURCE-HASHES.sha256` records each copied file before publication normalization. `CHECKSUMS.sha256` records the published package. A differing hash means the public copy received one of the documented transformations below.

## Publication transformations

- Machine-specific research roots were replaced with `<LOCAL_RESEARCH_ROOT>`.
- The local public-repository root was replaced with `<PUBLIC_EVIDENCE_ROOT>`.
- Internal task identifiers in orchestration provenance were replaced with `<internal-task-id-redacted>`.
- One operator-history sentence was rewritten to describe the lifecycle event without referring to a private conversation.
- Synthesis links were rewritten from local sibling directories to portable package paths and release-asset references.

No experimental result, vector, score, rank, case identifier, package version, source revision, or acceptance status was changed.

## Deliberate exclusions

- Working environments, caches, source clones, databases, wheelhouses, nested Git metadata, and failed operational logs.
- The rejected web presentation.
- The original 188.48 MiB `paired.jsonl` in uncompressed form. Because ordinary GitHub files cannot exceed 100 MiB, that single file is stored as deterministic gzip. Its metadata records the original and compressed sizes and hashes. Decompression reproduces the original bytes exactly.
- Third-party dependency binaries. Package versions and hashes remain in the retained environment and provenance records where applicable.

The original experiment manifests continue to describe the frozen local packets. They are retained as provenance records and should not be mistaken for manifests of this curated publication subset. `CHECKSUMS.sha256` is authoritative for the publication package.
