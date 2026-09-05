import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "skill-release-authorization-vnext"
CHECKER = RESEARCH / "check_workflow_integration_contract.py"
CONTRACT = RESEARCH / "workflow-integration-contract.json"
SPEC = importlib.util.spec_from_file_location(
    "workflow_integration_contract",
    CHECKER,
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def load_contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def write_contract(directory, value):
    path = Path(directory) / "contract.json"
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def make_contract_repo(directory):
    root = Path(directory)
    for relative in (
        ".github/workflows/clawhub-skill-publish.yml",
        "scripts/check_skill_release_authorization.py",
        "scripts/validate_skill_catalog.py",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/bonniegeng-max/openclaw-publisher.git",
        ],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "trusted baseline"],
        cwd=root,
        check=True,
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
    ).strip()
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", head],
        cwd=root,
        check=True,
    )
    contract = load_contract()
    contract["formalWorkflows"]["callerSha256"] = MODULE.digest_bytes(
        (root / contract["formalWorkflows"]["caller"]).read_bytes()
    )
    return root, contract, head


def bind_control_files(root, contract, commit):
    contract["trustedControl"]["commit"] = commit
    for item in contract["trustedControl"]["files"]:
        content = subprocess.check_output(
            ["git", "show", f"{commit}:{item['path']}"],
            cwd=root,
        )
        item["sha256"] = MODULE.digest_bytes(content)


