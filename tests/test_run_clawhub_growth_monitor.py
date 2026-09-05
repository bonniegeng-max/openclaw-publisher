import contextlib
import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
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
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("old first", encoding="utf-8")
            second.write_text("old second", encoding="utf-8")
            failure_injected = False

            def replace_with_failure(source, target):
                nonlocal failure_injected
                if (
                    not failure_injected
                    and target == second
                    and ".new." in source.name
                ):
                    failure_injected = True
                    raise OSError("simulated replace failure")
                source.replace(target)

            with self.assertRaisesRegex(OSError, "simulated replace failure"):
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
                {"first.txt", "second.txt"},
            )

    def test_output_bundle_rejects_duplicate_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "same.txt"

            with self.assertRaisesRegex(ValueError, "目标路径不能重复"):
                MODULE.commit_output_bundle(
                    [(target, b"first"), (target, b"second")]
                )

    def test_output_bundle_removes_new_files_during_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            new_target = root / "new.txt"
            existing_target = root / "existing.txt"
            existing_target.write_text("old", encoding="utf-8")

            def fail_existing_replacement(source, target):
                if target == existing_target and ".new." in source.name:
                    raise OSError("simulated replace failure")
                source.replace(target)

            with self.assertRaisesRegex(OSError, "simulated replace failure"):
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
                {"existing.txt"},
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
            self.assertFalse(
                (metrics / "clawhub-search-change-report.md").exists()
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
            self.assertTrue(
                (metrics / "clawhub-search-change-report.md").exists()
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
