import contextlib
import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_clawhub_growth_monitor.py"
SPEC = importlib.util.spec_from_file_location("run_clawhub_growth_monitor", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

OLD_TIME = "2026-08-20T00:00:00+00:00"
NEW_TIME = "2026-09-05T00:00:00+00:00"
NOW = datetime.fromisoformat("2026-09-05T01:00:00+00:00")
OBSERVATION_END = "2026-09-12T10:45:38+00:00"
OPEN_OBSERVATION_END = "2026-01-01T00:00:00+00:00"


def metrics_snapshot(label):
    return {
        "schemaVersion": 1,
        "collectedAt": label,
        "method": "clawhub inspect --json",
        "activeInstall": False,
        "skills": [
            {
                "slug": "alpha",
                "displayName": "Alpha",
                "summary": "Alpha summary",
                "topics": ["publishing"],
                "latestVersion": "1.0.0",
                "moderation": "clean",
                "stats": {
                    "downloads": 1,
                    "installs": 0,
                    "stars": 0,
                    "versions": 1,
                },
                "registryUpdatedAt": 123456,
            }
        ],
    }


def search_snapshot(label):
    return {
        "schemaVersion": 1,
        "collectedAt": label,
        "method": "clawhub search",
        "activeInstall": False,
        "cliVersion": "0.23.3",
        "queries": [
            {
                "slug": "alpha",
                "query": "alpha",
                "limit": 5,
                "rank": 1,
                "visible": True,
                "resultCount": 1,
                "results": [
                    {
                        "rank": 1,
                        "reference": "alpha v1.0.0",
                        "slug": "alpha",
                        "owner": "@owner",
                        "displayName": "Alpha",
                        "metric": {
                            "type": "score",
                            "value": 0.9,
                            "label": "score 0.900",
                        },
                    }
                ],
            }
        ],
    }


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_observation_policy(root, not_before=OBSERVATION_END):
    write_json(
        root / "metrics" / "observation-policy.json",
        {
            "schemaVersion": 1,
            "notBefore": not_before,
            "reason": "维护后的自然观察窗口",
        },
    )
    write_json(
        root / ".clawhub" / "skill-catalog.json",
        {"skills/alpha": {"displayName": "Alpha"}},
    )
    write_json(
        root / "metrics" / "search-queries.json",
        {
            "schemaVersion": 1,
            "queries": [{"slug": "alpha", "query": "alpha", "limit": 5}],
        },
    )


def write_open_observation_policy(root):
    write_observation_policy(root, OPEN_OBSERVATION_END)


def comparison_snapshot(
    status="eligible",
    decision_ready=True,
    previous_at=OLD_TIME,
    current_at=NEW_TIME,
):
    return {
        "schemaVersion": 1,
        "previousCollectedAt": previous_at,
        "currentCollectedAt": current_at,
        "evidenceQuality": {
            "status": status,
            "decisionReady": decision_ready,
            "reasons": [f"fixture status: {status}"],
        },
    }


class FakeRunner:
    def __init__(
        self,
        fail_on=None,
        comparison_statuses=None,
        metrics_payload=None,
        search_payload=None,
    ):
        self.fail_on = fail_on
        self.comparison_statuses = comparison_statuses or {
            "metrics": ("eligible", True),
            "search": ("eligible", True),
        }
        self.metrics_payload = metrics_payload
        self.search_payload = search_payload
        self.commands = []
        self.invocations = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        self.invocations.append((command, kwargs))
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
            write_json(
                output,
                self.metrics_payload
                if self.metrics_payload is not None
                else metrics_snapshot(NEW_TIME),
            )
        elif script == "collect_clawhub_search_visibility.py":
            write_json(
                output,
                self.search_payload
                if self.search_payload is not None
                else search_snapshot(NEW_TIME),
            )
        elif script == "compare_clawhub_metrics.py":
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(f"report for {output.name}\n", encoding="utf-8")
            kind = "search" if "search" in Path(command[2]).name else "metrics"
            status, decision_ready = self.comparison_statuses[kind]
            json_output = Path(command[command.index("--json-output") + 1])
            write_json(
                json_output,
                comparison_snapshot(status, decision_ready),
            )
        else:
            raise AssertionError(f"unexpected child script: {script}")
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="ok",
            stderr="",
        )


