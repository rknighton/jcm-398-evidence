"""Replay adversarial fixtures through one untouched shipped scorer lane."""

from __future__ import annotations

import argparse
import array
import base64
import hashlib
import json
import os
import platform
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lane", choices=("numpy", "python"), required=True)
    args = parser.parse_args()
    try:
        import numpy
        numpy_version = numpy.__version__
    except ImportError:
        numpy_version = None
    if (args.lane == "numpy") != (numpy_version is not None):
        raise RuntimeError(f"lane environment mismatch: {args.lane=} {numpy_version=}")
    from jcodemunch_mcp.storage import embedding_matrix as em
    output = []
    with args.input.open("r", encoding="utf-8") as handle:
        for line in handle:
            case = json.loads(line)
            raw = [(item["id"], decode(item["blob_b64"])) for item in case["candidates"]]
            matrix = em._build(raw)
            if matrix is None or matrix.vectorised != (args.lane == "numpy"):
                raise RuntimeError(f"matrix lane mismatch for {case['case_id']}")
            scores = matrix.score_all(case["query"])
            ordered = sorted(scores, key=lambda sid: (-scores[sid], sid))
            output.append({
                "case_id": case["case_id"], "lane": args.lane,
                "vectorised": matrix.vectorised, "ordered": ordered,
                "scores": {sid: value.hex() for sid, value in scores.items()},
                "python": platform.python_version(), "numpy": numpy_version,
                "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
            })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(canonical(item) + "\n" for item in output)
    args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(canonical({"status": "completed", "lane": args.lane, "cases": len(output),
                     "sha256": hashlib.sha256(payload.encode()).hexdigest()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
