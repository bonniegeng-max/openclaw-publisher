import copy
import importlib.util
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
BUILDER = RESEARCH / "immutable_staging_builder.py"
AUDITOR = RESEARCH / "check_immutable_staging_contract.py"
CONTRACT = RESEARCH / "immutable-staging-contract.json"

SPEC = importlib.util.spec_from_file_location("immutable_staging_builder", BUILDER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
AUDITOR_SPEC = importlib.util.spec_from_file_location(
    "check_immutable_staging_contract", AUDITOR
)
AUDITOR_MODULE = importlib.util.module_from_spec(AUDITOR_SPEC)
assert AUDITOR_SPEC.loader is not None
AUDITOR_SPEC.loader.exec_module(AUDITOR_MODULE)


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def make_fixture(workspace):
    workspace = workspace.resolve()
    root = workspace / "repository"
    output = workspace / "output"
    root.mkdir()
    output.mkdir(mode=0o700)
    os.chmod(output, 0o700)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=root, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=root, check=True
    )
    skill = root / "skills" / "demo-skill"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("committed body\n", encoding="utf-8")
    (skill / "CHANGELOG.md").write_text("# Changes\n", encoding="utf-8")
    (skill / ".clawhubignore").write_text(".DS_Store\n", encoding="utf-8")
    executable = skill / "references" / "check.py"
    executable.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    executable.chmod(0o755)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    commit = git(root, "rev-parse", "HEAD")
    snapshot = MODULE.GUARD.head_package_snapshot(
        root, commit, "skills/demo-skill"
    )
    target = {
        "path": "skills/demo-skill",
        "slug": "demo-skill",
        "packageSnapshot": snapshot,
    }
    guard = MODULE.GUARD.decision_result(
        valid=True,
        decision="single-target",
        event_name="workflow_dispatch",
        ref="",
        dry_run=True,
        changed_only=True,
        target=target,
        head_commit=commit,
    )
    return root, output, skill, guard


def clear_output(output):
    descriptor = os.open(
        output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    )
    try:
        for entry in list(os.scandir(descriptor)):
            MODULE.remove_tree_at(descriptor, entry.name)
    finally:
        os.close(descriptor)


def mode(path):
    return os.stat(path, follow_symlinks=False).st_mode & 0o777


