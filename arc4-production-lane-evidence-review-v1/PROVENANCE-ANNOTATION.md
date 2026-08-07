# Provenance annotation

The frozen local research directories remain unchanged. This publication directory contains selected copies.

`SOURCE-HASHES.sha256` records each copied file before publication normalization. `CHECKSUMS.sha256` records the published package. A differing hash means the public copy received one of the documented transformations below. Thirteen files differ; every other copied file is byte-identical to its frozen original.

## Publication transformations

Applied to Markdown and Python sources only:

- Machine-specific research roots were replaced with `<LOCAL_RESEARCH_ROOT>`.
- The local public-repository root was replaced with `<PUBLIC_EVIDENCE_ROOT>`.
- Internal task identifiers in orchestration provenance were replaced with `<internal-task-id-redacted>`.
- One operator-history sentence was rewritten to describe the lifecycle event without referring to a private conversation.
- Synthesis links were rewritten from local sibling directories to portable package paths.

No experimental result, vector, score, rank, case identifier, package version, source revision, or acceptance status was changed.

## Local paths that remain, and why

**The substitution above was not applied to raw JSON, JSONL or log records, and those records still contain the machine-specific research root.** 79 published files are affected, with 881 occurrences in total. [LOCAL-PATH-DISCLOSURE.json](LOCAL-PATH-DISCLOSURE.json) names every one of them with a per-pattern count, and `verify_package.py` fails if a local path appears in any file not on that list, or if a listed file no longer contains one.

They remain for a reason that is worth stating plainly rather than leaving as an implication. Those files are measurement, provenance, configuration and log records whose bytes are bound into content-addressed manifests. `packet/raw/rows.jsonl`, for example, is one of 434 entries in `packet/MANIFEST.json`, whose digest `c37c4d35...` is recorded in `packet/MANIFEST.sha256` and again as `manifest_sha256` inside `packet/self-test-progress.json`. `PACKET-STATUS.md` states that any manifest change invalidates the authenticated 53-of-93 mutation checkpoint. Editing the bytes to tidy a path would make those digests vouch for a run that did not happen, and would destroy a verification checkpoint, in exchange for concealing a Windows account name and a set of private research directory names.

What the retained paths disclose: an account name, and directory names such as the research root and per-experiment working directories. What they do not disclose: any credential, token, key, network address other than loopback, third-party material, or anything about a person other than the author.

An earlier draft of this document claimed the roots had been removed everywhere. They had not. The check that was supposed to catch it looked for a single-backslash form and therefore could not see the JSON-escaped form that every affected record uses. Both the claim and the check are corrected here.

## Deliberate exclusions

- Working environments, caches, source clones, databases, wheelhouses, nested Git metadata, and failed operational logs.
- The rejected web presentation.
- The original 188.48 MiB `paired.jsonl` in uncompressed form. Because ordinary GitHub files cannot exceed 100 MiB, that single file is stored as deterministic gzip. Its metadata records the original and compressed sizes and hashes, and decompression reproduces the original bytes exactly.
- Third-party dependency binaries, including `inputs/jcodemunch_mcp-1.108.228-py3-none-any.whl` from the comparison-v2 manifest. Package versions and hashes remain in the retained environment and provenance records.
- The three frozen corpus databases. Their SHA-256 digests are recorded in `evidence/adversarial-falsification/artifacts/provenance.json`, and the full-suite replay harness verifies each digest before scoring.

The original experiment manifests continue to describe the frozen local packets. They are retained as provenance records and should not be mistaken for manifests of this curated publication subset. `CHECKSUMS.sha256` is authoritative for the publication package, and [RETAINED-VERIFIERS.md](RETAINED-VERIFIERS.md) reconciles each frozen manifest against what is published here.

## Quoted digests that no longer resolve

Five documents in the comparison-v2 packet quote the frozen design contract as SHA-256 `4E885E262545660378CA508748AB5A8DF49CF1AA8B2AF96DDA0A6748AFE88FBE`. That is the pre-normalization digest of `evidence/comparison-v2/DESIGN.md`, recorded as such in `SOURCE-HASHES.sha256`. The published copy received the path substitution above and now hashes differently. The design content is unchanged; only the placeholder text differs. Each of those five documents carries a note to that effect, so a reader who checks the digest is not left concluding tampering.
