import importlib.util
import json
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_clawhub_growth_monitor.py"
SPEC = importlib.util.spec_from_file_location("run_clawhub_growth_monitor", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

OLD_TIME = "2026-08-20T00:00:00+00:00"
NEW_TIME = "2026-09-05T00:00:00+00:00"
NOW = datetime.fromisoformat("2026-09-05T01:00:00+00:00")


def metrics_snapshot(label):
    return {
        "schemaVersion": 1,
        "collectedAt": label,
        "method": "clawhub inspect --json",
        "activeInstall": False,
        "skills": [],
    }


def search_snapshot(label):
    return {
        "schemaVersion": 1,
        "collectedAt": label,
        "method": "clawhub search",
        "activeInstall": False,
        "queries": [],
    }


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class FakeRunner:
    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        script = Path(command[1]).name
        if script == self.fail_on:
            return subprocess.CompletedProcess(
                command,
                returncode=1,
                stdout="",
                stderr="simulated failure",
            )

        output = Path(command[command.index("--output") + 1])
        if script == "collect_clawhub_metrics.py":
            write_json(output, metrics_snapshot(NEW_TIME))
        elif script == "collect_clawhub_search_visibility.py":
            write_json(output, search_snapshot(NEW_TIME))
        elif script == "compare_clawhub_metrics.py":
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(f"report for {output.name}\n", encoding="utf-8")
        else:
            raise AssertionError(f"unexpected child script: {script}")
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="ok",
            stderr="",
        )


class RunClawHubGrowthMonitorTests(unittest.TestCase):
    def test_first_run_writes_latest_without_previous_or_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = FakeRunner()

            result = MODULE.run_monitor(
                root,
                python_bin="python3",
                clawhub_bin="clawhub",
                timeout=10,
                now=NOW,
                runner=runner,
            )

            metrics = root / "metrics"
            self.assertEqual(
                json.loads((metrics / "clawhub-latest.json").read_text()),
                metrics_snapshot(NEW_TIME),
            )
            self.assertEqual(
                json.loads((metrics / "clawhub-search-latest.json").read_text()),
                search_snapshot(NEW_TIME),
            )
            self.assertFalse((metrics / "clawhub-previous.json").exists())
            self.assertFalse((metrics / "clawhub-search-previous.json").exists())
            self.assertFalse((metrics / "clawhub-change-report.md").exists())
            self.assertFalse(
                (metrics / "clawhub-search-change-report.md").exists()
            )
            self.assertFalse(result["metricsCompared"])
            self.assertFalse(result["searchCompared"])
            self.assertEqual(len(runner.commands), 2)

    def test_existing_snapshots_are_rotated_after_all_stages_succeed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metrics = root / "metrics"
            old_metrics = metrics_snapshot(OLD_TIME)
            old_search = search_snapshot(OLD_TIME)
            write_json(metrics / "clawhub-latest.json", old_metrics)
            write_json(metrics / "clawhub-search-latest.json", old_search)
            runner = FakeRunner()

            result = MODULE.run_monitor(
                root,
                python_bin="python3",
                clawhub_bin="clawhub",
                timeout=10,
                now=NOW,
                runner=runner,
            )

            self.assertEqual(
                json.loads((metrics / "clawhub-previous.json").read_text()),
                old_metrics,
            )
            self.assertEqual(
                json.loads(
                    (metrics / "clawhub-search-previous.json").read_text()
                ),
                old_search,
            )
            self.assertEqual(
                json.loads((metrics / "clawhub-latest.json").read_text()),
                metrics_snapshot(NEW_TIME),
            )
            self.assertEqual(
                json.loads((metrics / "clawhub-search-latest.json").read_text()),
                search_snapshot(NEW_TIME),
            )
            self.assertTrue((metrics / "clawhub-change-report.md").exists())
            self.assertTrue(
                (metrics / "clawhub-search-change-report.md").exists()
            )
            self.assertTrue(result["metricsCompared"])
            self.assertTrue(result["searchCompared"])
            self.assertEqual(len(runner.commands), 4)

    def test_collection_failure_preserves_all_existing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metrics = root / "metrics"
            old_metrics = metrics_snapshot(OLD_TIME)
            old_search = search_snapshot(OLD_TIME)
            write_json(metrics / "clawhub-latest.json", old_metrics)
            write_json(metrics / "clawhub-search-latest.json", old_search)
            metrics_report = metrics / "clawhub-change-report.md"
            search_report = metrics / "clawhub-search-change-report.md"
            metrics_report.write_text("old metrics report\n", encoding="utf-8")
            search_report.write_text("old search report\n", encoding="utf-8")
            runner = FakeRunner(
                fail_on="collect_clawhub_search_visibility.py"
            )

            with self.assertRaisesRegex(RuntimeError, "simulated failure"):
                MODULE.run_monitor(
                    root,
                    python_bin="python3",
                    clawhub_bin="clawhub",
                    timeout=10,
                    now=NOW,
                    runner=runner,
                )

            self.assertEqual(
                json.loads((metrics / "clawhub-latest.json").read_text()),
                old_metrics,
            )
            self.assertEqual(
                json.loads((metrics / "clawhub-search-latest.json").read_text()),
                old_search,
            )
            self.assertEqual(
                metrics_report.read_text(encoding="utf-8"),
                "old metrics report\n",
            )
            self.assertEqual(
                search_report.read_text(encoding="utf-8"),
                "old search report\n",
            )
            self.assertFalse((metrics / "clawhub-previous.json").exists())
            self.assertFalse((metrics / "clawhub-search-previous.json").exists())

    def test_recent_complete_run_is_skipped_without_child_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metrics = root / "metrics"
            write_json(metrics / "clawhub-latest.json", metrics_snapshot(NEW_TIME))
            write_json(
                metrics / "clawhub-search-latest.json",
                search_snapshot(NEW_TIME),
            )
            runner = FakeRunner()

            result = MODULE.run_monitor(
                root,
                python_bin="python3",
                clawhub_bin="clawhub",
                timeout=10,
                now=NOW,
                runner=runner,
            )

            self.assertTrue(result["skipped"])
            self.assertIn("小于默认门槛 144 小时", result["skipReason"])
            self.assertEqual(runner.commands, [])

    def test_force_bypasses_recent_run_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metrics = root / "metrics"
            write_json(metrics / "clawhub-latest.json", metrics_snapshot(NEW_TIME))
            write_json(
                metrics / "clawhub-search-latest.json",
                search_snapshot(NEW_TIME),
            )
            runner = FakeRunner()

            result = MODULE.run_monitor(
                root,
                python_bin="python3",
                clawhub_bin="clawhub",
                timeout=10,
                force=True,
                now=NOW,
                runner=runner,
            )

            self.assertFalse(result["skipped"])
            self.assertEqual(len(runner.commands), 4)

    def test_future_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metrics = root / "metrics"
            future = "2026-09-06T00:00:00+00:00"
            write_json(metrics / "clawhub-latest.json", metrics_snapshot(future))
            write_json(
                metrics / "clawhub-search-latest.json",
                search_snapshot(future),
            )

            with self.assertRaisesRegex(ValueError, "晚于当前时间"):
                MODULE.run_monitor(
                    root,
                    python_bin="python3",
                    clawhub_bin="clawhub",
                    timeout=10,
                    now=NOW,
                    runner=FakeRunner(),
                )


if __name__ == "__main__":
    unittest.main()
