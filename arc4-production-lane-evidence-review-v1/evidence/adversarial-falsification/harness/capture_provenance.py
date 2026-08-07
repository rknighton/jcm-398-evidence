"""Capture immutable local source, wheel, corpus, and baseline provenance."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
WORKSPACE = HERE.parent
SOURCE = HERE / "working" / "source"
BASELINE = WORKSPACE / "arc4-production-lane-comparison-v1"
DB_ROOT = WORKSPACE / "candidate-cold-hydration-vetting" / "arc4-real-embedding-certification-v1" / "working" / "indexes"
DBS = {
    "django": DB_ROOT / "local-django-3eb2e228.db",
    "fastapi": DB_ROOT / "local-fastapi-c1d6b9c4.db",
    "jcodemunch": DB_ROOT / "local-arc4-research-v1-upstream-6f37f3de.db",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(*args: str) -> str:
    return subprocess.run(args, cwd=SOURCE, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()


def main() -> None:
    baseline_receipt = json.loads((BASELINE / "verification.txt").read_text(encoding="utf-8"))
    result = {
        "schema_version": "jcm-adversarial-provenance-v1",
        "target": {
            "tag": "v1.108.228",
            "source_commit": command("git", "rev-parse", "HEAD"),
            "source_clean": not bool(command("git", "status", "--porcelain")),
            "wheel_sha256": sha(HERE / "working" / "wheel" / "jcodemunch_mcp-1.108.228-py3-none-any.whl"),
        },
        "corpora": {name: {"path": str(path), "sha256": sha(path)} for name, path in DBS.items()},
        "provider_reproduction": json.loads(
            (HERE / "artifacts" / "controls" / "provider-vector-reproduction.json").read_text(encoding="utf-8")
        ),
        "baseline_packet": {
            "path": str(BASELINE),
            "verification_status": baseline_receipt["status"],
            "manifest_sha256": sha(BASELINE / "artifacts" / "manifest.json"),
            "verification_receipt_sha256": sha(BASELINE / "verification.txt"),
        },
    }
    output = HERE / "artifacts" / "provenance.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
