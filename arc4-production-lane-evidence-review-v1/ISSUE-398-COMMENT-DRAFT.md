# Draft: comment for issue 398

> **Why a comment and not a new issue.** #403 is already the Arc 4 evidence issue and closed as
> completed; #398 is where the production-lane comparison was requested and where the maintainer
> said "no deadline on this one, it answers a question we raised, so it's ours to wait on". Opening
> a third issue for the same arc would also cut against the stated rule that an issue opens when
> work starts or when a user is blocked. Neither applies. An earlier draft of this package proposed
> a new issue; that was the wrong venue and it has been dropped.
>
> Replace `<PUBLIC_REPOSITORY_URL>` and `<COMMIT>` before posting. Everything below is inline so
> the comment stands on its own if nobody follows the link.

---

## Arc 4 production-lane comparison, on the terms you set

Pinned `v1.108.228`. Both shipped lanes. Rank 0, ordered top-k, membership and exact ties reported separately. New comparison, not a rerun.

**Rank 0 did not change in any of 5,000 real-embedding queries.** That is the counterweight I withdrew on 2026-08-04, restored on evidence that actually exercises the NumPy-absent lane. It comes back narrower than the sentence it replaces, and the rest of that sentence does not come back at all.

| Dimension | k=1 | k=5 | k=10 | k=25 | k=50 | k=100 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ordered top-k differs | **0** | 5 | 11 | 19 | 51 | 114 |
| Membership differs | **0** | 4 | 10 | 16 | 33 | 29 |

Exact-tie partitions inside the returned top 100 differ in 130 of the 5,000. Full-depth ordering differs in 4,971.

5,000 generated queries seeded from indexed symbols, 1,667 Django, 1,667 FastAPI, 1,666 jCodeMunch, against the same three frozen corpora as the certification packet, digests checked before scoring. Two isolated environments on Python 3.13.7, NumPy 2.4.4 present in one and absent in the other. Ordering by `(-score, symbol_id)`, matching `retrieval/signal_fusion.py`.

## Three things that cut against my own earlier framing

**My screen was the binding limitation, and it was worse than I flagged.** It nominated 33 queries. Against the complete replay that is 5 true positives, 28 false alarms and **109 misses**: 4.4% sensitivity. It emulated both lanes inside NumPy rather than running them, and the emulation was a poor proxy in both directions. Anything I said resting on those 33 understated the suite by about an order of magnitude.

**"Only deep adjacent swaps" was wrong.** It fit the five nominations, whose earliest change was at position 38. Across the suite the earliest change is at position **2**, nineteen queries differ inside the first 25 results, four change which results appear in the first five, and 83 of the 114 differ in more than two positions.

**The certification packet's version gap, restated for the record.** It measured `1.108.212`, not the `.228` everything else here pins. I mentioned this in passing on 2026-08-04; it is now stated in the claim ledger rather than left in a thread.

## Why the lanes actually disagree, which is not the story either of us has been telling

All 114 disagreements classify with no residue:

| Class | Count |
| --- | ---: |
| The two swapped symbols hold **byte-identical stored embeddings** | 103 |
| NumPy float32 exact tie that float64 separates | 9 |
| Genuine score-order inversion | 2 |

The dominant class is not a float32-versus-float64 story. For a Django query, `ProfileForm.Meta#class` and `LogEntry.Meta#class` have byte-identical stored blobs, and after normalisation `numpy.array_equal` on their two matrix rows is `True`. Scored one row at a time, both return `0x1.56a7fc0p-1`. Scored the way `_scores_numpy` scores, `matrix.dot(qv)` returns `0x1.56a7fe0p-1` for row 34172 and `0x1.56a7fc0p-1` for row 2407.

Identical inputs, different outputs, from row position alone. A blocked BLAS matrix-vector product vectorises the reduction and float32 addition is not associative, so the summation order depends on where the row sits. It is deterministic, not flaky: fresh processes reproduce it exactly.

Across all 5,000 top-100 lists: **34,320 duplicate-vector groups, 97 split by the NumPy lane, 0 split by the pure-Python lane.**

**So `(-score, symbol_id)` is correct and is being denied the equality it needs.** It canonicalises duplicate-embedding clusters in the pure-Python lane without a single exception. In the NumPy lane it cannot fire on 97 groups, and that accounts for 103 of the 114 differences.

Two consequences. First, the NumPy lane is not row-order independent, so **re-indexing can change returned order with no change to any embedding, any query, or whether NumPy is importable.** That is a wider axis than installation state, and it is the one the tie-break was meant to close. Second, 103 of 114 reorder items the model scores as exactly equivalent, so for those neither ordering is worse.

The remedy this points at is making the NumPy lane's scores comparable before the sort, or grouping identical rows, rather than lane 3. I am not asking you to unpark lane 3 and this does not move its premise: the exact scorer is still 2.9 ms warm and nothing here shows something slow that certification would accelerate.

## Also worth knowing

`ROADMAP.md` on `main` still says, in Arc 4, that "the hazard is real in principle and does not fire in practice on Django, FastAPI or jcm", and that the tie-break shipped on the strength of that. It rests on the zero I retracted, and the section has not been edited since 2026-08-03. This comment is the replacement evidence for the half of it that survives; the ordering, membership and tie halves do not.

## What this is not

Generated queries seeded from indexed symbols, not user traffic. Three corpora, one host, one release. A within-suite rate, not a production rate. And it compares the scoring lane rather than a complete tool response: adapter-to-tool agreement was confirmed for 5 cases previously, not for 5,000. It says nothing about which ordering is better.

## Evidence

`<PUBLIC_REPOSITORY_URL>/tree/<COMMIT>/arc4-production-lane-evidence-review-v1`

All 5,000 per-lane records, the 114 disagreements with both lanes' scores, the harnesses, and a comparison verifier that re-derives every number above from the shipped bytes with the standard library alone, no corpus database and no install required:

```text
py -3 -B evidence/full-suite-replay/harness/compare_lanes.py
```

It has no `continue` in its checking loop, and it re-derives the five findings I published earlier as a control. All five reproduce byte-identically.

The same repository carries the corrections this round produced: the package verifier now separates what it recomputes from what it only cross-checks, `LOCAL-PATH-DISCLOSURE.json` names every file that still contains my local research root instead of claiming none do, and `RETAINED-VERIFIERS.md` records that the four original packet verifiers do not run in the published layout and why.

## Still open on my side

The emitted-`task` corpus is being assembled in #422. Nothing in this comment is gated on it.