class WorkflowIntegrationContractTests(unittest.TestCase):
    def test_repository_contract_is_honest_and_blocked(self):
        result = MODULE.evaluate(ROOT, CONTRACT)

        self.assertTrue(result["valid"], result["errors"])
        self.assertFalse(result["deploymentReady"])
        self.assertEqual(
            result["contractStatus"],
            "offline-contract-ready-not-wired",
        )
        self.assertEqual(result["localEvidence"]["currentEvidenceLevel"], "E0")
        self.assertFalse(result["localEvidence"]["formalWorkflowWired"])
        self.assertFalse(
            result["localEvidence"]["environmentConfigurationVerified"]
        )
        self.assertTrue(
            result["localEvidence"]["trustedControlAnchorVerified"]
        )
        for gate in (
            "trusted-control-execution",
            "trusted-reusable-workflow",
            "trusted-clawhub-cli",
            "formal-workflow-wiring",
            "validation-environment",
            "production-environment",
            "controlled-run",
        ):
            with self.subTest(gate=gate):
                self.assertIn(gate, result["blockingGates"])

    def test_contract_uses_verified_control_commit_and_no_future_fake_sha(self):
        contract = load_contract()

        self.assertEqual(
            contract["targetRepository"],
            "bonniegeng-max/openclaw-publisher",
        )
        self.assertEqual(
            contract["trustedControl"]["repository"],
            contract["targetRepository"],
        )
        self.assertRegex(
            contract["trustedControl"]["commit"],
            r"^[0-9a-f]{40}$",
        )
        self.assertTrue(
            all(
                isinstance(item["sha256"], str)
                and item["sha256"].startswith("sha256:")
                for item in contract["trustedControl"]["files"]
            )
        )
        self.assertIsNone(
            contract["trustedReusableWorkflow"]["commit"]
        )
        self.assertFalse(
            contract["trustedReusableWorkflow"]["verified"]
        )
        self.assertIsNone(contract["trustedClawHubCli"]["commit"])
        self.assertFalse(contract["trustedClawHubCli"]["verified"])

    def test_observation_hold_matches_formal_workflow_state(self):
        contract = load_contract()
        formal = contract["formalWorkflows"]
        caller = ROOT / formal["caller"]
        reusable = ROOT / formal["authorizedReusable"]

        self.assertTrue(caller.is_file())
        self.assertFalse(reusable.exists())
        caller_text = caller.read_text(encoding="utf-8")
        self.assertNotIn(
            "check_skill_release_authorization.py",
            caller_text,
        )
        self.assertNotIn(
            "clawhub-skill-publish-authorized.yml",
            caller_text,
        )

    def test_unverified_external_controls_cannot_be_claimed(self):
        mutations = []

        workflow = load_contract()
        workflow["formalWorkflows"]["wired"] = True
        mutations.append(("formal workflow", workflow))

        reusable = load_contract()
        reusable["trustedReusableWorkflow"]["verified"] = True
        mutations.append(("trusted reusable", reusable))

        cli = load_contract()
        cli["trustedClawHubCli"]["verified"] = True
        mutations.append(("trusted CLI", cli))

        environment = load_contract()
        environment["environments"]["production"][
            "configurationVerified"
        ] = True
        mutations.append(("production environment", environment))

        controlled = load_contract()
        controlled["controlledRun"]["verified"] = True
        mutations.append(("controlled run", controlled))

        control_execution = load_contract()
        control_execution["trustedControlExecution"]["verified"] = True
        mutations.append(("trusted control execution", control_execution))

        for label, value in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                result = MODULE.evaluate(
                    ROOT,
                    write_contract(directory, value),
                )
                self.assertFalse(result["valid"])
                self.assertFalse(result["deploymentReady"])
                self.assertTrue(result["errors"])

    def test_fake_trusted_control_commit_is_rejected(self):
        contract = load_contract()
        contract["trustedControl"]["commit"] = "f" * 40
        for item in contract["trustedControl"]["files"]:
            item["sha256"] = "sha256:" + "0" * 64

        with tempfile.TemporaryDirectory() as directory:
            result = MODULE.evaluate(
                ROOT,
                write_contract(directory, contract),
            )

        self.assertFalse(result["valid"])
        self.assertFalse(result["deploymentReady"])
        self.assertIn(
            "trusted control anchor must identify a Git commit",
            result["errors"],
        )

    def test_pinned_control_digest_must_match_git_object(self):
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
        contract = load_contract()
        contract["trustedControl"]["commit"] = head
        for item in contract["trustedControl"]["files"]:
            content = subprocess.check_output(
                ["git", "show", f"{head}:{item['path']}"],
                cwd=ROOT,
            )
            item["sha256"] = MODULE.digest_bytes(content)
        contract["trustedControl"]["files"][0]["sha256"] = (
            "sha256:" + "0" * 64
        )

        with tempfile.TemporaryDirectory() as directory:
            result = MODULE.evaluate(
                ROOT,
                write_contract(directory, contract),
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            "trusted control file digests do not match the pinned commit",
            result["errors"],
        )

    def test_tree_object_cannot_impersonate_trusted_commit(self):
        tree = subprocess.check_output(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=ROOT,
            text=True,
        ).strip()
        contract = load_contract()
        contract["trustedControl"]["commit"] = tree
        for item in contract["trustedControl"]["files"]:
            content = subprocess.check_output(
                ["git", "show", f"{tree}:{item['path']}"],
                cwd=ROOT,
            )
            item["sha256"] = MODULE.digest_bytes(content)

        with tempfile.TemporaryDirectory() as directory:
            result = MODULE.evaluate(
                ROOT,
                write_contract(directory, contract),
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            "trusted control anchor must identify a Git commit",
            result["errors"],
        )

    def test_unreachable_commit_cannot_be_trusted_control(self):
        with tempfile.TemporaryDirectory() as directory:
            root, contract, _ = make_contract_repo(directory)
            subprocess.run(
                ["git", "checkout", "-q", "--orphan", "untrusted"],
                cwd=root,
                check=True,
            )
            (root / "untrusted.txt").write_text(
                "not on origin/main\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "untrusted control"],
                cwd=root,
                check=True,
            )
            untrusted = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
            ).strip()
            bind_control_files(root, contract, untrusted)
            result = MODULE.evaluate(
                root,
                write_contract(directory, contract),
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            "trusted control commit must be reachable from origin/main",
            result["errors"],
        )

    def test_symlink_git_entry_cannot_be_trusted_control(self):
        with tempfile.TemporaryDirectory() as directory:
            root, contract, _ = make_contract_repo(directory)
            validator = root / "scripts" / "validate_skill_catalog.py"
            replacement = root / "scripts" / "replacement.py"
            replacement.write_text("# replacement\n", encoding="utf-8")
            validator.unlink()
            validator.symlink_to(replacement.name)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "symlinked validator"],
                cwd=root,
                check=True,
            )
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
            ).strip()
            subprocess.run(
                ["git", "update-ref", "refs/remotes/origin/main", head],
                cwd=root,
                check=True,
            )
            bind_control_files(root, contract, head)
            result = MODULE.evaluate(
                root,
                write_contract(directory, contract),
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            (
                "trusted control path must be a regular Git blob: "
                "scripts/validate_skill_catalog.py"
            ),
            result["errors"],
        )

    def test_malformed_nested_control_path_returns_structured_error(self):
        contract = load_contract()
        contract["trustedControl"]["files"][0]["path"] = []

        with tempfile.TemporaryDirectory() as directory:
            result = MODULE.evaluate(
                ROOT,
                write_contract(directory, contract),
            )

        self.assertFalse(result["valid"])
        self.assertFalse(result["deploymentReady"])
        self.assertTrue(result["errors"])

    def test_observation_hold_is_bound_to_full_caller_digest(self):
        contract = load_contract()
        contract["formalWorkflows"]["callerSha256"] = (
            "sha256:" + "0" * 64
        )

        with tempfile.TemporaryDirectory() as directory:
            result = MODULE.evaluate(
                ROOT,
                write_contract(directory, contract),
            )

        self.assertFalse(result["valid"])
        self.assertFalse(result["checks"]["observation-hold-intact"])

    def test_evidence_boundaries_cannot_be_downgraded(self):
        contract = load_contract()
        contract["evidencePolicy"]["downloadableClaimRequires"] = "E2"

        with tempfile.TemporaryDirectory() as directory:
            result = MODULE.evaluate(
                ROOT,
                write_contract(directory, contract),
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            "evidence policy must preserve E0-E4 claim boundaries",
            result["errors"],
        )

    def test_environment_requirements_are_fixed(self):
        contract = load_contract()
        contract["environments"]["production"]["requirements"][
            "preventSelfReview"
        ] = False

        with tempfile.TemporaryDirectory() as directory:
            result = MODULE.evaluate(
                ROOT,
                write_contract(directory, contract),
            )

        self.assertFalse(result["valid"])
        self.assertTrue(
            any(
                "clawhub-production must remain unverified" in error
                for error in result["errors"]
            )
        )

    def test_contract_rejects_duplicate_keys_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            duplicate = Path(directory) / "duplicate.json"
            duplicate.write_text(
                '{"schemaVersion": 1, "schemaVersion": 1}\n',
                encoding="utf-8",
            )
            duplicate_result = MODULE.evaluate(ROOT, duplicate)
            self.assertFalse(duplicate_result["valid"])
            self.assertIn("duplicate key", duplicate_result["errors"][0])

            symlink = Path(directory) / "contract-link.json"
            symlink.symlink_to(CONTRACT)
            symlink_result = MODULE.evaluate(ROOT, symlink)
            self.assertFalse(symlink_result["valid"])
            self.assertIn("regular file", symlink_result["errors"][0])

    def test_nonstandard_json_constant_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            malformed = Path(directory) / "nan.json"
            malformed.write_text(
                '{"schemaVersion": NaN}\n',
                encoding="utf-8",
            )
            result = MODULE.evaluate(ROOT, malformed)

        self.assertFalse(result["valid"])
        self.assertIn("invalid JSON constant", result["errors"][0])

    def test_contract_repository_must_match_origin(self):
        contract = load_contract()
        contract["targetRepository"] = "attacker/example"

        with tempfile.TemporaryDirectory() as directory:
            result = MODULE.evaluate(
                ROOT,
                write_contract(directory, contract),
            )

        self.assertFalse(result["valid"])
        self.assertFalse(result["checks"]["target-repository"])

    def test_cli_reports_valid_but_blocked_contract(self):
        completed = subprocess.run(
            [sys.executable, str(CHECKER)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertTrue(result["valid"], result["errors"])
        self.assertFalse(result["deploymentReady"])
        self.assertNotEqual(result["blockingGates"], [])
        self.assertEqual(completed.stderr, "")

    def test_cli_rejects_symlinked_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            symlink = Path(directory) / "contract-link.json"
            symlink.symlink_to(CONTRACT)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(CHECKER),
                    "--contract",
                    str(symlink),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            result = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 2)
        self.assertFalse(result["valid"])
        self.assertIn("regular file", result["errors"][0])
        self.assertNotIn("Traceback", completed.stderr)

    def test_checker_has_no_network_or_workflow_execution_surface(self):
        source = CHECKER.read_text(encoding="utf-8")

        for forbidden in (
            "import requests",
            "from requests",
            "import urllib",
            "from urllib",
            "socket.",
            "curl ",
            "wget ",
            "clawhub ",
            "gh ",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertNotIn("shell=True", source)


if __name__ == "__main__":
    unittest.main()