class ImmutableStagingBuilderTests(unittest.TestCase):
    def test_contract_auditor_is_valid_and_never_authorizes(self):
        result = AUDITOR_MODULE.evaluate(ROOT, CONTRACT)
        self.assertTrue(result["valid"], result["errors"])
        self.assertFalse(result["deploymentReady"])
        self.assertFalse(result["authorizationGranted"])
        self.assertTrue(result["checks"]["two-stage-anchoring"])
        self.assertTrue(result["checks"]["builder-forbidden-surface"])
        self.assertTrue(result["checks"]["builder-draft"])
        self.assertTrue(result["checks"]["builder-baseline"])

    def test_contract_auditor_rejects_builder_draft_drift(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["builderEvidence"]["draft"]["sha256"] = (
            "sha256:" + "0" * 64
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            result = AUDITOR_MODULE.evaluate(ROOT, path)

        self.assertFalse(result["valid"])
        self.assertFalse(result["checks"]["builder-draft"])

    def test_complete_guard_schema_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output, _, guard = make_fixture(Path(directory))
            cases = []
            missing = copy.deepcopy(guard)
            missing.pop("eventRef")
            cases.append(missing)
            extra = copy.deepcopy(guard)
            extra["commit"] = guard["headCommit"]
            cases.append(extra)
            authorized = copy.deepcopy(guard)
            authorized["authorized"] = True
            cases.append(authorized)
            inconsistent = copy.deepcopy(guard)
            inconsistent["authorizationEligible"] = True
            cases.append(inconsistent)
            for candidate in cases:
                with self.subTest(keys=set(candidate)):
                    result = MODULE.build_staging(
                        root, output, guard_result=candidate
                    )
                    self.assertFalse(result["valid"])
                    self.assertEqual(result["status"], "failed")
                    self.assertFalse(result["authorizationGranted"])
            self.assertEqual(list(output.iterdir()), [])

    def test_guard_snapshot_is_revalidated_as_a_whole(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output, _, guard = make_fixture(Path(directory))
            tampered = copy.deepcopy(guard)
            tampered["packageSnapshot"]["files"][0]["sha256"] = (
                "sha256:" + "0" * 64
            )
            tampered["packageSnapshot"]["packageDigest"] = (
                MODULE.GUARD.canonical_package_digest(
                    tampered["skillPath"],
                    tampered["packageSnapshot"]["treeOid"],
                    tampered["packageSnapshot"]["files"],
                )
            )
            result = MODULE.build_staging(root, output, guard_result=tampered)
            self.assertFalse(result["valid"])
            self.assertIn("does not match pinned Git", result["errors"][0])
            self.assertEqual(list(output.iterdir()), [])

    def test_forged_file_paths_and_incomplete_real_push_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output, _, guard = make_fixture(Path(directory))
            absolute = copy.deepcopy(guard)
            absolute["packageSnapshot"]["files"][0]["path"] = "/escape"
            absolute["packageSnapshot"]["packageDigest"] = (
                MODULE.GUARD.canonical_package_digest(
                    absolute["skillPath"],
                    absolute["packageSnapshot"]["treeOid"],
                    absolute["packageSnapshot"]["files"],
                )
            )
            absolute_result = MODULE.build_staging(
                root,
                output,
                guard_result=absolute,
            )

            forged_push = copy.deepcopy(guard)
            forged_push.update(
                {
                    "eventName": "push",
                    "ref": MODULE.GUARD.PRODUCTION_REF,
                    "dryRun": False,
                    "changedOnly": True,
                    "authorizationEligible": True,
                    "baseCommit": None,
                    "eventBefore": None,
                    "eventSha": forged_push["headCommit"],
                    "eventRef": MODULE.GUARD.PRODUCTION_REF,
                }
            )
            forged_push_result = MODULE.build_staging(
                root,
                output,
                guard_result=forged_push,
            )

        self.assertFalse(absolute_result["valid"])
        self.assertIn("package file is invalid", absolute_result["errors"][0])
        self.assertFalse(forged_push_result["valid"])
        self.assertIn(
            "trusted event boundaries",
            forged_push_result["errors"][0],
        )

    def test_guard_commit_must_remain_checked_out_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output, _, guard = make_fixture(Path(directory))
            (root / "later.txt").write_text("later\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "later"],
                cwd=root,
                check=True,
            )
            result = MODULE.build_staging(root, output, guard_result=guard)

        self.assertFalse(result["valid"])
        self.assertIn("checked-out HEAD", result["errors"][0])

    def test_build_uses_pinned_blobs_and_seals_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output, skill, guard = make_fixture(Path(directory))
            (skill / "SKILL.md").write_text(
                "attacker worktree bytes\n", encoding="utf-8"
            )
            (skill / "ignored.tmp").write_text("untracked\n", encoding="utf-8")
            result = MODULE.build_staging(root, output, guard_result=guard)
            try:
                self.assertTrue(result["valid"], result["errors"])
                self.assertEqual(result["status"], "committed")
                self.assertFalse(result["authorizationGranted"])
                final = output / result["outputName"]
                self.assertEqual(
                    (final / "package" / "SKILL.md").read_text(encoding="utf-8"),
                    "committed body\n",
                )
                self.assertFalse((final / "package" / "ignored.tmp").exists())
                manifest = json.loads(
                    (final / "manifest.json").read_text(encoding="utf-8")
                )
                self.assertEqual(manifest, result["manifest"])
                self.assertEqual(
                    manifest["guardResultDigest"], MODULE.sha256_json(guard)
                )
                descriptor = MODULE.artifact_descriptor(
                    manifest["guardResultDigest"],
                    guard["headCommit"],
                    guard["skillPath"],
                    guard["packageSnapshot"],
                )
                self.assertEqual(
                    manifest["artifactDigest"], MODULE.sha256_json(descriptor)
                )
                self.assertFalse(manifest["authorizationGranted"])
                self.assertEqual(mode(final), 0o555)
                self.assertEqual(mode(final / "package"), 0o555)
                self.assertEqual(mode(final / "package" / "references"), 0o555)
                self.assertEqual(mode(final / "manifest.json"), 0o444)
                self.assertEqual(mode(final / "package" / "SKILL.md"), 0o444)
                self.assertEqual(
                    mode(final / "package" / "references" / "check.py"), 0o555
                )
                for key, replacement in (
                    ("authorizationGranted", True),
                    ("worktreeRead", True),
                    ("researchStatus", "deployment-ready"),
                    ("format", "unknown"),
                ):
                    changed = copy.deepcopy(manifest)
                    changed[key] = replacement
                    with self.subTest(manifest_field=key):
                        with self.assertRaisesRegex(
                            ValueError,
                            "security declarations|artifactDigest",
                        ):
                            MODULE.validate_manifest(changed)
            finally:
                clear_output(output)

    def test_random_mkdirat_and_rename_use_the_verified_parent_fd(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output, _, guard = make_fixture(Path(directory))
            actual = MODULE.native_rename_noreplace
            calls = []

            def recording(parent_fd, source, destination):
                calls.append((parent_fd, source, destination))
                self.assertTrue(source.startswith(".immutable-staging-"))
                self.assertNotIn("/", source)
                self.assertNotIn("/", destination)
                return actual(parent_fd, source, destination)

            with mock.patch.object(
                MODULE, "native_rename_noreplace", side_effect=recording
            ):
                result = MODULE.build_staging(root, output, guard_result=guard)
            try:
                self.assertTrue(result["valid"], result["errors"])
                self.assertEqual(len(calls), 1)
                self.assertGreaterEqual(calls[0][0], 0)
            finally:
                clear_output(output)

    def test_existing_destination_is_preserved_and_temp_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output, _, guard = make_fixture(Path(directory))
            first = MODULE.build_staging(root, output, guard_result=guard)
            before = (
                output / first["outputName"] / "manifest.json"
            ).read_bytes()
            second = MODULE.build_staging(root, output, guard_result=guard)
            try:
                self.assertTrue(first["valid"])
                self.assertFalse(second["valid"])
                self.assertFalse(second["created"])
                self.assertEqual(
                    (
                        output / first["outputName"] / "manifest.json"
                    ).read_bytes(),
                    before,
                )
                self.assertFalse(
                    any(
                        item.name.startswith(".immutable-staging-")
                        for item in output.iterdir()
                    )
                )
            finally:
                clear_output(output)

    def test_post_rename_fsync_failure_is_uncertain_and_retains_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output, _, guard = make_fixture(Path(directory))
            actual_rename = MODULE.native_rename_noreplace
            actual_fsync = MODULE.os.fsync
            state = {"renamed": False, "parent_fd": None}

            def rename(parent_fd, source, destination):
                actual_rename(parent_fd, source, destination)
                state["parent_fd"] = parent_fd
                state["renamed"] = True

            def fsync(descriptor):
                if state["renamed"] and descriptor == state["parent_fd"]:
                    raise OSError("simulated parent fsync failure")
                return actual_fsync(descriptor)

            with mock.patch.object(
                MODULE, "native_rename_noreplace", side_effect=rename
            ), mock.patch.object(MODULE.os, "fsync", side_effect=fsync):
                result = MODULE.build_staging(root, output, guard_result=guard)
            try:
                self.assertFalse(result["valid"])
                self.assertTrue(result["created"])
                self.assertEqual(result["status"], "commit-uncertain")
                self.assertFalse(result["authorizationGranted"])
                self.assertTrue((output / result["outputName"]).is_dir())
                self.assertEqual(len(list(output.iterdir())), 1)
            finally:
                clear_output(output)

    def test_post_rename_same_fd_review_failure_is_commit_uncertain(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output, _, guard = make_fixture(Path(directory))
            actual_review = MODULE.review_package_fd
            calls = 0

            def fail_fourth_review(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 4:
                    raise ValueError("simulated post-rename drift")
                return actual_review(*args, **kwargs)

            with mock.patch.object(
                MODULE,
                "review_package_fd",
                side_effect=fail_fourth_review,
            ):
                result = MODULE.build_staging(
                    root,
                    output,
                    guard_result=guard,
                )
            try:
                self.assertEqual(calls, 4)
                self.assertFalse(result["valid"])
                self.assertTrue(result["created"])
                self.assertEqual(result["status"], "commit-uncertain")
                self.assertTrue((output / result["outputName"]).is_dir())
            finally:
                clear_output(output)

    def test_pre_rename_failure_cleans_only_random_temporary_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output, _, guard = make_fixture(Path(directory))
            with mock.patch.object(
                MODULE,
                "native_rename_noreplace",
                side_effect=OSError("rename denied"),
            ):
                result = MODULE.build_staging(root, output, guard_result=guard)
            self.assertFalse(result["valid"])
            self.assertFalse(result["created"])
            self.assertEqual(result["status"], "failed")
            self.assertEqual(list(output.iterdir()), [])

    def test_cleanup_failure_is_reported_with_residue_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output, _, guard = make_fixture(Path(directory))
            with mock.patch.object(
                MODULE,
                "native_rename_noreplace",
                side_effect=OSError("rename denied"),
            ), mock.patch.object(
                MODULE,
                "remove_tree_at",
                return_value=False,
            ):
                result = MODULE.build_staging(
                    root,
                    output,
                    guard_result=guard,
                )
            try:
                self.assertFalse(result["valid"])
                self.assertFalse(result["created"])
                self.assertEqual(result["status"], "failed-with-residue")
                self.assertTrue(
                    result["residueName"].startswith(".immutable-staging-")
                )
                self.assertTrue((output / result["residueName"]).is_dir())
            finally:
                clear_output(output)

    def test_random_directory_open_failure_removes_allocated_name(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve()
            os.chmod(output, 0o700)
            parent_fd = os.open(
                output,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
            actual_open = MODULE.os.open

            def fail_random_open(path, *args, **kwargs):
                if (
                    isinstance(path, str)
                    and path.startswith(".immutable-staging-")
                ):
                    raise OSError("simulated open failure")
                return actual_open(path, *args, **kwargs)

            try:
                with mock.patch.object(
                    MODULE.os,
                    "open",
                    side_effect=fail_random_open,
                ):
                    with self.assertRaisesRegex(
                        OSError,
                        "simulated open failure",
                    ):
                        MODULE.random_mkdirat(parent_fd)
            finally:
                os.close(parent_fd)
            self.assertEqual(list(output.iterdir()), [])

    def test_head_change_during_staging_is_rejected_and_cleaned(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output, _, guard = make_fixture(Path(directory))
            original = MODULE.GUARD.head_package_snapshot
            calls = 0

            def move_head_after_second_snapshot(*args, **kwargs):
                nonlocal calls
                snapshot = original(*args, **kwargs)
                calls += 1
                if calls == 2:
                    (root / "later.txt").write_text("later\n", encoding="utf-8")
                    subprocess.run(["git", "add", "."], cwd=root, check=True)
                    subprocess.run(
                        ["git", "commit", "-qm", "move head"],
                        cwd=root,
                        check=True,
                    )
                return snapshot

            with mock.patch.object(
                MODULE.GUARD,
                "head_package_snapshot",
                side_effect=move_head_after_second_snapshot,
            ):
                result = MODULE.build_staging(
                    root,
                    output,
                    guard_result=guard,
                )

        self.assertEqual(calls, 2)
        self.assertFalse(result["valid"])
        self.assertFalse(result["created"])
        self.assertIn("HEAD changed", result["errors"][0])

    def test_output_parent_is_component_nofollow_and_outside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            root, output, _, guard = make_fixture(workspace)
            public = workspace / "public"
            public.mkdir(mode=0o755)
            alias = workspace / "alias"
            alias.symlink_to(output, target_is_directory=True)
            inside = root / "staging"
            inside.mkdir(mode=0o700)
            cases = (
                (Path("relative"), "absolute"),
                (public, "private"),
                (alias, "opened safely"),
                (inside, "outside"),
            )
            for parent, expected in cases:
                with self.subTest(parent=parent):
                    result = MODULE.build_staging(
                        root, parent, guard_result=guard
                    )
                    self.assertFalse(result["valid"])
                    self.assertIn(expected, result["errors"][0])

    def test_strict_guard_json_loader_rejects_duplicate_keys_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            source = workspace / "guard.json"
            source.write_text('{"schemaVersion":2,"schemaVersion":2}', encoding="utf-8")
            source.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "duplicate key"):
                MODULE.load_guard_result(source)
            alias = workspace / "alias.json"
            alias.symlink_to(source)
            with self.assertRaisesRegex(ValueError, "strict JSON"):
                MODULE.load_guard_result(alias)
            source.write_text("{}", encoding="utf-8")
            source.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private"):
                MODULE.load_guard_result(source)

    def test_malformed_nested_guard_types_fail_structurally(self):
        with tempfile.TemporaryDirectory() as directory:
            root, output, _, guard = make_fixture(Path(directory))
            for value in (None, 1, []):
                malformed = copy.deepcopy(guard)
                malformed["packageSnapshot"]["treeOid"] = value
                with self.subTest(tree_oid=value):
                    result = MODULE.build_staging(
                        root,
                        output,
                        guard_result=malformed,
                    )
                    self.assertFalse(result["valid"])
                    self.assertEqual(result["status"], "failed")
                    self.assertFalse(result["authorizationGranted"])

    def test_cli_accepts_only_guard_result_json_and_stays_offline(self):
        source = BUILDER.read_text(encoding="utf-8")
        for forbidden in (
            "shutil", "tempfile", "os.walk", "requests", "urllib", "socket.",
            "os.replace(", "os.rename(", "shell=True", "clawhub ",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertNotIn("--commit", source)
        self.assertNotIn("--skill-path", source)
        self.assertNotIn("--package-digest", source)
        completed = subprocess.run(
            [sys.executable, str(BUILDER)],
            check=False, capture_output=True, text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["authorizationGranted"])
        self.assertEqual(completed.stderr, "")

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            root, output, _, guard = make_fixture(workspace)
            guard_path = workspace / "guard-result.json"
            guard_path.write_text(json.dumps(guard), encoding="utf-8")
            guard_path.chmod(0o600)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(BUILDER),
                    "--repo-root",
                    str(root),
                    "--output-parent",
                    str(output),
                    "--guard-result",
                    str(guard_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            result = json.loads(completed.stdout)
            try:
                self.assertEqual(completed.returncode, 0, result["errors"])
                self.assertTrue(result["valid"])
                self.assertEqual(result["status"], "committed")
                self.assertFalse(result["authorizationGranted"])
                self.assertNotIn("outputPath", result)
                self.assertEqual(
                    set(result),
                    {
                        "schemaVersion",
                        "valid",
                        "status",
                        "researchStatus",
                        "created",
                        "authorizationGranted",
                        "outputName",
                        "residueName",
                        "manifest",
                        "errors",
                    },
                )
                self.assertEqual(completed.stderr, "")
            finally:
                clear_output(output)


if __name__ == "__main__":
    unittest.main()
