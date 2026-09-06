import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).parents[1]
RESEARCH = ROOT / "research" / "skill-release-authorization-vnext"
CONSUMER = RESEARCH / "trusted_artifact_publish_consumer.py"
AUDITOR = RESEARCH / "check_trusted_artifact_publish_consumer_contract.py"
CONTRACT = RESEARCH / "trusted-artifact-publish-consumer-contract.json"
SPEC = importlib.util.spec_from_file_location(
    "trusted_artifact_publish_consumer", CONSUMER
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
AUDITOR_SPEC = importlib.util.spec_from_file_location(
    "check_trusted_artifact_publish_consumer_contract", AUDITOR
)
AUDITOR_MODULE = importlib.util.module_from_spec(AUDITOR_SPEC)
assert AUDITOR_SPEC.loader is not None
AUDITOR_SPEC.loader.exec_module(AUDITOR_MODULE)


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def git(root, *args, text=True):
    completed = subprocess.run(
        ["/usr/bin/git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=text,
    )
    return completed.stdout.strip() if text else completed.stdout


def initialize_checkout(root: Path, files: dict[str, bytes]) -> str:
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture")
    commit = git(root, "rev-parse", "HEAD")
    git(
        root, "remote", "add", "origin",
        "https://github.com/bonniegeng-max/openclaw-publisher.git",
    )
    git(root, "update-ref", "refs/remotes/origin/main", commit)
    git(root, "branch", "--set-upstream-to", "origin/main", "main")
    return commit


def initialize_candidate(root: Path, slug: str, files: dict[str, bytes]):
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    (root / "seed").write_text("seed\n", encoding="utf-8")
    git(root, "add", "seed")
    git(root, "commit", "-qm", "base")
    base = git(root, "rev-parse", "HEAD")
    for path, content in files.items():
        target = root / "skills" / slug / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    git(root, "add", ".")
    git(root, "commit", "-qm", "candidate")
    candidate = git(root, "rev-parse", "HEAD")
    authorization = root / ".clawhub" / "skill-release-authorization.json"
    authorization.parent.mkdir()
    authorization.write_text("{}\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "authorization")
    head = git(root, "rev-parse", "HEAD")
    git(
        root, "remote", "add", "origin",
        "https://github.com/bonniegeng-max/openclaw-publisher.git",
    )
    git(root, "update-ref", "refs/remotes/origin/main", head)
    git(root, "branch", "--set-upstream-to", "origin/main", "main")
    return base, candidate, head


def control_evidence(root: Path, commit: str, paths, *, include_mode: bool):
    result = {}
    for label, relative in paths.items():
        record = git(root, "ls-tree", commit, "--", relative)
        metadata, observed = record.split("\t", 1)
        mode, kind, oid = metadata.split()
        assert kind == "blob" and observed == relative
        blob = git(root, "cat-file", "blob", oid, text=False)
        item = {
            "path": relative,
            "blobOid": oid,
            "sha256": "sha256:" + hashlib.sha256(blob).hexdigest(),
        }
        if include_mode:
            item["mode"] = mode
        result[label] = item
    return result


def make_fixture(parent: Path):
    slug = "demo-skill"
    version = "1.2.3"
    file_bytes = {
        ".clawhubignore": b".DS_Store\n",
        "CHANGELOG.md": b"# Changes\n",
        "SKILL.md": (
            b"---\nname: demo-skill\ndescription: Demo\nversion: 1.2.3\n---\n"
            b"# Demo\n"
        ),
        "references/note.md": b"note\n",
    }
    candidate = parent / "candidate"
    control = parent / "control"
    base_commit, candidate_commit, commit = initialize_candidate(
        candidate, slug, file_bytes
    )
    control_files = {
        **{
            path: (ROOT / path).read_bytes()
            for path in MODULE.PREFLIGHT_CONTROL_FILES.values()
        },
        **{
            path: (ROOT / path).read_bytes()
            for path in MODULE.STAGING_CONTROL_FILES.values()
        },
    }
    control_commit = initialize_checkout(control, control_files)
    files = []
    package_files = []
    index_records = {
        record.split("\t", 1)[1]: record.split("\t", 1)[0].split()
        for record in git(
            candidate, "ls-tree", "-r", commit, "--", f"skills/{slug}"
        ).splitlines()
    }
    for path, data in sorted(file_bytes.items()):
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        mode, kind, blob = index_records[f"skills/{slug}/{path}"]
        assert kind == "blob"
        files.append({
            "path": path,
            "sourceMode": mode,
            "artifactMode": "0555" if mode == "100755" else "0444",
            "blobOid": blob,
            "sha256": digest,
        })
        package_files.append({
            "path": path,
            "mode": mode,
            "blobOid": blob,
            "sha256": digest,
        })
    package_payload = {
        "files": package_files,
        "format": "safe-publish-package-v1",
        "skillPath": f"skills/{slug}",
        "treeOid": git(candidate, "rev-parse", f"{commit}:skills/{slug}"),
    }
    descriptor = {
        "schemaVersion": 2,
        "researchStatus": "research-only-not-wired",
        "format": "immutable-skill-staging-v2",
        "guardResultDigest": "sha256:" + "c" * 64,
        "source": {
            "commit": commit,
            "skillPath": f"skills/{slug}",
            "treeOid": package_payload["treeOid"],
            "packageDigest": (
                "sha256:" + hashlib.sha256(canonical(package_payload)).hexdigest()
            ),
        },
        "packageDirectory": "package",
        "files": files,
        "worktreeRead": False,
        "authorizationGranted": False,
    }
    manifest = {
        **descriptor,
        "artifactDigest": (
            "sha256:" + hashlib.sha256(canonical(descriptor)).hexdigest()
        ),
    }
    output_name = f"{slug}-{commit[:12]}-{manifest['artifactDigest'][7:19]}"
    artifact = parent / output_name
    package = artifact / "package"
    package.mkdir(parents=True)
    for path, data in file_bytes.items():
        target = package / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o444)
    for directory in sorted(
        [item for item in package.rglob("*") if item.is_dir()],
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        directory.chmod(0o555)
    package.chmod(0o555)
    (artifact / "manifest.json").write_bytes(canonical(manifest))
    (artifact / "manifest.json").chmod(0o444)
    artifact.chmod(0o555)
    staging = {
        "schemaVersion": 2,
        "valid": True,
        "status": "committed",
        "researchStatus": "research-only-not-wired",
        "created": True,
        "authorizationGranted": False,
        "outputName": output_name,
        "residueName": None,
        "manifest": manifest,
        "errors": [],
        "launcherObservations": {
            "isolatedModeObserved": True,
            "childEnvironmentAllowlisted": True,
            "controlCommit": control_commit,
            "controlFiles": control_evidence(
                control, control_commit, MODULE.STAGING_CONTROL_FILES,
                include_mode=True,
            ),
            "sameControlCommit": True,
            "guardAndBuilderSeparated": True,
            "guardResultDigestVerified": True,
            "independentCheckouts": True,
            "inMemoryFraming": "trusted-staging-v1",
            "timeoutSeconds": 180,
            "artifactVerification": {
                "manifestMatched": True,
                "artifactDigestVerified": True,
                "fileCount": len(files),
                "contentBytes": sum(len(item) for item in file_bytes.values()),
            },
            "artifactVerificationSemantics":
                "final-snapshot-consumer-must-revalidate",
            "formalWorkflowWired": False,
        },
        "artifactState": "present-verified-snapshot",
    }
    catalog = {
        f"skills/{slug}": {
            "displayName": "Demo Skill",
            "categories": ["development"],
            "topics": ["demo"],
        }
    }
    content_hasher = hashlib.sha256()
    MODULE.update_digest(
        content_hasher,
        f"skills/{slug}#catalog",
        canonical(catalog[f"skills/{slug}"]),
    )
    for path, data in sorted(file_bytes.items()):
        MODULE.update_digest(content_hasher, f"skills/{slug}/{path}", data)
    authorization = {
        "valid": True,
        "authorized": True,
        "mode": "dry-run",
        "evaluatedAt": datetime.now(timezone.utc).isoformat(),
        "releaseId": f"{slug}-{version}",
        "baseCommit": base_commit,
        "candidateCommit": candidate_commit,
        "headCommit": commit,
        "targets": [{"slug": slug, "version": version}],
        "catalogChanged": False,
        "contentDigest": "sha256:" + content_hasher.hexdigest(),
        "changeSetDigest": "sha256:" + "2" * 64,
        "authorizationChanged": True,
        "blockingReasons": [],
        "errors": [],
        "trustedControl": {
            "repository": MODULE.EXPECTED_REPOSITORY,
            "commit": control_commit,
            "files": control_evidence(
                control, control_commit, MODULE.PREFLIGHT_CONTROL_FILES,
                include_mode=False,
            ),
            "independentCheckout": True,
            "executingCheckerPathMatched": True,
        },
        "launcherObservations": dict(MODULE.PREFLIGHT_OBSERVATIONS),
    }
    return authorization, staging, catalog, file_bytes


def consume_fixture(authorization, staging, catalog, parent):
    return MODULE.consume(
        authorization,
        staging,
        catalog,
        parent,
        parent / "candidate",
        parent / "control",
        authorization["trustedControl"]["commit"],
        authorization["headCommit"],
    )


def simulator_binding(authorization, staging, catalog):
    target = authorization["targets"][0]
    return {
        "slug": target["slug"],
        "version": target["version"],
        **MODULE.validate_catalog(catalog, target["slug"]),
        "files": [
            {
                "path": item["path"],
                "artifactMode": item["artifactMode"],
                "sha256": item["sha256"],
            }
            for item in staging["manifest"]["files"]
        ],
    }


class TrustedArtifactPublishConsumerTests(unittest.TestCase):
    def test_consume_jointly_validates_and_only_simulates_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = make_fixture(parent)
            result = consume_fixture(authorization, staging, catalog, parent)
        self.assertTrue(result["valid"])
        self.assertEqual(result["status"], "simulated")
        self.assertTrue(result["packageFdPreserved"])
        self.assertEqual(result["cliMode"], "simulation-only")
        self.assertFalse(result["networkUsed"])
        self.assertFalse(result["credentialsAccepted"])
        self.assertFalse(result["publicationAttempted"])
        self.assertTrue(result["candidateCheckoutVerified"])
        self.assertTrue(result["controlCheckoutVerified"])
        self.assertEqual(result["authorizationFreshnessSeconds"], 900)
        self.assertTrue(result["authorizationContentValidated"])
        self.assertNotIn("authorizationValidated", result)
        self.assertFalse(result["oneTimeRunReplayProtection"])
        self.assertFalse(result["authorizationProvenanceVerified"])
        self.assertEqual(
            result["authorizationProvenance"],
            "content-validated-self-asserted-input-not-launcher-attested",
        )
        self.assertFalse(result["realMutationAllowed"])
        self.assertEqual(
            result["trustUpgradeRequired"],
            "external-launcher-pinned-to-verified-control-blob",
        )
        self.assertEqual(result["displayName"], "Demo Skill")
        self.assertEqual(result["categories"], ["development"])
        self.assertEqual(result["topics"], ["demo"])

    def test_verified_package_fd_survives_path_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, files = make_fixture(parent)
            binding = simulator_binding(authorization, staging, catalog)
            verified = MODULE.open_verified_package(parent, staging)
            package_fd, snapshots = verified.package_fd, verified.snapshots
            artifact = parent / staging["outputName"]
            artifact.rename(parent / ".original")
            replacement = parent / staging["outputName"]
            replacement.mkdir(mode=0o755)
            (replacement / "package").mkdir()
            (replacement / "package" / "SKILL.md").write_text(
                "malicious\n", encoding="utf-8"
            )
            try:
                observed = MODULE.run_simulator(package_fd, binding)
            finally:
                with self.assertRaisesRegex(ValueError, "FD metadata changed"):
                    verified.revalidate_all()
                verified.close()
            self.assertTrue(observed["allManifestFilesVerified"])
            self.assertEqual(observed["manifestFileCount"], len(files))
            self.assertEqual(snapshots["SKILL.md"], files["SKILL.md"])

    def test_commit_slug_version_and_catalog_mismatches_fail_closed(self):
        mutations = (
            ("commit", lambda auth, staging, catalog: staging["manifest"]["source"].__setitem__("commit", "f" * 40)),
            ("slug", lambda auth, staging, catalog: staging["manifest"]["source"].__setitem__("skillPath", "skills/other")),
            ("version", lambda auth, staging, catalog: auth["targets"][0].__setitem__("version", "9.9.9")),
            ("catalog", lambda auth, staging, catalog: catalog.clear()),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory).resolve()
                os.chmod(parent, 0o700)
                authorization, staging, catalog, _ = make_fixture(parent)
                mutate(authorization, staging, catalog)
                with self.assertRaises(ValueError):
                    consume_fixture(authorization, staging, catalog, parent)

    def test_content_digest_binds_target_catalog_entry_and_every_file(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = make_fixture(parent)
            catalog["skills/demo-skill"]["topics"] = ["changed"]
            with self.assertRaisesRegex(ValueError, "contentDigest"):
                consume_fixture(authorization, staging, catalog, parent)

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = make_fixture(parent)
            authorization["contentDigest"] = "sha256:" + "0" * 64
            with self.assertRaisesRegex(ValueError, "contentDigest"):
                consume_fixture(authorization, staging, catalog, parent)

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            _, staging, _, _ = make_fixture(parent)
            verified = MODULE.open_verified_package(parent, staging)
            try:
                incomplete = dict(verified.snapshots)
                incomplete.pop("references/note.md")
                with self.assertRaisesRegex(ValueError, "every manifest file"):
                    MODULE.recompute_content_digest(
                        "demo-skill",
                        {
                            "displayName": "Demo Skill",
                            "categories": ["development"],
                            "topics": ["demo"],
                        },
                        staging["manifest"],
                        incomplete,
                    )
            finally:
                verified.close()

    def test_simulator_rejects_non_skill_manifest_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = make_fixture(parent)
            verified = MODULE.open_verified_package(parent, staging)
            try:
                os.chmod("references/note.md", 0o644, dir_fd=verified.package_fd)
                descriptor = os.open(
                    "references/note.md",
                    os.O_WRONLY | os.O_TRUNC,
                    dir_fd=verified.package_fd,
                )
                try:
                    os.write(descriptor, b"changed\n")
                finally:
                    os.close(descriptor)
                os.chmod("references/note.md", 0o444, dir_fd=verified.package_fd)
                with self.assertRaisesRegex(
                    ValueError, "simulator failed"
                ):
                    MODULE.run_simulator(
                        verified.package_fd,
                        simulator_binding(authorization, staging, catalog),
                    )
            finally:
                verified.close()

    def test_authorization_catalog_changed_and_evaluated_at_types_are_strict(self):
        mutations = (
            ("catalogChanged", 0),
            ("catalogChanged", "false"),
            ("evaluatedAt", None),
            ("evaluatedAt", ""),
        )
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                with tempfile.TemporaryDirectory() as directory:
                    parent = Path(directory).resolve()
                    os.chmod(parent, 0o700)
                    authorization, staging, catalog, _ = make_fixture(parent)
                    authorization[field] = value
                    with self.assertRaisesRegex(ValueError, field):
                        consume_fixture(
                            authorization, staging, catalog, parent
                        )

    def test_authorization_freshness_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = make_fixture(parent)
            authorization["evaluatedAt"] = (
                datetime.now(timezone.utc) - timedelta(minutes=16)
            ).isoformat()
            with self.assertRaisesRegex(ValueError, "freshness"):
                consume_fixture(authorization, staging, catalog, parent)

    def test_forged_provenance_and_replay_claims_cannot_enable_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = make_fixture(parent)
            for field in (
                "authorizationProvenanceVerified",
                "oneTimeRunReplayProtection",
                "realMutationAllowed",
            ):
                forged = copy.deepcopy(authorization)
                forged[field] = True
                with self.subTest(field=field), self.assertRaisesRegex(
                    ValueError, "authorization fields"
                ):
                    consume_fixture(forged, staging, catalog, parent)
            result = consume_fixture(authorization, staging, catalog, parent)
            self.assertEqual(result["status"], "simulated")
            self.assertFalse(result["authorizationProvenanceVerified"])
            self.assertFalse(result["oneTimeRunReplayProtection"])
            self.assertFalse(result["realMutationAllowed"])

    def test_git_checkout_manifest_and_control_evidence_are_revalidated(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = make_fixture(parent)
            git(parent / "candidate", "remote", "set-url", "origin",
                "https://github.com/example/not-trusted.git")
            with self.assertRaisesRegex(ValueError, "origin"):
                consume_fixture(authorization, staging, catalog, parent)

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = make_fixture(parent)
            staging["launcherObservations"]["controlFiles"]["guard"].pop("mode")
            with self.assertRaisesRegex(ValueError, "malformed"):
                consume_fixture(authorization, staging, catalog, parent)

    def test_git_common_directory_alternates_and_object_metadata_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, _, _, _ = make_fixture(parent)
            candidate = parent / "candidate"
            alternates = candidate / ".git" / "objects" / "info" / "alternates"
            alternates.write_text(
                str(parent / "control" / ".git" / "objects") + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "alternates"):
                MODULE.verify_checkout(
                    candidate, authorization["headCommit"], "candidate"
                )

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, _, _, _ = make_fixture(parent)
            candidate = parent / "candidate"
            loose = next(
                path for path in (candidate / ".git" / "objects").glob("*/*")
                if path.is_file() and path.parent.name != "info"
            )
            linked = candidate / ".git" / "object-hardlink"
            os.link(loose, linked)
            try:
                with self.assertRaisesRegex(ValueError, "object store file is unsafe"):
                    MODULE.verify_checkout(
                        candidate, authorization["headCommit"], "candidate"
                    )
            finally:
                linked.unlink()

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, _, _, _ = make_fixture(parent)
            candidate = parent / "candidate"
            objects = candidate / ".git" / "objects"
            original = candidate / ".git" / "objects-private"
            objects.rename(original)
            objects.symlink_to(original, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "opened safely"):
                MODULE.verify_checkout(
                    candidate, authorization["headCommit"], "candidate"
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repository"
            commit = initialize_checkout(root, {"tracked": b"value\n"})
            worktree = (Path(directory) / "linked-worktree").resolve()
            git(root, "worktree", "add", "-q", "-b", "linked", str(worktree))
            with self.assertRaisesRegex(ValueError, "object store"):
                MODULE.verify_checkout(worktree, commit, "linked")

    def test_run_git_streams_ten_mib_blob_and_enforces_wall_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git(root, "init", "-q", "-b", "main")
            payload = b"x" * (10 * 1024 * 1024)
            hashed = subprocess.run(
                ["/usr/bin/git", "hash-object", "-w", "--stdin"],
                cwd=root,
                input=payload,
                capture_output=True,
                check=True,
            )
            oid = hashed.stdout.decode("ascii").strip()
            observed = MODULE.run_git(root, "cat-file", "blob", oid)
            self.assertEqual(observed.returncode, 0)
            self.assertEqual(observed.stdout, payload)
            self.assertLessEqual(
                len(observed.stdout) + len(observed.stderr),
                MODULE.MAX_GIT_OUTPUT_BYTES,
            )

            sleeper = root / "trusted-git-test"
            sleeper.write_text("#!/bin/sh\n/bin/sleep 10\n", encoding="utf-8")
            sleeper.chmod(0o700)
            with mock.patch.object(
                MODULE, "TRUSTED_GIT_ENTRY", sleeper
            ), mock.patch.object(MODULE, "GIT_TIMEOUT_SECONDS", 0.05):
                with self.assertRaises(MODULE.ChildTerminationError) as timeout:
                    MODULE.run_git(root, "ignored")
            self.assertEqual(
                timeout.exception.termination["reason"], "trusted-git-timeout"
            )
            self.assertTrue(timeout.exception.termination["leaderReaped"])

            emitter = root / "trusted-git-output-test"
            emitter.write_text(
                "#!/usr/bin/python3\nimport os\nos.write(1, b'x' * 2048)\n",
                encoding="utf-8",
            )
            emitter.chmod(0o700)
            with mock.patch.object(
                MODULE, "TRUSTED_GIT_ENTRY", emitter
            ), mock.patch.object(MODULE, "MAX_GIT_OUTPUT_BYTES", 1024):
                with self.assertRaises(MODULE.ChildTerminationError) as overflow:
                    MODULE.run_git(root, "ignored")
            self.assertEqual(
                overflow.exception.termination["reason"],
                "trusted-git-output-overflow",
            )
            self.assertTrue(overflow.exception.termination["leaderReaped"])

    def test_expected_commits_trusted_control_and_observations_are_strict(self):
        mutations = (
            (
                "authorization-control",
                lambda auth, staging: auth["trustedControl"].__setitem__(
                    "commit", "8" * 40
                ),
            ),
            (
                "authorization-control-files",
                lambda auth, staging: auth["trustedControl"]["files"].pop(
                    "validator"
                ),
            ),
            (
                "preflight-observation",
                lambda auth, staging: auth["launcherObservations"].__setitem__(
                    "isolatedModeObserved", False
                ),
            ),
            (
                "staging-control",
                lambda auth, staging: staging["launcherObservations"].__setitem__(
                    "controlCommit", "8" * 40
                ),
            ),
            (
                "staging-control-files",
                lambda auth, staging: staging["launcherObservations"][
                    "controlFiles"
                ].pop("guard"),
            ),
            (
                "staging-observation",
                lambda auth, staging: staging["launcherObservations"].__setitem__(
                    "sameControlCommit", False
                ),
            ),
            (
                "artifact-observation",
                lambda auth, staging: staging["launcherObservations"][
                    "artifactVerification"
                ].__setitem__("manifestMatched", False),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory).resolve()
                os.chmod(parent, 0o700)
                authorization, staging, catalog, _ = make_fixture(parent)
                mutate(authorization, staging)
                with self.assertRaises(ValueError):
                    consume_fixture(authorization, staging, catalog, parent)

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = make_fixture(parent)
            with self.assertRaisesRegex(ValueError, "expected head"):
                MODULE.consume(
                    authorization, staging, catalog, parent,
                    parent / "candidate", parent / "control",
                    authorization["trustedControl"]["commit"], "7" * 40,
                )

    def test_owner_mode_nlink_inode_and_post_consumption_fd_checks_fail_closed(self):
        for label, mutate in (
            (
                "mode",
                lambda package: (package / "SKILL.md").chmod(0o644),
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory).resolve()
                os.chmod(parent, 0o700)
                authorization, staging, catalog, _ = make_fixture(parent)
                package = parent / staging["outputName"] / "package"
                mutate(package)
                with self.assertRaises(ValueError):
                    consume_fixture(authorization, staging, catalog, parent)

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = make_fixture(parent)
            package = parent / staging["outputName"] / "package"
            package.chmod(0o755)
            os.link(package / "SKILL.md", package / "SKILL-hardlink.md")
            package.chmod(0o555)
            with self.assertRaises(ValueError):
                consume_fixture(authorization, staging, catalog, parent)

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = make_fixture(parent)

            def mutate_after_verification(package_fd, binding):
                os.chmod("SKILL.md", 0o644, dir_fd=package_fd)
                return {
                    "schemaVersion": 1,
                    "simulated": True,
                    "packageFdInherited": True,
                    "allManifestFilesVerified": True,
                    "manifestFileCount": len(staging["manifest"]["files"]),
                    "slug": binding["slug"],
                    "version": binding["version"],
                    "displayName": binding["displayName"],
                    "categories": binding["categories"],
                    "topics": binding["topics"],
                }

            with mock.patch.object(
                MODULE, "run_simulator", side_effect=mutate_after_verification
            ):
                with self.assertRaisesRegex(ValueError, "FD metadata changed"):
                    consume_fixture(authorization, staging, catalog, parent)

    def test_fd_owner_and_read_time_inode_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input"
            path.write_bytes(b"payload")
            path.chmod(0o444)
            descriptor = os.open(path, os.O_RDONLY)
            actual = os.fstat(descriptor)
            os.close(descriptor)

            def changed(**overrides):
                values = {
                    name: getattr(actual, name)
                    for name in dir(actual)
                    if name.startswith("st_")
                }
                values.update(overrides)
                return types.SimpleNamespace(**values)

            original_fstat = os.fstat
            calls = 0

            def inode_race(fd):
                nonlocal calls
                calls += 1
                observed = original_fstat(fd)
                if calls == 2:
                    values = {
                        name: getattr(observed, name)
                        for name in dir(observed)
                        if name.startswith("st_")
                    }
                    values["st_ino"] = observed.st_ino + 1
                    return types.SimpleNamespace(**values)
                return observed

            parent_fd = os.open(directory, os.O_RDONLY)
            try:
                with mock.patch.object(MODULE.os, "fstat", side_effect=inode_race):
                    with self.assertRaisesRegex(
                        ValueError, "changed while being read"
                    ):
                        MODULE.read_open_file_at(
                            parent_fd,
                            "input",
                            0o444,
                            "test input",
                        )
            finally:
                os.close(parent_fd)

            descriptor = os.open(path, os.O_RDONLY)
            try:
                identity = MODULE.metadata_identity(actual)
                verified = MODULE.VerifiedPackage(
                    descriptor,
                    {"test file": b"payload"},
                    {"test file": descriptor},
                    {"test file": identity},
                    {"test file": 0o444},
                    {"test file": "file"},
                )
                with mock.patch.object(
                    MODULE.os,
                    "fstat",
                    return_value=changed(st_uid=actual.st_uid + 1),
                ):
                    with self.assertRaisesRegex(ValueError, "FD metadata changed"):
                        verified.revalidate_all()
            finally:
                os.close(descriptor)

    def test_structured_termination_failure_records_confirmed_reap(self):
        termination = {
            "attempted": True,
            "reason": "timeout",
            "signal": "SIGKILL",
            "processGroupTargeted": True,
            "leaderPid": 123,
            "leaderReaped": True,
            "returnCode": -9,
        }
        result = MODULE.failure("simulator execution timed out", termination)
        self.assertFalse(result["valid"])
        self.assertFalse(result["authorizationContentValidated"])
        self.assertNotIn("authorizationValidated", result)
        self.assertFalse(result["authorizationProvenanceVerified"])
        self.assertEqual(result["termination"], termination)
        self.assertTrue(result["termination"]["leaderReaped"])

    def test_fast_exit_is_reaped_without_racy_killpg(self):
        process = mock.Mock()
        process.pid = 123
        process.poll.return_value = 0
        process.wait.return_value = 0
        with mock.patch.object(MODULE.os, "killpg") as killpg:
            observation = MODULE.terminate(process, "timeout")
        killpg.assert_not_called()
        self.assertFalse(observation["attempted"])
        self.assertFalse(observation["processGroupTargeted"])
        self.assertTrue(observation["leaderReaped"])
        self.assertEqual(observation["returnCode"], 0)

    def test_exit_between_poll_and_killpg_is_not_retried(self):
        process = mock.Mock()
        process.pid = 123
        process.poll.side_effect = [None, 0]
        process.wait.return_value = 0
        with mock.patch.object(
            MODULE.os, "killpg", side_effect=ProcessLookupError
        ) as killpg:
            observation = MODULE.terminate(process, "timeout")
        killpg.assert_called_once_with(123, MODULE.signal.SIGKILL)
        self.assertTrue(observation["attempted"])
        self.assertFalse(observation["processGroupTargeted"])
        self.assertTrue(observation["leaderExitedBeforeSignal"])
        self.assertTrue(observation["leaderReaped"])
        self.assertNotIn("killError", observation)

    def test_invalid_states_and_multiple_targets_are_rejected(self):
        cases = []
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = make_fixture(parent)
            denied = copy.deepcopy(authorization)
            denied["authorized"] = False
            cases.append((denied, staging, catalog))
            publish = copy.deepcopy(authorization)
            publish["mode"] = "publish"
            cases.append((publish, staging, catalog))
            multiple = copy.deepcopy(authorization)
            multiple["targets"].append({"slug": "other", "version": "1.0.0"})
            cases.append((multiple, staging, catalog))
            uncertain = copy.deepcopy(staging)
            uncertain["status"] = "commit-uncertain"
            cases.append((authorization, uncertain, catalog))
            for auth_value, staging_value, catalog_value in cases:
                with self.assertRaises(ValueError):
                    consume_fixture(
                        auth_value, staging_value, catalog_value, parent
                    )

    def test_simulator_is_bounded_and_package_fd_is_explicit(self):
        source = CONSUMER.read_text(encoding="utf-8")
        self.assertIn("pass_fds=(package_fd,)", source)
        self.assertIn("start_new_session=True", source)
        self.assertNotIn("CLAWHUB_TOKEN", source)
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = make_fixture(parent)
            verified = MODULE.open_verified_package(parent, staging)
            package_fd = verified.package_fd
            binding = simulator_binding(authorization, staging, catalog)
            try:
                with mock.patch.object(
                    MODULE, "SIMULATOR", "import time; time.sleep(10)"
                ), mock.patch.object(MODULE, "CHILD_TIMEOUT_SECONDS", 0.05):
                    with self.assertRaises(MODULE.ChildTerminationError) as timeout:
                        MODULE.run_simulator(
                            package_fd,
                            binding,
                        )
                    self.assertTrue(timeout.exception.termination["leaderReaped"])
                    self.assertEqual(
                        timeout.exception.termination["reason"], "timeout"
                    )
                with mock.patch.object(
                    MODULE,
                    "SIMULATOR",
                    "import os; os.write(1, b'x' * 2048)",
                ), mock.patch.object(MODULE, "MAX_CHILD_OUTPUT_BYTES", 1024):
                    with self.assertRaises(
                        MODULE.ChildTerminationError
                    ) as overflow:
                        MODULE.run_simulator(
                            package_fd,
                            binding,
                        )
                    self.assertTrue(overflow.exception.termination["leaderReaped"])
                    self.assertEqual(
                        overflow.exception.termination["reason"],
                        "output-overflow",
                    )
            finally:
                verified.revalidate_all()
                verified.close()

    def test_child_termination_error_is_not_overwritten_by_final_revalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = make_fixture(parent)
            verified = MODULE.open_verified_package(parent, staging)
            termination = {"leaderReaped": True, "reason": "timeout"}
            with mock.patch.object(
                MODULE, "open_verified_package", return_value=verified
            ), mock.patch.object(
                MODULE,
                "run_simulator",
                side_effect=MODULE.ChildTerminationError("primary", termination),
            ), mock.patch.object(
                verified, "revalidate_all", side_effect=ValueError("secondary")
            ):
                with self.assertRaises(MODULE.ChildTerminationError) as observed:
                    consume_fixture(authorization, staging, catalog, parent)
            self.assertEqual(observed.exception.termination, termination)

    def test_cli_requires_isolated_mode_and_contract_audit_is_offline(self):
        completed = subprocess.run(
            [sys.executable, str(CONSUMER)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("isolated mode", json.loads(completed.stdout)["errors"][0])
        audited = subprocess.run(
            [sys.executable, str(AUDITOR), "--repo-root", str(ROOT)],
            check=False,
            capture_output=True,
            text=True,
        )
        result = json.loads(audited.stdout)
        self.assertEqual(audited.returncode, 1, result["errors"])
        self.assertTrue(result["valid"])
        self.assertFalse(result["deploymentReady"])
        self.assertFalse(result["authorizationGranted"])

    def test_isolated_cli_requires_and_checks_expected_control_and_head(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            os.chmod(parent, 0o700)
            authorization, staging, catalog, _ = make_fixture(parent)
            inputs = {}
            for name, value in (
                ("authorization", authorization),
                ("staging", staging),
                ("catalog", catalog),
            ):
                path = parent / f"{name}.json"
                path.write_bytes(canonical(value))
                path.chmod(0o600)
                inputs[name] = path
            command = [
                sys.executable,
                "-I",
                str(CONSUMER),
                "--authorization-result",
                str(inputs["authorization"]),
                "--staging-result",
                str(inputs["staging"]),
                "--catalog",
                str(inputs["catalog"]),
                "--artifact-parent",
                str(parent),
                "--candidate-root",
                str(parent / "candidate"),
                "--control-root",
                str(parent / "control"),
                "--expected-control-commit",
                authorization["trustedControl"]["commit"],
                "--expected-head-commit",
                authorization["headCommit"],
            ]
            completed = subprocess.run(
                command, check=False, capture_output=True, text=True
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertTrue(json.loads(completed.stdout)["valid"])

            command[-1] = "7" * 40
            rejected = subprocess.run(
                command, check=False, capture_output=True, text=True
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn(
                "expected head", json.loads(rejected.stdout)["errors"][0]
            )

    def test_source_and_contract_keep_forbidden_surfaces_absent(self):
        source = CONSUMER.read_text(encoding="utf-8")
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        for forbidden in (
            "requests", "urllib", "socket.", "http://", "https://",
            "CLAWHUB_TOKEN", "GITHUB_TOKEN", "shell=True", "clawhub ",
            ".github/workflows/",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertEqual(contract["status"], "research-only-not-wired")
        self.assertFalse(contract["cliBoundary"]["realCliAllowed"])
        self.assertEqual(
            contract["cliBoundary"]["realCliPackageAccessRequirement"],
            "fd-native-or-read-only-isolated-copy",
        )
        self.assertFalse(
            contract["cliBoundary"]["mutationCapableRealCliAllowed"]
        )
        self.assertFalse(
            contract["artifactBoundary"]["postCheckPreventsPriorMutation"]
        )
        self.assertFalse(contract["evidenceBoundary"]["consumerDeploymentAllowed"])
        self.assertIsNone(contract["consumerEvidence"]["baseline"])
        self.assertIsNone(contract["auditorEvidence"]["baseline"])
        self.assertFalse(contract["twoStageAnchoring"]["localIntegrityPinned"])
        self.assertTrue(
            contract["twoStageAnchoring"][
                "deploymentRemainsBlockedAfterStageTwo"
            ]
        )
        self.assertFalse(
            contract["twoStageAnchoring"]["remoteCommitVerified"]
        )
        self.assertEqual(contract["evidenceBoundary"]["currentLevel"], "E0")
        self.assertFalse(contract["cliBoundary"]["networkCallsPresent"])
        self.assertFalse(contract["formalWorkflowModified"])

    def test_auditor_rejects_stale_draft_sha_and_premature_baseline(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        mutations = (
            lambda value: value["consumerEvidence"]["draft"].__setitem__(
                "sha256", "sha256:" + "0" * 64
            ),
            lambda value: value["auditorEvidence"].__setitem__(
                "baseline", {
                    "path": str(AUDITOR.relative_to(ROOT)),
                    "commit": "1" * 40,
                    "mode": "100644",
                    "blobOid": "2" * 40,
                    "sha256": "sha256:" + "3" * 64,
                }
            ),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as directory:
                candidate = copy.deepcopy(contract)
                mutate(candidate)
                path = Path(directory) / "contract.json"
                path.write_text(json.dumps(candidate), encoding="utf-8")
                result = AUDITOR_MODULE.evaluate(ROOT, path)
                self.assertFalse(result["valid"])
                self.assertFalse(result["deploymentReady"])

    def test_pinned_local_integrity_remains_e0_and_protected_paths_are_checked(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        research_files = contract["repositoryBoundary"]["researchOnlyFiles"]
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "repository"
            commit = initialize_checkout(
                root,
                {
                    relative: (ROOT / relative).read_bytes()
                    for relative in research_files
                },
            )
            pinned = copy.deepcopy(contract)
            for evidence_name, relative in (
                (
                    "consumerEvidence",
                    str(CONSUMER.relative_to(ROOT)),
                ),
                (
                    "auditorEvidence",
                    str(AUDITOR.relative_to(ROOT)),
                ),
            ):
                draft = AUDITOR_MODULE.working_file_evidence(root, relative)
                record = git(root, "ls-tree", commit, "--", relative)
                metadata, observed_path = record.split("\t", 1)
                mode, kind, oid = metadata.split()
                self.assertEqual((kind, observed_path), ("blob", relative))
                pinned[evidence_name] = {
                    "baseline": {
                        "path": relative,
                        "commit": commit,
                        "mode": mode,
                        "blobOid": oid,
                        "sha256": draft["sha256"],
                    },
                    "draft": draft,
                }
            pinned["twoStageAnchoring"]["localIntegrityPinned"] = True
            pinned["evidenceBoundary"]["consumerBaselinePinned"] = True
            pinned["evidenceBoundary"]["auditorBaselinePinned"] = True
            self.assertEqual(pinned["evidenceBoundary"]["currentLevel"], "E0")
            pinned_path = parent / "pinned-contract.json"
            pinned_path.write_text(json.dumps(pinned), encoding="utf-8")
            result = AUDITOR_MODULE.evaluate(root, pinned_path)
            self.assertTrue(result["valid"], result["errors"])
            self.assertFalse(result["deploymentReady"])

            overstated = copy.deepcopy(pinned)
            overstated["evidenceBoundary"]["currentLevel"] = "E1"
            pinned_path.write_text(json.dumps(overstated), encoding="utf-8")
            result = AUDITOR_MODULE.evaluate(root, pinned_path)
            self.assertFalse(result["valid"])
            self.assertFalse(result["deploymentReady"])

        relative = "AGENTS.md"
        commit = git(ROOT, "rev-parse", "HEAD")
        record = git(ROOT, "ls-tree", commit, "--", relative)
        metadata, observed_path = record.split("\t", 1)
        mode, kind, oid = metadata.split()
        self.assertEqual((kind, observed_path), ("blob", relative))
        draft = AUDITOR_MODULE.working_file_evidence(ROOT, relative)
        baseline = {
            "path": relative,
            "commit": commit,
            "mode": mode,
            "blobOid": oid,
            "sha256": draft["sha256"],
        }
        self.assertTrue(
            AUDITOR_MODULE.baseline_evidence_matches(
                ROOT, baseline, relative, draft
            )
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git(root, "init", "-q", "-b", "main")
            git(root, "config", "user.email", "test@example.invalid")
            git(root, "config", "user.name", "Test")
            (root / "seed").write_text("seed\n", encoding="utf-8")
            git(root, "add", "seed")
            git(root, "commit", "-qm", "seed")
            (root / "skills").mkdir()
            (root / "skills" / "untracked.txt").write_text(
                "untracked\n", encoding="utf-8"
            )
            self.assertFalse(AUDITOR_MODULE.protected_paths_unchanged(root))


if __name__ == "__main__":
    unittest.main()
