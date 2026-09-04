import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "collect_clawhub_metrics.py"
SPEC = importlib.util.spec_from_file_location("collect_clawhub_metrics", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CollectClawHubMetricsTests(unittest.TestCase):
    def test_load_slugs_is_sorted_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "skills/zeta": {},
                        "skills/alpha": {},
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(MODULE.load_slugs(catalog), ["alpha", "zeta"])

    def test_load_slugs_rejects_non_skill_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.json"
            catalog.write_text(
                json.dumps({"plugins/example": {}}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "unexpected catalog key"):
                MODULE.load_slugs(catalog)

    def test_inspect_skill_normalizes_registry_payload(self):
        payload = {
            "skill": {
                "slug": "example-skill",
                "displayName": "Example Skill",
                "summary": "Example summary",
                "topics": ["publishing"],
                "stats": {
                    "downloads": 12,
                    "installs": 1,
                    "stars": 2,
                    "versions": 3,
                },
                "updatedAt": 123456,
            },
            "latestVersion": {"version": "1.2.0"},
            "moderation": {"verdict": "clean"},
        }

        def fake_runner(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )

        result = MODULE.inspect_skill(
            "clawhub",
            "example-skill",
            10,
            runner=fake_runner,
        )

        self.assertEqual(result["slug"], "example-skill")
        self.assertEqual(result["latestVersion"], "1.2.0")
        self.assertEqual(result["moderation"], "clean")
        self.assertEqual(result["stats"]["downloads"], 12)

    def test_inspect_skill_surfaces_cli_failure(self):
        def fake_runner(*args, **kwargs):
            return subprocess.CompletedProcess(
                args=args[0],
                returncode=1,
                stdout="",
                stderr="registry unavailable",
            )

        with self.assertRaisesRegex(RuntimeError, "registry unavailable"):
            MODULE.inspect_skill(
                "clawhub",
                "example-skill",
                10,
                runner=fake_runner,
            )

    def test_write_json_atomic_replaces_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "metrics" / "latest.json"
            MODULE.write_json_atomic(output, {"schemaVersion": 1})

            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                {"schemaVersion": 1},
            )
            self.assertEqual(list(output.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
