import copy
import tempfile
import unittest
from pathlib import Path

from harness.common import load_json
from harness.controls import validate_control_record
from harness.verify import Rejected, verify_synthetic_control
from tests.packet_fixture import build_packet


class ClosedControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory()
        cls.packet = build_packet(Path(cls._temporary.name))
        cls.records = {f"C{number}": load_json(cls.packet / "controls" / f"C{number}.json") for number in range(1, 22)}

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    def test_material_control_families_reject_unknown_evidence(self):
        for control_id in ("C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12", "C13", "C14", "C15", "C16", "C20", "C21"):
            with self.subTest(control_id=control_id):
                record = copy.deepcopy(self.records[control_id])
                record["evidence"]["self_attested"] = True
                with self.assertRaises(RuntimeError):
                    validate_control_record(record)

    def test_material_control_families_reject_false_positive_values(self):
        mutations = {
            "C1": lambda value: value["lanes"]["numpy_present"].__setitem__("wheel_sha256", "0" * 64),
            "C2": lambda value: value.__setitem__("checkout_clean", False),
            "C3": lambda value: value.__setitem__("database_unchanged_rows", 263),
            "C4": lambda value: value.__setitem__("matching_rows", 263),
            "C5": lambda value: value.__setitem__("numpy_version", "2.4.3"),
            "C6": lambda value: value.__setitem__("find_spec_none_after", 131),
            "C7": lambda value: value.__setitem__("topup_tripwire_events", 1),
            "C8": lambda value: value.__setitem__("matrix_rounded_score_matches", 239),
            "C9": lambda value: value.__setitem__("seeds", ["0"]),
            "C10": lambda value: value.__setitem__("matrix_numpy_first", 59),
            "C11": lambda value: value.__setitem__("database_unchanged_rows", 239),
            "C12": lambda value: value.__setitem__("warm_cache_hit_rows", 11),
            "C13": lambda value: value.__setitem__("verification_entrypoint", "trust_packet"),
            "C14": lambda value: value.__setitem__("warm_matrix_stamp_unchanged_rows", 119),
            "C15": lambda value: value.__setitem__("effective_weight_matches_rows", 263),
            "C16": lambda value: value.__setitem__("only_declared_difference", "numpy-and-pip"),
            "C20": lambda value: value.__setitem__("candidate_set_matches_rows", 239),
            "C21": lambda value: value.__setitem__("outbound_attempts", 1),
        }
        for control_id, mutate in mutations.items():
            with self.subTest(control_id=control_id):
                record = copy.deepcopy(self.records[control_id])
                mutate(record["evidence"])
                with self.assertRaises(RuntimeError):
                    validate_control_record(record)

    def test_metric_fixture_rejects_unnamed_or_missing_projection_fields(self):
        for mutation in ("unknown", "missing"):
            evidence = copy.deepcopy(self.records["C17"]["evidence"])
            projection = evidence["fixtures"][0]["expected_projection"]
            if mutation == "unknown":
                projection["unnamed_metric"] = False
            else:
                projection.pop("m12_first_divergence_rank")
            with self.subTest(mutation=mutation), self.assertRaises(Rejected):
                verify_synthetic_control("C17", evidence)


if __name__ == "__main__":
    unittest.main()
