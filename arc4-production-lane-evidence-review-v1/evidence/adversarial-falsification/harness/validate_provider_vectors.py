"""Re-encode the frozen text suite with the target provider and prove byte identity."""

from __future__ import annotations

import array
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SOURCE = HERE / "artifacts" / "queries" / "provider-text.jsonl"
OUTPUT = HERE / "artifacts" / "controls" / "provider-vector-reproduction.json"
BATCH_SIZE = 128


def float32_bytes(values: list[float]) -> bytes:
    return array.array("f", values).tobytes()


def main() -> None:
    from jcodemunch_mcp.tools.embed_repo import _detect_provider, embed_texts

    records = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line]
    provider = _detect_provider()
    expected_provider = ("local_onnx", "all-MiniLM-L6-v2")
    if provider != expected_provider:
        raise RuntimeError(f"provider mismatch: expected {expected_provider!r}, got {provider!r}")

    mismatches: list[dict[str, object]] = []
    dimensions: set[int] = set()
    reproduced = 0
    for start in range(0, len(records), BATCH_SIZE):
        batch = records[start : start + BATCH_SIZE]
        vectors = embed_texts([item["text"] for item in batch], *provider)
        if len(vectors) != len(batch):
            raise RuntimeError(f"batch cardinality mismatch at offset {start}")
        for item, vector in zip(batch, vectors):
            dimensions.add(len(vector))
            actual = hashlib.sha256(float32_bytes(vector)).hexdigest()
            frozen = hashlib.sha256(float32_bytes(item["vector"])).hexdigest()
            expected = item["vector_sha256"]
            if actual != expected or frozen != expected:
                mismatches.append(
                    {
                        "query_id": item["query_id"],
                        "expected_sha256": expected,
                        "frozen_sha256": frozen,
                        "reproduced_sha256": actual,
                    }
                )
            reproduced += 1

    result = {
        "schema_version": "jcm-provider-vector-reproduction-v1",
        "target": "jcodemunch-mcp-v1.108.228",
        "provider": {"name": provider[0], "model": provider[1]},
        "batch_size": BATCH_SIZE,
        "queries": len(records),
        "reproduced": reproduced,
        "dimensions": sorted(dimensions),
        "comparison": "float32-byte-for-byte",
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "status": "PASS" if not mismatches and reproduced == len(records) else "FAIL",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "mismatches"}, indent=2, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
