# Release asset contract

The prepared SQLite indexes are distributed as a release asset rather than committed
to Git. The Django database is larger than GitHub's 100 MB per-file limit, while each
release asset remains below GitHub's 2 GiB limit.

## Fixed names

| Item | Name |
| --- | --- |
| Release tag | `arc4-real-embedding-certification-v1` |
| Release title | `Arc 4 real-embedding certification v1` |
| Archive | `arc4-real-embedding-indexes-v1.zip` |
| Checksum | `arc4-real-embedding-indexes-v1.sha256` |
| External manifest | `arc4-real-embedding-indexes-v1.manifest.json` |
| Tracked manifest | `release-asset-manifest.json` |

The archive contains a deterministic internal `manifest.json` and an `indexes/`
directory. The external and tracked manifests add the archive hash and exact size.

## Coverage

The public archive includes:

- Django at commit `274a1d494d11d87a1b767340d1f398f197810f93`
- FastAPI at commit `95f8322ee1dcda7ceace7b1c4f6c9915b36d748f`

Together they contain 58,966 real vectors and cover both load-bearing roadmap gate
corpora. The JCodeMunch control database is excluded from public redistribution pending
written permission under its pinned custom license. This is a distribution boundary,
not a measurement omission. The canonical CSV retains every control row.

## Build locally

Run against the isolated prepared databases from the research packet:

```powershell
py -3 release_asset.py audit --index-dir <prepared-index-directory>
py -3 release_asset.py build --index-dir <prepared-index-directory> --output-dir <empty-release-output-directory>
```

The builder refuses to overwrite release files. It verifies each database hash,
`PRAGMA integrity_check`, embedding count and width, and absence of the measured host's
machine-local path markers before writing the archive.

## Verify or install

```powershell
py -3 release_asset.py verify --archive <archive-path>
py -3 release_asset.py install --archive <archive-path>
```

Installation rejects path traversal, duplicate members, unexpected files, hash
mismatches, existing destinations, SQLite corruption, vector-count drift, and local
path leakage. It writes only to the requested new destination and its sibling
`preparation.json`.

## Publication checklist

1. Confirm the focused upstream issue disposition.
2. Confirm the tracked and external manifests match the final archive SHA-256.
3. Run `py -3 verify.py --self-test` from this directory.
4. Run `py -3 release_asset.py verify --archive <archive-path>`.
5. Upload the archive, checksum, and external manifest to the matching release tag.
6. Link the release from the focused follow-up issue connected to umbrella issue 398.

Steps 1 through 5 are complete. The archive, checksum, and external manifest are
published under the matching evidence-repository release tag. Step 6 remains pending:
the focused upstream follow-up issue is still a local draft and has not been submitted.
