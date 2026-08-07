import tempfile
import unittest
import shutil
import json
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from harness.artifacts import canonical_packet_paths
from harness.campaign import CampaignOwner, child_environment, environment_creation_commands, frozen_original_snapshot, ordered_rows_for_execution, rows_for_mode, validate_campaign_config
from harness.cases import QUERY_IDS, generate_frozen_cases
from harness.common import atomic_write, atomic_write_new, canonical_json_bytes, sha256_bytes, sha256_file
from harness.metrics import ordering_sha256
from harness.orchestrator import commit_pair_fragment, run_worker
from harness.invocation import job_publication_path, lane_layout, publish_job
from harness.packet import retain_failure_invocations, write_manifest
from harness.worker import NETWORK_PROBE_ENV, PROTOCOL_SELF_TEST_ENV, PROTOCOL_SELF_TEST_SCHEMA
from tests.packet_fixture import NUMPY, OFFICIAL, PIP, build_packet
from tests.worker_fixtures import protocol_job
from harness.worker_protocol import PLANNED_ROW_KEYS


def config(root: Path):
    paths = {name: str(root / name) for name in (
        "runtime", "packet", "harness", "python.exe", "wheelhouse", "official.whl",
        "DESIGN.md", "FROZEN-CONFIG.json", "original.csv",
        "wheelhouse-spec.json", "wheelhouse-receipt.json",
    )}
    packet_paths = canonical_packet_paths(Path(paths["packet"]))
    vectors = {query_id: [float(index + 1)] * 384 for index, query_id in enumerate(QUERY_IDS)}
    return {
        "schema": "arc4.campaign-config/v1", "run_id": "run",
        "runtime_root": paths["runtime"], "packet_root": paths["packet"], "harness_root": paths["harness"],
        "python_executable": paths["python.exe"], "wheelhouse": paths["wheelhouse"],
        "lane_interpreters": {"numpy_present": str(root / "present" / "Scripts" / "python.exe"), "numpy_absent": str(root / "absent" / "Scripts" / "python.exe")},
        "frozen_cases": str(packet_paths["frozen_cases"]), "environment_lock": str(packet_paths["environment_lock"]),
        "preregistration_inputs": str(packet_paths["preregistration_inputs"]), "preregistration_commit_receipt": str(packet_paths["preregistration_commit_receipt"]),
        "preregistration_repository": str(root),
        "corpora": {name: {"database": str(root / f"{name}.db"), "repo_id": name, "candidate_ids": ["a", "b"]} for name in ("django", "fastapi", "jcodemunch")},
        "queries": {query_id: {"query_text": query_id, "query_vector": vectors[query_id], "query_vector_sha256": hashlib.sha256(json.dumps(vectors[query_id], ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=False).encode("utf-8")).hexdigest()} for index, query_id in enumerate(QUERY_IDS)},
        "worker_timeout_seconds": 900, "official_wheel": paths["official.whl"],
        "source_checkout": str(root / "source-checkout"), "source_build_output": str(root / "source-build-output"),
        "source_build_receipt": str(packet_paths["source_build_receipt"]), "source_build_receipt_digest": str(packet_paths["source_build_receipt_digest"]),
        "p0_receipt": str(packet_paths["p0_receipt"]), "design_path": paths["DESIGN.md"], "frozen_config": paths["FROZEN-CONFIG.json"],
        "approved_utc": "2026-08-05T00:00:00Z", "pypi_url": "https://files.pythonhosted.org/fixture.whl",
        "wheelhouse_spec": paths["wheelhouse-spec.json"], "wheelhouse_receipt": paths["wheelhouse-receipt.json"],
        "original_matrix_csv": paths["original.csv"],
        "environment_capture_specs": {"numpy_present": str(Path(paths["packet"]) / "env" / "raw-numpy-present.json"), "numpy_absent": str(Path(paths["packet"]) / "env" / "raw-numpy-absent.json")},
        "environment_lane_roots": {"numpy_present": {"lane_venv": str(root / "present"), "trial_root": str(root / "trial-present")}, "numpy_absent": {"lane_venv": str(root / "absent"), "trial_root": str(root / "trial-absent")}},
        "child_environment": {"system_root": str(root / "Windows"), "temp": str(root / "temp"), "locale": "C", "timezone": "UTC", "pythonhashseed": "0"},
    }


def write_fixture_environment_binding(value: dict) -> None:
    Path(value["environment_lock"]).parent.mkdir(parents=True, exist_ok=True)
    configuration = {"share_savings": False, "perf_telemetry_enabled": False, "embed_model": "arc4-fixture-sentinel"}
    bindings = {}
    for lane, name in (("numpy_present", "numpy-present.json"), ("numpy_absent", "numpy-absent.json")):
        manifest_path = Path(value["packet_root"]) / "env" / name
        atomic_write(manifest_path, canonical_json_bytes({"configuration": configuration}), allowed_root=Path(value["packet_root"]))
        bindings[lane] = {"path": f"env/{name}", "sha256": sha256_file(manifest_path)}
    roots = {}
    for lane in ("numpy_present", "numpy_absent"):
        lane_root = Path(value["environment_lane_roots"][lane]["lane_venv"]).resolve()
        interpreter = lane_root / "Scripts" / "python.exe"
        interpreter.parent.mkdir(parents=True, exist_ok=True)
        if not interpreter.exists():
            interpreter.write_bytes(f"fixture-{lane}".encode("ascii"))
        package_root = lane_root / "Lib" / "site-packages" / "jcodemunch_mcp"
        package_root.mkdir(parents=True, exist_ok=True)
        roots[lane] = {"lane_venv": str(lane_root), "trial_root": str(Path(value["environment_lane_roots"][lane]["trial_root"]).resolve()), "python_executable": str(interpreter.resolve()), "python_executable_sha256": sha256_file(interpreter), "package_root": str(package_root.resolve())}
    Path(value["environment_lock"]).write_bytes(canonical_json_bytes({"manifest_bindings": {"canonical": bindings, "roots": roots}}))


