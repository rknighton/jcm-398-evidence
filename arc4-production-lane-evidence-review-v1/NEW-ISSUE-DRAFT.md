# Arc 4 production-lane evidence review

## Key judgment

Small numerical differences between the NumPy and pure-Python scoring methods were already known and expected. The completed testing confirms that they can change a ranking, but it did not find evidence of a practically significant problem in the semi-realistic or fixed real-codebase comparisons. The evidence cannot prove perfect safety or establish a production failure rate. On balance, the faster method appears more likely than not safe enough to be worth using, especially when uncertain result boundaries are checked exactly.

The review package is here:

<PUBLIC_REPOSITORY_URL>/tree/<COMMIT>/arc4-production-lane-evidence-review-v1

The short report leads with the decision judgment, then states the working hypothesis, surviving evidence, strongest adversarial case, and recommendation. It also links the underlying experiment reports, complete unpacked data, provenance, and verifiers.

The most important limits are explicit:

- Synthetic rank-0 flips prove possibility, not production frequency or answer degradation.
- Five deep adjacent swaps were confirmed among 33 fully replayed nominations from 5,000 generated queries, but the other 4,967 were not fully replayed. The 5,000 total therefore does not establish a disagreement rate.
- The authoritative official-package comparison covered only 12 fixed problems.
- Comparison-v2 findings are usable, but literal design acceptance remains incomplete at 53 of 93 authenticated mutation tests and lacks a final canonical verifier receipt.

Recommendation: continue pursuing the faster lane with exact boundary rescore or fallback, keep the sensitive cases as regression tests, and use representative production monitoring if a field incidence estimate becomes necessary.
