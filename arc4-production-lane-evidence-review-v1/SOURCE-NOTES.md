# Source and review notes

## Report contract

The audience is product maintainers and reviewers who should not need numerical-analysis expertise. Claims are deliberately underclaimed. Raw observations, derived summaries, engineering judgments, and unknowns are kept distinct.

## Evidence hierarchy

1. Raw or structured observations.
2. Frozen designs, configurations, and provenance records.
3. Applicable verifier output and current lifecycle authority.
4. Experiment reports.
5. Derived assessments and this synthesis.

Repeated measurements support repeatability, not input breadth. Candidate comparisons support numerical characterization, not independent sample counts. Purpose-built adversarial cases support possibility, not prevalence.

## Baseline framing

Issue 398 already recorded a synthetic rank-0 disagreement between NumPy float32 and pure-Python float64 scoring. The four-symbol fixture in this packet is an independent baseline confirmation and calibration. It is not an unexpected defect discovery and cannot establish practical frequency, severity, or answer quality.

## Independent challenge

Three independent read-only reviews challenged package structure, public-release hygiene, and evidence provenance. Their material corrections were incorporated here: the 5,000-query screening denominator is not used as frequency evidence; the v2 formal-acceptance ceiling is explicit; local paths and internal review identifiers are removed from public copies; and all claim-bearing raw evidence is unpacked and directly inspectable.

## Remaining limits

- No experiment sampled representative production traffic.
- The 4,967 provider-text screen negatives were not fully replayed through both actual lanes.
- Replaying all 5,000 queries requires adapting the retained replay harness to consume the complete frozen query file and supplying equivalent local indexes. That is proposed follow-up work, not a command this package claims is presently turnkey.
- Comparison v1 is supplemental. Comparison v2 is the authoritative official-package comparison.
- Comparison v2 findings are usable, but literal design acceptance remains incomplete at 53 of 93 authenticated mutation tests, with no canonical success receipt for the final verifier.
- The report assigns no numerical production safety probability.
