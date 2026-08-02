# Third-party source and distribution notes

The prepared indexes are derived from public source snapshots. They retain indexed
symbol metadata and source text, so their distribution follows the license at each
pinned commit.

The repository and release archive include the pinned notices at
`licenses/django-LICENSE.txt` and `licenses/fastapi-LICENSE.txt`.

| Corpus | Pinned commit | License at that commit | Public asset |
| --- | --- | --- | --- |
| Django | `274a1d494d11d87a1b767340d1f398f197810f93` | [Django license](https://github.com/django/django/blob/274a1d494d11d87a1b767340d1f398f197810f93/LICENSE) | Included |
| FastAPI | `95f8322ee1dcda7ceace7b1c4f6c9915b36d748f` | [MIT](https://github.com/fastapi/fastapi/blob/95f8322ee1dcda7ceace7b1c4f6c9915b36d748f/LICENSE) | Included |
| JCodeMunch control | `c78392cac0d50570d5cf86558d8d3674c0bea068` | [Dual-Use License 1.1](https://github.com/jgravelle/jcodemunch-mcp/blob/c78392cac0d50570d5cf86558d8d3674c0bea068/LICENSE) | Excluded pending written permission |

The JCodeMunch control index is not a verbatim copy. It is a repackaged SQLite
derivative containing indexed source text and generated embeddings. The pinned custom
license limits redistribution of modified, repackaged, or derivative forms without
written permission, so the public release builder excludes it. No legal conclusion is
claimed beyond following that explicit conservative boundary.

The complete raw measurement CSV still identifies the control corpus, commit, source
database hash, prepared database hash, embedding-generation identity, query-vector
hashes, and all measured results. Reproducing the omitted control embeddings took about
5 minutes 34 seconds on the measured host.
