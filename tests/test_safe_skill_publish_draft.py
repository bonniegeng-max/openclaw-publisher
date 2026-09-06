import importlib.util
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "skill-release-authorization-vnext"
GUARD = RESEARCH / "safe_publish_target_guard.py"
CONTRACT = RESEARCH / "safe-publish-target-contract.json"
GUIDE = RESEARCH / "safe-publish-target-guard.md"
CONTRACT_CHECKER = RESEARCH / "check_safe_publish_target_contract.py"
SPEC = importlib.util.spec_from_file_location("safe_publish_target_guard", GUARD)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
CHECKER_SPEC = importlib.util.spec_from_file_location(
    "check_safe_publish_target_contract",
    CONTRACT_CHECKER,
)
CHECKER_MODULE = importlib.util.module_from_spec(CHECKER_SPEC)
assert CHECKER_SPEC.loader is not None
CHECKER_SPEC.loader.exec_module(CHECKER_MODULE)


def git(root, *args):
    return subprocess.check_output(
        ["git", *args],
        cwd=root,
        text=True,
    ).strip()


def commit_all(root, message):
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True)
    return git(root, "rev-parse", "HEAD")


def add_skill(root, slug, body="body\n"):
    skill = root / "skills" / slug
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(body, encoding="utf-8")
    (skill / "CHANGELOG.md").write_text("# Changes\n", encoding="utf-8")
    (skill / ".clawhubignore").write_text(".DS_Store\n", encoding="utf-8")
    return skill


def write_contract(directory, value):
    path = Path(directory) / "safe-contract.json"
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def make_repo(directory):
    root = Path(directory)
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
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    base = commit_all(root, "baseline")
    return root, base


