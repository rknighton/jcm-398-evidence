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

Four independent read-only reviews challenged package structure, public-release hygiene, and evidence provenance. Their material corrections were incorporated here: the v2 formal-acceptance ceiling is explicit; internal review identifiers are removed from public copies; local research roots survive in raw provenance and log records and are disclosed in `LOCAL-PATH-DISCLOSURE.json` rather than claimed to be absent; the verifier now states which figures it recomputes and which it only cross-checks; and all claim-bearing raw evidence is unpacked and directly inspectable.

The fourth review also executed the follow-up this package had only specified. The 5,000-query denominator is therefore now a measured denominator rather than an unusable one, and two claims in the previous draft were withdrawn as a result. Both withdrawals are recorded in `REPORT.md` under "What the Complete Replay Changed".

## Remaining limits

- No experiment sampled representative production traffic.
- All 5,000 provider-text queries have now been replayed through both actual lanes; see `evidence/full-suite-replay/`. Reproducing that replay still requires the three frozen corpus databases, which are outside the publication boundary, and both lane environments. The comparison step alone runs on the shipped bytes with the standard library.
- The replay compares the scoring lane, not a complete tool response.
- Comparison v1 is supplemental. Comparison v2 is the authoritative official-package fixed comparison, and it shares its 12 problems and 3 corpora with comparison v1 and the guarded candidate.
- Comparison v2 findings are usable, but literal design acceptance remains incomplete at 53 of 93 authenticated mutation tests, with no canonical success receipt for the final verifier.
- The report assigns no numerical production safety probability.
