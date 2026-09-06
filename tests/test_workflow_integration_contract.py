import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


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
        "research/skill-release-authorization-vnext/trusted_preflight_launcher.py",
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
        entry = subprocess.check_output(
            ["git", "ls-tree", commit, "--", item["path"]],
            cwd=root,
            text=True,
        ).strip().split(maxsplit=3)
        item["mode"] = entry[0]
        item["blobOid"] = entry[2]
        content = subprocess.check_output(
            ["git", "show", f"{commit}:{item['path']}"],
            cwd=root,
        )
        item["sha256"] = MODULE.digest_bytes(content)
    draft = contract["trustedControlExecution"]["launcherDraft"]
    draft["commit"] = commit
    entry = subprocess.check_output(
        ["git", "ls-tree", commit, "--", draft["path"]],
        cwd=root,
        text=True,
    ).strip().split(maxsplit=3)
    draft["mode"] = entry[0]
    draft["blobOid"] = entry[2]
    content = subprocess.check_output(
        ["git", "show", f"{commit}:{draft['path']}"],
        cwd=root,
    )
    draft["sha256"] = MODULE.digest_bytes(content)


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
            result["localEvidence"]["controlAnchorLocallyConsistent"]
        )
        self.assertTrue(
            result["localEvidence"]["launcherDraftLocallyConsistent"]
        )
        self.assertNotIn(
            "trustedControlAnchorVerified",
            result["localEvidence"],
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

    def test_contract_uses_local_control_commit_and_no_future_fake_sha(self):
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
                isinstance(item["mode"], str)
                and item["mode"] in {"100644", "100755"}
                and isinstance(item["blobOid"], str)
                and len(item["blobOid"]) == 40
                and isinstance(item["sha256"], str)
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
        launcher = contract["trustedControlExecution"]["launcherDraft"]
        self.assertEqual(
            launcher["path"],
            MODULE.EXPECTED_LAUNCHER_DRAFT,
        )
        self.assertRegex(launcher["commit"], r"^[0-9a-f]{40}$")
        self.assertIn(launcher["mode"], {"100644", "100755"})
        self.assertRegex(launcher["blobOid"], r"^[0-9a-f]{40}$")
        self.assertRegex(launcher["sha256"], r"^sha256:[0-9a-f]{64}$")

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

        launcher_draft = load_contract()
        launcher_draft["trustedControlExecution"]["launcherDraft"][
            "sha256"
        ] = "sha256:" + "0" * 64
        mutations.append(("launcher draft", launcher_draft))

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
            "trusted control file evidence does not match the pinned commit",
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

    def test_replace_ref_cannot_change_trusted_control_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root, contract, head = make_contract_repo(directory)
            bind_control_files(root, contract, head)
            checker = root / "scripts" / "check_skill_release_authorization.py"
            checker.write_text(
                "raise RuntimeError('replacement checker')\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "malicious replacement"],
                cwd=root,
                check=True,
            )
            replacement = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
            ).strip()
            subprocess.run(
                ["git", "--no-replace-objects", "reset", "--hard", "-q", head],
                cwd=root,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "update-ref",
                    f"refs/replace/{head}",
                    replacement,
                ],
                cwd=root,
                check=True,
            )

            result = MODULE.evaluate(
                root,
                write_contract(directory, contract),
            )

        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["checks"]["local-control-anchor"])
        self.assertTrue(result["checks"]["launcher-draft-anchor"])

    def test_git_environment_filters_untrusted_git_variables(self):
        injected = {
            "GIT_DIR": "/attacker/git-dir",
            "GIT_WORK_TREE": "/attacker/work-tree",
            "GIT_COMMON_DIR": "/attacker/common-dir",
            "GIT_INDEX_FILE": "/attacker/index",
            "GIT_OBJECT_DIRECTORY": "/attacker/objects",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/attacker/alternate",
            "GIT_NAMESPACE": "attacker",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.fsmonitor",
            "GIT_CONFIG_VALUE_0": "/attacker/fsmonitor",
            "GIT_CONFIG_PARAMETERS": "'core.fsmonitor=/attacker/fsmonitor'",
            "GIT_REPLACE_REF_BASE": "refs/attacker/",
            "GIT_NO_LAZY_FETCH": "0",
            "GIT_NO_REPLACE_OBJECTS": "0",
            "GIT_EXTERNAL_DIFF": "/attacker/diff",
        }

        with mock.patch.dict(os.environ, injected, clear=False):
            environment = MODULE.git_environment()

        for key in (
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_COMMON_DIR",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_NAMESPACE",
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_KEY_0",
            "GIT_CONFIG_VALUE_0",
            "GIT_CONFIG_PARAMETERS",
            "GIT_REPLACE_REF_BASE",
        ):
            with self.subTest(key=key):
                self.assertNotIn(key, environment)
        self.assertEqual(environment["GIT_NO_LAZY_FETCH"], "1")
        self.assertEqual(environment["GIT_NO_REPLACE_OBJECTS"], "1")
        self.assertEqual(environment["GIT_EXTERNAL_DIFF"], "")

    def test_git_injections_cannot_redirect_contract_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root, contract, head = make_contract_repo(workspace / "trusted")
            (root / "trusted-marker.txt").write_text(
                "unique trusted commit\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "unique trusted control"],
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
            attacker, _, _ = make_contract_repo(workspace / "attacker")
            attacker_checker = (
                attacker / "scripts" / "check_skill_release_authorization.py"
            )
            attacker_checker.write_text(
                "raise RuntimeError('attacker repository')\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=attacker, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "attacker control"],
                cwd=attacker,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "remote",
                    "set-url",
                    "origin",
                    "https://github.com/attacker/example.git",
                ],
                cwd=attacker,
                check=True,
            )
            cases = (
                ("git-dir", {"GIT_DIR": str(attacker / ".git")}),
                (
                    "object-directory",
                    {
                        "GIT_OBJECT_DIRECTORY": str(
                            attacker / ".git" / "objects"
                        )
                    },
                ),
                (
                    "common-directory",
                    {"GIT_COMMON_DIR": str(attacker / ".git")},
                ),
                (
                    "config-injection",
                    {
                        "GIT_CONFIG_COUNT": "1",
                        "GIT_CONFIG_KEY_0": "remote.origin.url",
                        "GIT_CONFIG_VALUE_0": (
                            "https://github.com/attacker/example.git"
                        ),
                    },
                ),
            )

            for label, injected in cases:
                with self.subTest(injection=label):
                    with mock.patch.dict(os.environ, injected, clear=False):
                        result = MODULE.evaluate(
                            root,
                            write_contract(directory, contract),
                        )
                    self.assertTrue(result["valid"], result["errors"])
                    self.assertEqual(
                        result["localEvidence"]["originRepository"],
                        "bonniegeng-max/openclaw-publisher",
                    )
                    self.assertTrue(
                        result["checks"]["local-control-anchor"]
                    )
                    self.assertTrue(
                        result["checks"]["launcher-draft-anchor"]
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

    def test_origin_identity_uses_raw_local_url_without_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root, contract, head = make_contract_repo(directory)
            bind_control_files(root, contract, head)
            subprocess.run(
                [
                    "git",
                    "remote",
                    "set-url",
                    "origin",
                    "https://github.com/attacker/example.git",
                ],
                cwd=root,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "config",
                    "--local",
                    "url.https://github.com/bonniegeng-max/"
                    "openclaw-publisher.git.insteadOf",
                    "https://github.com/attacker/example.git",
                ],
                cwd=root,
                check=True,
            )

            result = MODULE.evaluate(
                root,
                write_contract(directory, contract),
            )

        self.assertFalse(result["valid"])
        self.assertFalse(result["checks"]["target-repository"])
        self.assertEqual(
            result["localEvidence"]["originRepository"],
            "attacker/example",
        )

    def test_repository_layout_rejects_subdirectory_and_linked_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            root, contract, head = make_contract_repo(directory)
            bind_control_files(root, contract, head)
            subdirectory = root / "nested"
            subdirectory.mkdir()
            result = MODULE.evaluate(
                subdirectory,
                write_contract(directory, contract),
            )

        self.assertFalse(result["valid"])
        self.assertFalse(result["checks"]["repository-layout"])
        self.assertTrue(
            any(
                "repository Git layout cannot be inspected" in error
                for error in result["errors"]
            ),
            result["errors"],
        )

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            primary, contract, head = make_contract_repo(workspace / "primary")
            bind_control_files(primary, contract, head)
            linked = workspace / "linked"
            subprocess.run(
                ["git", "worktree", "add", "-q", "--detach", str(linked), head],
                cwd=primary,
                check=True,
            )
            result = MODULE.evaluate(
                linked,
                write_contract(directory, contract),
            )

        self.assertFalse(result["valid"])
        self.assertFalse(result["checks"]["repository-layout"])
        self.assertIn(
            "repository .git must be a local directory",
            result["errors"],
        )

    def test_repository_layout_rejects_object_alternates(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root, contract, head = make_contract_repo(workspace / "trusted")
            bind_control_files(root, contract, head)
            alternate, _, _ = make_contract_repo(workspace / "alternate")
            alternates = root / ".git" / "objects" / "info" / "alternates"
            alternates.parent.mkdir(parents=True, exist_ok=True)
            alternates.write_text(
                str(alternate / ".git" / "objects") + "\n",
                encoding="utf-8",
            )

            result = MODULE.evaluate(
                root,
                write_contract(directory, contract),
            )

        self.assertFalse(result["valid"])
        self.assertFalse(result["checks"]["repository-layout"])
        self.assertIn(
            "repository object store must not use alternates",
            result["errors"],
        )

    def test_control_mode_and_blob_oid_are_bound(self):
        for field, value in (
            ("mode", "100755"),
            ("blobOid", "0" * 40),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root, contract, head = make_contract_repo(directory)
                bind_control_files(root, contract, head)
                contract["trustedControl"]["files"][0][field] = value

                result = MODULE.evaluate(
                    root,
                    write_contract(directory, contract),
                )

            self.assertFalse(result["valid"])
            self.assertFalse(result["checks"]["local-control-anchor"])
            self.assertIn(
                "trusted control file evidence does not match the pinned commit",
                result["errors"],
            )

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
