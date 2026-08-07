import subprocess
import tempfile
import unittest
import json
from pathlib import Path

from harness.campaign import validate_frozen_execution_inputs, validate_preregistration_commit
from harness.common import canonical_json_bytes, sha256_file
from harness.packet import write_manifest
from harness.verify import Rejected, verify_packet
from tests.packet_fixture import build_packet
from tests.test_campaign import config


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, timeout=10,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def committed_fixture(root: Path) -> tuple[dict, dict]:
    value = config(root)
    packet = Path(value["packet_root"])
    packet.mkdir(parents=True)
    for path, payload in (
        (Path(value["frozen_cases"]), b"{}\n"),
        (Path(value["environment_lock"]), b"{}\n"),
        (Path(value["p0_receipt"]), b"{}\n"),
        (Path(value["source_build_receipt"]), b"{}\n"),
        (Path(value["source_build_receipt_digest"]), ("0" * 64 + "\n").encode("ascii")),
        (packet / "SOURCE-INVENTORY.json", b"{}\n"),
        (Path(value["design_path"]), b"design\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    frozen_config = Path(value["frozen_config"])
    frozen_config.write_bytes(canonical_json_bytes(value))
    (packet / "CONFIG.json").write_bytes(frozen_config.read_bytes())
    prereg = {
        "config_sha256": sha256_file(packet / "CONFIG.json"),
        "frozen_cases_sha256": sha256_file(Path(value["frozen_cases"])),
        "environment_lock_sha256": sha256_file(Path(value["environment_lock"])),
        "p0_receipt_sha256": sha256_file(Path(value["p0_receipt"])),
        "source_inventory_sha256": sha256_file(packet / "SOURCE-INVENTORY.json"),
        "design_sha256": sha256_file(Path(value["design_path"])),
    }
    Path(value["preregistration_inputs"]).write_bytes(canonical_json_bytes(prereg))
    git(root, "init", "-q")
    git(root, "config", "user.email", "arc4@example.invalid")
    git(root, "config", "user.name", "Arc4")
    git(root, "add", "FROZEN-CONFIG.json", "DESIGN.md", "packet")
    git(root, "commit", "-q", "-m", "preregister")
    commit = git(root, "rev-parse", "HEAD")
    artifacts = {
        "CONFIG.json": packet / "CONFIG.json",
        "ENVIRONMENT-LOCK.json": Path(value["environment_lock"]),
        "P0-RECEIPT.json": Path(value["p0_receipt"]),
        "PREREGISTRATION-INPUTS.json": Path(value["preregistration_inputs"]),
        "SOURCE-BUILD-RECEIPT.json": Path(value["source_build_receipt"]),
        "SOURCE-BUILD-RECEIPT.sha256": Path(value["source_build_receipt_digest"]),
        "SOURCE-INVENTORY.json": packet / "SOURCE-INVENTORY.json",
        "frozen-cases.json": Path(value["frozen_cases"]),
    }
    receipt = {"schema": "arc4.preregistration-commit/v1", "commit_sha": commit, "committed": True, "files": {name: sha256_file(path) for name, path in artifacts.items()}}
    Path(value["preregistration_commit_receipt"]).write_bytes(canonical_json_bytes(receipt))
    return value, receipt


class CampaignProvenanceTests(unittest.TestCase):
    def test_real_commit_and_tree_blobs_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, receipt = committed_fixture(root)
            self.assertEqual(receipt, validate_preregistration_commit(value))
            fabricated = dict(receipt)
            fabricated["commit_sha"] = "0" * 40
            Path(value["preregistration_commit_receipt"]).write_bytes(canonical_json_bytes(fabricated))
            with self.assertRaisesRegex(RuntimeError, "prereg_git_command"):
                validate_preregistration_commit(value)

    def test_working_tree_only_bytes_and_tree_mismatch_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, receipt = committed_fixture(root)
            Path(value["p0_receipt"]).write_bytes(b'{"changed":true}\n')
            receipt["files"]["P0-RECEIPT.json"] = sha256_file(Path(value["p0_receipt"]))
            Path(value["preregistration_commit_receipt"]).write_bytes(canonical_json_bytes(receipt))
            with self.assertRaisesRegex(RuntimeError, "prereg_tree_hash"):
                validate_preregistration_commit(value)

    def test_active_config_and_preregistered_hashes_revalidate_immediately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value, _ = committed_fixture(root)
            validate_frozen_execution_inputs(value)
            changed = dict(value)
            changed["worker_timeout_seconds"] = 901
            with self.assertRaisesRegex(RuntimeError, "active_config_bytes"):
                validate_frozen_execution_inputs(changed)
            Path(value["p0_receipt"]).write_bytes(b'{"changed":true}\n')
            with self.assertRaisesRegex(RuntimeError, "active_preregistration_hashes"):
                validate_frozen_execution_inputs(value)
            Path(value["p0_receipt"]).write_bytes(b"{}\n")
            (Path(value["packet_root"]) / "SOURCE-INVENTORY.json").write_bytes(b'{"changed":true}\n')
            with self.assertRaisesRegex(RuntimeError, "active_preregistration_hashes"):
                validate_frozen_execution_inputs(value)

    def test_committed_preregistration_semantic_mutations_reject(self):
        mutations = {
            "schema": lambda value: value.__setitem__("schema", "arc4.preregistration-inputs/v0"),
            "timestamp": lambda value: value.__setitem__("approved_utc", "not-utc"),
            "run_identity": lambda value: value.__setitem__("run_id", "different-run"),
            "row_count": lambda value: value.__setitem__("matrix_rows", 239),
            "pair_count": lambda value: value.__setitem__("preflight_pairs", 11),
            "claim_ceiling": lambda value: value.__setitem__("claim_ceiling", "broader_claim"),
            "p0_claim_ceiling": lambda value: value.__setitem__("p0_claim_ceiling", "reproducible_build"),
            "p0_noncoverage": lambda value: value.__setitem__("p0_does_not_establish", []),
            "early_stop": lambda value: value.__setitem__("no_early_stop", False),
            "complete_coverage": lambda value: value.__setitem__("verdict_requires_complete_coverage", False),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                packet = build_packet(root)
                prereg_path = packet / "PREREGISTRATION-INPUTS.json"
                prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
                mutate(prereg)
                prereg_path.write_bytes(canonical_json_bytes(prereg))
                write_manifest(packet)
                git(root, "init", "-q")
                git(root, "config", "user.email", "arc4@example.invalid")
                git(root, "config", "user.name", "Arc4")
                git(root, "add", "packet")
                git(root, "commit", "-q", "-m", f"mutated {name}")
                committed = subprocess.run(["git", "show", "HEAD:packet/PREREGISTRATION-INPUTS.json"], cwd=root, check=True, timeout=10, stdout=subprocess.PIPE).stdout
                self.assertEqual(prereg_path.read_bytes(), committed)
                with self.assertRaises(Rejected):
                    verify_packet(packet)


if __name__ == "__main__":
    unittest.main()