class SafeSkillPublishDraftTests(unittest.TestCase):
    def test_contract_checker_reports_valid_but_not_deployment_ready(self):
        result = CHECKER_MODULE.evaluate(ROOT, CONTRACT)

        self.assertTrue(result["valid"], result["errors"])
        self.assertFalse(result["deploymentReady"])
        self.assertEqual(result["contractStatus"], "research-only-not-wired")
        self.assertTrue(result["checks"]["guard-baseline"])
        self.assertTrue(result["checks"]["formal-baselines"])
        self.assertEqual(
            set(result["knownFormalRisks"]),
            CHECKER_MODULE.EXPECTED_RISKS,
        )

    def test_contract_checker_rejects_policy_and_baseline_drift(self):
        mutations = []
        digest = json.loads(CONTRACT.read_text(encoding="utf-8"))
        digest["guardBaseline"]["sha256"] = "sha256:" + "0" * 64
        mutations.append(("guard digest", digest, "guard-baseline"))

        policy = json.loads(CONTRACT.read_text(encoding="utf-8"))
        policy["selectionRules"]["maximumTargets"] = 2
        mutations.append(("selection policy", policy, "selection-rules"))

        extra = json.loads(CONTRACT.read_text(encoding="utf-8"))
        extra["trusted"] = True
        mutations.append(("extra field", extra, "top-level-fields"))

        for label, contract, check in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                result = CHECKER_MODULE.evaluate(
                    ROOT,
                    write_contract(directory, contract),
                )
                self.assertFalse(result["valid"])
                self.assertFalse(result["checks"][check])

    def test_contract_checker_rejects_duplicate_and_nonstandard_json(self):
        for label, content, expected in (
            (
                "duplicate",
                '{"schemaVersion":1,"schemaVersion":1}\n',
                "duplicate key",
            ),
            (
                "nan",
                '{"schemaVersion":NaN}\n',
                "invalid JSON constant",
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "invalid.json"
                path.write_text(content, encoding="utf-8")
                result = CHECKER_MODULE.evaluate(ROOT, path)
                self.assertFalse(result["valid"])
                self.assertIn(expected, result["errors"][0])

    def test_research_contract_and_guide_are_explicitly_not_wired(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        guide = GUIDE.read_text(encoding="utf-8")

        self.assertEqual(contract["schemaVersion"], MODULE.SCHEMA_VERSION)
        self.assertEqual(contract["status"], "research-only-not-wired")
        self.assertFalse(contract["formalWorkflowModified"])
        self.assertEqual(
            set(contract["knownFormalRisks"]),
            {
                "workflow-dispatch-can-request-real-publish",
                "changed-only-can-fall-back-to-root-scan",
                "multiple-targets-can-be-published",
            },
        )
        self.assertFalse(contract["executionBoundary"]["networkCallsPresent"])
        self.assertFalse(contract["executionBoundary"]["osNetworkSandboxPresent"])
        self.assertFalse(contract["executionBoundary"]["credentialsAccepted"])
        self.assertFalse(contract["executionBoundary"]["registryMutationAllowed"])
        self.assertEqual(
            contract["executionBoundary"]["allowedExecutables"],
            ["python3", "/usr/bin/git"],
        )
        self.assertEqual(
            contract["executionBoundary"]["gitTimeoutSeconds"],
            MODULE.GIT_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            contract["executionBoundary"]["maximumCombinedGitOutputBytes"],
            MODULE.MAX_GIT_OUTPUT_BYTES,
        )
        self.assertGreater(MODULE.MAX_GIT_OUTPUT_BYTES, MODULE.MAX_FILE_BYTES)
        self.assertEqual(
            contract["selectionRules"]["packageSnapshotSource"],
            "HEAD-tree",
        )
        self.assertEqual(
            contract["selectionRules"]["worktreeTraversal"],
            "no-follow",
        )
        self.assertEqual(
            contract["selectionRules"]["nonTargetPackageSnapshot"],
            None,
        )
        self.assertEqual(contract["selectionRules"]["maximumTargets"], 1)
        self.assertFalse(contract["evidenceBoundary"]["deploymentReady"])
        self.assertIn("research-only-not-wired", guide)
        self.assertIn("源码不发起网络调用", guide)
        self.assertIn("不构成 E1-E4", guide)

    def test_guard_draft_and_formal_baselines_match_evidence(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(
            contract["guardBaseline"]["path"],
            contract["guard"],
        )
        self.assertEqual(
            set(contract["formalBaselines"]),
            {"caller", "local"},
        )
        guard_draft = contract["guardDraft"]
        current_guard = ROOT / guard_draft["path"]
        self.assertEqual(guard_draft["mode"], "100644")
        self.assertEqual(
            guard_draft["sha256"],
            "sha256:" + hashlib.sha256(current_guard.read_bytes()).hexdigest(),
        )
        baselines = contract["formalBaselines"]
        for label, baseline in baselines.items():
            with self.subTest(label=label):
                entry = subprocess.check_output(
                    [
                        "git",
                        "ls-tree",
                        baseline["commit"],
                        "--",
                        baseline["path"],
                    ],
                    cwd=ROOT,
                    text=True,
                ).strip().split(maxsplit=3)
                content = subprocess.check_output(
                    [
                        "git",
                        "show",
                        f"{baseline['commit']}:{baseline['path']}",
                    ],
                    cwd=ROOT,
                )
                current = ROOT / baseline["path"]
                current_mode = (
                    "100755"
                    if os.stat(current).st_mode & 0o111
                    else "100644"
                )
                self.assertEqual(entry[0], baseline["mode"])
                self.assertEqual(entry[1], "blob")
                self.assertEqual(entry[2], baseline["blobOid"])
                self.assertEqual(
                    "sha256:" + hashlib.sha256(content).hexdigest(),
                    baseline["sha256"],
                )
                self.assertEqual(current.read_bytes(), content)
                self.assertEqual(current_mode, baseline["mode"])

    def test_workflow_dispatch_cannot_request_real_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            add_skill(root, "demo-skill")
            commit_all(root, "add skill")
            result = MODULE.evaluate(
                root,
                event_name="workflow_dispatch",
                dry_run=False,
                changed_only=True,
                skill_path="skills/demo-skill",
            )

        self.assertFalse(result["valid"])
        self.assertFalse(result["mutationAllowed"])
        self.assertIn(
            "restricted to dry-run",
            result["blockingReasons"][0],
        )

    def test_only_push_main_can_request_mutation(self):
        cases = (
            ("pull_request", "refs/pull/1/merge", "restricted to dry-run"),
            ("schedule", "refs/heads/main", "not supported"),
            ("push", "refs/heads/topic", "requires a push"),
        )
        for event_name, ref, expected in cases:
            with self.subTest(event_name=event_name, ref=ref):
                with tempfile.TemporaryDirectory() as directory:
                    root, _ = make_repo(directory)
                    add_skill(root, "demo-skill")
                    commit_all(root, "add skill")
                    result = MODULE.evaluate(
                        root,
                        event_name=event_name,
                        ref=ref,
                        dry_run=False,
                        changed_only=True,
                        skill_path="skills/demo-skill",
                    )

                self.assertFalse(result["valid"])
                self.assertFalse(result["mutationAllowed"])
                self.assertIn(expected, result["blockingReasons"][0])

    def test_real_publish_requires_base_and_changed_explicit_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = make_repo(directory)
            add_skill(root, "demo-skill")
            head = commit_all(root, "add skill")
            missing_base = MODULE.evaluate(
                root,
                event_name="push",
                ref="refs/heads/main",
                dry_run=False,
                changed_only=True,
                skill_path="skills/demo-skill",
            )
            unchanged = MODULE.evaluate(
                root,
                event_name="push",
                ref="refs/heads/main",
                dry_run=False,
                changed_only=True,
                base=head,
                head=head,
                skill_path="skills/demo-skill",
                event_before=head,
                event_sha=head,
                event_ref="refs/heads/main",
            )
            changed = MODULE.evaluate(
                root,
                event_name="push",
                ref="refs/heads/main",
                dry_run=False,
                changed_only=True,
                base=base,
                head=head,
                skill_path="skills/demo-skill",
                event_before=base,
                event_sha=head,
                event_ref="refs/heads/main",
            )

        self.assertFalse(missing_base["valid"])
        self.assertIn(
            "requires a full base commit",
            missing_base["blockingReasons"][0],
        )
        self.assertFalse(unchanged["valid"])
        self.assertIn(
            "is not changed",
            unchanged["blockingReasons"][0],
        )
        self.assertTrue(changed["valid"], changed["blockingReasons"])
        self.assertTrue(changed["authorizationEligible"])
        self.assertFalse(changed["authorized"])
        self.assertFalse(changed["mutationAllowed"])

    def test_real_publish_boundaries_match_trusted_event_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root, event_before = make_repo(directory)
            add_skill(root, "first-skill")
            middle = commit_all(root, "first skill")
            add_skill(root, "second-skill")
            event_sha = commit_all(root, "second skill")
            cases = (
                (
                    "truncated-base",
                    {
                        "base": middle,
                        "head": event_sha,
                        "event_before": event_before,
                        "event_sha": event_sha,
                        "event_ref": "refs/heads/main",
                    },
                    "must match trusted push event evidence",
                ),
                (
                    "symbolic-head",
                    {
                        "base": event_before,
                        "head": "HEAD",
                        "event_before": event_before,
                        "event_sha": event_sha,
                        "event_ref": "refs/heads/main",
                    },
                    "head must be a full lowercase commit",
                ),
                (
                    "missing-event-evidence",
                    {
                        "base": event_before,
                        "head": event_sha,
                    },
                    "complete trusted push event evidence",
                ),
            )
            for label, boundaries, expected in cases:
                with self.subTest(label=label):
                    result = MODULE.evaluate(
                        root,
                        event_name="push",
                        ref="refs/heads/main",
                        dry_run=False,
                        changed_only=True,
                        skill_path="skills/second-skill",
                        **boundaries,
                    )
                    self.assertFalse(result["valid"])
                    self.assertFalse(result["authorizationEligible"])
                    self.assertFalse(result["authorized"])
                    self.assertFalse(result["mutationAllowed"])
                    self.assertIn(expected, result["blockingReasons"][0])

            unbounded = MODULE.evaluate(
                root,
                event_name="push",
                ref="refs/heads/main",
                dry_run=False,
                changed_only=False,
                base=event_before,
                head=event_sha,
                skill_path="skills/second-skill",
                event_before=event_before,
                event_sha=event_sha,
                event_ref="refs/heads/main",
            )

        self.assertFalse(unbounded["valid"])
        self.assertIn(
            "requires changed_only true",
            unbounded["blockingReasons"][0],
        )

    def test_inherited_path_cannot_select_git(self):
        with tempfile.TemporaryDirectory() as directory:
            fake_git = Path(directory) / "git"
            fake_git.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_git.chmod(0o755)
            with mock.patch.dict(
                "os.environ",
                {"PATH": str(fake_git.parent)},
                clear=False,
            ), mock.patch.object(
                MODULE.subprocess,
                "Popen",
                wraps=subprocess.Popen,
            ) as popen:
                completed = MODULE.run_git(Path(directory), "--version")

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(popen.call_args.args[0][0], "/usr/bin/git")
        self.assertEqual(popen.call_args.kwargs["env"]["PATH"], "/usr/bin")
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_git_timeout_is_a_structured_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            with mock.patch.object(
                MODULE,
                "run_git",
                side_effect=ValueError("Git command timed out"),
            ):
                result = MODULE.evaluate(
                    root,
                    event_name="push",
                    dry_run=True,
                    changed_only=True,
                    skill_path="skills/demo-skill",
                )

        self.assertFalse(result["valid"])
        self.assertIn("timed out", result["blockingReasons"][0])

    def test_git_output_is_incrementally_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            for index in range(100):
                (root / f"untracked-{index:03d}-with-long-name.txt").write_text(
                    "x\n",
                    encoding="utf-8",
                )
            with mock.patch.object(MODULE, "MAX_GIT_OUTPUT_BYTES", 1024):
                with self.assertRaisesRegex(ValueError, "output exceeds"):
                    MODULE.run_git(
                        root,
                        "status",
                        "--porcelain=v1",
                        "-z",
                        text=False,
                    )

    def test_git_wall_clock_timeout_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            with mock.patch.object(MODULE, "GIT_TIMEOUT_SECONDS", 0.05):
                with self.assertRaisesRegex(ValueError, "timed out"):
                    MODULE.run_git(
                        root,
                        "-c",
                        "alias.stall=!/bin/sleep 10",
                        "stall",
                    )

    def test_unconfirmed_git_reap_is_a_value_error(self):
        stdout_read, stdout_write = os.pipe()
        stderr_read, stderr_write = os.pipe()

        class UnreapableProcess:
            pid = 99999999
            stdout = os.fdopen(stdout_read, "rb")
            stderr = os.fdopen(stderr_read, "rb")

            def poll(self):
                return None

            def kill(self):
                return None

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("git", timeout)

        try:
            with mock.patch.object(
                MODULE.subprocess,
                "Popen",
                return_value=UnreapableProcess(),
            ), mock.patch.object(MODULE, "GIT_TIMEOUT_SECONDS", 0):
                with self.assertRaisesRegex(
                    ValueError,
                    "termination could not be confirmed",
                ):
                    MODULE.run_git(Path("/"), "--version")
        finally:
            os.close(stdout_write)
            os.close(stderr_write)

    def test_repository_object_store_hardlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            object_file = next(
                path
                for path in (root / ".git" / "objects").rglob("*")
                if path.is_file()
            )
            os.link(object_file, object_file.with_name(object_file.name + ".linked"))
            result = MODULE.evaluate(
                root,
                event_name="workflow_dispatch",
                dry_run=True,
                changed_only=True,
                skill_path="skills/demo-skill",
            )

        self.assertFalse(result["valid"])
        self.assertIn("hardlinked", result["blockingReasons"][0])

    def test_repository_object_store_writable_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            object_file = next(
                path
                for path in (root / ".git" / "objects").rglob("*")
                if path.is_file()
            )
            object_file.chmod(0o666)
            result = MODULE.evaluate(
                root,
                event_name="workflow_dispatch",
                dry_run=True,
                changed_only=True,
                skill_path="skills/demo-skill",
            )

        self.assertFalse(result["valid"])
        self.assertIn("untrusted writable entry", result["blockingReasons"][0])

    def test_changed_only_without_base_or_explicit_path_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            result = MODULE.evaluate(
                root,
                event_name="push",
                dry_run=True,
                changed_only=True,
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            "requires a valid base or explicit skill_path",
            result["blockingReasons"][0],
        )

    def test_unbounded_scan_is_rejected_even_when_changed_only_is_false(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            result = MODULE.evaluate(
                root,
                event_name="push",
                dry_run=True,
                changed_only=False,
            )

        self.assertFalse(result["valid"])
        self.assertIn("unbounded", result["blockingReasons"][0])

    def test_zero_changed_skills_is_a_successful_no_op(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = make_repo(directory)
            (root / "README.md").write_text("changed\n", encoding="utf-8")
            head = commit_all(root, "non-skill change")
            result = MODULE.evaluate(
                root,
                event_name="push",
                dry_run=False,
                changed_only=True,
                ref="refs/heads/main",
                base=base,
                head=head,
                event_before=base,
                event_sha=head,
                event_ref="refs/heads/main",
            )

        self.assertTrue(result["valid"], result["blockingReasons"])
        self.assertEqual(result["decision"], "no-op")
        self.assertFalse(result["mutationAllowed"])
        self.assertFalse(result["authorizationEligible"])
        self.assertEqual(result["targetCount"], 0)
        self.assertIsNone(result["skillPath"])
        self.assertIsNone(result["packageSnapshot"])

    def test_exactly_one_changed_skill_is_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = make_repo(directory)
            add_skill(root, "demo-skill")
            head = commit_all(root, "add one skill")
            expected_tree = git(
                root,
                "rev-parse",
                f"{head}:skills/demo-skill",
            )
            result = MODULE.evaluate(
                root,
                event_name="push",
                dry_run=False,
                changed_only=True,
                ref="refs/heads/main",
                base=base,
                head=head,
                event_before=base,
                event_sha=head,
                event_ref="refs/heads/main",
            )

        self.assertTrue(result["valid"], result["blockingReasons"])
        self.assertEqual(result["decision"], "single-target")
        self.assertTrue(result["authorizationEligible"])
        self.assertFalse(result["authorized"])
        self.assertFalse(result["mutationAllowed"])
        self.assertEqual(result["targetCount"], 1)
        self.assertEqual(result["skillPath"], "skills/demo-skill")
        self.assertEqual(result["slug"], "demo-skill")
        snapshot = result["packageSnapshot"]
        self.assertEqual(snapshot["treeOid"], expected_tree)
        self.assertEqual(
            [item["path"] for item in snapshot["files"]],
            [".clawhubignore", "CHANGELOG.md", "SKILL.md"],
        )
        canonical = json.dumps(
            {
                "files": snapshot["files"],
                "format": MODULE.PACKAGE_DIGEST_FORMAT,
                "skillPath": "skills/demo-skill",
                "treeOid": snapshot["treeOid"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(
            snapshot["packageDigest"],
            "sha256:" + hashlib.sha256(canonical).hexdigest(),
        )
        self.assertEqual(
            set(snapshot),
            {"treeOid", "files", "packageDigest"},
        )
        self.assertTrue(
            all(
                set(item) == {"path", "mode", "blobOid", "sha256"}
                for item in snapshot["files"]
            )
        )

    def test_package_digest_binds_format_target_and_every_file_field(self):
        tree_oid = "1" * 40
        files = [
            {
                "path": "SKILL.md",
                "mode": "100644",
                "blobOid": "2" * 40,
                "sha256": "sha256:" + "3" * 64,
            }
        ]
        baseline = MODULE.canonical_package_digest(
            "skills/demo-skill",
            tree_oid,
            files,
        )
        variants = [
            (
                "skillPath",
                lambda: MODULE.canonical_package_digest(
                    "skills/other-skill",
                    tree_oid,
                    files,
                ),
            ),
            (
                "treeOid",
                lambda: MODULE.canonical_package_digest(
                    "skills/demo-skill",
                    "4" * 40,
                    files,
                ),
            ),
        ]
        for field, replacement in (
            ("path", "OTHER.md"),
            ("mode", "100755"),
            ("blobOid", "5" * 40),
            ("sha256", "sha256:" + "6" * 64),
        ):
            mutated = [dict(files[0])]
            mutated[0][field] = replacement
            variants.append(
                (
                    field,
                    lambda mutated=mutated: MODULE.canonical_package_digest(
                        "skills/demo-skill",
                        tree_oid,
                        mutated,
                    ),
                )
            )
        for label, digest in variants:
            with self.subTest(label=label):
                self.assertNotEqual(digest(), baseline)
        with mock.patch.object(
            MODULE,
            "PACKAGE_DIGEST_FORMAT",
            "safe-publish-package-v2",
        ):
            self.assertNotEqual(
                MODULE.canonical_package_digest(
                    "skills/demo-skill",
                    tree_oid,
                    files,
                ),
                baseline,
            )

    def test_multiple_changed_skills_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = make_repo(directory)
            add_skill(root, "first-skill")
            add_skill(root, "second-skill")
            head = commit_all(root, "add two skills")
            result = MODULE.evaluate(
                root,
                event_name="push",
                dry_run=True,
                changed_only=True,
                base=base,
                head=head,
            )

        self.assertFalse(result["valid"])
        self.assertFalse(result["mutationAllowed"])
        self.assertIn("more than one", result["blockingReasons"][0])

    def test_deleted_and_added_skills_are_still_multiple_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            first = add_skill(root, "first-skill")
            base = commit_all(root, "add first skill")
            for child in first.iterdir():
                child.unlink()
            first.rmdir()
            add_skill(root, "second-skill")
            head = commit_all(root, "replace skill")
            result = MODULE.evaluate(
                root,
                event_name="push",
                dry_run=True,
                changed_only=True,
                base=base,
                head=head,
            )

        self.assertFalse(result["valid"])
        self.assertIn("more than one", result["blockingReasons"][0])

    def test_explicit_target_cannot_hide_another_changed_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = make_repo(directory)
            add_skill(root, "first-skill")
            add_skill(root, "second-skill")
            head = commit_all(root, "add two skills")
            result = MODULE.evaluate(
                root,
                event_name="push",
                dry_run=True,
                changed_only=True,
                base=base,
                head=head,
                skill_path="skills/first-skill",
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            "does not cover all changed Skills",
            result["blockingReasons"][0],
        )

    def test_explicit_path_is_strictly_validated(self):
        invalid_paths = (
            "",
            "/skills/demo-skill",
            "skills//demo-skill",
            "skills/../demo-skill",
            "skills/demo-skill/",
            "skills\\demo-skill",
            "other/demo-skill",
            "skills/Demo-Skill",
            "skills/clawhub-demo",
            "skills/demo-clawhub",
            "skills/demo-skill/nested",
        )
        for value in invalid_paths:
            with self.subTest(skill_path=value):
                with tempfile.TemporaryDirectory() as directory:
                    root, _ = make_repo(directory)
                    add_skill(root, "demo-skill")
                    commit_all(root, "add valid fixture")
                    result = MODULE.evaluate(
                        root,
                        event_name="push",
                        dry_run=True,
                        changed_only=True,
                        skill_path=value,
                    )
                self.assertFalse(result["valid"])
                self.assertFalse(result["mutationAllowed"])

    def test_explicit_path_requires_complete_regular_skill_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            skill = add_skill(root, "demo-skill")
            (skill / "CHANGELOG.md").unlink()
            commit_all(root, "add incomplete skill")
            result = MODULE.evaluate(
                root,
                event_name="push",
                dry_run=True,
                changed_only=True,
                skill_path="skills/demo-skill",
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            "missing required file CHANGELOG.md",
            result["blockingReasons"][0],
        )

    def test_explicit_path_rejects_symlinked_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            real = add_skill(root, "real-skill")
            alias = root / "skills" / "alias-skill"
            alias.symlink_to(real.name, target_is_directory=True)
            commit_all(root, "add symlinked skill")
            result = MODULE.evaluate(
                root,
                event_name="push",
                dry_run=True,
                changed_only=True,
                skill_path="skills/alias-skill",
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            "must not contain symlinks",
            result["blockingReasons"][0],
        )
        self.assertIsNone(result["packageSnapshot"])

    def test_head_tree_snapshot_rejects_nested_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            skill = add_skill(root, "demo-skill")
            (skill / "linked.md").symlink_to("SKILL.md")
            commit_all(root, "add package with symlink")
            result = MODULE.evaluate(
                root,
                event_name="workflow_dispatch",
                dry_run=True,
                changed_only=True,
                skill_path="skills/demo-skill",
            )

        self.assertFalse(result["valid"])
        self.assertIsNone(result["packageSnapshot"])
        self.assertIn("only regular files", result["blockingReasons"][0])

    def test_ignored_extra_file_is_rejected_by_exact_worktree_walk(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            skill = add_skill(root, "demo-skill")
            (skill / ".gitignore").write_text("ignored.tmp\n", encoding="utf-8")
            commit_all(root, "add skill")
            (skill / "ignored.tmp").write_text("not packaged\n", encoding="utf-8")
            self.assertEqual(git(root, "status", "--porcelain"), "")
            result = MODULE.evaluate(
                root,
                event_name="workflow_dispatch",
                dry_run=True,
                changed_only=True,
                skill_path="skills/demo-skill",
            )

        self.assertFalse(result["valid"])
        self.assertIsNone(result["packageSnapshot"])
        self.assertIn("extra or ignored entries", result["blockingReasons"][0])

    def test_empty_directory_is_rejected_by_exact_worktree_walk(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            skill = add_skill(root, "demo-skill")
            commit_all(root, "add skill")
            (skill / "empty").mkdir()
            self.assertEqual(git(root, "status", "--porcelain"), "")
            result = MODULE.evaluate(
                root,
                event_name="workflow_dispatch",
                dry_run=True,
                changed_only=True,
                skill_path="skills/demo-skill",
            )

        self.assertFalse(result["valid"])
        self.assertIsNone(result["packageSnapshot"])
        self.assertIn("extra or ignored entries", result["blockingReasons"][0])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO requires os.mkfifo")
    def test_ignored_special_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            skill = add_skill(root, "demo-skill")
            (skill / ".gitignore").write_text(
                "ignored.pipe\n",
                encoding="utf-8",
            )
            commit_all(root, "add skill")
            os.mkfifo(skill / "ignored.pipe")
            self.assertEqual(git(root, "status", "--porcelain"), "")
            result = MODULE.evaluate(
                root,
                event_name="workflow_dispatch",
                dry_run=True,
                changed_only=True,
                skill_path="skills/demo-skill",
            )

        self.assertFalse(result["valid"])
        self.assertIsNone(result["packageSnapshot"])
        self.assertIn("only regular files", result["blockingReasons"][0])

    def test_hardlinked_package_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            skill = add_skill(root, "demo-skill")
            duplicate = skill / "duplicate.md"
            duplicate.write_text("body\n", encoding="utf-8")
            commit_all(root, "add skill")
            duplicate.unlink()
            os.link(skill / "SKILL.md", duplicate)
            self.assertEqual(git(root, "status", "--porcelain"), "")
            result = MODULE.evaluate(
                root,
                event_name="workflow_dispatch",
                dry_run=True,
                changed_only=True,
                skill_path="skills/demo-skill",
            )

        self.assertFalse(result["valid"])
        self.assertIsNone(result["packageSnapshot"])
        self.assertIn("hardlinked files", result["blockingReasons"][0])

    def test_missing_no_follow_platform_capability_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            add_skill(root, "demo-skill")
            for capability in ("O_NOFOLLOW", "O_DIRECTORY"):
                with self.subTest(capability=capability), mock.patch.object(
                    MODULE.os,
                    capability,
                    None,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "lacks required O_NOFOLLOW",
                    ):
                        MODULE.worktree_package_evidence(
                            root,
                            "skills/demo-skill",
                        )

    def test_intermediate_skill_path_symlink_is_rejected_by_openat_walk(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            add_skill(root, "demo-skill")
            skills = root / "skills"
            relocated = root / "skills-relocated"
            skills.rename(relocated)
            skills.symlink_to(relocated)
            with self.assertRaisesRegex(
                ValueError,
                "cannot be opened safely",
            ):
                MODULE.worktree_package_evidence(
                    root,
                    "skills/demo-skill",
                )

    def test_symlinked_git_object_store_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            objects = root / ".git" / "objects"
            relocated = root / "objects-relocated"
            objects.rename(relocated)
            objects.symlink_to(relocated)
            result = MODULE.evaluate(
                root,
                event_name="workflow_dispatch",
                dry_run=True,
                changed_only=True,
                skill_path="skills/demo-skill",
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            "object store must be a local directory",
            result["blockingReasons"][0],
        )

    def test_symlink_below_git_object_store_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            pack = root / ".git" / "objects" / "pack"
            relocated = root / ".git" / "pack-relocated"
            pack.rename(relocated)
            pack.symlink_to(relocated)
            result = MODULE.evaluate(
                root,
                event_name="workflow_dispatch",
                dry_run=True,
                changed_only=True,
                skill_path="skills/demo-skill",
            )

        self.assertFalse(result["valid"])
        self.assertIn(
            "object store must not contain symlinks",
            result["blockingReasons"][0],
        )

    def test_package_resource_limits_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            add_skill(root, "demo-skill")
            commit_all(root, "add skill")
            with mock.patch.object(MODULE, "MAX_FILE_BYTES", 1):
                oversized = MODULE.evaluate(
                    root,
                    event_name="workflow_dispatch",
                    dry_run=True,
                    changed_only=True,
                    skill_path="skills/demo-skill",
                )
            with mock.patch.object(MODULE, "MAX_PACKAGE_FILES", 2):
                too_many = MODULE.evaluate(
                    root,
                    event_name="workflow_dispatch",
                    dry_run=True,
                    changed_only=True,
                    skill_path="skills/demo-skill",
                )

        self.assertFalse(oversized["valid"])
        self.assertIn(
            "file exceeds maximum size",
            oversized["blockingReasons"][0],
        )
        self.assertFalse(too_many["valid"])
        self.assertIn(
            "exceeds maximum file count",
            too_many["blockingReasons"][0],
        )

    def test_final_clean_check_rejects_change_after_second_package_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            add_skill(root, "demo-skill")
            commit_all(root, "add skill")
            original_validate = MODULE.validate_skill_folder
            call_count = 0

            def mutate_after_second_validation(*args, **kwargs):
                nonlocal call_count
                result = original_validate(*args, **kwargs)
                call_count += 1
                if call_count == 2:
                    (root / "README.md").write_text(
                        "changed after validation\n",
                        encoding="utf-8",
                    )
                return result

            with mock.patch.object(
                MODULE,
                "validate_skill_folder",
                side_effect=mutate_after_second_validation,
            ):
                result = MODULE.evaluate(
                    root,
                    event_name="workflow_dispatch",
                    dry_run=True,
                    changed_only=True,
                    skill_path="skills/demo-skill",
                )

        self.assertEqual(call_count, 2)
        self.assertFalse(result["valid"])
        self.assertIsNone(result["packageSnapshot"])
        self.assertIn("worktree must be clean", result["blockingReasons"][0])

    def test_invalid_or_non_ancestor_base_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = make_repo(directory)
            add_skill(root, "demo-skill")
            head = commit_all(root, "add skill")
            malformed = MODULE.evaluate(
                root,
                event_name="push",
                dry_run=True,
                changed_only=True,
                base="HEAD~1",
                head=head,
            )
            symbolic = MODULE.evaluate(
                root,
                event_name="push",
                dry_run=True,
                changed_only=True,
                base="HEAD",
                head=head,
            )
            subprocess.run(
                ["git", "checkout", "-q", "-b", "sibling", base],
                cwd=root,
                check=True,
            )
            (root / "sibling.txt").write_text("sibling\n", encoding="utf-8")
            sibling = commit_all(root, "sibling commit")
            subprocess.run(
                ["git", "checkout", "-q", "--detach", head],
                cwd=root,
                check=True,
            )
            reversed_range = MODULE.evaluate(
                root,
                event_name="push",
                dry_run=True,
                changed_only=True,
                base=sibling,
                head=head,
            )

        self.assertFalse(malformed["valid"])
        self.assertIn(
            "full lowercase commit",
            malformed["blockingReasons"][0],
        )
        self.assertFalse(symbolic["valid"])
        self.assertIn(
            "base must be a full lowercase commit",
            symbolic["blockingReasons"][0],
        )
        self.assertFalse(reversed_range["valid"])
        self.assertIn("ancestor", reversed_range["blockingReasons"][0])

    def test_non_string_and_non_boolean_inputs_fail_structurally(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            cases = (
                {"event_name": [], "dry_run": True, "changed_only": True},
                {"event_name": "push", "dry_run": "false", "changed_only": True},
                {"event_name": "push", "dry_run": True, "changed_only": 1},
            )
            for values in cases:
                with self.subTest(values=values):
                    result = MODULE.evaluate(
                        root,
                        skill_path="skills/demo-skill",
                        **values,
                    )
                    json.dumps(result)
                    self.assertFalse(result["valid"])
                    self.assertFalse(result["mutationAllowed"])
                    self.assertTrue(result["blockingReasons"])

    def test_dirty_worktree_and_non_head_commit_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = make_repo(directory)
            add_skill(root, "demo-skill")
            head = commit_all(root, "add skill")
            dirty = root / "README.md"
            dirty.write_text("dirty\n", encoding="utf-8")
            dirty_result = MODULE.evaluate(
                root,
                event_name="push",
                dry_run=True,
                changed_only=True,
                base=base,
                head=head,
            )
            dirty.write_text("fixture\n", encoding="utf-8")
            stale_result = MODULE.evaluate(
                root,
                event_name="push",
                dry_run=True,
                changed_only=True,
                base=base,
                head=base,
            )

        self.assertFalse(dirty_result["valid"])
        self.assertIn(
            "worktree must be clean",
            dirty_result["blockingReasons"][0],
        )
        self.assertFalse(stale_result["valid"])
        self.assertIn(
            "checked-out repository HEAD",
            stale_result["blockingReasons"][0],
        )

    def test_cli_emits_json_and_uses_documented_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _ = make_repo(directory)
            add_skill(root, "demo-skill")
            commit_all(root, "add skill")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(GUARD),
                    "--repo-root",
                    str(root),
                    "--event-name",
                    "workflow_dispatch",
                    "--dry-run",
                    "true",
                    "--changed-only",
                    "true",
                    "--skill-path",
                    "skills/demo-skill",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            result = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(result["valid"])
        self.assertEqual(result["decision"], "single-target")
        self.assertFalse(result["mutationAllowed"])
        self.assertEqual(
            set(result),
            {
                "schemaVersion",
                "valid",
                "decision",
                "eventName",
                "ref",
                "dryRun",
                "changedOnly",
                "authorizationEligible",
                "authorized",
                "mutationAllowed",
                "targetCount",
                "skillPath",
                "slug",
                "packageSnapshot",
                "baseCommit",
                "headCommit",
                "eventBefore",
                "eventSha",
                "eventRef",
                "blockingReasons",
            },
        )
        self.assertEqual(completed.stderr, "")

    def test_all_decisions_preserve_exact_result_schema_and_invariants(self):
        fields = {
            "schemaVersion",
            "valid",
            "decision",
            "eventName",
            "ref",
            "dryRun",
            "changedOnly",
            "authorizationEligible",
            "authorized",
            "mutationAllowed",
            "targetCount",
            "skillPath",
            "slug",
            "packageSnapshot",
            "baseCommit",
            "headCommit",
            "eventBefore",
            "eventSha",
            "eventRef",
            "blockingReasons",
        }
        snapshot = {"treeOid": "1" * 40, "files": [], "packageDigest": "x"}
        cases = (
            MODULE.decision_result(
                valid=False,
                decision="blocked",
                event_name="push",
                ref="",
                dry_run=True,
                changed_only=True,
                blocking_reasons=["blocked"],
            ),
            MODULE.decision_result(
                valid=True,
                decision="no-op",
                event_name="push",
                ref="",
                dry_run=True,
                changed_only=True,
            ),
            MODULE.decision_result(
                valid=True,
                decision="single-target",
                event_name="push",
                ref="",
                dry_run=True,
                changed_only=True,
                target={
                    "path": "skills/demo-skill",
                    "slug": "demo-skill",
                    "packageSnapshot": snapshot,
                },
            ),
        )
        for result in cases:
            with self.subTest(decision=result["decision"]):
                self.assertEqual(set(result), fields)
                self.assertFalse(result["authorized"])
                self.assertFalse(result["mutationAllowed"])
                self.assertEqual(
                    result["authorizationEligible"],
                    result["valid"]
                    and result["decision"] == "single-target"
                    and result["eventName"] == "push"
                    and result["ref"] == MODULE.PRODUCTION_REF
                    and result["dryRun"] is False
                    and result["changedOnly"] is True
                    and result["baseCommit"] == result["eventBefore"]
                    and result["headCommit"] == result["eventSha"]
                    and result["ref"] == result["eventRef"],
                )
                if result["decision"] == "single-target":
                    self.assertIs(result["packageSnapshot"], snapshot)
                else:
                    self.assertIsNone(result["packageSnapshot"])

    def test_guard_has_only_offline_standard_library_and_git_surface(self):
        source = GUARD.read_text(encoding="utf-8")

        for forbidden in (
            "requests",
            "urllib",
            "socket.",
            "curl ",
            "wget ",
            "clawhub ",
            "bun ",
            "CLAWHUB_TOKEN",
            "GH_TOKEN",
            "shell=True",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn('Path("/usr/bin/git")', source)


if __name__ == "__main__":
    unittest.main()
