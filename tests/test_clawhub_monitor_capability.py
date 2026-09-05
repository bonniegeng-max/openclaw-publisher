import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "clawhub_monitor_capability.py"
)
SPEC = importlib.util.spec_from_file_location(
    "clawhub_monitor_capability",
    SCRIPT,
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ClawHubMonitorCapabilityTests(unittest.TestCase):
    def create_fixture(self, root, now=1000.0):
        script = root / "collect_clawhub_metrics.py"
        output = root / "metrics.json"
        previous = root / "unused-previous.json"
        capability = root / ".collector-capability.json"
        environment = MODULE.create_monitor_capability_env(
            capability,
            parent_pid=1234,
            bindings={script: (output, previous)},
            now_epoch=now,
            base_environment={
                "PATH": "/usr/bin",
                MODULE.CAPABILITY_FILE_ENV: "stale-file",
                MODULE.CAPABILITY_TOKEN_ENV: "stale-token",
            },
        )
        return script, output, previous, capability, environment

    def test_valid_capability_binds_parent_script_and_output_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script, output, previous, capability, environment = (
                self.create_fixture(root)
            )

            MODULE.validate_collector_capability(
                script,
                output,
                previous,
                environment=environment,
                parent_pid=1234,
                now_epoch=1001.0,
            )

            self.assertEqual(oct(capability.stat().st_mode & 0o777), "0o600")
            self.assertNotEqual(
                environment[MODULE.CAPABILITY_TOKEN_ENV],
                "stale-token",
            )

    def test_missing_blank_and_wrong_tokens_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script, output, previous, _, environment = self.create_fixture(root)
            cases = [
                {},
                {
                    MODULE.CAPABILITY_FILE_ENV: " ",
                    MODULE.CAPABILITY_TOKEN_ENV: " ",
                },
                {
                    **environment,
                    MODULE.CAPABILITY_TOKEN_ENV: "wrong-token",
                },
            ]

            for candidate in cases:
                with self.subTest(candidate=candidate):
                    with self.assertRaises(PermissionError):
                        MODULE.validate_collector_capability(
                            script,
                            output,
                            previous,
                            environment=candidate,
                            parent_pid=1234,
                            now_epoch=1001.0,
                        )

    def test_wrong_parent_output_and_expired_context_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script, output, previous, _, environment = self.create_fixture(root)
            cases = [
                {
                    "parent_pid": 4321,
                    "script_path": script,
                    "output_path": output,
                    "now_epoch": 1001.0,
                },
                {
                    "parent_pid": 1234,
                    "script_path": script,
                    "output_path": root / "other.json",
                    "now_epoch": 1001.0,
                },
                {
                    "parent_pid": 1234,
                    "script_path": root / "other" / script.name,
                    "output_path": output,
                    "now_epoch": 1001.0,
                },
                {
                    "parent_pid": 1234,
                    "script_path": script,
                    "output_path": output,
                    "now_epoch": 1601.0,
                },
                {
                    "parent_pid": 1234,
                    "script_path": script,
                    "output_path": output,
                    "now_epoch": float("nan"),
                },
            ]

            for case in cases:
                with self.subTest(case=case):
                    with self.assertRaises(PermissionError):
                        MODULE.validate_collector_capability(
                            case["script_path"],
                            case["output_path"],
                            previous,
                            environment=environment,
                            parent_pid=case["parent_pid"],
                            now_epoch=case["now_epoch"],
                        )

    def test_non_finite_issue_time_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            with self.assertRaisesRegex(ValueError, "有限数值"):
                MODULE.create_monitor_capability_env(
                    root / "capability.json",
                    parent_pid=1234,
                    bindings={
                        root / "collector.py": (
                            root / "output.json",
                            root / "previous.json",
                        )
                    },
                    now_epoch=float("nan"),
                )

    def test_duplicate_fields_and_symlink_context_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script, output, previous, capability, environment = (
                self.create_fixture(root)
            )
            payload = json.loads(capability.read_text(encoding="utf-8"))
            capability.write_text(
                '{"schemaVersion":1,"schemaVersion":1}',
                encoding="utf-8",
            )
            os.chmod(capability, 0o600)
            with self.assertRaisesRegex(ValueError, "重复字段"):
                MODULE.validate_collector_capability(
                    script,
                    output,
                    previous,
                    environment=environment,
                    parent_pid=1234,
                    now_epoch=1001.0,
                )

            capability.write_text(json.dumps(payload), encoding="utf-8")
            symlink = root / "capability-link.json"
            symlink.symlink_to(capability)
            linked_environment = {
                **environment,
                MODULE.CAPABILITY_FILE_ENV: str(symlink),
            }
            with self.assertRaisesRegex(PermissionError, "能力文件无效"):
                MODULE.validate_collector_capability(
                    script,
                    output,
                    previous,
                    environment=linked_environment,
                    parent_pid=1234,
                    now_epoch=1001.0,
                )

    def test_sanitized_environment_removes_only_capability_values(self):
        result = MODULE.sanitized_environment(
            {
                "PATH": "/usr/bin",
                MODULE.CAPABILITY_FILE_ENV: "context",
                MODULE.CAPABILITY_TOKEN_ENV: "token",
            }
        )

        self.assertEqual(result, {"PATH": "/usr/bin"})


if __name__ == "__main__":
    unittest.main()
