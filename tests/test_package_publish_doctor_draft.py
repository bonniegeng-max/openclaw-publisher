import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
DRAFT = ROOT / "research" / "package-publish-doctor" / "draft"
SKILL = DRAFT / "SKILL.md"
CANONICAL = DRAFT / "scripts" / "diagnose.py"
WRAPPER = DRAFT.parent / "diagnose.py"
ANONYMOUS_INPUT = DRAFT / "examples" / "anonymous-input.json"


def frontmatter(text):
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise AssertionError("SKILL.md frontmatter missing")
    values = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


class PackagePublishDoctorDraftTests(unittest.TestCase):
    def test_draft_has_complete_skill_package_structure(self):
        required = {
            "SKILL.md",
            "CHANGELOG.md",
            ".clawhubignore",
            "references/failure-map.md",
            "references/input-contract.md",
            "scripts/diagnose.py",
            "templates/package_diagnosis_report.md",
            "examples/anonymous-input.json",
            "examples/three_layer_diagnosis.md",
            "examples/package_release_scan_stalled.md",
            "examples/source_and_verification_failures.md",
        }
        present = {
            path.relative_to(DRAFT).as_posix()
            for path in DRAFT.rglob("*")
            if path.is_file()
        }
        self.assertTrue(required.issubset(present), required - present)

    def test_frontmatter_uses_safe_draft_identity(self):
        values = frontmatter(SKILL.read_text(encoding="utf-8"))

        self.assertEqual(values["name"], "ClawHub Package Publish Doctor")
        self.assertEqual(values["slug"], "package-publish-doctor")
        self.assertEqual(values["version"], "0.1.9")
        self.assertLessEqual(len(values["description"]), 200)
        self.assertFalse(values["slug"].startswith("clawhub-"))
        self.assertFalse(values["slug"].endswith("-clawhub"))

    def test_draft_is_not_publishable_from_current_catalog(self):
        catalog = json.loads(
            (ROOT / ".clawhub" / "skill-catalog.json").read_text(
                encoding="utf-8"
            )
        )
        serialized = json.dumps(catalog)

        self.assertNotIn("package-publish-doctor", serialized)
        self.assertFalse((ROOT / "skills" / "package-publish-doctor").exists())

    def test_research_changes_are_covered_by_ci(self):
        workflow = (
            ROOT / ".github" / "workflows" / "metrics-tools-ci.yml"
        ).read_text(encoding="utf-8")

        self.assertGreaterEqual(
            workflow.count('"research/package-publish-doctor/**"'),
            2,
        )
        self.assertIn(
            "research/package-publish-doctor/draft/scripts/*.py",
            workflow,
        )

    def test_skill_declares_core_safety_boundaries(self):
        text = SKILL.read_text(encoding="utf-8")
        required_phrases = [
            "Do not publish, install, download, or mutate registry state",
            "Do not bypass Plugin Inspector",
            "Do not widen permissions",
            "Do not expose secrets",
            "Do not recommend an unreleased `main` commit",
            "return `UNKNOWN`",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_bundled_resource_links_resolve(self):
        text = SKILL.read_text(encoding="utf-8")
        references = re.findall(
            r"`((?:references|templates|examples|scripts)/[^`]+)`",
            text,
        )

        self.assertTrue(references)
        for relative in references:
            with self.subTest(relative=relative):
                self.assertTrue((DRAFT / relative).is_file())

    def test_canonical_cli_runs_standalone_with_anonymous_input(self):
        with tempfile.TemporaryDirectory() as directory:
            isolated = Path(directory) / "package-publish-doctor"
            shutil.copytree(DRAFT, isolated)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(isolated / "scripts" / "diagnose.py"),
                    str(isolated / "examples" / "anonymous-input.json"),
                ],
                cwd=isolated,
                check=True,
                capture_output=True,
                text=True,
            )
            result = json.loads(completed.stdout)

        self.assertTrue(result["matched"])
        self.assertEqual(
            result["diagnosis"],
            "REUSABLE_WORKFLOW_ACTIONS_PERMISSION",
        )
        self.assertEqual(result["conclusion"], "blocked")
        self.assertEqual(
            result["observedContext"],
            {
                "workflowRef": "package-publish.yml@v0.23.3"
            },
        )
        self.assertTrue(result["rejectedShortcuts"])
        self.assertTrue(result["verificationSteps"])
        self.assertTrue(result["doNotClaim"])
        self.assertEqual(result["caseId"], "anonymous-workflow-startup-failure")

    def test_wrapper_and_canonical_cli_outputs_are_identical(self):
        outputs = []
        for script in (CANONICAL, WRAPPER):
            completed = subprocess.run(
                [sys.executable, str(script), str(ANONYMOUS_INPUT)],
                check=True,
                capture_output=True,
                text=True,
            )
            outputs.append(json.loads(completed.stdout))

        self.assertEqual(outputs[0], outputs[1])

    def test_cli_reports_input_contract_errors_without_tracebacks(self):
        cases = [
            (b"{", "invalid JSON at line 1, column 2"),
            (b"[]", "top-level JSON value must be an object"),
            (b"{}", "required field 'input' is missing"),
            (b'{"input":[]}', "field 'input' must be an object"),
            (b"\xff", "input file must be valid UTF-8"),
            (
                b'{"input":{"surface":"package","pendingHours":NaN}}',
                "invalid JSON constant: NaN",
            ),
            (
                b'{"input":{"surface":"package","pendingHours":Infinity}}',
                "invalid JSON constant: Infinity",
            ),
            (
                b'{"input":{"surface":"package","pendingHours":-Infinity}}',
                "invalid JSON constant: -Infinity",
            ),
        ]
        for payload, expected_message in cases:
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "case.json"
                    path.write_bytes(payload)
                    completed = subprocess.run(
                        [sys.executable, str(CANONICAL), str(path)],
                        capture_output=True,
                        text=True,
                    )

                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stdout, "")
                error = json.loads(completed.stderr)
                self.assertEqual(set(error), {"error", "message"})
                self.assertEqual(error["error"], "INPUT_CONTRACT_ERROR")
                self.assertIn(expected_message, error["message"])
                self.assertNotIn("Traceback", completed.stderr)

    def test_cli_reports_unreadable_path_without_echoing_the_path(self):
        missing = ROOT / "private-account-secret-input.json"
        completed = subprocess.run(
            [sys.executable, str(CANONICAL), str(missing)],
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        error = json.loads(completed.stderr)
        self.assertEqual(error["error"], "INPUT_CONTRACT_ERROR")
        self.assertIn("unable to read input file", error["message"])
        self.assertNotIn(str(missing), completed.stderr)
        self.assertNotIn("private-account-secret", completed.stderr)

    def test_valid_unknown_is_not_an_input_contract_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unknown.json"
            path.write_text(
                json.dumps({"input": {"surface": "package"}}),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(CANONICAL), str(path)],
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(json.loads(completed.stdout)["diagnosis"], "UNKNOWN")

    def test_malformed_rule_evidence_is_unknown_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "malformed-evidence.json"
            path.write_text(
                json.dumps(
                    {
                        "input": {
                            "surface": "package",
                            "files": [{}],
                            "effectiveCallerPermissions": [],
                            "trust": [],
                        }
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(CANONICAL), str(path)],
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stderr, "")
        self.assertNotIn("Traceback", completed.stdout)
        self.assertEqual(json.loads(completed.stdout)["diagnosis"], "UNKNOWN")

    def test_isolated_surrogate_is_safely_omitted_from_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "surrogate.json"
            path.write_text(
                '{"id":"\\ud800","source":"\\udfff",'
                '"input":{"surface":"package"}}',
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(CANONICAL), str(path)],
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stderr, "")
        self.assertNotIn("Traceback", completed.stdout)
        result = json.loads(completed.stdout)
        self.assertIsNone(result["caseId"])
        self.assertIsNone(result["source"])
        self.assertEqual(result["diagnosis"], "UNKNOWN")

    def test_wrapper_and_canonical_cli_errors_are_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text("[]", encoding="utf-8")
            results = [
                subprocess.run(
                    [sys.executable, str(script), str(path)],
                    capture_output=True,
                    text=True,
                )
                for script in (CANONICAL, WRAPPER)
            ]

        self.assertEqual(
            [(result.returncode, result.stdout, result.stderr) for result in results],
            [(2, "", results[0].stderr), (2, "", results[0].stderr)],
        )

    def test_root_script_is_compatibility_forwarder_without_rules(self):
        text = WRAPPER.read_text(encoding="utf-8")

        self.assertIn('"draft" / "scripts" / "diagnose.py"', text)
        self.assertIn("InputContractError = _IMPL.InputContractError", text)
        self.assertNotIn("def diagnose(", text)
        self.assertNotIn("REUSABLE_WORKFLOW_ACTIONS_PERMISSION", text)


if __name__ == "__main__":
    unittest.main()
