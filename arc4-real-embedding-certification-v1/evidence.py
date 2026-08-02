"""Standard-library aggregation for reports and independent verification."""

from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path
from typing import Any

from arc4lib import CSV_COLUMNS


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
            raise ValueError("canonical CSV header does not match fixed schema")
        return list(reader)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _logical_candidate_rows(rows: list[dict[str, str]], corpus: str) -> list[dict[str, str]]:
    selected = [
        row
        for row in rows
        if row["corpus"] == corpus
        and row["mode"] == "float32_certified_candidate"
        and row["cache_state"] == "generation_warm"
        and row["repetition"] == "1"
    ]
    selected.sort(key=lambda row: row["query_id"])
    return selected


def _timing_rows(rows: list[dict[str, str]], corpus: str, mode: str, cache: str) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if row["corpus"] == corpus and row["mode"] == mode and row["cache_state"] == cache
    ]


def compute_summary(rows: list[dict[str, str]], config: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "row_count": len(rows),
        "column_count": len(CSV_COLUMNS),
        "pair_count": len({row["pair_id"] for row in rows}),
        "parity_count": sum(row["canonical_parity"] == "true" for row in rows),
        "corpora": {},
        "provenance": {
            "embedding_dimension": rows[0]["embedding_dimension"],
            "embedding_model": rows[0]["embedding_model"],
            "measured_source_sha": rows[0]["baseline_source_sha"],
            "measured_version": rows[0]["baseline_version"],
        },
    }
    for corpus_config in config["corpora"]:
        corpus = corpus_config["name"]
        logical = _logical_candidate_rows(rows, corpus)
        if len(logical) != len(config["queries"]):
            raise ValueError(f"logical call coverage is incomplete for {corpus}")
        denominator = sum(int(row["candidate_count"]) for row in logical)
        counts = {
            key: sum(int(row[key]) for row in logical)
            for key in (
                "exact_tie_count",
                "near_tie_count",
                "genuine_disagreement_count",
                "other_certified_count",
                "total_certified_count",
            )
        }
        call_fractions = [float(row["total_certified_fraction"]) for row in logical]
        bands = {
            "pass_band": sum(value <= config["authority"]["django_breadth_pass_max"] for value in call_fractions),
            "design_band": sum(
                config["authority"]["django_breadth_pass_max"] < value
                <= config["authority"]["django_breadth_design_max"]
                for value in call_fractions
            ),
            "fail_band": sum(value > config["authority"]["django_breadth_design_max"] for value in call_fractions),
        }
        timing: dict[str, Any] = {}
        for cache in config["measurement"]["cache_states"]:
            by_mode: dict[str, float] = {}
            for mode in config["measurement"]["modes"]:
                values = [
                    int(row["scoring_ns"]) / 1_000_000.0
                    for row in _timing_rows(rows, corpus, mode, cache)
                ]
                by_mode[mode] = statistics.median(values)
            timing[cache] = {
                "median_scoring_ms": by_mode,
                "candidate_speedup": (
                    by_mode["exact_tiebreak_baseline"]
                    / by_mode["float32_certified_candidate"]
                    if by_mode["float32_certified_candidate"] > 0.0
                    else 0.0
                ),
            }
        corpus_summary = {
            "role": corpus_config["role"],
            "logical_call_count": len(logical),
            "candidate_denominator": denominator,
            **counts,
            "exact_tie_fraction": counts["exact_tie_count"] / denominator,
            "near_tie_fraction": counts["near_tie_count"] / denominator,
            "genuine_disagreement_fraction": counts["genuine_disagreement_count"] / denominator,
            "total_certified_fraction": counts["total_certified_count"] / denominator,
            "per_call": {
                "minimum": min(call_fractions),
                "median": statistics.median(call_fractions),
                "p95": percentile(call_fractions, 0.95),
                "maximum": max(call_fractions),
                **bands,
            },
            "timing": timing,
            "vector_count": int(logical[0]["embedding_vector_count"]),
            "embedding_generation_identity": logical[0]["embedding_generation_identity"],
            "corpus_commit": logical[0]["corpus_commit"],
        }
        summary["corpora"][corpus] = corpus_summary

    django = summary["corpora"]["django"]
    breadth = django["total_certified_fraction"]
    genuine = django["genuine_disagreement_fraction"]
    parity_ok = summary["parity_count"] == summary["row_count"]
    warm_speedup = django["timing"]["generation_warm"]["candidate_speedup"]
    if (
        not parity_ok
        or breadth > config["authority"]["django_breadth_design_max"]
        or genuine > config["authority"]["genuine_disagreement_fail_above"]
    ):
        verdict = "fail"
    elif (
        breadth > config["authority"]["django_breadth_pass_max"]
        or warm_speedup < config["authority"]["warm_speed_rationale"]
    ):
        verdict = "design answer required"
    else:
        verdict = "pass"
    summary["roadmap_verdict"] = verdict
    return summary


def display_claims(summary: dict[str, Any]) -> dict[str, str]:
    claims = {
        "row_count": str(summary["row_count"]),
        "column_count": str(summary["column_count"]),
        "pair_count": str(summary["pair_count"]),
        "parity_count": str(summary["parity_count"]),
        "roadmap_verdict": summary["roadmap_verdict"],
        "embedding_dimension": summary["provenance"]["embedding_dimension"],
        "embedding_model": summary["provenance"]["embedding_model"],
        "measured_source_sha": summary["provenance"]["measured_source_sha"],
        "measured_version": summary["provenance"]["measured_version"],
    }
    for corpus, values in summary["corpora"].items():
        prefix = corpus
        claims[f"{prefix}_vector_count"] = str(values["vector_count"])
        claims[f"{prefix}_corpus_commit"] = values["corpus_commit"]
        claims[f"{prefix}_candidate_denominator"] = str(values["candidate_denominator"])
        for key in (
            "exact_tie_count",
            "near_tie_count",
            "genuine_disagreement_count",
            "total_certified_count",
        ):
            claims[f"{prefix}_{key}"] = str(values[key])
        for key in (
            "exact_tie_fraction",
            "near_tie_fraction",
            "genuine_disagreement_fraction",
            "total_certified_fraction",
        ):
            claims[f"{prefix}_{key}"] = f"{100.0 * values[key]:.4f}%"
        for key in ("minimum", "median", "p95", "maximum"):
            claims[f"{prefix}_per_call_{key}"] = f"{100.0 * values['per_call'][key]:.4f}%"
        for key in ("pass_band", "design_band", "fail_band"):
            claims[f"{prefix}_{key}_calls"] = str(values["per_call"][key])
        for cache in ("cold_fresh_process", "generation_warm"):
            timing = values["timing"][cache]
            claims[f"{prefix}_{cache}_speedup"] = f"{timing['candidate_speedup']:.2f}x"
            for mode, milliseconds in timing["median_scoring_ms"].items():
                claims[f"{prefix}_{cache}_{mode}_median_ms"] = f"{milliseconds:.3f} ms"
    return claims
