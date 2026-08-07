from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .common import require


CANONICAL_PACKET_PATHS = {
    "config": "CONFIG.json",
    "environment_lock": "ENVIRONMENT-LOCK.json",
    "frozen_cases": "frozen-cases.json",
    "p0_receipt": "P0-RECEIPT.json",
    "preregistration_commit_receipt": "PREREGISTRATION-COMMIT.json",
    "preregistration_inputs": "PREREGISTRATION-INPUTS.json",
    "source_build_receipt": "SOURCE-BUILD-RECEIPT.json",
    "source_build_receipt_digest": "SOURCE-BUILD-RECEIPT.sha256",
    "source_inventory": "SOURCE-INVENTORY.json",
}

CONFIG_TO_ARTIFACT = {
    "environment_lock": "environment_lock",
    "frozen_cases": "frozen_cases",
    "p0_receipt": "p0_receipt",
    "preregistration_commit_receipt": "preregistration_commit_receipt",
    "preregistration_inputs": "preregistration_inputs",
    "source_build_receipt": "source_build_receipt",
    "source_build_receipt_digest": "source_build_receipt_digest",
}


def canonical_packet_paths(packet_root: Path) -> dict[str, Path]:
    root = packet_root.resolve()
    return {key: (root / relative).resolve() for key, relative in CANONICAL_PACKET_PATHS.items()}


def validate_canonical_config_paths(config: Mapping[str, object]) -> dict[str, Path]:
    root = Path(str(config["packet_root"])).resolve()
    paths = canonical_packet_paths(root)
    for config_key, artifact_key in CONFIG_TO_ARTIFACT.items():
        observed = Path(str(config[config_key])).resolve()
        require(observed == paths[artifact_key], "campaign_artifact_path", f"{config_key}:{observed}")
    frozen_config = Path(str(config["frozen_config"])).resolve()
    require(frozen_config != paths["config"], "campaign_frozen_config_source", str(frozen_config))
    capture_specs = config["environment_capture_specs"]
    require(isinstance(capture_specs, Mapping), "campaign_capture_specs", str(capture_specs))
    expected_raw = {
        "numpy_present": (root / "env" / "raw-numpy-present.json").resolve(),
        "numpy_absent": (root / "env" / "raw-numpy-absent.json").resolve(),
    }
    for lane, expected in expected_raw.items():
        observed = Path(str(capture_specs.get(lane))).resolve()
        require(observed == expected, "campaign_artifact_path", f"environment_capture_specs.{lane}:{observed}")
    return paths
