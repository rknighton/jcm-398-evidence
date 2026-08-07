from common import compare_case, tie_groups


def evidence(ids, values):
    scores = [{"id": sid, "cosine_hex": value.hex(), "final_hex": value.hex()} for sid, value in zip(ids, values)]
    ranked = sorted(scores, key=lambda row: (-float.fromhex(row["final_hex"]), row["id"]))
    return {"scores": scores, "ranked_scores": ranked, "ordered_positive_ids": [r["id"] for r in ranked]}


def test_negative_comparison():
    item = evidence(["b", "a"], [0.5, 0.5])
    result = compare_case(item, item, {"paired_case_id": "x", "corpus": "c", "query_id": "q", "top_k": 2})
    assert result["rank_0"]["equal"] and result["ordered_top_k"]["equal"] and result["membership"]["equal"]
    assert result["exact_ties"]["numpy"]["group_count"] == 1
    assert result["ordered_top_k"]["numpy"] == ["a", "b"]


def test_ordered_only_divergence():
    n = evidence(["a", "b", "c"], [0.9, 0.8, 0.7])
    p = evidence(["a", "b", "c"], [0.9, 0.7, 0.8])
    result = compare_case(n, p, {"paired_case_id": "x", "corpus": "c", "query_id": "q", "top_k": 3})
    assert result["rank_0"]["equal"]
    assert not result["ordered_top_k"]["equal"]
    assert result["membership"]["equal"]
    assert result["ordered_top_k"]["first_differing_rank"] == 1


def test_boundary_tie():
    rows = [{"id": "a", "final_hex": (1.0).hex()}, {"id": "b", "final_hex": (0.5).hex()}, {"id": "c", "final_hex": (0.5).hex()}]
    result = tie_groups(rows, 2)
    assert len(result["crossing_top_k_boundary"]) == 1
