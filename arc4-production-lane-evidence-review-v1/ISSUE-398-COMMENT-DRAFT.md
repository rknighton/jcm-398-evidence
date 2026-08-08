# Draft: comment for issue 398

> **Venue.** A comment on 398, not a new issue. #403 is already the Arc 4 evidence issue and
> closed as completed; 398 is where this comparison was requested and where you said "no
> deadline on this one, it answers a question we raised, so it's ours to wait on"; and an issue
> here opens when work starts or a user is blocked. An earlier draft proposed a third issue,
> which was wrong and has been dropped.
>
> Replace `<PUBLIC_REPOSITORY_URL>` and `<COMMIT>` before posting.

---

## Arc 4 production-lane comparison, v1.108.228

The comparison you accepted in [comment 5177953577](https://github.com/jgravelle/jcodemunch-mcp/issues/398#issuecomment-5177953577). Pinned `v1.108.228`, NumPy-present against NumPy-absent, a new production-lane comparison rather than a rerun of the certification candidate.

**The requested four dimensions, on the fixed suite:**

| Dimension | By ranking problem | By replicated pair |
| --- | ---: | ---: |
| Rank-0 difference | **0 of 12** | 0 of 120 |
| Ordered top-k difference | **0 of 12** | 0 of 120 |
| Top-k membership difference | **0 of 12** | 0 of 120 |
| Exact-tie partition difference | **8 of 12** | 80 of 120 |

Twelve corpus-by-query ranking problems over Django, FastAPI and jCodeMunch, each run in two cache states with five repetitions. The 120 pairs are repeat executions of those 12 problems, not 120 independent samples; the repetitions establish stability, not breadth. Returned depth was 25 for two query forms and 10 for the other two, and the earliest full-depth divergence in any pair was at position 1,556, so the first 100 positions were identical in every pair.

So the returned results matched on this suite while the arithmetic underneath did not: scores, exact-tie partitions, and ordering far below the returned depth all differ. That is the honest shape of the answer.

**Claim ceiling.** A descriptive census of a purposive fixed suite built from four distinct query vectors. It is not a production-rate estimate, and it does not show that divergence cannot occur elsewhere.

## Why a new comparison was needed

The earlier zero I reported did not test this. That packet compared its own exact baseline against a local float32 certification candidate, every row with NumPy present, so the shipped NumPy-absent lane never ran. I withdrew it on 2026-08-04 and this replaces it. The certification candidate is not in `.228` and its absence is not a gap in the result above.

One thing worth flagging: `ROADMAP.md` on `main` still says, in Arc 4, that the hazard "does not fire in practice on Django, FastAPI or jcm" and that the tie-break shipped on the strength of that. That rests on the withdrawn zero, and the section has not been edited since 2026-08-03. The table above, plus the supplemental result below, is the replacement with valid provenance, and it is narrower: rank 0 held, the other three dimensions did not.

## Supplemental breadth, beyond what you asked for

As an additional stress on that conclusion, all 5,000 of the previously frozen query vectors were replayed through both scorers. These are **mechanically generated text queries scored against three frozen real code indexes**, not user traffic and not 5,000 complete tool calls: this is a scorer-level comparison, whereas the table above is the complete production-lane study.

| Dimension | k=1 | k=5 | k=10 | k=25 | k=50 | k=100 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ordered top-k differs | **0** | 5 | 11 | 19 | 51 | 114 |
| Membership differs | **0** | 4 | 10 | 16 | 33 | 29 |

Exact-tie partitions inside the retained top 100 differed for 130 queries.

Two corrections to my own earlier framing come out of this.

**My 33-query screen was not a trustworthy proxy.** Against the completed suite it scored 5 true positives, 28 false alarms and **109 misses**. It emulated both lanes in NumPy rather than running them.

**"Only deep adjacent swaps" is withdrawn.** It fit the five nominations, whose earliest change was at position 38. Across the full suite the earliest change is at position 2, nineteen queries differ inside the first 25 results, and 83 of the 114 differ in more than two positions.

## Interpretation

- The two production lanes are demonstrably not equivalent.
- No rank-0 difference appeared in either real-input suite.
- Ordered and membership differences do occur inside returned depths in the broader scorer-level suite.
- Neither experiment estimates a production rate, and neither shows that a changed result is worse.
- On balance this supports retaining the fast lane rather than removing it. It is not a safety proof.

One engineering observation, offered as a hypothesis rather than a result. In 103 of the 114 disagreeing queries the first differing pair was scored exactly equal by the pure-Python lane and unequal by the NumPy lane, so `(-score, symbol_id)` canonicalised it in one lane and had nothing to act on in the other. In an inspected Django example the two symbols held byte-identical stored vectors and the NumPy scores still differed by one float32 step, which would make a blocked reduction row-order sensitive. I have not measured how far that generalises, what fraction of each full permutation it explains, or what a canonicalisation would cost, so I am not proposing a change on it. The detail is in the linked report if it is useful; if not, ignore it. Nothing here moves lane 3's parked premise.

## Evidence

`<PUBLIC_REPOSITORY_URL>/tree/<COMMIT>/arc4-production-lane-evidence-review-v1`

`verify_package.py` is the release gate. It prints, on every run, which figures it recomputes from raw records, which it only cross-checks between documents, and which it does not cover. `evidence/full-suite-replay/harness/compare_lanes.py` is a read-only reproducer for the supplemental replay: it re-derives that section's numbers from the shipped bytes with the standard library alone, compares them byte for byte against the committed artifacts, and fails on drift. Neither derives the mechanism observation above, and both say so.
