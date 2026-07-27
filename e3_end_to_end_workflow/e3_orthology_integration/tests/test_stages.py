"""Unit and integration tests for restartable stage state management."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from e3orthology.errors import InputValidationError, StageStateError
from e3orthology.stages import (
    StageSpec,
    current_input_records,
    evaluate_stage_reuse,
    execute_stage,
    invalidate_downstream,
    relative_file_record,
    run_stage_plan,
    stage_directory,
)
from tests.helpers import write_text


class StageTests(unittest.TestCase):
    """Exercise atomic execution, reuse, invalidation and control validation."""

    @staticmethod
    def _spec(input_path: Path, name: str = "stage_a") -> StageSpec:
        """Build a stage that copies fixture content into a declared output."""

        def execute(staging: Path) -> dict[str, int]:
            """Write one deterministic output."""

            payload = input_path.read_text(encoding="utf-8")
            (staging / "output.txt").write_text(payload, encoding="utf-8")
            return {"characters": len(payload)}

        return StageSpec(
            name=name,
            version="1",
            expected_outputs=("output.txt",),
            input_provider=lambda: (input_path,),
            executor=execute,
        )

    def test_stage_directory_records_execution_and_reuse(self) -> None:
        """A completed stage is reusable only while all checksums agree."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = write_text(root / "input.txt", "value")
            spec = self._spec(input_path)
            expected_directory = root.resolve() / "stages" / "stage_a"
            self.assertEqual(
                stage_directory(run_root=root, stage_name="stage_a"), expected_directory
            )
            self.assertEqual(len(current_input_records(paths=(input_path,))), 1)
            missing = evaluate_stage_reuse(
                run_root=root,
                spec=spec,
                config_digest="digest",
                package_version="1.0",
            )
            self.assertFalse(missing.reusable)
            manifest = execute_stage(
                run_root=root,
                spec=spec,
                config_digest="digest",
                package_version="1.0",
            )
            self.assertEqual(manifest["status"], "SUCCESS")
            reusable = evaluate_stage_reuse(
                run_root=root,
                spec=spec,
                config_digest="digest",
                package_version="1.0",
            )
            self.assertTrue(reusable.reusable)
            output = expected_directory / "output.txt"
            self.assertEqual(
                relative_file_record(root=expected_directory, path=output)["relative_path"],
                "output.txt",
            )
            with self.assertRaises(InputValidationError):
                relative_file_record(root=expected_directory, path=input_path)
            output.write_text("tampered", encoding="utf-8")
            changed = evaluate_stage_reuse(
                run_root=root,
                spec=spec,
                config_digest="digest",
                package_version="1.0",
            )
            self.assertEqual(changed.reason, "recorded_output_checksum_changed")

    def test_failed_stage_is_retained_and_not_published(self) -> None:
        """Executor and output-contract failures are retained under failed."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = write_text(root / "input", "x")

            def fail_executor(staging: Path) -> dict[str, int]:
                """Raise a deliberate fixture failure."""

                raise RuntimeError("deliberate")

            spec = StageSpec("failure", "1", ("output",), lambda: (input_path,), fail_executor)
            with self.assertRaises(RuntimeError):
                execute_stage(
                    run_root=root,
                    spec=spec,
                    config_digest="x",
                    package_version="1",
                )
            failed = list((root / "failed").iterdir())
            self.assertEqual(len(failed), 1)
            manifest = json.loads((failed[0] / "stage_manifest.json").read_text())
            self.assertEqual(manifest["status"], "FAILED")
            self.assertFalse(stage_directory(run_root=root, stage_name="failure").exists())

            def omit_output(staging: Path) -> dict[str, int]:
                """Return successfully without satisfying the output contract."""

                return {}

            missing_spec = StageSpec(
                "missing_output",
                "1",
                ("output",),
                lambda: (input_path,),
                omit_output,
            )
            with self.assertRaises(StageStateError):
                execute_stage(
                    run_root=root,
                    spec=missing_spec,
                    config_digest="x",
                    package_version="1",
                )

    def test_invalidation_and_stage_plan_controls(self) -> None:
        """Bounded plans validate upstream state and reject unsafe controls."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_text(root / "source", "x")
            first = self._spec(source, "first")
            second = self._spec(source, "second")
            specs = (first, second)
            decisions = run_stage_plan(
                run_root=root,
                ordered_specs=specs,
                config_digest="d",
                package_version="1",
                resume=False,
                start_at=None,
                stop_after=None,
                force_stages=set(),
                dry_run=False,
            )
            self.assertEqual([row["decision"] for row in decisions], ["RUN", "RUN"])
            resumed = run_stage_plan(
                run_root=root,
                ordered_specs=specs,
                config_digest="d",
                package_version="1",
                resume=True,
                start_at=None,
                stop_after=None,
                force_stages=set(),
                dry_run=False,
            )
            self.assertEqual(
                [row["decision"] for row in resumed],
                ["SKIPPED_VALIDATED", "SKIPPED_VALIDATED"],
            )
            with self.assertRaises(StageStateError):
                run_stage_plan(
                    run_root=root,
                    ordered_specs=specs,
                    config_digest="d",
                    package_version="1",
                    resume=False,
                    start_at=None,
                    stop_after=None,
                    force_stages=set(),
                    dry_run=False,
                )
            invalidated = invalidate_downstream(
                run_root=root,
                ordered_specs=specs,
                changed_stage_index=0,
            )
            self.assertEqual(invalidated, ["second"])
            for kwargs in (
                {"ordered_specs": (), "force_stages": set()},
                {"ordered_specs": (first, first), "force_stages": set()},
                {"ordered_specs": specs, "force_stages": {"unknown"}},
                {"ordered_specs": specs, "force_stages": set(), "start_at": "unknown"},
                {"ordered_specs": specs, "force_stages": set(), "stop_after": "unknown"},
                {
                    "ordered_specs": specs,
                    "force_stages": set(),
                    "start_at": "second",
                    "stop_after": "first",
                },
            ):
                parameters = {
                    "run_root": root,
                    "ordered_specs": specs,
                    "config_digest": "d",
                    "package_version": "1",
                    "resume": True,
                    "start_at": None,
                    "stop_after": None,
                    "force_stages": set(),
                    "dry_run": True,
                    **kwargs,
                }
                with self.subTest(parameters=parameters), self.assertRaises(StageStateError):
                    run_stage_plan(**parameters)

            empty_root = root / "empty"
            with self.assertRaises(StageStateError):
                run_stage_plan(
                    run_root=empty_root,
                    ordered_specs=specs,
                    config_digest="d",
                    package_version="1",
                    resume=True,
                    start_at="second",
                    stop_after="second",
                    force_stages=set(),
                    dry_run=True,
                )

    def test_every_manifest_reuse_guard(self) -> None:
        """Each manifest field and file guard returns a distinct non-reuse reason."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = write_text(root / "source", "value")
            spec = self._spec(source)
            execute_stage(
                run_root=root,
                spec=spec,
                config_digest="digest",
                package_version="1",
            )
            final = stage_directory(run_root=root, stage_name=spec.name)
            manifest_path = final / "stage_manifest.json"
            original = json.loads(manifest_path.read_text(encoding="utf-8"))

            manifest_path.unlink()
            self.assertEqual(
                evaluate_stage_reuse(
                    run_root=root,
                    spec=spec,
                    config_digest="digest",
                    package_version="1",
                ).reason,
                "stage_manifest_missing",
            )
            manifest_path.write_text("not json", encoding="utf-8")
            self.assertEqual(
                evaluate_stage_reuse(
                    run_root=root,
                    spec=spec,
                    config_digest="digest",
                    package_version="1",
                ).reason,
                "stage_manifest_invalid_json",
            )

            cases = (
                ("status", "FAILED", "stage_status_not_success"),
                ("stage_version", "different", "stage_version_changed"),
                ("package_version", "different", "package_version_changed"),
                ("config_digest", "different", "configuration_changed"),
                ("inputs", [], "stage_inputs_changed"),
                ("outputs", None, "output_manifest_missing"),
                ("outputs", [], "expected_output_not_recorded"),
            )
            for key, value, reason in cases:
                changed = {**original, key: value}
                manifest_path.write_text(json.dumps(changed), encoding="utf-8")
                with self.subTest(reason=reason):
                    self.assertEqual(
                        evaluate_stage_reuse(
                            run_root=root,
                            spec=spec,
                            config_digest="digest",
                            package_version="1",
                        ).reason,
                        reason,
                    )

            empty_expected_spec = StageSpec(
                name=spec.name,
                version=spec.version,
                expected_outputs=(),
                input_provider=spec.input_provider,
                executor=spec.executor,
            )
            invalid_output = {**original, "outputs": [{"relative_path": None}]}
            manifest_path.write_text(json.dumps(invalid_output), encoding="utf-8")
            self.assertEqual(
                evaluate_stage_reuse(
                    run_root=root,
                    spec=empty_expected_spec,
                    config_digest="digest",
                    package_version="1",
                ).reason,
                "invalid_output_record",
            )

            manifest_path.write_text(json.dumps(original), encoding="utf-8")
            source.rename(root / "source.moved")
            self.assertEqual(
                evaluate_stage_reuse(
                    run_root=root,
                    spec=spec,
                    config_digest="digest",
                    package_version="1",
                ).reason,
                "stage_input_missing_or_invalid",
            )
            (root / "source.moved").rename(source)
            (final / "output.txt").unlink()
            self.assertEqual(
                evaluate_stage_reuse(
                    run_root=root,
                    spec=spec,
                    config_digest="digest",
                    package_version="1",
                ).reason,
                "recorded_output_missing_or_invalid",
            )