class RunClawHubGrowthMonitorTests(unittest.TestCase):
    def test_repository_observation_policy_is_valid(self):
        policy = MODULE.load_observation_policy(
            SCRIPT.parents[1] / "metrics" / "observation-policy.json"
        )

        self.assertIsNotNone(policy)
        self.assertEqual(policy["notBeforeText"], OBSERVATION_END)
        self.assertIsNotNone(policy["notBefore"].tzinfo)

    def test_missing_observation_policy_fails_before_any_child_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner = FakeRunner()

            with self.assertRaisesRegex(
                FileNotFoundError,
                "观察策略文件缺失",
            ):
                MODULE.run_monitor(
                    root,
                    python_bin="python3",
                    clawhub_bin="clawhub",
                    timeout=10,
                    now=NOW,
                    runner=runner,
                )

            self.assertEqual(runner.commands, [])

    def test_output_bundle_rolls_back_mid_commit_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "clawhub-latest.json"
            second = root / "clawhub-search-latest.json"
            first.write_text("old first", encoding="utf-8")
            second.write_text("old second", encoding="utf-8")
            failure_injected = False

            def replace_with_failure(source, target):
                nonlocal failure_injected
                if (
                    not failure_injected
                    and target == second
                    and source.name == f"new--{target.name}"
                ):
                    failure_injected = True
                    raise OSError("simulated replace failure")
                source.replace(target)

            with self.assertRaisesRegex(OSError, "simulated replace failure"):
                with MODULE.monitor_lock(root):
                    MODULE.commit_output_bundle(
                        [
                            (first, b"new first"),
                            (second, b"new second"),
                        ],
                        replace_file=replace_with_failure,
                    )

            self.assertEqual(first.read_text(encoding="utf-8"), "old first")
            self.assertEqual(second.read_text(encoding="utf-8"), "old second")
            self.assertEqual(
                {path.name for path in root.iterdir()},
                {
                    "clawhub-latest.json",
                    "clawhub-search-latest.json",
                    MODULE.MONITOR_LOCK_NAME,
                },
            )

    def test_output_bundle_rejects_duplicate_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "clawhub-latest.json"

            with self.assertRaisesRegex(ValueError, "目标路径不能重复"):
                with MODULE.monitor_lock(root):
                    MODULE.commit_output_bundle(
                        [(target, b"first"), (target, b"second")]
                    )

    def test_output_bundle_requires_lock_and_rejects_reserved_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "clawhub-latest.json"
            with self.assertRaisesRegex(RuntimeError, "必须持有单实例锁"):
                MODULE.commit_output_bundle([(target, b"content")])

            reserved = root / MODULE.TRANSACTION_JOURNAL_NAME
            with MODULE.monitor_lock(root):
                with self.assertRaisesRegex(ValueError, "不受支持"):
                    MODULE.commit_output_bundle([(reserved, b"content")])
            self.assertFalse(reserved.exists())

    def test_output_bundle_removes_new_files_during_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            new_target = root / "clawhub-growth-decision.md"
            existing_target = root / "clawhub-latest.json"
            existing_target.write_text("old", encoding="utf-8")

            def fail_existing_replacement(source, target):
                if (
                    target == existing_target
                    and source.name == f"new--{target.name}"
                ):
                    raise OSError("simulated replace failure")
                source.replace(target)

            with self.assertRaisesRegex(OSError, "simulated replace failure"):
                with MODULE.monitor_lock(root):
                    MODULE.commit_output_bundle(
                        [
                            (new_target, b"created"),
                            (existing_target, b"new"),
                        ],
                        replace_file=fail_existing_replacement,
                    )

            self.assertFalse(new_target.exists())
            self.assertEqual(
                existing_target.read_text(encoding="utf-8"),
                "old",
            )
            self.assertEqual(
                {path.name for path in root.iterdir()},
                {"clawhub-latest.json", MODULE.MONITOR_LOCK_NAME},
            )

    def test_output_bundle_recovers_after_uncatchable_interruption(self):
        class SimulatedProcessTermination(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "clawhub-latest.json"
            second = root / "clawhub-search-latest.json"
            first.write_text("old first", encoding="utf-8")
            second.write_text("old second", encoding="utf-8")

            def terminate_mid_commit(source, target):
                if target == second and source.name == f"new--{target.name}":
                    raise SimulatedProcessTermination()
                source.replace(target)

            with self.assertRaises(SimulatedProcessTermination):
                with MODULE.monitor_lock(root):
                    MODULE.commit_output_bundle(
                        [
                            (first, b"new first"),
                            (second, b"new second"),
                        ],
                        replace_file=terminate_mid_commit,
                    )

            journal = root / MODULE.TRANSACTION_JOURNAL_NAME
            self.assertTrue(journal.exists())
            self.assertEqual(first.read_text(encoding="utf-8"), "new first")
            self.assertTrue(second.exists())
            self.assertEqual(
                second.read_text(encoding="utf-8"),
                "old second",
            )

            def fail_during_first_recovery(source, target):
                if target.name == first.name:
                    raise OSError("simulated recovery interruption")
                source.replace(target)

            with self.assertRaisesRegex(
                OSError,
                "simulated recovery interruption",
            ):
                with MODULE.monitor_lock(root):
                    MODULE.recover_output_bundle(
                        root,
                        replace_file=fail_during_first_recovery,
                    )
            self.assertTrue(journal.exists())
            self.assertEqual(first.read_text(encoding="utf-8"), "new first")
            self.assertEqual(second.read_text(encoding="utf-8"), "old second")

            with MODULE.monitor_lock(root):
                self.assertTrue(MODULE.recover_output_bundle(root))
            self.assertEqual(first.read_text(encoding="utf-8"), "old first")
            self.assertEqual(second.read_text(encoding="utf-8"), "old second")
            self.assertFalse(journal.exists())
            self.assertEqual(
                {path.name for path in root.iterdir()},
                {
                    "clawhub-latest.json",
                    "clawhub-search-latest.json",
                    MODULE.MONITOR_LOCK_NAME,
                },
            )

    def test_transaction_recovery_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transaction_id = "a" * 32
            (root / MODULE.TRANSACTION_ROOT_NAME / transaction_id).mkdir(
                parents=True
            )
            write_json(
                root / MODULE.TRANSACTION_JOURNAL_NAME,
                {
                    "schemaVersion": 1,
                    "phase": "prepared",
                    "transactionId": transaction_id,
                    "entries": [
                        {
                            "target": "../outside.json",
                            "prepared": ".outside.json.new.example.tmp",
                            "backup": None,
                            "existed": False,
                        }
                    ],
                },
            )

            with self.assertRaisesRegex(ValueError, "target 不受支持"):
                with MODULE.monitor_lock(root):
                    MODULE.recover_output_bundle(root)

    def test_recovery_without_journal_preserves_similar_user_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            user_file = root / ".notes.new.keep.tmp"
            user_file.write_text("keep", encoding="utf-8")

            with MODULE.monitor_lock(root):
                self.assertFalse(MODULE.recover_output_bundle(root))
            self.assertEqual(user_file.read_text(encoding="utf-8"), "keep")

    def test_recovery_requires_current_thread_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            with self.assertRaisesRegex(RuntimeError, "当前线程必须持有"):
                MODULE.recover_output_bundle(root)

    def test_recovery_rejects_dangling_journal_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = root / MODULE.TRANSACTION_JOURNAL_NAME
            journal.symlink_to(root / "missing-journal.json")

            with MODULE.monitor_lock(root):
                with self.assertRaisesRegex(RuntimeError, "不能是 symlink"):
                    MODULE.recover_output_bundle(root)

    def test_transaction_root_is_synced_before_journal_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "clawhub-latest.json"
            events = []
            original_sync = MODULE.sync_directory
            original_write_journal = MODULE.write_transaction_journal

            def record_sync(path):
                events.append(("sync", path.resolve()))
                original_sync(path)

            def record_journal(path, payload):
                events.append(("journal", path.parent.resolve()))
                original_write_journal(path, payload)

            with (
                mock.patch.object(
                    MODULE,
                    "sync_directory",
                    side_effect=record_sync,
                ),
                mock.patch.object(
                    MODULE,
                    "write_transaction_journal",
                    side_effect=record_journal,
                ),
                MODULE.monitor_lock(root),
            ):
                MODULE.commit_output_bundle([(target, b"content")])

            journal_index = next(
                index
                for index, event in enumerate(events)
                if event[0] == "journal"
            )
            prior_syncs = [
                path
                for event, path in events[:journal_index]
                if event == "sync"
            ]
            transaction_root = (root / MODULE.TRANSACTION_ROOT_NAME).resolve()
            self.assertEqual(len(prior_syncs), 3)
            self.assertEqual(prior_syncs[0], root.resolve())
            self.assertEqual(prior_syncs[1].parent, transaction_root)
            self.assertEqual(prior_syncs[2], transaction_root)

    def test_post_commit_sync_failure_defers_committed_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "clawhub-latest.json"
            target.write_text("old", encoding="utf-8")
            journal = root / MODULE.TRANSACTION_JOURNAL_NAME
            transaction_root = root / MODULE.TRANSACTION_ROOT_NAME
            original_sync = MODULE.sync_directory
            failure_injected = False

            def fail_after_journal_unlink(path):
                nonlocal failure_injected
                if (
                    not failure_injected
                    and path.resolve() == root.resolve()
                    and target.read_text(encoding="utf-8") == "new"
                    and not journal.exists()
                ):
                    failure_injected = True
                    raise OSError("simulated post-commit sync failure")
                original_sync(path)

            stderr = io.StringIO()
            with (
                mock.patch.object(
                    MODULE,
                    "sync_directory",
                    side_effect=fail_after_journal_unlink,
                ),
                contextlib.redirect_stderr(stderr),
                MODULE.monitor_lock(root),
            ):
                MODULE.commit_output_bundle([(target, b"new")])

            self.assertTrue(failure_injected)
            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            self.assertFalse(journal.exists())
            self.assertTrue(transaction_root.exists())
            self.assertIn("committed journal", stderr.getvalue())

            with MODULE.monitor_lock(root):
                self.assertIsNone(MODULE.recover_output_bundle(root))
            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            self.assertFalse(transaction_root.exists())

    def test_committed_journal_is_finalized_without_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "clawhub-latest.json"
            target.write_text("new", encoding="utf-8")
            transaction_id = "b" * 32
            transaction_directory = (
                root / MODULE.TRANSACTION_ROOT_NAME / transaction_id
            )
            transaction_directory.mkdir(parents=True)
            backup = transaction_directory / f"old--{target.name}"
            backup.write_text("old", encoding="utf-8")
            write_json(
                root / MODULE.TRANSACTION_JOURNAL_NAME,
                {
                    "schemaVersion": 1,
                    "phase": "committed",
                    "transactionId": transaction_id,
                    "entries": [
                        {
                            "target": target.name,
                            "prepared": f"new--{target.name}",
                            "backup": backup.name,
                            "backupSha256": MODULE.sha256_file(backup),
                            "existed": True,
                        }
                    ],
                },
            )

            with MODULE.monitor_lock(root):
                self.assertEqual(
                    MODULE.recover_output_bundle(root),
                    "committed",
                )

            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            self.assertFalse(
                (root / MODULE.TRANSACTION_JOURNAL_NAME).exists()
            )
            self.assertFalse(
                (root / MODULE.TRANSACTION_ROOT_NAME).exists()
            )

    def test_orphan_cleanup_preserves_non_transaction_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transaction_root = root / MODULE.TRANSACTION_ROOT_NAME
            orphan = transaction_root / ("a" * 32)
            user_directory = transaction_root / "notes"
            orphan.mkdir(parents=True)
            user_directory.mkdir()
            (orphan / "old--clawhub-latest.json").write_text(
                "backup",
                encoding="utf-8",
            )

            with MODULE.monitor_lock(root):
                self.assertFalse(MODULE.recover_output_bundle(root))

            self.assertFalse(orphan.exists())
            self.assertTrue(user_directory.is_dir())

    def test_post_commit_cleanup_failure_is_deferred_without_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "clawhub-latest.json"
            target.write_text("old", encoding="utf-8")
            transaction_root = root / MODULE.TRANSACTION_ROOT_NAME
            cleanup_calls = 0
            original_cleanup = MODULE.remove_transaction_directory

            def fail_first_cleanup(directory_path, transaction_directory):
                nonlocal cleanup_calls
                cleanup_calls += 1
                if cleanup_calls == 1:
                    raise OSError("simulated cleanup failure")
                original_cleanup(directory_path, transaction_directory)

            stderr = io.StringIO()
            with (
                mock.patch.object(
                    MODULE,
                    "remove_transaction_directory",
                    side_effect=fail_first_cleanup,
                ),
                contextlib.redirect_stderr(stderr),
                MODULE.monitor_lock(root),
            ):
                MODULE.commit_output_bundle([(target, b"new")])

            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            self.assertTrue(transaction_root.exists())
            self.assertIn("备份清理失败", stderr.getvalue())

            with MODULE.monitor_lock(root):
                self.assertFalse(MODULE.recover_output_bundle(root))
            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            self.assertFalse(transaction_root.exists())

    def test_next_monitor_run_recovers_crash_before_guard_or_network(self):
        class SimulatedProcessTermination(BaseException):
            pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
            metrics_dir = root / "metrics"
            metrics_latest = metrics_dir / "clawhub-latest.json"
            search_latest = metrics_dir / "clawhub-search-latest.json"
            old_metrics = metrics_snapshot(NEW_TIME)
            old_search = search_snapshot(NEW_TIME)
            write_json(metrics_latest, old_metrics)
            write_json(search_latest, old_search)

            def terminate_mid_commit(source, target):
                if (
                    target == search_latest
                    and source.name == f"new--{target.name}"
                ):
                    raise SimulatedProcessTermination()
                source.replace(target)

            with self.assertRaises(SimulatedProcessTermination):
                with MODULE.monitor_lock(metrics_dir):
                    MODULE.commit_output_bundle(
                        [
                            (
                                metrics_latest,
                                MODULE.json_bytes(metrics_snapshot(OLD_TIME)),
                            ),
                            (
                                search_latest,
                                MODULE.json_bytes(search_snapshot(OLD_TIME)),
                            ),
                        ],
                        replace_file=terminate_mid_commit,
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
            self.assertEqual(runner.commands, [])
            self.assertEqual(
                json.loads(metrics_latest.read_text(encoding="utf-8")),
                old_metrics,
            )
            self.assertEqual(
                json.loads(search_latest.read_text(encoding="utf-8")),
                old_search,
            )
            self.assertFalse(
                (metrics_dir / MODULE.TRANSACTION_JOURNAL_NAME).exists()
            )

    def test_monitor_lock_rejects_concurrent_run_before_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
            runner = FakeRunner()

            with MODULE.monitor_lock(root / "metrics"):
                with self.assertRaisesRegex(RuntimeError, "正在运行"):
                    MODULE.run_monitor(
                        root,
                        python_bin="python3",
                        clawhub_bin="clawhub",
                        timeout=10,
                        now=NOW,
                        runner=runner,
                    )

            self.assertEqual(runner.commands, [])

    def test_monitor_lock_rejects_separate_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metrics_dir = root / "metrics"
            metrics_dir.mkdir()
            ready = root / "ready"
            child_code = (
                "import importlib.util, pathlib, sys, time\n"
                "script = pathlib.Path(sys.argv[1])\n"
                "sys.path.insert(0, str(script.parent))\n"
                "spec = importlib.util.spec_from_file_location('monitor', script)\n"
                "module = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(module)\n"
                "with module.monitor_lock(pathlib.Path(sys.argv[2])):\n"
                "    pathlib.Path(sys.argv[3]).write_text('ready')\n"
                "    time.sleep(10)\n"
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    child_code,
                    str(SCRIPT),
                    str(metrics_dir),
                    str(ready),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                for _ in range(100):
                    if ready.exists() or process.poll() is not None:
                        break
                    time.sleep(0.02)
                self.assertTrue(
                    ready.exists(),
                    "separate lock holder did not become ready",
                )
                with self.assertRaisesRegex(RuntimeError, "正在运行"):
                    with MODULE.monitor_lock(metrics_dir):
                        self.fail("separate process lock must not be acquired")
            finally:
                process.terminate()
                process.wait(timeout=5)

    def test_monitor_rejects_symlinked_metrics_directory(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            tempfile.TemporaryDirectory() as outside_directory,
        ):
            root = Path(directory)
            (root / "metrics").symlink_to(
                Path(outside_directory),
                target_is_directory=True,
            )
            runner = FakeRunner()

            with self.assertRaisesRegex(RuntimeError, "不能是 symlink"):
                MODULE.run_monitor(
                    root,
                    python_bin="python3",
                    clawhub_bin="clawhub",
                    timeout=10,
                    now=NOW,
                    runner=runner,
                )

            self.assertEqual(runner.commands, [])

    def test_monitor_lock_rejects_symlinked_lock_file(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            tempfile.TemporaryDirectory() as outside_directory,
        ):
            metrics_dir = Path(directory) / "metrics"
            metrics_dir.mkdir()
            external_lock = Path(outside_directory) / "external.lock"
            external_lock.write_text("external", encoding="utf-8")
            (metrics_dir / MODULE.MONITOR_LOCK_NAME).symlink_to(external_lock)

            with self.assertRaises(OSError):
                with MODULE.monitor_lock(metrics_dir):
                    self.fail("symlinked lock must never be acquired")

            self.assertEqual(
                external_lock.read_text(encoding="utf-8"),
                "external",
            )

    def test_first_run_writes_latest_without_previous_or_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
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
            self.assertFalse((metrics / "clawhub-change-report.json").exists())
            self.assertFalse(
                (metrics / "clawhub-search-change-report.md").exists()
            )
            self.assertFalse(
                (metrics / "clawhub-search-change-report.json").exists()
            )
            decision = json.loads(
                (metrics / "clawhub-growth-decision.json").read_text()
            )
            self.assertFalse(decision["decisionReady"])
            self.assertEqual(decision["status"], "data-quality-blocked")
            self.assertTrue(
                (metrics / "clawhub-growth-decision.md").exists()
            )
            self.assertFalse(result["metricsCompared"])
            self.assertFalse(result["searchCompared"])
            self.assertFalse(result["decisionReady"])
            self.assertEqual(len(runner.commands), 2)

    def test_collected_snapshot_pair_rejects_untrusted_shapes(self):
        metrics = metrics_snapshot(NEW_TIME)
        search = search_snapshot(NEW_TIME)
        expected_slugs = {"alpha"}
        expected_queries = {"alpha": ("alpha", 5)}
        cases = []

        contaminated = copy.deepcopy(metrics)
        contaminated["activeInstall"] = True
        cases.append(("activeInstall", contaminated, search))

        wrong_slug = copy.deepcopy(metrics)
        wrong_slug["skills"][0]["slug"] = "beta"
        cases.append(("slug 集合", wrong_slug, search))

        missing_stat = copy.deepcopy(metrics)
        del missing_stat["skills"][0]["stats"]["downloads"]
        cases.append(("stats 缺少 downloads", missing_stat, search))

        drifted_query = copy.deepcopy(search)
        drifted_query["queries"][0]["query"] = "changed"
        cases.append(("query 或 limit", metrics, drifted_query))

        inconsistent_rank = copy.deepcopy(search)
        inconsistent_rank["queries"][0]["rank"] = None
        inconsistent_rank["queries"][0]["visible"] = False
        cases.append(("目标 rank", metrics, inconsistent_rank))

        cross_round = copy.deepcopy(search)
        cross_round["collectedAt"] = "2026-09-05T00:15:01+00:00"
        cases.append(("同一轮采集", metrics, cross_round))

        for message, metrics_payload, search_payload in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    MODULE.validate_collected_snapshot_pair(
                        metrics_payload,
                        search_payload,
                        expected_slugs,
                        expected_queries,
                    )

    def test_invalid_new_snapshot_preserves_existing_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
            metrics_dir = root / "metrics"
            old_metrics = metrics_snapshot(OLD_TIME)
            old_search = search_snapshot(OLD_TIME)
            write_json(metrics_dir / "clawhub-latest.json", old_metrics)
            write_json(
                metrics_dir / "clawhub-search-latest.json",
                old_search,
            )
            invalid_metrics = metrics_snapshot(NEW_TIME)
            invalid_metrics["activeInstall"] = True
            runner = FakeRunner(metrics_payload=invalid_metrics)

            with self.assertRaisesRegex(ValueError, "activeInstall"):
                MODULE.run_monitor(
                    root,
                    python_bin="python3",
                    clawhub_bin="clawhub",
                    timeout=10,
                    now=NOW,
                    runner=runner,
                )

            self.assertEqual(
                json.loads(
                    (metrics_dir / "clawhub-latest.json").read_text()
                ),
                old_metrics,
            )
            self.assertEqual(
                json.loads(
                    (metrics_dir / "clawhub-search-latest.json").read_text()
                ),
                old_search,
            )
            self.assertEqual(len(runner.commands), 2)

    def test_real_subprocess_collectors_accept_only_issued_capability(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
            scripts = root / "scripts"
            scripts.mkdir()
            source_scripts = SCRIPT.parent
            for name in (
                "clawhub_monitor_capability.py",
                "collect_clawhub_metrics.py",
                "collect_clawhub_search_visibility.py",
            ):
                (scripts / name).symlink_to(source_scripts / name)

            write_json(
                root / ".clawhub" / "skill-catalog.json",
                {"skills/alpha": {}},
            )
            write_json(
                root / "metrics" / "search-queries.json",
                {
                    "schemaVersion": 1,
                    "queries": [
                        {"slug": "alpha", "query": "alpha", "limit": 5}
                    ],
                },
            )
            fake_clawhub = root / "fake-clawhub"
            fake_clawhub.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import json",
                        "import sys",
                        "if sys.argv[1:] == ['--cli-version']:",
                        "    print('0.23.3')",
                        "elif sys.argv[1:3] == ['inspect', 'alpha']:",
                        "    print(json.dumps({",
                        "        'skill': {",
                        "            'slug': 'alpha',",
                        "            'displayName': 'Alpha',",
                        "            'summary': 'Alpha summary',",
                        "            'topics': ['publishing'],",
                        "            'stats': {",
                        "                'downloads': 1,",
                        "                'installs': 0,",
                        "                'stars': 0,",
                        "                'versions': 1,",
                        "            },",
                        "        },",
                        "        'latestVersion': {'version': '1.0.0'},",
                        "        'moderation': {'verdict': 'clean'},",
                        "    }))",
                        "elif sys.argv[1:3] == ['search', 'alpha']:",
                        "    print('alpha v1.0.0  @owner  Alpha  score 0.900')",
                        "else:",
                        "    raise SystemExit(2)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            os.chmod(fake_clawhub, 0o755)

            result = MODULE.run_monitor(
                root,
                python_bin=sys.executable,
                clawhub_bin=str(fake_clawhub),
                timeout=10,
                now=NOW,
            )

            self.assertFalse(result["skipped"])
            self.assertEqual(result["metricsCollectedAt"][:4], "2026")
            self.assertEqual(result["searchCollectedAt"][:4], "2026")
            self.assertTrue(
                (root / "metrics" / "clawhub-latest.json").exists()
            )
            self.assertTrue(
                (root / "metrics" / "clawhub-search-latest.json").exists()
            )

    def test_collectors_share_capability_but_compare_does_not_receive_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
            metrics = root / "metrics"
            write_json(metrics / "clawhub-latest.json", metrics_snapshot(OLD_TIME))
            write_json(
                metrics / "clawhub-search-latest.json",
                search_snapshot(OLD_TIME),
            )
            runner = FakeRunner()

            MODULE.run_monitor(
                root,
                python_bin="python3",
                clawhub_bin="clawhub",
                timeout=10,
                now=NOW,
                runner=runner,
            )

            self.assertEqual(len(runner.invocations), 4)
            collector_environments = [
                runner.invocations[index][1]["env"] for index in (0, 1)
            ]
            self.assertEqual(
                collector_environments[0][
                    "OPENCLAW_MONITOR_CAPABILITY_FILE"
                ],
                collector_environments[1][
                    "OPENCLAW_MONITOR_CAPABILITY_FILE"
                ],
            )
            self.assertEqual(
                collector_environments[0][
                    "OPENCLAW_MONITOR_CAPABILITY_TOKEN"
                ],
                collector_environments[1][
                    "OPENCLAW_MONITOR_CAPABILITY_TOKEN"
                ],
            )
            for command, options in runner.invocations[:2]:
                token = options["env"][
                    "OPENCLAW_MONITOR_CAPABILITY_TOKEN"
                ]
                self.assertNotIn(token, command)
            for _, options in runner.invocations[2:]:
                self.assertNotIn("env", options)

    def test_first_run_before_observation_window_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_observation_policy(root)
            runner = FakeRunner()

            with mock.patch.object(
                MODULE,
                "create_monitor_capability_env",
            ) as create_capability:
                result = MODULE.run_monitor(
                    root,
                    python_bin="python3",
                    clawhub_bin="clawhub",
                    timeout=10,
                    now=NOW,
                    runner=runner,
                )

            self.assertTrue(result["skipped"])
            self.assertEqual(result["notBefore"], OBSERVATION_END)
            self.assertIn("自然观察窗口尚未结束", result["skipReason"])
            self.assertEqual(
                result["recommendedAction"],
                "wait-for-next-window",
            )
            self.assertEqual(runner.commands, [])
            create_capability.assert_not_called()
            self.assertFalse((root / "metrics" / "clawhub-latest.json").exists())

    def test_first_run_at_observation_boundary_proceeds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_observation_policy(root)
            runner = FakeRunner()

            result = MODULE.run_monitor(
                root,
                python_bin="python3",
                clawhub_bin="clawhub",
                timeout=10,
                now=datetime.fromisoformat(OBSERVATION_END),
                runner=runner,
            )

            self.assertFalse(result["skipped"])
            self.assertEqual(result["notBefore"], OBSERVATION_END)
            self.assertEqual(len(runner.commands), 2)

    def test_force_bypasses_observation_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_observation_policy(root)
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
            self.assertEqual(result["notBefore"], OBSERVATION_END)
            self.assertEqual(len(runner.commands), 2)

    def test_force_before_observation_end_cannot_become_decision_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_observation_policy(root)
            metrics = root / "metrics"
            write_json(metrics / "clawhub-latest.json", metrics_snapshot(OLD_TIME))
            write_json(
                metrics / "clawhub-search-latest.json",
                search_snapshot(OLD_TIME),
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
            self.assertFalse(result["decisionReady"])
            self.assertEqual(result["decisionStatus"], "observing")
            self.assertEqual(
                result["recommendedAction"],
                "continue-observation",
            )
            decision = json.loads(
                (metrics / "clawhub-growth-decision.json").read_text()
            )
            self.assertEqual(
                decision["observationGate"],
                {
                    "notBefore": OBSERVATION_END,
                    "satisfied": False,
                    "forcedCollection": True,
                },
            )
            self.assertIn("不得进入增长决策", " ".join(decision["reasons"]))

    def test_existing_snapshots_are_rotated_after_all_stages_succeed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
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
            self.assertEqual(
                json.loads(
                    (metrics / "clawhub-change-report.json").read_text()
                ),
                comparison_snapshot(),
            )
            self.assertTrue(
                (metrics / "clawhub-search-change-report.md").exists()
            )
            self.assertEqual(
                json.loads(
                    (
                        metrics / "clawhub-search-change-report.json"
                    ).read_text()
                ),
                comparison_snapshot(),
            )
            self.assertTrue(result["metricsCompared"])
            self.assertTrue(result["searchCompared"])
            self.assertTrue(result["decisionReady"])
            self.assertEqual(result["decisionStatus"], "eligible")
            self.assertEqual(
                result["recommendedAction"],
                "review-growth-signals",
            )
            self.assertEqual(len(runner.commands), 4)

    def test_collection_failure_preserves_all_existing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
            metrics = root / "metrics"
            old_metrics = metrics_snapshot(OLD_TIME)
            old_search = search_snapshot(OLD_TIME)
            write_json(metrics / "clawhub-latest.json", old_metrics)
            write_json(metrics / "clawhub-search-latest.json", old_search)
            metrics_report = metrics / "clawhub-change-report.md"
            search_report = metrics / "clawhub-search-change-report.md"
            decision_json = metrics / "clawhub-growth-decision.json"
            decision_report = metrics / "clawhub-growth-decision.md"
            metrics_report.write_text("old metrics report\n", encoding="utf-8")
            search_report.write_text("old search report\n", encoding="utf-8")
            write_json(decision_json, {"decisionReady": False, "old": True})
            decision_report.write_text("old decision report\n", encoding="utf-8")
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
            self.assertEqual(
                json.loads(decision_json.read_text()),
                {"decisionReady": False, "old": True},
            )
            self.assertEqual(
                decision_report.read_text(encoding="utf-8"),
                "old decision report\n",
            )
            self.assertFalse((metrics / "clawhub-previous.json").exists())
            self.assertFalse((metrics / "clawhub-search-previous.json").exists())
            self.assertEqual(
                [Path(command[1]).name for command in runner.commands],
                [
                    "collect_clawhub_metrics.py",
                    "collect_clawhub_search_visibility.py",
                ],
            )

    def test_comparison_failure_preserves_existing_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
            metrics = root / "metrics"
            old_metrics = metrics_snapshot(OLD_TIME)
            old_search = search_snapshot(OLD_TIME)
            write_json(metrics / "clawhub-latest.json", old_metrics)
            write_json(metrics / "clawhub-search-latest.json", old_search)

            with self.assertRaisesRegex(RuntimeError, "simulated failure"):
                MODULE.run_monitor(
                    root,
                    python_bin="python3",
                    clawhub_bin="clawhub",
                    timeout=10,
                    now=NOW,
                    runner=FakeRunner(fail_on="compare_clawhub_metrics.py"),
                )

            self.assertEqual(
                json.loads((metrics / "clawhub-latest.json").read_text()),
                old_metrics,
            )
            self.assertEqual(
                json.loads((metrics / "clawhub-search-latest.json").read_text()),
                old_search,
            )
            self.assertFalse((metrics / "clawhub-previous.json").exists())
            self.assertFalse((metrics / "clawhub-search-previous.json").exists())
            self.assertFalse(
                (metrics / "clawhub-growth-decision.json").exists()
            )

    def test_missing_comparison_artifact_preserves_existing_baseline(self):
        for missing_kind, artifact_option in (
            ("metrics", "--output"),
            ("metrics", "--json-output"),
            ("search", "--output"),
            ("search", "--json-output"),
        ):
            with self.subTest(
                missing_kind=missing_kind,
                artifact_option=artifact_option,
            ), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                write_open_observation_policy(root)
                metrics = root / "metrics"
                old_metrics = metrics_snapshot(OLD_TIME)
                old_search = search_snapshot(OLD_TIME)
                write_json(metrics / "clawhub-latest.json", old_metrics)
                write_json(metrics / "clawhub-search-latest.json", old_search)
                metrics_report = metrics / "clawhub-change-report.md"
                search_report = metrics / "clawhub-search-change-report.md"
                metrics_report.write_text(
                    "old metrics report\n",
                    encoding="utf-8",
                )
                search_report.write_text(
                    "old search report\n",
                    encoding="utf-8",
                )
                runner = FakeRunner()

                def omit_one_artifact(command, **kwargs):
                    result = runner(command, **kwargs)
                    script = Path(command[1]).name
                    if script == "compare_clawhub_metrics.py":
                        kind = (
                            "search"
                            if "search" in Path(command[2]).name
                            else "metrics"
                        )
                        if kind == missing_kind:
                            artifact = Path(
                                command[command.index(artifact_option) + 1]
                            )
                            artifact.unlink()
                    return result

                with self.assertRaisesRegex(
                    RuntimeError,
                    "未生成约定的",
                ):
                    MODULE.run_monitor(
                        root,
                        python_bin="python3",
                        clawhub_bin="clawhub",
                        timeout=10,
                        now=NOW,
                        runner=omit_one_artifact,
                    )

                self.assertEqual(
                    json.loads((metrics / "clawhub-latest.json").read_text()),
                    old_metrics,
                )
                self.assertEqual(
                    json.loads(
                        (metrics / "clawhub-search-latest.json").read_text()
                    ),
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
                self.assertFalse(
                    (metrics / "clawhub-previous.json").exists()
                )
                self.assertFalse(
                    (metrics / "clawhub-search-previous.json").exists()
                )

    def test_recent_complete_run_is_skipped_without_child_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
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
            self.assertIsNone(result["decisionReady"])
            self.assertEqual(result["decisionStatus"], "skipped")
            self.assertEqual(
                result["recommendedAction"],
                "wait-for-next-window",
            )
            self.assertEqual(runner.commands, [])

    def test_force_bypasses_recent_run_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
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

    def test_force_does_not_bypass_future_snapshot_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
            metrics = root / "metrics"
            future = "2026-09-06T00:00:00+00:00"
            write_json(metrics / "clawhub-latest.json", metrics_snapshot(future))
            write_json(
                metrics / "clawhub-search-latest.json",
                search_snapshot(future),
            )
            runner = FakeRunner()

            with self.assertRaisesRegex(ValueError, "晚于当前时间"):
                MODULE.run_monitor(
                    root,
                    python_bin="python3",
                    clawhub_bin="clawhub",
                    timeout=10,
                    force=True,
                    now=NOW,
                    runner=runner,
                )

            self.assertEqual(runner.commands, [])

    def test_force_does_not_bypass_malformed_snapshot_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
            metrics = root / "metrics"
            write_json(
                metrics / "clawhub-latest.json",
                metrics_snapshot("not-a-timestamp"),
            )
            runner = FakeRunner()

            with self.assertRaisesRegex(ValueError, "不是有效的 ISO 8601"):
                MODULE.run_monitor(
                    root,
                    python_bin="python3",
                    clawhub_bin="clawhub",
                    timeout=10,
                    force=True,
                    now=NOW,
                    runner=runner,
                )

            self.assertEqual(runner.commands, [])

    def test_partial_future_snapshot_is_rejected_before_first_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
            metrics = root / "metrics"
            future = "2026-09-06T00:00:00+00:00"
            write_json(metrics / "clawhub-latest.json", metrics_snapshot(future))
            runner = FakeRunner()

            with self.assertRaisesRegex(ValueError, "晚于当前时间"):
                MODULE.run_monitor(
                    root,
                    python_bin="python3",
                    clawhub_bin="clawhub",
                    timeout=10,
                    now=NOW,
                    runner=runner,
                )

            self.assertEqual(runner.commands, [])

    def test_single_sided_latest_fails_closed_without_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
            metrics = root / "metrics"
            write_json(metrics / "clawhub-latest.json", metrics_snapshot(OLD_TIME))
            runner = FakeRunner()

            with self.assertRaisesRegex(
                ValueError,
                "必须同时存在或同时缺失",
            ):
                MODULE.run_monitor(
                    root,
                    python_bin="python3",
                    clawhub_bin="clawhub",
                    timeout=10,
                    now=NOW,
                    runner=runner,
                )

            self.assertEqual(runner.commands, [])

    def test_missing_latest_with_stale_derived_output_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
            stale_report = root / "metrics" / "clawhub-change-report.md"
            stale_report.write_text("stale\n", encoding="utf-8")
            runner = FakeRunner()

            with self.assertRaisesRegex(
                ValueError,
                "latest 均缺失但仍存在派生产物",
            ):
                MODULE.run_monitor(
                    root,
                    python_bin="python3",
                    clawhub_bin="clawhub",
                    timeout=10,
                    now=NOW,
                    runner=runner,
                )

            self.assertEqual(runner.commands, [])
            self.assertEqual(
                stale_report.read_text(encoding="utf-8"),
                "stale\n",
            )

    def test_missing_latest_with_stale_json_sidecar_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
            stale_sidecar = root / "metrics" / "clawhub-change-report.json"
            write_json(stale_sidecar, comparison_snapshot())
            runner = FakeRunner()

            with self.assertRaisesRegex(
                ValueError,
                "latest 均缺失但仍存在派生产物",
            ):
                MODULE.run_monitor(
                    root,
                    python_bin="python3",
                    clawhub_bin="clawhub",
                    timeout=10,
                    now=NOW,
                    runner=runner,
                )

            self.assertEqual(runner.commands, [])
            self.assertEqual(
                json.loads(stale_sidecar.read_text(encoding="utf-8")),
                comparison_snapshot(),
            )

    def test_future_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_open_observation_policy(root)
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

    def test_combined_gate_rejects_one_ineligible_component(self):
        decision = MODULE.combine_decisions(
            comparison_snapshot("eligible", True),
            comparison_snapshot("premature", False),
        )

        self.assertFalse(decision["decisionReady"])
        self.assertEqual(decision["status"], "observing")
        self.assertEqual(
            decision["recommendedAction"],
            "continue-observation",
        )

    def test_combined_gate_prioritizes_data_quality(self):
        decision = MODULE.combine_decisions(
            comparison_snapshot("eligible", True),
            comparison_snapshot("incomparable", False),
        )

        self.assertFalse(decision["decisionReady"])
        self.assertEqual(decision["status"], "data-quality-blocked")
        self.assertEqual(
            decision["recommendedAction"],
            "repair-data-quality",
        )

    def test_combined_gate_rejects_cross_run_snapshot_pair(self):
        decision = MODULE.combine_decisions(
            comparison_snapshot(),
            comparison_snapshot(
                previous_at="2026-08-20T00:20:01+00:00",
                current_at="2026-09-05T00:20:01+00:00",
            ),
        )

        self.assertFalse(decision["decisionReady"])
        self.assertEqual(decision["status"], "data-quality-blocked")
        self.assertFalse(decision["pairing"]["aligned"])
        self.assertGreater(
            decision["pairing"]["currentSkewMinutes"],
            MODULE.MAX_PAIR_SKEW_MINUTES,
        )

    def test_combined_gate_accepts_small_collector_time_skew(self):
        decision = MODULE.combine_decisions(
            comparison_snapshot(),
            comparison_snapshot(
                previous_at="2026-08-20T00:14:59+00:00",
                current_at="2026-09-05T00:14:59+00:00",
            ),
        )

        self.assertTrue(decision["decisionReady"])
        self.assertEqual(decision["status"], "eligible")
        self.assertTrue(decision["pairing"]["aligned"])

    def test_combined_gate_rejects_malformed_component_evidence(self):
        malformed = {
            "evidenceQuality": {
                "status": "eligible",
                "decisionReady": "true",
                "reasons": "not-a-list",
            }
        }
        decision = MODULE.combine_decisions(
            comparison_snapshot("eligible", True),
            malformed,
        )

        self.assertFalse(decision["decisionReady"])
        self.assertEqual(decision["status"], "data-quality-blocked")
        self.assertFalse(decision["components"]["search"]["available"])

    def test_cli_rejects_minimum_interval_override(self):
        with mock.patch.object(
            MODULE.sys,
            "argv",
            [
                "run_clawhub_growth_monitor.py",
                "--min-interval-hours",
                "0.001",
            ],
        ):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    MODULE.parse_args()

    def test_cli_rejects_python_interpreter_override(self):
        with mock.patch.object(
            MODULE.sys,
            "argv",
            [
                "run_clawhub_growth_monitor.py",
                "--python-bin",
                "/tmp/wrapper",
            ],
        ):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    MODULE.parse_args()

    def test_cli_rejects_clawhub_executable_override(self):
        with mock.patch.object(
            MODULE.sys,
            "argv",
            [
                "run_clawhub_growth_monitor.py",
                "--clawhub-bin",
                "/tmp/fake-clawhub",
            ],
        ):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    MODULE.parse_args()


if __name__ == "__main__":
    unittest.main()