def prepared_cases(value: dict) -> dict:
    corpora = []
    for name in ("django", "fastapi", "jcodemunch"):
        database = Path(value["corpora"][name]["database"])
        database.write_bytes(name.encode("ascii"))
        corpora.append({"name": name, "working_database_sha256": sha256_file(database), "candidate_ids": ["a", "b"]})
    queries = {
        query_id: {
            "query": query_id,
            "query_embedding_sha256": value["queries"][query_id]["query_vector_sha256"],
            "serialized_args": {"query": query_id, "semantic_only": index < 2, "semantic_weight": 1.0 if index < 2 else 0.5, "max_results": 10 if index in (0, 2) else 25, "detail_level": "compact", "debug": False},
        }
        for index, query_id in enumerate(QUERY_IDS)
    }
    write_fixture_environment_binding(value)
    atomic_write(Path(value["packet_root"]) / "CONFIG.json", canonical_json_bytes(value), allowed_root=Path(value["packet_root"]))
    cases = generate_frozen_cases(run_id="run", corpora=corpora, queries=queries)
    atomic_write(Path(value["frozen_cases"]), canonical_json_bytes(cases), allowed_root=Path(value["packet_root"]))
    return cases


def successful_result(command, **kwargs):
    job = json.loads(Path(kwargs.get("job_path", command[-1])).read_text(encoding="utf-8"))
    planned_keys = (
        "problem_id", "case_id", "pair_id", "corpus", "form_id", "query_id", "cache_state", "repetition", "top_k",
        "serialized_args", "serialized_args_sha256", "debug_observation_args", "debug_observation_args_sha256",
        "corpus_sha256", "candidate_ids_sha256", "candidate_count", "query_vector_sha256", "lane_invocation_order", "row_id", "arm",
    )
    matrix = job["arm"] == "matrix"
    final = {"a": 1.0, "b": 0.5} if matrix else {}
    debug_scores = [{"id": key, "public_score": round(value, 4), "adapter_rounded": round(value, 4)} for key, value in ({"a": 1.0, "b": 0.5}).items()]
    lane_present = job["lane"] == "numpy_present"
    return {
        "schema": "arc4.row-result/v1", **{key: job[key] for key in planned_keys}, "lane": job["lane"],
        "attempt_n": job["attempt_n"], "attempt_methodology": job["attempt_methodology"], "repair_reason": job["repair_reason"],
        "pair_invocation_ordinal": job["pair_invocation_ordinal"], "observed_query_vector_sha256": job["query_vector_sha256"],
        "frozen_source_files": job["frozen_source_files"], "trial_source_files": job["trial_source_files"],
        "public_result_ids": ["a", "b"], "raw_cosine": {key: value.hex() for key, value in final.items()},
        "final_scores": {key: value.hex() for key, value in final.items()}, "full_depth_ordering_sha256": ordering_sha256(final) if matrix else None,
        "provider_calls": [], "warmup_result": None, "cache_before": {}, "cache_after_public": {}, "cache_after_warmup": None,
        "served_from_result_cache": False, "database_state_before": {}, "database_state": {},
        "matrix_stamp_before_measurement": None, "matrix_stamp_after_measurement": None, "wall_ns": 1, "process_cpu_ns": 1,
        "debug_observation": {"debug": True, "ordered_ids": ["a", "b"], "scores": debug_scores, "order_matches": True, "rounded_scores_match": True, "adapter_kind": "final" if matrix else "bm25_identity"},
        "package_evidence": {"official_wheel_sha256": "ff74b6344430053c6fad9064892d6a3904ffba6265823e3fba4dfde78f9a0488", "environment_lock_sha256": job["environment_lock_sha256"], "installed_version": "1.108.228", "payload_file_count": 1, "payload_matches_official_wheel": True, "module_origins": {"jcodemunch_mcp": "fixture.py"}},
        "lane_evidence": {"numpy_version": "2.4.4" if lane_present else None, "numpy_import_failed_before": not lane_present, "numpy_importable_before": lane_present, "numpy_helper_non_null_before": lane_present, "numpy_importable_after": lane_present, "numpy_import_failed_after": not lane_present, "numpy_helper_non_null_after": lane_present, "matrix_vectorised": lane_present if matrix else None},
        "controls": {"network_attempts": [], "network_tripwire_installed_before_config": True, "network_lifetime_guard_registered": True, "credentials_absent": True, "sharing_disabled": True, "package_unchanged": True, "database_unchanged": True, "candidate_set_matches": True, "provider_expected_calls": 0, "provider_observed_calls": 0, "topup_tripwire_events": 0, "storage_tuning_absent": True, "home_tuning_absent": True, "effective_weight_matches": True},
    }


