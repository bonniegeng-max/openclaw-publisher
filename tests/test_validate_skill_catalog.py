import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "validate_skill_catalog.py"
CATALOG = ROOT / ".clawhub" / "skill-catalog.json"
METRICS_WORKFLOW = ROOT / ".github" / "workflows" / "metrics-tools-ci.yml"

SPEC = importlib.util.spec_from_file_location(
    "validate_skill_catalog",
    SCRIPT,
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def stage_repo(directory):
    root = Path(directory)
    shutil.copytree(ROOT / "skills", root / "skills")
    (root / ".clawhub").mkdir()
    shutil.copy2(CATALOG, root / ".clawhub" / "skill-catalog.json")
    return root, root / ".clawhub" / "skill-catalog.json"


def replace_frontmatter_field(path, field, value):
    lines = path.read_text(encoding="utf-8").splitlines()
    prefix = f"{field}:"
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{field}: {value}"
            break
    else:
        raise AssertionError(f"frontmatter field missing: {field}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class ValidateSkillCatalogTests(unittest.TestCase):
    def test_current_catalog_is_valid(self):
        result = MODULE.validate(ROOT, CATALOG)

        self.assertTrue(result["valid"])
        self.assertEqual(result["entryCount"], 7)
        self.assertEqual(result["errors"], [])

    def test_cli_returns_structured_success(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--repo-root",
                str(ROOT),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        self.assertTrue(result["valid"])
        self.assertEqual(result["entryCount"], 7)
        self.assertEqual(completed.stderr, "")

    def test_malformed_metadata_tokens_are_invalid_without_traceback(self):
        original = json.loads(CATALOG.read_text(encoding="utf-8"))
        first_key = sorted(original)[0]
        mutations = (
            ("categories", "development"),
            ("topics", {"bad": True}),
            ("categories", [{"bad": True}]),
            ("topics", []),
            ("categories", ["development", "development"]),
            ("topics", ["invalid token"]),
            ("categories", ["development", ""]),
        )

        for field, value in mutations:
            with self.subTest(field=field, value=value):
                with tempfile.TemporaryDirectory() as directory:
                    root, catalog_path = stage_repo(directory)
                    catalog = copy.deepcopy(original)
                    catalog[first_key][field] = value
                    catalog_path.write_text(
                        json.dumps(catalog),
                        encoding="utf-8",
                    )
                    result = MODULE.validate(root, catalog_path)

                self.assertFalse(result["valid"])
                self.assertTrue(
                    any(
                        error["code"] == "METADATA_TOKENS_INVALID"
                        and error["path"] == f"{first_key}.{field}"
                        for error in result["errors"]
                    )
                )

    def test_catalog_identity_and_fields_must_match_skill(self):
        original = json.loads(CATALOG.read_text(encoding="utf-8"))
        first_key = sorted(original)[0]

        with tempfile.TemporaryDirectory() as directory:
            root, catalog_path = stage_repo(directory)
            catalog = copy.deepcopy(original)
            catalog[first_key]["displayName"] = "Wrong Display Name"
            catalog[first_key]["unexpected"] = True
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            result = MODULE.validate(root, catalog_path)

        codes = {error["code"] for error in result["errors"]}
        self.assertFalse(result["valid"])
        self.assertIn("CATALOG_FIELDS_INVALID", codes)
        self.assertIn("SKILL_NAME_MISMATCH", codes)

    def test_required_files_and_catalog_coverage_are_enforced(self):
        original = json.loads(CATALOG.read_text(encoding="utf-8"))
        first_key = sorted(original)[0]
        second_key = sorted(original)[1]

        with tempfile.TemporaryDirectory() as directory:
            root, catalog_path = stage_repo(directory)
            (root / first_key / "CHANGELOG.md").unlink()
            catalog = copy.deepcopy(original)
            del catalog[second_key]
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            result = MODULE.validate(root, catalog_path)

        codes = {error["code"] for error in result["errors"]}
        self.assertFalse(result["valid"])
        self.assertIn("REQUIRED_FILE_MISSING", codes)
        self.assertIn("CATALOG_ENTRY_MISSING", codes)

    def test_frontmatter_version_requires_three_part_semver(self):
        original = json.loads(CATALOG.read_text(encoding="utf-8"))
        first_key = sorted(original)[0]

        for version in ("1.0", "01.0.0", "v1.0.0", "1.0.0-beta"):
            with self.subTest(version=version):
                with tempfile.TemporaryDirectory() as directory:
                    root, catalog_path = stage_repo(directory)
                    replace_frontmatter_field(
                        root / first_key / "SKILL.md",
                        "version",
                        version,
                    )
                    result = MODULE.validate(root, catalog_path)

                self.assertFalse(result["valid"])
                self.assertTrue(
                    any(
                        error["code"] == "SKILL_VERSION_INVALID"
                        for error in result["errors"]
                    )
                )

    def test_changelog_must_include_frontmatter_version(self):
        original = json.loads(CATALOG.read_text(encoding="utf-8"))
        first_key = sorted(original)[0]

        with tempfile.TemporaryDirectory() as directory:
            root, catalog_path = stage_repo(directory)
            replace_frontmatter_field(
                root / first_key / "SKILL.md",
                "version",
                "9.9.9",
            )
            result = MODULE.validate(root, catalog_path)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any(
                error["code"] == "CHANGELOG_VERSION_MISSING"
                for error in result["errors"]
            )
        )

    def test_description_must_be_nonempty(self):
        original = json.loads(CATALOG.read_text(encoding="utf-8"))
        first_key = sorted(original)[0]

        with tempfile.TemporaryDirectory() as directory:
            root, catalog_path = stage_repo(directory)
            replace_frontmatter_field(
                root / first_key / "SKILL.md",
                "description",
                "",
            )
            result = MODULE.validate(root, catalog_path)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any(
                error["code"] == "SKILL_DESCRIPTION_INVALID"
                for error in result["errors"]
            )
        )

    def test_display_names_must_be_unique(self):
        original = json.loads(CATALOG.read_text(encoding="utf-8"))
        first_key, second_key = sorted(original)[:2]
        duplicate_name = original[first_key]["displayName"]

        with tempfile.TemporaryDirectory() as directory:
            root, catalog_path = stage_repo(directory)
            catalog = copy.deepcopy(original)
            catalog[second_key]["displayName"] = duplicate_name
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            replace_frontmatter_field(
                root / second_key / "SKILL.md",
                "name",
                duplicate_name,
            )
            result = MODULE.validate(root, catalog_path)

        self.assertFalse(result["valid"])
        self.assertTrue(
            any(
                error["code"] == "DISPLAY_NAME_DUPLICATE"
                for error in result["errors"]
            )
        )

    def test_invalid_slug_and_protected_namespace_are_rejected(self):
        cases = (
            ("skills/Invalid_Slug", "SLUG_FORMAT_INVALID"),
            ("skills/clawhub-example", "SLUG_NAMESPACE_PROTECTED"),
            ("skills/example-clawhub", "SLUG_NAMESPACE_PROTECTED"),
            ("nested/example", "CATALOG_KEY_INVALID"),
        )

        for catalog_key, expected_code in cases:
            with self.subTest(catalog_key=catalog_key):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    skill_dir = root / catalog_key
                    skill_dir.mkdir(parents=True)
                    slug = skill_dir.name
                    (skill_dir / "SKILL.md").write_text(
                        (
                            "---\n"
                            "name: Example\n"
                            f"slug: {slug}\n"
                            "version: 1.0.0\n"
                            "---\n"
                        ),
                        encoding="utf-8",
                    )
                    (skill_dir / "CHANGELOG.md").write_text(
                        "# Changelog\n",
                        encoding="utf-8",
                    )
                    (skill_dir / ".clawhubignore").write_text(
                        ".git\n",
                        encoding="utf-8",
                    )
                    catalog_path = root / "catalog.json"
                    catalog_path.write_text(
                        json.dumps(
                            {
                                catalog_key: {
                                    "displayName": "Example",
                                    "categories": ["development"],
                                    "topics": ["example"],
                                }
                            }
                        ),
                        encoding="utf-8",
                    )
                    result = MODULE.validate(root, catalog_path)

                self.assertFalse(result["valid"])
                self.assertTrue(
                    any(
                        error["code"] == expected_code
                        for error in result["errors"]
                    )
                )

    def test_nonstandard_or_non_object_json_returns_input_error(self):
        values = (
            "[1, 2, 3]",
            '{"entry": NaN}',
            "{not-json}",
        )

        for raw in values:
            with self.subTest(raw=raw):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    catalog_path = root / "catalog.json"
                    catalog_path.write_text(raw, encoding="utf-8")
                    result = MODULE.validate(root, catalog_path)

                self.assertFalse(result["valid"])
                self.assertEqual(result["entryCount"], 0)
                self.assertEqual(
                    result["errors"][0]["code"],
                    "CATALOG_INPUT_INVALID",
                )

    def test_invalid_cli_returns_two_without_stderr_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "catalog.json"
            catalog_path.write_text('{"entry": NaN}', encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo-root",
                    str(root),
                    "--catalog",
                    str(catalog_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        result = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(result["valid"])
        self.assertEqual(completed.stderr, "")

    def test_validator_has_no_network_or_process_imports(self):
        source = SCRIPT.read_text(encoding="utf-8")

        for forbidden in (
            "import requests",
            "import urllib.request",
            "import subprocess",
            "from subprocess",
            "socket.",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_metrics_ci_runs_preflight_for_skill_and_catalog_changes(self):
        workflow = METRICS_WORKFLOW.read_text(encoding="utf-8")

        self.assertEqual(workflow.count('"skills/**"'), 2)
        self.assertEqual(
            workflow.count('".clawhub/skill-catalog.json"'),
            2,
        )
        self.assertIn(
            "run: python scripts/validate_skill_catalog.py",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
