import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "collect_clawhub_search_visibility.py"
)
SPEC = importlib.util.spec_from_file_location(
    "collect_clawhub_search_visibility",
    SCRIPT,
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CollectClawHubSearchVisibilityTests(unittest.TestCase):
    def test_load_queries_normalizes_terms(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queries.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "queries": [
                            {
                                "slug": "alpha",
                                "query": "  publish   readiness ",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                MODULE.load_queries(path),
                [
                    {
                        "slug": "alpha",
                        "query": "publish readiness",
                        "limit": 20,
                    }
                ],
            )

    def test_load_queries_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queries.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "queries": [
                            {"slug": "alpha", "query": "same query"},
                            {"slug": "beta", "query": "Same Query"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "query 重复"):
                MODULE.load_queries(path)

    def test_query_coverage_must_match_catalog(self):
        queries = [{"slug": "alpha", "query": "alpha", "limit": 20}]

        with self.assertRaisesRegex(ValueError, "缺少：beta"):
            MODULE.validate_query_coverage(queries, {"alpha", "beta"})

    def test_parse_search_output_handles_native_and_skills_sh_metrics(self):
        output = "\n".join(
            [
                (
                    "skill-publish-readiness v1.0.7  @bonniegeng-max  "
                    "Skill Publish Readiness  1 installs / 60d"
                ),
                (
                    "owner/repo@skill  @owner  External Skill  "
                    "1,234 skills.sh lifetime installs"
                ),
                "other-skill v2.0.0  @owner  Other Skill  score 0.875",
            ]
        )

        results = MODULE.parse_search_output(output)

        self.assertEqual(results[0]["slug"], "skill-publish-readiness")
        self.assertEqual(
            results[0]["metric"],
            {
                "type": "rolling60DayInstalls",
                "value": 1,
                "label": "1 installs / 60d",
            },
        )
        self.assertEqual(
            results[1]["metric"]["type"],
            "skillsShLifetimeInstalls",
        )
        self.assertEqual(results[1]["metric"]["value"], 1234)
        self.assertEqual(results[2]["metric"]["value"], 0.875)

    def test_parse_search_output_strips_ansi(self):
        output = (
            "\x1b[36malpha v1.0.0\x1b[0m  @owner  "
            "\x1b[1mAlpha\x1b[0m  7 downloads\n"
        )

        results = MODULE.parse_search_output(output)

        self.assertEqual(results[0]["slug"], "alpha")
        self.assertEqual(results[0]["metric"]["value"], 7)

    def test_parse_search_output_accepts_no_results(self):
        self.assertEqual(MODULE.parse_search_output("No skills found.\n"), [])

    def test_parse_search_output_rejects_unknown_format(self):
        with self.assertRaisesRegex(ValueError, "无法解析搜索结果行"):
            MODULE.parse_search_output("unexpected output")

    def test_collect_query_records_target_rank(self):
        observed_environment = {}

        def fake_runner(*args, **kwargs):
            observed_environment.update(kwargs["env"])
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout=(
                    "other v1.0.0  @owner  Other  score 0.900\n"
                    "alpha v1.2.0  @owner  Alpha  2 installs / 60d\n"
                ),
                stderr="",
            )

        with mock.patch.dict(
            MODULE.os.environ,
            {
                "OPENCLAW_MONITOR_CAPABILITY_FILE": "/private/context.json",
                "OPENCLAW_MONITOR_CAPABILITY_TOKEN": "secret-token",
            },
        ), mock.patch.object(MODULE, "require_collector_session"):
            result = MODULE.collect_query(
                "clawhub",
                {"slug": "alpha", "query": "alpha query", "limit": 20},
                timeout=10,
                runner=fake_runner,
            )

        self.assertEqual(result["rank"], 2)
        self.assertTrue(result["visible"])
        self.assertEqual(result["resultCount"], 2)
        self.assertEqual(observed_environment["NO_COLOR"], "1")
        self.assertEqual(observed_environment["FORCE_COLOR"], "0")
        self.assertNotIn(
            "OPENCLAW_MONITOR_CAPABILITY_FILE",
            observed_environment,
        )
        self.assertNotIn(
            "OPENCLAW_MONITOR_CAPABILITY_TOKEN",
            observed_environment,
        )

    def test_collect_query_surfaces_cli_failure(self):
        def fake_runner(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=1,
                stdout="",
                stderr="registry unavailable",
            )

        with mock.patch.object(MODULE, "require_collector_session"):
            with self.assertRaisesRegex(RuntimeError, "registry unavailable"):
                MODULE.collect_query(
                    "clawhub",
                    {"slug": "alpha", "query": "alpha", "limit": 20},
                    timeout=10,
                    runner=fake_runner,
                )

    def test_imported_run_cli_requires_validated_session_before_runner(self):
        called = False

        def fake_runner(*args, **kwargs):
            nonlocal called
            called = True
            raise AssertionError("runner must not be called")

        with self.assertRaisesRegex(PermissionError, "已验证的采集会话"):
            MODULE.run_cli(
                ["clawhub", "search", "alpha"],
                timeout=10,
                runner=fake_runner,
            )

        self.assertFalse(called)

    def test_build_snapshot_records_cli_version_and_no_install(self):
        with tempfile.TemporaryDirectory() as directory:
            query_path = Path(directory) / "queries.json"
            catalog_path = Path(directory) / "catalog.json"
            query_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "queries": [
                            {"slug": "alpha", "query": "alpha", "limit": 5}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            catalog_path.write_text(
                json.dumps({"skills/alpha": {}}),
                encoding="utf-8",
            )
            commands = []

            def fake_runner(*args, **kwargs):
                command = args[0]
                commands.append(command)
                if command[1:] == ["--cli-version"]:
                    stdout = "0.23.3\n"
                else:
                    stdout = "alpha v1.0.0  @owner  Alpha  score 0.900\n"
                return subprocess.CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout=stdout,
                    stderr="",
                )

            with mock.patch.object(MODULE, "require_collector_session"):
                result = MODULE.build_snapshot(
                    query_path,
                    catalog_path,
                    "clawhub",
                    timeout=10,
                    runner=fake_runner,
                )

            self.assertEqual(result["cliVersion"], "0.23.3")
            self.assertFalse(result["activeInstall"])
            self.assertEqual(result["queries"][0]["rank"], 1)
            self.assertEqual(
                commands,
                [
                    ["clawhub", "--cli-version"],
                    ["clawhub", "search", "alpha", "--limit", "5"],
                ],
            )

    def test_main_rejects_direct_invocation_before_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "latest.json"
            args = SimpleNamespace(
                queries=root / "queries.json",
                catalog=root / "catalog.json",
                output=output,
                previous_output=root / "previous.json",
                clawhub_bin="clawhub",
                timeout=10,
            )
            with (
                mock.patch.object(MODULE, "parse_args", return_value=args),
                mock.patch.object(MODULE, "build_snapshot") as build_snapshot,
                mock.patch.dict(MODULE.os.environ, {}, clear=True),
            ):
                result = MODULE.main()

            self.assertEqual(result, 1)
            build_snapshot.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
