"""Verify the severity assessment against the retained adversarial packet."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKET = HERE.parent / "arc4-production-lane-adversarial-falsification-v1"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(value, message):
    if not value:
        raise RuntimeError(message)


def main():
    evidence = load(HERE / "evidence.json")
    summary = load(PACKET / "artifacts" / "summary.json")
    findings = load(PACKET / "artifacts" / "findings" / "provider-actual-findings.json")
    hybrid = load(PACKET / "artifacts" / "findings" / "hybrid-findings.json")
    receipt = load(PACKET / "verification.txt")

    require(receipt["status"] == "PASS", "adversarial packet verification failed")
    require(evidence["target"]["commit"] == "8bed872e9436093be9f89d35fb84e0cb58a293af", "target mismatch")
    require(summary["geometric"]["rank0_flips"] == evidence["observations"]["geometric"]["rank0_flips"] == 3211, "geometric mismatch")
    require(len(findings) == evidence["observations"]["provider_text"]["ordered_top_k_findings"] == 5, "provider finding mismatch")
    require(len(hybrid) == evidence["observations"]["hybrid"]["ordered_top_k_findings"] == 11, "hybrid mismatch")

    ranks = []
    tie_count = 0
    for finding in findings:
        numpy_ids = finding["numpy"]["ordered_top_100"]
        python_ids = finding["python"]["ordered_top_100"]
        changed = [index for index, pair in enumerate(zip(numpy_ids, python_ids), 1) if pair[0] != pair[1]]
        require(len(changed) == 2, f"non-adjacent-swap shape {finding['query_id']}")
        ranks.append(changed[0])
        a, b = numpy_ids[changed[0] - 1], python_ids[changed[0] - 1]
        if finding["numpy"]["score_hex"][a] == finding["numpy"]["score_hex"][b]:
            tie_count += 1
    require(sorted(ranks) == evidence["observations"]["provider_text"]["first_changed_ranks"], "rank mismatch")
    require(tie_count == 4 and len(findings) - tie_count == 1, "mechanism classification mismatch")
    require(not any(item["dimensions"]["1"]["rank0"] for item in findings), "provider rank0 mismatch")
    require(not any(value["membership"] for item in findings for value in item["dimensions"].values()), "provider membership mismatch")
    require(evidence["publication_state"] == "local_only", "publication state mismatch")
    report = (HERE / "REPORT.md").read_text(encoding="utf-8")
    require("low demonstrated normal-use severity" in report, "verdict missing")
    require("do not prove a meaningful normal-use failure" in report, "normal-use boundary missing")
    print(json.dumps({"status": "PASS", "provider_findings": len(findings), "float32_tie_findings": tie_count, "genuine_inversions": 1, "first_changed_ranks": sorted(ranks)}, indent=2))


if __name__ == "__main__":
    main()
