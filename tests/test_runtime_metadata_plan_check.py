import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "published-skills-runtime-metadata-vnext"
PLAN = RESEARCH / "change-plan.json"
CHECKER = RESEARCH / "check_runtime_plan.py"
POLICY = ROOT / "metrics" / "observation-policy.json"

SPEC = importlib.util.spec_from_file_location(
    "runtime_metadata_plan_check",
    CHECKER,
)
CHECK_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK_MODULE)

BEFORE_WINDOW = datetime(2026, 9, 5, tzinfo=timezone.utc)
AFTER_WINDOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


def write_json(directory, name, value):
    path = Path(directory) / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


class RuntimeMetadataPlanCheckTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads(PLAN.read_text(encoding="utf-8"))
        self.policy = json.loads(POLICY.read_text(encoding="utf-8"))

    def evaluate_plan(self, plan, now=BEFORE_WINDOW, policy=None):
        with tempfile.TemporaryDirectory() as directory:
            plan_path = write_json(directory, "plan.json", plan)
            policy_path = write_json(
                directory,
                "policy.json",
                self.policy if policy is None else policy,
            )
            return CHECK_MODULE.evaluate(ROOT, plan_path, policy_path, now)

    def test_current_plan_is_valid_but_review_is_time_gated(self):
        result = CHECK_MODULE.evaluate(ROOT, PLAN, POLICY, BEFORE_WINDOW)

        self.assertTrue(result["valid"])
        self.assertFalse(result["readyForFreshReview"])
        self.assertFalse(result["readyToApply"])
        self.assertEqual(result["targetCount"], 7)
        self.assertEqual(
            result["blockingReasons"],
            ["observation-window", "fresh-need-review"],
        )
        self.assertEqual(result["errors"], [])
        self.assertTrue(
            result["localEvidence"]["currentFormalMetadataMatchesPlanBaseline"]
        )
        self.assertTrue(result["localEvidence"]["targetSetMatchesCatalog"])

    def test_elapsed_window_allows_review_but_never_auto_applies(self):
        result = CHECK_MODULE.evaluate(ROOT, PLAN, POLICY, AFTER_WINDOW)

        self.assertTrue(result["valid"])
        self.assertTrue(result["readyForFreshReview"])
        self.assertFalse(result["readyToApply"])
        self.assertEqual(result["blockingReasons"], ["fresh-need-review"])
        self.assertTrue(result["localEvidence"]["observationWindowElapsed"])

    def test_formal_version_drift_invalidates_plan(self):
        plan = copy.deepcopy(self.plan)
        plan["targets"][0]["currentVersion"] = "9.9.9"

        result = self.evaluate_plan(plan)

        self.assertFalse(result["valid"])
        self.assertFalse(result["readyForFreshReview"])
        self.assertIn(
            "skill-summary-rewriter: currentVersion does not match formal SKILL.md",
            result["errors"],
        )

    def test_target_set_must_be_complete_unique_and_well_formed(self):
        mutations = []

        missing = copy.deepcopy(self.plan)
        missing["targets"].pop()
        mutations.append((missing, "runtime target set must equal"))

        duplicate = copy.deepcopy(self.plan)
        duplicate["targets"].append(copy.deepcopy(duplicate["targets"][0]))
        mutations.append((duplicate, "runtime target slugs must be unique"))

        malformed = copy.deepcopy(self.plan)
        malformed["targets"][0] = []
        mutations.append(
            (
                malformed,
                "every runtime target must be an object with a string slug",
            )
        )

        illegal_slug = copy.deepcopy(self.plan)
        illegal_slug["targets"][0]["slug"] = "../skill-summary-rewriter"
        mutations.append((illegal_slug, "target slug must use lowercase kebab-case"))

        for plan, expected in mutations:
            with self.subTest(expected=expected):
                result = self.evaluate_plan(plan)
                self.assertFalse(result["valid"])
                self.assertTrue(
                    any(expected in error for error in result["errors"]),
                    result["errors"],
                )

    def test_malformed_list_and_replace_values_are_structured_invalid(self):
        mutations = []

        remove_dict = copy.deepcopy(self.plan)
        remove_dict["targets"][0]["remove"] = [{"bad": True}]
        mutations.append((remove_dict, "text-only remove contract is invalid"))

        retain_list = copy.deepcopy(self.plan)
        retain_list["targets"][0]["retain"] = [["metadata.openclaw.emoji"]]
        mutations.append((retain_list, "text-only retain contract is invalid"))

        duplicate_retain = copy.deepcopy(self.plan)
        duplicate_retain["targets"][0]["retain"] = [
            "metadata.openclaw.emoji",
            "metadata.openclaw.homepage",
            "metadata.openclaw.homepage",
        ]
        mutations.append((duplicate_retain, "text-only retain contract is invalid"))

        replace_list = copy.deepcopy(self.plan)
        replace_list["targets"][2]["replace"] = []
        mutations.append((replace_list, "CLI operating-system change is invalid"))

        os_change_list = copy.deepcopy(self.plan)
        os_change_list["targets"][2]["replace"]["metadata.openclaw.os"] = []
        mutations.append((os_change_list, "CLI operating-system change is invalid"))

        for plan, expected in mutations:
            with self.subTest(expected=expected):
                result = self.evaluate_plan(plan)
                self.assertFalse(result["valid"])
                self.assertIn(expected, "\n".join(result["errors"]))

    def test_evidence_path_cannot_escape_repository(self):
        plan = copy.deepcopy(self.plan)
        plan["evidence"]["linuxWorkflow"] = "../outside.yml"

        result = self.evaluate_plan(plan)

        self.assertFalse(result["valid"])
        self.assertIn(
            "Linux workflow evidence path escapes repository root",
            result["errors"],
        )

    def test_evidence_claims_and_release_policy_cannot_be_relaxed(self):
        mutations = []

        evidence = copy.deepcopy(self.plan)
        evidence["evidence"]["linuxWorkflowRunner"] = "macos-latest"
        mutations.append((evidence, "Linux workflow runner evidence"))

        matches = copy.deepcopy(self.plan)
        matches["evidence"]["macSpecificCommandMatches"] = ["brew"]
        mutations.append((matches, "macSpecificCommandMatches"))

        claims = copy.deepcopy(self.plan)
        claims["claims"]["downloadImpactConfirmed"] = True
        mutations.append((claims, "claims do not preserve evidence boundaries"))

        release_policy = copy.deepcopy(self.plan)
        release_policy["releasePolicy"][
            "maxPlannedE4InstallsPerChangedVersion"
        ] = 2
        mutations.append((release_policy, "releasePolicy is invalid"))

        for plan, expected in mutations:
            with self.subTest(expected=expected):
                result = self.evaluate_plan(plan)
                self.assertFalse(result["valid"])
                self.assertIn(expected, "\n".join(result["errors"]))

    def test_observation_policy_time_and_schema_are_locked(self):
        drifted_policy = copy.deepcopy(self.policy)
        drifted_policy["notBefore"] = "2026-09-11T10:45:38+00:00"
        result = self.evaluate_plan(self.plan, policy=drifted_policy)
        self.assertFalse(result["valid"])
        self.assertIn(
            "runtime plan observation time must match observation policy",
            result["errors"],
        )

        bad_schema = copy.deepcopy(self.policy)
        bad_schema["schemaVersion"] = 2
        result = self.evaluate_plan(self.plan, policy=bad_schema)
        self.assertFalse(result["valid"])
        self.assertIn(
            "observation policy schemaVersion must equal 1",
            result["errors"],
        )

    def test_invalid_json_is_structured_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            plan_path = Path(directory) / "plan.json"
            plan_path.write_text("{", encoding="utf-8")
            result = CHECK_MODULE.evaluate(
                ROOT,
                plan_path,
                POLICY,
                BEFORE_WINDOW,
            )

        self.assertFalse(result["valid"])
        self.assertFalse(result["readyForFreshReview"])
        self.assertFalse(result["readyToApply"])
        self.assertIn("cannot be read as JSON", result["errors"][0])

    def test_cli_exit_codes_distinguish_valid_hold_review_and_invalid(self):
        cases = (
            (BEFORE_WINDOW.isoformat(), False, 0, False),
            (BEFORE_WINDOW.isoformat(), True, 1, False),
            (AFTER_WINDOW.isoformat(), True, 0, True),
        )

        for now, require_review, expected_code, expected_review in cases:
            with self.subTest(now=now, require_review=require_review):
                command = [
                    sys.executable,
                    str(CHECKER),
                    "--repo-root",
                    str(ROOT),
                    "--now",
                    now,
                ]
                if require_review:
                    command.append("--require-review-window")
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                result = json.loads(completed.stdout)
                self.assertEqual(completed.returncode, expected_code)
                self.assertTrue(result["valid"])
                self.assertEqual(
                    result["readyForFreshReview"],
                    expected_review,
                )
                self.assertFalse(result["readyToApply"])
                self.assertEqual(completed.stderr, "")

        with tempfile.TemporaryDirectory() as directory:
            invalid_plan = Path(directory) / "plan.json"
            invalid_plan.write_text("[]", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--repo-root",
                    str(ROOT),
                    "--plan",
                    str(invalid_plan),
                    "--now",
                    BEFORE_WINDOW.isoformat(),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        result = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(result["valid"])
        self.assertNotIn("Traceback", completed.stderr)

    def test_invalid_now_is_an_argument_error_without_traceback(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(CHECKER),
                "--repo-root",
                str(ROOT),
                "--now",
                "not-a-time",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stdout, "")
        self.assertIn("invalid --now value", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_checker_has_no_network_or_process_execution_imports(self):
        source = CHECKER.read_text(encoding="utf-8")

        for forbidden in (
            "import requests",
            "import urllib.request",
            "import subprocess",
            "from subprocess",
            "socket.",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
