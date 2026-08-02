# Evidence for jcodemunch-mcp#398

Supporting material requested on
[#398](https://github.com/jgravelle/jcodemunch-mcp/issues/398), for the arcs now on
`ROADMAP.md`. The original root bundle covers Arcs 1 and 2. The versioned
[`arc4-real-embedding-certification-v1`](arc4-real-embedding-certification-v1/README.md)
bundle covers the later real-embedding certification gate, including its reusable
harness, raw measurements, verifier, and separately downloadable prepared-index asset.

## Evidence bundles

| Bundle | Location | Verification |
| --- | --- | --- |
| Arcs 1 and 2 | Repository root | `python verify.py` |
| Arc 4 real-embedding certification v1 | `arc4-real-embedding-certification-v1/` | `py -3 verify.py --self-test` from that directory |

The remainder of this root document describes the original Arcs 1 and 2 bundle.

Produced against source revision
[`c2201a55`](https://github.com/jgravelle/jcodemunch-mcp/tree/c2201a55b6e1b0ea38043c514ab7bc3a372bad13)
(v1.108.207). Twelve of the fourteen source-run CSVs are entirely at that revision. Two
Arc 1 boundary files carry earlier `6996cc08` rows, one of them mixed with current rows;
neither backs a quoted figure. `verify.py` classifies all fourteen and `INDEX.json`
records the class per file.

## Start here

```bash
python verify.py
```

No arguments, no dependencies, no checkout needed. It recomputes the checks it lists from
the shipped CSVs and prints claimed against recomputed, so a disagreement shows up as a
line rather than an argument. Exit code 0 means all 26 checks reproduce.

**What it covers:** the 38-case Django code-loading headline and its distribution, the
four-repo per-case control, the Arc 2 Django and FastAPI medians, file integrity, and
provenance classification. **What it does not cover:** the versioned Arc 4 pack, the Arc
5 semantic figures, and the pooled Arc 2 and Arc 3 case-group numbers. Run the Arc 4
verifier separately from its own directory.

```
CHECK                                        CLAIMED        RECOMPUTED
aggregate throughput                           3.22x           3.2213x   ok
median case ratio                              1.23x            1.232x   ok
top 3 tools share                              91.9%             91.9%   ok
canonical response parity             38 of 38 match    38 of 38 match   ok
django: separated regressions                      0                 0   ok
...
26 of 26 checks reproduce.
```

## Layout

| Path | What |
| --- | --- |
| `verify.py` | Recomputes every published figure and self-checks file hashes. Start here. |
| `INDEX.json` | Machine-readable manifest: per-file purpose, row grain, modes, repos, provenance SHA, hashes. |
| `DATA-DICTIONARY.md` | What every column means, including which timing column to use and how to pair A/B rows. |
| `supporting-data/source-runs/` | The 14 fixed-schema CSVs. |
| `supporting-data/manifests/` | Deterministic summaries. Regenerable from the CSVs. |
| `supporting-data/tools/` | The harnesses. |
| `bench_public_full_blast_radius.py` | Base harness the drivers import. |
| `jcodemunch_selective_hydration_all_measurements.csv` | Unified archive, broader than the issue. See caveats. |

## Re-running the measurements

Two environment variables, both validated at startup with an actionable message:

```bash
export JCM_BASELINE_ROOT=/path/to/jcodemunch-mcp    # clean checkout at c2201a55
export JCM_CANDIDATE_ROOT=/path/to/checkout         # tree carrying the prototype
python supporting-data/tools/bench_generation_safe_hybrid_e2e.py
```

`psutil` is the only non-stdlib requirement. Both roots must be git checkouts, since the
harness records `git rev-parse HEAD` into every row.

The prototype is deliberately **not** in this bundle. These harnesses measure whatever
tree you point them at, which is what makes them useful against your own implementation
rather than only against mine.

**The corpora need indexing first.** `REPOS` in `bench_public_full_blast_radius.py` maps
upstream repositories to local index names, and jcodemunch derives those names from the
indexed path, so yours will differ from mine. Override without editing the file:

```bash
export JCM_BENCH_REPOS='{"django/django":"django-<your-suffix>", ...}'
```

For canonical response hashes to match the shipped rows, index these commits (also in
`INDEX.json` under `corpora`):

| Repo | Commit | Symbols |
| --- | --- | --- |
| django/django | `274a1d49` | 45,561 |
| fastapi/fastapi | `95f8322e` | 13,405 |
| gin-gonic/gin | `34dac209` | 1,834 |
| expressjs/express | `a3714473` | 471 |

The analyzers need none of this. They read the shipped CSVs and regenerate the shipped
manifests byte-for-byte:

```bash
python supporting-data/tools/analyze_hydration_trace_v2.py
python supporting-data/tools/analyze_generation_safe_hybrid_screen.py
```

## Three things worth knowing before you aggregate

**The unified archive is broader than the issue.** It retains exploratory rows at
`6996cc08` next to the `c2201a55` rows. No `6996cc08` row backs any figure quoted
in #398. Filter on `jcodemunch_source_sha` first, and note that the 18-column
boundary run spells that column `source_sha`.

**The Arc 2 classification screen is one pair per case.** 58 of its 144 cases (40.3%) are
Express and Gin calls with sub-50ms baselines, which a single pair cannot separate from
timing variance. Django at 5.17x and FastAPI at 2.59x are the load-bearing part of that
arc. `generation_safe_hybrid_e2e_deep_v3.csv` has 5 repetitions per case and is the
better file if you want per-case separation.

**Aggregate is not typical.** The 3.22x headline is summed wall time; the median case is
1.23x, and two tools carry 62.5% of the baseline time. Both numbers are in `verify.py`
so neither has to be taken on trust.

## Rejected variants are included

`mode` values beginning `generation_unsafe_global_` are a variant that was tried and
rejected. They are retained so the rejection is auditable rather than invisible.