class CampaignTests(unittest.TestCase):
    @staticmethod
    def _mark_lease_owner_stale(owner: CampaignOwner) -> None:
        value = json.loads(owner.lease.path.read_text(encoding="utf-8"))
        value["owner"]["creation_time"] = 1
        atomic_write(owner.lease.path, canonical_json_bytes(value), allowed_root=owner.runtime_root)

    @staticmethod
    def _persist_lane_results(owner: CampaignOwner, rows, *, count: int, attempt_n: int = 1, methodology: str = "initial", repair_reason=None) -> None:
        pair_directory = sha256_bytes(rows[0]["pair_id"].encode("utf-8"))
        namespace = "repair" if methodology == "explicit_repair" else "measured"
        for row, ordinal in ordered_rows_for_execution(rows)[:count]:
            job = owner._materialize_job(row, namespace=namespace, pair_invocation_ordinal=ordinal, attempt_n=attempt_n, methodology=methodology, repair_reason=repair_reason)
            result = successful_result(["python", "-m", "harness.worker", str(job)])
            path = owner.runtime_root / "pair-attempts" / pair_directory / f"attempt-{attempt_n:04d}" / f"{row['lane']}.json"
            atomic_write_new(path, canonical_json_bytes(result), allowed_root=owner.runtime_root)

    def test_campaign_artifact_paths_are_fixed_and_external_config_is_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            value = config(Path(directory))
            validate_campaign_config(value)
            for key in ("frozen_cases", "environment_lock", "preregistration_inputs", "preregistration_commit_receipt", "source_build_receipt", "source_build_receipt_digest", "p0_receipt"):
                mutated = dict(value)
                mutated[key] = str(Path(directory) / "alternate" / Path(str(value[key])).name)
                with self.assertRaisesRegex(RuntimeError, "campaign_artifact_path"):
                    validate_campaign_config(mutated)
            mutated = dict(value)
            mutated["frozen_config"] = str(Path(value["packet_root"]) / "CONFIG.json")
            with self.assertRaisesRegex(RuntimeError, "campaign_frozen_config_source"):
                validate_campaign_config(mutated)

    def test_environment_commands_are_frozen_no_deps_installs(self):
        with tempfile.TemporaryDirectory() as directory:
            value = config(Path(directory))
            wheelhouse = Path(value["wheelhouse"])
            wheelhouse.mkdir()
            for source in (OFFICIAL, NUMPY, PIP):
                shutil.copy2(source, wheelhouse / source.name)
            validate_campaign_config(value)
            commands = environment_creation_commands(value)
            self.assertEqual(6, len(commands))
            pip_commands = [command for command in commands if command[1:3] == ["-m", "pip"]]
            self.assertEqual(4, len(pip_commands))
            self.assertTrue(all("--no-index" in command and "--no-deps" in command for command in pip_commands))

    def test_modes_are_explicit_and_staged_cannot_select_rows(self):
        corpora = [{"name": name, "working_database_sha256": digit * 64, "candidate_ids": ["a"]} for name, digit in (("django", "a"), ("fastapi", "b"), ("jcodemunch", "c"))]
        queries = {}
        for index, query_id in enumerate(QUERY_IDS):
            semantic_only = index < 2
            queries[query_id] = {"query": query_id, "query_embedding_sha256": f"{index + 1:x}" * 64, "serialized_args": {"query": query_id, "semantic_only": semantic_only, "semantic_weight": 1.0 if semantic_only else 0.5, "max_results": 10 if index in (0, 2) else 25, "detail_level": "compact", "debug": False}}
        cases = generate_frozen_cases(run_id="run", corpora=corpora, queries=queries)
        self.assertEqual([], rows_for_mode(cases, "staged"))
        self.assertEqual(24, len(rows_for_mode(cases, "preflight")))
        self.assertEqual(264, len(rows_for_mode(cases, "full-run")))

    def test_owned_p0_uses_only_generator_return_and_binds_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = config(root)
            packet = Path(value["packet_root"])
            packet.mkdir(exist_ok=True)
            Path(value["source_build_receipt"]).write_bytes(b"caller-authored receipt must be replaced\n")
            output = Path(value["source_build_output"])
            rebuilt = output / "owned.whl"
            observed_calls = []

            def generator(**kwargs):
                observed_calls.append(kwargs)
                output.mkdir()
                rebuilt.write_bytes(b"owned wheel")
                receipt = {"produced_wheel": {"path": str(rebuilt.resolve()), "sha256": sha256_file(rebuilt)}}
                digest = sha256_bytes(canonical_json_bytes(receipt))
                atomic_write(Path(kwargs["receipt_path"]), canonical_json_bytes(receipt), allowed_root=packet)
                atomic_write(Path(kwargs["digest_path"]), (digest + "\n").encode("ascii"), allowed_root=packet)
                return receipt, digest

            def compare(_official, wheel, **_kwargs):
                self.assertEqual(rebuilt.resolve(), wheel)
                return {"status": "passed", "rebuilt_sha256": sha256_file(wheel)}

            owner = CampaignOwner(value)
            with mock.patch("harness.campaign.generate_and_write_source_build_receipt", side_effect=generator), mock.patch("harness.campaign.validate_source_build_receipt") as validator, mock.patch("harness.campaign.compare_wheels", side_effect=compare):
                receipt, digest, result = owner._run_owned_p0()
            self.assertEqual(1, len(observed_calls))
            self.assertEqual(Path(value["source_checkout"]), observed_calls[0]["checkout"])
            self.assertEqual(Path(value["python_executable"]), observed_calls[0]["python_executable"])
            self.assertEqual(Path(value["source_build_output"]), observed_calls[0]["output_directory"])
            self.assertEqual(canonical_json_bytes(receipt), Path(value["source_build_receipt"]).read_bytes())
            self.assertEqual(digest, sha256_bytes(canonical_json_bytes(receipt)))
            self.assertEqual(sha256_file(rebuilt), result["rebuilt_sha256"])
            validator.assert_called_once()

    def test_owned_p0_rejects_generator_receipt_or_wheel_substitution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = config(root)
            packet = Path(value["packet_root"])
            packet.mkdir()
            output = Path(value["source_build_output"])
            output.mkdir()
            rebuilt = output / "owned.whl"
            rebuilt.write_bytes(b"owned")
            receipt = {"produced_wheel": {"path": str(rebuilt.resolve()), "sha256": sha256_file(rebuilt)}}
            digest = sha256_bytes(canonical_json_bytes(receipt))

            def mismatched_generator(**kwargs):
                atomic_write(Path(kwargs["receipt_path"]), canonical_json_bytes({"different": True}), allowed_root=packet)
                atomic_write(Path(kwargs["digest_path"]), (digest + "\n").encode("ascii"), allowed_root=packet)
                return receipt, digest

            owner = CampaignOwner(value)
            with mock.patch("harness.campaign.generate_and_write_source_build_receipt", side_effect=mismatched_generator), mock.patch("harness.campaign.compare_wheels") as compare:
                with self.assertRaisesRegex(RuntimeError, "owned_source_build_receipt_bytes"):
                    owner._run_owned_p0()
            compare.assert_not_called()

            substituted = root / "substituted.whl"
            substituted.write_bytes(b"substituted")
            substituted_receipt = {"produced_wheel": {"path": str(substituted.resolve()), "sha256": sha256_file(substituted)}}
            substituted_digest = sha256_bytes(canonical_json_bytes(substituted_receipt))
            def substituted_generator(**kwargs):
                atomic_write(Path(kwargs["receipt_path"]), canonical_json_bytes(substituted_receipt), allowed_root=packet)
                atomic_write(Path(kwargs["digest_path"]), (substituted_digest + "\n").encode("ascii"), allowed_root=packet)
                return substituted_receipt, substituted_digest
            with mock.patch("harness.campaign.generate_and_write_source_build_receipt", side_effect=substituted_generator), mock.patch("harness.campaign.compare_wheels") as compare:
                with self.assertRaisesRegex(RuntimeError, "owned_source_build_wheel_root"):
                    owner._run_owned_p0()
            compare.assert_not_called()

    def test_full_semantic_preregistration_gate_runs_before_any_row(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = config(root)
            cases = prepared_cases(value)
            atomic_write(Path(value["frozen_cases"]), canonical_json_bytes(cases), allowed_root=root)
            owner = CampaignOwner(value)
            with mock.patch("harness.campaign.validate_preregistration_commit"), mock.patch("harness.campaign.validate_frozen_execution_inputs"), mock.patch("harness.campaign.validate_full_preregistration_semantics", side_effect=RuntimeError("semantic preregistration rejection")), mock.patch.object(owner, "_execute_rows") as execute_rows:
                with self.assertRaisesRegex(RuntimeError, "semantic preregistration rejection"):
                    owner.execute("preflight")
            execute_rows.assert_not_called()

    def test_pair_execution_uses_declared_lane_order_and_observed_ordinal(self):
        corpora = [{"name": name, "working_database_sha256": digit * 64, "candidate_ids": ["a"]} for name, digit in (("django", "a"), ("fastapi", "b"), ("jcodemunch", "c"))]
        queries = {query_id: {"query": query_id, "query_embedding_sha256": f"{index + 1:x}" * 64, "serialized_args": {"query": query_id, "semantic_only": index < 2, "semantic_weight": 1.0 if index < 2 else 0.5, "max_results": 10 if index in (0, 2) else 25, "detail_level": "compact", "debug": False}} for index, query_id in enumerate(QUERY_IDS)}
        cases = generate_frozen_cases(run_id="run", corpora=corpora, queries=queries)
        ordered = ordered_rows_for_execution(rows_for_mode(cases, "preflight"))
        for index in range(0, len(ordered), 2):
            first, second = ordered[index], ordered[index + 1]
            expected_first = "numpy_present" if first[0]["lane_invocation_order"] == "numpy_first" else "numpy_absent"
            self.assertEqual((expected_first, 1), (first[0]["lane"], first[1]))
            self.assertEqual(2, second[1])

    def test_child_environment_is_closed_and_drops_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            value = config(Path(directory))
            home = Path(directory) / "trial-home"
            environment = child_environment(value, Path(sys.executable), home=home)
            self.assertEqual("0", environment["PYTHONHASHSEED"])
            self.assertEqual("1", environment["PYTHONNOUSERSITE"])
            self.assertFalse(any(key.endswith("API_KEY") for key in environment))
            self.assertNotIn("JCODEMUNCH_EMBED_MATRIX_CACHE", environment)
            observed = subprocess.run(
                [sys.executable, "-c", "from pathlib import Path; print(Path.home())"],
                cwd=directory, env=environment, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=10, check=True,
            ).stdout.strip()
            self.assertEqual(home.resolve(), Path(observed).resolve())

    def test_rowless_failures_are_appendable_closed_and_preserve_original_error(self):
        with tempfile.TemporaryDirectory() as directory:
            value = config(Path(directory))
            owner = CampaignOwner(value)
            owner.lease.acquire()
            try:
                stages = (("setup", "infrastructure"), ("p0", "protocol"), ("environment", "infrastructure"), ("control", "protocol"), ("consolidation", "infrastructure"), ("verification", "verification"))
                for stage, classification in stages:
                    owner._failure(stage=stage, classification=classification, code=f"{stage}_failure", reason=f"original {stage} error")
            finally:
                owner.lease.release()
            records = [json.loads(line) for line in owner.failure_journal.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(6, len(records))
            for record in records:
                self.assertEqual(1, record["attempt_n"])
                self.assertEqual("initial", record["methodology"])
                self.assertEqual({"run_id": "run", "row_id": None, "pair_id": None, "case_id": None, "problem_id": None, "arm": None, "lane": None}, record["row_identity"])
                self.assertTrue(record["reason"].startswith("original "))

    def test_trial_copy_includes_present_sidecars_and_rejects_drift_from_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = config(root)
            for name in ("django", "fastapi", "jcodemunch"):
                database = Path(value["corpora"][name]["database"])
                database.write_bytes(name.encode("ascii"))
            django = Path(value["corpora"]["django"]["database"])
            Path(str(django) + "-wal").write_bytes(b"wal")
            Path(str(django) + "-shm").write_bytes(b"shm")
            write_fixture_environment_binding(value)
            owner = CampaignOwner(value)
            atomic_write(owner.runtime_root / "frozen-originals-start.json", canonical_json_bytes(frozen_original_snapshot(value)), allowed_root=owner.runtime_root)
            corpora = [{"name": name, "working_database_sha256": sha256_file(Path(value["corpora"][name]["database"])), "candidate_ids": ["a", "b"]} for name in ("django", "fastapi", "jcodemunch")]
            queries = {query_id: {"query": query_id, "query_embedding_sha256": value["queries"][query_id]["query_vector_sha256"], "serialized_args": {"query": query_id, "semantic_only": index < 2, "semantic_weight": 1.0 if index < 2 else 0.5, "max_results": 10 if index in (0, 2) else 25, "detail_level": "compact", "debug": False}} for index, query_id in enumerate(QUERY_IDS)}
            cases = generate_frozen_cases(run_id="run", corpora=corpora, queries=queries)
            atomic_write(Path(value["packet_root"]) / "CONFIG.json", canonical_json_bytes(value), allowed_root=Path(value["packet_root"]))
            atomic_write(Path(value["frozen_cases"]), canonical_json_bytes(cases), allowed_root=Path(value["packet_root"]))
            row = next(item for item in cases["planned_rows"] if item["corpus"] == "django")
            job = owner._materialize_job(row)
            job_value = json.loads(job.read_text(encoding="utf-8"))
            trial_database = Path(job_value["database"])
            self.assertEqual("0", job_value["python_hash_seed"])
            self.assertEqual("arc4-fixture-sentinel", job_value["embed_model"])
            self.assertEqual(
                {"share_savings": False, "perf_telemetry_enabled": False, "embed_model": "arc4-fixture-sentinel"},
                json.loads((Path(job_value["storage_path"]) / "config.jsonc").read_text(encoding="utf-8")),
            )
            self.assertEqual(b"wal", Path(str(trial_database) + "-wal").read_bytes())
            self.assertEqual(b"shm", Path(str(trial_database) + "-shm").read_bytes())
            Path(str(django) + "-wal").write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, "frozen_database_changed_since_start"):
                owner._materialize_job(row, namespace="drift")

    def test_explicit_repair_preserves_failure_and_increments_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = config(root)
            cases = prepared_cases(value)
            pair = cases["planned_rows"][0]["pair_id"]
            rows = [row for row in cases["planned_rows"] if row["pair_id"] == pair]
            calls = 0

            def fail_once(command, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("original worker error")
                return successful_result(command, **kwargs)

            owner = CampaignOwner(value, worker_runner=fail_once)
            owner.lease.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "original worker error"):
                    owner._execute_rows(rows)
                executed, skipped = owner._execute_rows(rows, repair_reason="operator corrected fixture")
            finally:
                owner.lease.release()
            self.assertEqual((2, 0), (executed, skipped))
            failures = owner._failure_records()
            self.assertEqual(1, len(failures))
            self.assertEqual(1, failures[0]["attempt_n"])
            fragments = [json.loads(path.read_text(encoding="utf-8")) for path in (owner.runtime_root / "fragments").glob("*.json")]
            self.assertEqual({2}, {item["attempt_n"] for item in fragments})

    def test_second_explicit_failure_advances_attempt_without_implicit_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = config(root)
            cases = prepared_cases(value)
            row = cases["planned_rows"][0]
            rows = [item for item in cases["planned_rows"] if item["pair_id"] == row["pair_id"]]
            owner = CampaignOwner(value, worker_runner=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("still failing")))
            owner.lease.acquire()
            try:
                owner._failure(stage="worker", classification="product_lane", code="worker_failure", reason="first failure", row=row, attempt_n=1)
                with self.assertRaisesRegex(RuntimeError, "still failing"):
                    owner._execute_rows(rows, repair_reason="declared repair one")
                self.assertEqual(3, owner._repair_attempt(rows))
            finally:
                owner.lease.release()
            self.assertEqual([1, 2], [record["attempt_n"] for record in owner._failure_records()])

    def test_wrong_identity_repair_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = config(root)
            cases = prepared_cases(value)
            first, wrong = cases["planned_rows"][0], cases["planned_rows"][-1]
            wrong_rows = [item for item in cases["planned_rows"] if item["pair_id"] == wrong["pair_id"]]
            owner = CampaignOwner(value)
            owner.lease.acquire()
            try:
                owner._failure(stage="worker", classification="product_lane", code="worker_failure", reason="first failure", row=first)
                with self.assertRaisesRegex(RuntimeError, "repair_without_failure"):
                    owner._repair_attempt(wrong_rows)
            finally:
                owner.lease.release()

    def test_repair_resume_skips_existing_valid_fragment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = config(root)
            cases = prepared_cases(value)
            pair = cases["planned_rows"][0]["pair_id"]
            rows = [row for row in cases["planned_rows"] if row["pair_id"] == pair]
            owner = CampaignOwner(value, worker_runner=successful_result)
            owner.lease.acquire()
            try:
                owner._failure(stage="worker", classification="product_lane", code="worker_failure", reason="prior pair failure", row=rows[0])
                owner._repair_declaration(rows, 2, "resume declared repair")
                results = []
                for ordinal, row in enumerate(rows, 1):
                    job = owner._materialize_job(row, namespace="repair", pair_invocation_ordinal=ordinal, attempt_n=2, methodology="explicit_repair", repair_reason="resume declared repair")
                    results.append(successful_result(["python", "-m", "harness.worker", str(job)], attempt_root=root, timeout_seconds=1, environment={}))
                commit_pair_fragment(lease=owner.lease, results=results, expected_rows=rows, attempt_n=2, methodology="explicit_repair", repair_reason="resume declared repair", fragments_root=owner.runtime_root / "fragments")
                executed, skipped = owner._execute_rows(rows, repair_reason="resume declared repair")
            finally:
                owner.lease.release()
            self.assertEqual((0, 2), (executed, skipped))

    def test_stale_owner_reconciles_each_crash_boundary_without_attempt_reuse(self):
        scenarios = ("lease_only", "declaration", "lane_one", "lane_two", "before_promotion")
        for scenario in scenarios:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                value = config(root)
                cases = prepared_cases(value)
                pair_id = cases["planned_rows"][0]["pair_id"]
                rows = [row for row in cases["planned_rows"] if row["pair_id"] == pair_id]
                crashed = CampaignOwner(value, worker_runner=successful_result)
                crashed.lease.acquire()
                if scenario == "declaration":
                    crashed._failure(stage="worker", classification="product_lane", code="worker_failure", reason="attempt one failed", row=rows[0])
                    crashed._repair_declaration(rows, 2, "resume after crash")
                elif scenario in {"lane_one", "lane_two", "before_promotion"}:
                    self._persist_lane_results(crashed, rows, count=1 if scenario == "lane_one" else 2)
                self._mark_lease_owner_stale(crashed)
                resumed = CampaignOwner(value, worker_runner=successful_result)
                resumed.lease.acquire()
                try:
                    self.assertIsNotNone(resumed.lease.recovered_owner)
                    if scenario == "declaration":
                        executed, skipped = resumed._execute_rows(rows, repair_reason="resume after crash")
                        self.assertEqual((2, 0), (executed, skipped))
                        self.assertEqual([1, 2], [item["attempt_n"] for item in resumed._failure_records()])
                        fragment = next((resumed.runtime_root / "fragments").glob("*.json"))
                        self.assertEqual(3, json.loads(fragment.read_text(encoding="utf-8"))["attempt_n"])
                    elif scenario == "lane_one":
                        with self.assertRaisesRegex(RuntimeError, "pair_attempt_requires_repair"):
                            resumed._execute_rows(rows)
                        self.assertEqual([1], [item["attempt_n"] for item in resumed._failure_records()])
                        executed, skipped = resumed._execute_rows(rows, repair_reason="resume incomplete initial attempt")
                        self.assertEqual((2, 0), (executed, skipped))
                    elif scenario in {"lane_two", "before_promotion"}:
                        self.assertEqual((0, 2), resumed._execute_rows(rows))
                        fragment = next((resumed.runtime_root / "fragments").glob("*.json"))
                        self.assertEqual(1, json.loads(fragment.read_text(encoding="utf-8"))["attempt_n"])
                    else:
                        self.assertEqual((2, 0), resumed._execute_rows(rows))
                finally:
                    resumed.lease.release()

    def test_persistence_failures_are_journaled_at_row_or_pair_grain(self):
        failure_points = ("declaration", "lane_one", "lane_two", "promotion")
        for point in failure_points:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                value = config(root)
                cases = prepared_cases(value)
                pair_id = cases["planned_rows"][0]["pair_id"]
                rows = [row for row in cases["planned_rows"] if row["pair_id"] == pair_id]
                owner = CampaignOwner(value, worker_runner=successful_result)
                owner.lease.acquire()
                try:
                    if point == "declaration":
                        owner._failure(stage="worker", classification="product_lane", code="worker_failure", reason="attempt one failed", row=rows[0])
                        original = atomic_write_new
                        def fail_declaration(path, data, *, allowed_root):
                            if "repair-declarations" in Path(path).parts:
                                raise OSError("injected declaration persistence")
                            return original(path, data, allowed_root=allowed_root)
                        with mock.patch("harness.campaign.atomic_write_new", side_effect=fail_declaration), self.assertRaisesRegex(OSError, "injected declaration persistence"):
                            owner._execute_rows(rows, repair_reason="declared persistence repair")
                        record = owner._failure_records()[-1]
                        self.assertIsNone(record["row_identity"]["lane"])
                        self.assertEqual(pair_id, record["row_identity"]["pair_id"])
                        continue
                    original = atomic_write_new
                    calls = 0
                    def fail_lane(path, data, *, allowed_root):
                        nonlocal calls
                        if "pair-attempts" in Path(path).parts:
                            calls += 1
                            target = 1 if point == "lane_one" else 2
                            if calls == target:
                                raise OSError(f"injected {point} persistence")
                        return original(path, data, allowed_root=allowed_root)
                    if point in {"lane_one", "lane_two"}:
                        with mock.patch("harness.campaign.atomic_write_new", side_effect=fail_lane), self.assertRaisesRegex(OSError, f"injected {point} persistence"):
                            owner._execute_rows(rows)
                        record = owner._failure_records()[-1]
                        expected_lane = ordered_rows_for_execution(rows)[0 if point == "lane_one" else 1][0]["lane"]
                        self.assertEqual(expected_lane, record["row_identity"]["lane"])
                    else:
                        with mock.patch("harness.campaign.commit_pair_fragment", side_effect=OSError("injected promotion persistence")), self.assertRaisesRegex(OSError, "injected promotion persistence"):
                            owner._execute_rows(rows)
                        record = owner._failure_records()[-1]
                        self.assertEqual(pair_id, record["row_identity"]["pair_id"])
                        self.assertIsNone(record["row_identity"]["lane"])
                finally:
                    owner.lease.release()

    def test_asymmetric_second_lane_validation_failure_keeps_actual_lane(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = config(root)
            cases = prepared_cases(value)
            pair_id = cases["planned_rows"][0]["pair_id"]
            rows = [row for row in cases["planned_rows"] if row["pair_id"] == pair_id]
            calls = 0
            failing_lane = ordered_rows_for_execution(rows)[1][0]["lane"]

            def malformed_second(command, **kwargs):
                nonlocal calls
                calls += 1
                result = successful_result(command, **kwargs)
                if calls == 2:
                    result["public_result_ids"] = ["not-a-candidate"]
                return result

            owner = CampaignOwner(value, worker_runner=malformed_second)
            owner.lease.acquire()
            try:
                with self.assertRaises(RuntimeError):
                    owner._execute_rows(rows)
            finally:
                owner.lease.release()
            failure = owner._failure_records()[-1]
            self.assertEqual(failing_lane, failure["row_identity"]["lane"])
            self.assertIsNotNone(failure["row_identity"]["row_id"])

    def test_journal_failure_preserves_the_original_persistence_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = config(root)
            cases = prepared_cases(value)
            pair_id = cases["planned_rows"][0]["pair_id"]
            rows = [row for row in cases["planned_rows"] if row["pair_id"] == pair_id]
            owner = CampaignOwner(value, worker_runner=successful_result)
            owner.lease.acquire()
            try:
                with mock.patch("harness.campaign.atomic_write_new", side_effect=OSError("original lane persistence")), mock.patch("harness.campaign.append_failure", side_effect=OSError("journal disk failure")):
                    with self.assertRaisesRegex(RuntimeError, "failure_journal_failed") as raised:
                        owner._execute_rows(rows)
                self.assertIn("original lane persistence", str(raised.exception))
                self.assertIn("journal disk failure", str(raised.exception))
            finally:
                owner.lease.release()

    def test_actual_worker_rejection_survives_journal_fault_restart_and_standalone_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = build_packet(root)
            value = json.loads((packet / "CONFIG.json").read_text(encoding="utf-8"))
            cases = json.loads((packet / "frozen-cases.json").read_text(encoding="utf-8"))
            pair_id = cases["planned_rows"][0]["pair_id"]
            rows = [row for row in cases["planned_rows"] if row["pair_id"] == pair_id]

            def actual_network_rejection(command, **kwargs):
                environment = dict(kwargs.pop("environment"))
                environment["PYTHONHASHSEED"] = "0"
                environment["PYTHONHOME"] = str(Path(sys.executable).resolve().parent)
                environment[NETWORK_PROBE_ENV] = "1"
                kwargs["timeout_seconds"] = 10
                return run_worker(
                    command,
                    environment=environment, **kwargs,
                )

            crashed = CampaignOwner(value, worker_runner=actual_network_rejection)
            crashed.lease.acquire()
            with mock.patch("harness.campaign.append_failure", side_effect=OSError("injected journal persistence failure")):
                with self.assertRaisesRegex(RuntimeError, "failure_journal_failed"):
                    crashed._execute_rows(rows)
            self._mark_lease_owner_stale(crashed)

            resumed = CampaignOwner(value, worker_runner=successful_result)
            resumed.lease.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "pair_attempt_requires_repair"):
                    resumed._execute_rows(rows)
                recovered = resumed._failure_records()
                self.assertEqual(1, len(recovered))
                self.assertEqual("network_attempt", recovered[0]["evidence"]["worker_rejection"]["error_code"])
                self.assertEqual("infrastructure_failure", recovered[0]["error_code"])
                shutil.rmtree(packet / "invocations")
                packet_failure = retain_failure_invocations(packet, recovered)[0]
                atomic_write(packet / "FAILURE-JOURNAL.jsonl", canonical_json_bytes(packet_failure), allowed_root=packet)
                write_manifest(packet)
            finally:
                resumed.lease.release()

            completed = subprocess.run(
                [sys.executable, str(packet / "verify.py")], cwd=packet, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stdout)

    def test_metadata_free_worker_rejection_survives_journal_fault_restart_and_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = build_packet(root)
            value = json.loads((packet / "CONFIG.json").read_text(encoding="utf-8"))
            cases = json.loads((packet / "frozen-cases.json").read_text(encoding="utf-8"))
            pair_id = cases["planned_rows"][0]["pair_id"]
            rows = [row for row in cases["planned_rows"] if row["pair_id"] == pair_id]

            def actual_malformed_rejection(command, **kwargs):
                environment = dict(kwargs.pop("environment"))
                environment["PYTHONHASHSEED"] = "0"
                environment["PYTHONHOME"] = str(Path(sys.executable).resolve().parent)
                kwargs["timeout_seconds"] = 10
                original_popen = subprocess.Popen

                def remove_artifact_then_launch(actual_command, *args, **popen_kwargs):
                    Path(actual_command[-1]).unlink()
                    return original_popen(actual_command, *args, **popen_kwargs)

                with mock.patch("harness.orchestrator.subprocess.Popen", side_effect=remove_artifact_then_launch):
                    return run_worker(
                        command,
                        environment=environment, **kwargs,
                    )

            crashed = CampaignOwner(value, worker_runner=actual_malformed_rejection)
            crashed.lease.acquire()
            with mock.patch("harness.campaign.append_failure", side_effect=OSError("injected journal persistence failure")):
                with self.assertRaisesRegex(RuntimeError, "failure_journal_failed"):
                    crashed._execute_rows(rows)
            self._mark_lease_owner_stale(crashed)

            resumed = CampaignOwner(value, worker_runner=successful_result)
            resumed.lease.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "pair_attempt_requires_repair"):
                    resumed._execute_rows(rows)
                recovered = resumed._failure_records()
                self.assertEqual(1, len(recovered))
                self.assertEqual("worker_job_transport", recovered[0]["evidence"]["worker_rejection"]["error_code"])
                self.assertIsNone(recovered[0]["evidence"]["worker_rejection"]["lane"])
                self.assertEqual(recovered[0]["row_identity"]["row_id"], recovered[0]["evidence"]["invocation_binding"]["row_identity"]["row_id"])
                shutil.rmtree(packet / "invocations")
                packet_failure = retain_failure_invocations(packet, recovered)[0]
                atomic_write(packet / "FAILURE-JOURNAL.jsonl", canonical_json_bytes(packet_failure), allowed_root=packet)
                write_manifest(packet)
            finally:
                resumed.lease.release()

            completed = subprocess.run(
                [sys.executable, str(packet / "verify.py")], cwd=packet, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stdout)

    def test_final_seed_worker_mutation_is_caught_by_last_original_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = config(root)
            cases = prepared_cases(value)
            owner = CampaignOwner(value)
            (owner.runtime_root / "fragments").mkdir(parents=True)
            Path(value["p0_receipt"]).parent.mkdir(parents=True, exist_ok=True)
            Path(value["p0_receipt"]).write_bytes(b"{}\n")
            atomic_write(owner.runtime_root / "frozen-originals-start.json", canonical_json_bytes(frozen_original_snapshot(value)), allowed_root=owner.runtime_root)
            original = Path(value["corpora"]["django"]["database"])

            def mutating_seed(_cases):
                original.write_bytes(b"mutated")
                return {}

            owner._seed_control = mutating_seed
            owner.lease.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "frozen_original_changed_during_seed_control"):
                    owner._finish_full_run(cases)
            finally:
                owner.lease.release()

    def test_production_prelaunch_rejects_semantic_and_command_substitution_before_popen(self):
        mutations = ("other-row", "cross-lane", "database", "corpus-source", "noncanonical", "interpreter", "command")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                packet = build_packet(root)
                value = json.loads((packet / "CONFIG.json").read_text(encoding="utf-8"))
                cases = json.loads((packet / "frozen-cases.json").read_text(encoding="utf-8"))
                row = cases["planned_rows"][0]
                owner = CampaignOwner(value)
                job_path = owner._materialize_job(row)
                job = json.loads(job_path.read_text(encoding="utf-8"))
                layout = lane_layout(value, row["lane"])
                command = [str(layout["interpreter"]), "-m", "harness.worker"]
                if mutation == "other-row":
                    alternate = next(item for item in cases["planned_rows"] if item["row_id"] != row["row_id"])
                    for key in PLANNED_ROW_KEYS:
                        job[key] = alternate[key]
                elif mutation == "cross-lane":
                    alternate = next(item for item in cases["planned_rows"] if item["pair_id"] == row["pair_id"] and item["lane"] != row["lane"])
                    for key in PLANNED_ROW_KEYS:
                        job[key] = alternate[key]
                elif mutation == "database":
                    job["database"] = str((Path(job["storage_path"]) / "substituted.db").resolve())
                    job["trial_source_files"]["database_path"] = job["database"]
                elif mutation == "corpus-source":
                    job["repo_id"] = "substituted/repository"
                elif mutation == "interpreter":
                    other = "numpy_absent" if row["lane"] == "numpy_present" else "numpy_present"
                    command[0] = value["lane_interpreters"][other]
                elif mutation == "command":
                    command.append("unexpected")
                if mutation not in {"interpreter", "command"}:
                    payload = canonical_json_bytes(job)
                    if mutation == "noncanonical":
                        payload = json.dumps(job, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
                    job_path.write_bytes(payload)
                    publication = {"schema": "arc4.job-publication/v1", "path": str(job_path.resolve()), "sha256": sha256_bytes(payload), "bytes": len(payload)}
                    job_publication_path(job_path).write_bytes(canonical_json_bytes(publication))
                else:
                    publication = json.loads(job_publication_path(job_path).read_text(encoding="utf-8"))
                with mock.patch("harness.orchestrator.subprocess.Popen") as popen, self.assertRaises(RuntimeError):
                    run_worker(
                        command, attempt_root=owner.runtime_root / f"attempt-{mutation}", timeout_seconds=10,
                        run_id=value["run_id"], planned_row=row, attempt_n=1, methodology="initial",
                        repair_reason=None, job_path=job_path, job_publication=publication,
                        lane_root=layout["lane_root"], package_root=layout["package_root"], environment={},
                    )
                popen.assert_not_called()

    def test_c9_all_seed_conditions_cross_real_worker_precondition_and_remain_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = build_packet(root)
            value = json.loads((packet / "CONFIG.json").read_text(encoding="utf-8"))
            cases = json.loads((packet / "frozen-cases.json").read_text(encoding="utf-8"))
            row = next(item for item in cases["planned_rows"] if item["arm"] == "matrix" and item["cache_state"] == "cold_fresh_process" and item["repetition"] == 1)
            owner = CampaignOwner(value)
            ordinal = 1 if (row["lane_invocation_order"] == "numpy_first") == (row["lane"] == "numpy_present") else 2
            for label in ("0", "1", "2", "3", "4", "unset"):
                declared = None if label == "unset" else label
                job_path = owner._materialize_job(row, namespace=f"seed-{label}", pair_invocation_ordinal=ordinal, control_id="C9", python_hash_seed=declared)
                job = json.loads(job_path.read_text(encoding="utf-8"))
                self.assertEqual(("control", True, "C9", declared), (job["execution_namespace"], job["is_control"], job["control_id"], job["python_hash_seed"]))
                layout = lane_layout(value, row["lane"])
                environment = child_environment(value, layout["interpreter"], home=Path(job["home_path"]), seed=declared)
                if declared is None:
                    environment.pop("PYTHONHASHSEED", None)
                environment["PYTHONHOME"] = str(Path(sys.executable).resolve().parent)
                environment[NETWORK_PROBE_ENV] = "1"
                publication = json.loads(job_publication_path(job_path).read_text(encoding="utf-8"))
                with self.subTest(seed=label), self.assertRaisesRegex(RuntimeError, "network_attempt"):
                    run_worker(
                        [str(layout["interpreter"]), "-m", "harness.worker"],
                        attempt_root=owner.runtime_root / "attempts" / "control" / "C9" / row["row_id"] / f"seed-{label}" / "attempt-0001",
                        timeout_seconds=10, run_id=value["run_id"], planned_row=row, attempt_n=1,
                        methodology="initial", repair_reason=None, job_path=job_path,
                        job_publication=publication, lane_root=layout["lane_root"], package_root=layout["package_root"],
                        environment=environment,
                    )
                receipt = json.loads((owner.runtime_root / "attempts" / "control" / "C9" / row["row_id"] / f"seed-{label}" / "attempt-0001" / "receipt.json").read_text(encoding="utf-8"))
                self.assertEqual(("control", True, "C9"), (receipt["rejection"]["execution_namespace"], receipt["rejection"]["is_control"], receipt["rejection"]["control_id"]))
            self.assertFalse((owner.runtime_root / "fragments").exists())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = build_packet(root)
            value = json.loads((packet / "CONFIG.json").read_text(encoding="utf-8"))
            cases = json.loads((packet / "frozen-cases.json").read_text(encoding="utf-8"))
            row = next(item for item in cases["planned_rows"] if item["arm"] == "matrix" and item["cache_state"] == "cold_fresh_process" and item["repetition"] == 1)
            owner = CampaignOwner(value)
            ordinal = 1 if (row["lane_invocation_order"] == "numpy_first") == (row["lane"] == "numpy_present") else 2
            job_path = owner._materialize_job(row, namespace="seed-0", pair_invocation_ordinal=ordinal, control_id="C9", python_hash_seed="0")
            job = json.loads(job_path.read_text(encoding="utf-8"))
            layout = lane_layout(value, row["lane"])
            environment = child_environment(value, layout["interpreter"], home=Path(job["home_path"]), seed="1")
            environment["PYTHONHOME"] = str(Path(sys.executable).resolve().parent)
            publication = json.loads(job_publication_path(job_path).read_text(encoding="utf-8"))
            with self.assertRaisesRegex(RuntimeError, "worker_hash_seed"):
                run_worker(
                    [str(layout["interpreter"]), "-m", "harness.worker"], attempt_root=owner.runtime_root / "mismatch",
                    timeout_seconds=10, run_id=value["run_id"], planned_row=row, attempt_n=1,
                    methodology="initial", repair_reason=None, job_path=job_path, job_publication=publication,
                    lane_root=layout["lane_root"], package_root=layout["package_root"], environment=environment,
                )


if __name__ == "__main__":
    unittest.main()
