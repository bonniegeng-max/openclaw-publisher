---
name: ClawHub Package Publish Doctor
slug: package-publish-doctor
description: Diagnose ClawHub package and plugin publication failures across workflow permissions, packing, manifests, Inspector, uploads, publication state, and artifact verification.
version: 0.1.5
metadata:
  openclaw:
    os: [macos]
    emoji: "🧰"
    requires:
      bins:
        - git
        - clawhub
        - python3
    homepage: https://github.com/bonniegeng-max/openclaw-publisher
    install:
      - kind: node
        package: clawhub
        bins: [clawhub]
---

# ClawHub Package Publish Doctor

Your package publish failed. Diagnose the broken layer before changing the artifact.

Use this Skill when `clawhub package validate`, `pack`, `publish`, publication waiting, `package verify`, or the official reusable package workflow fails or returns conflicting signals.

## Trigger conditions

Invoke when the user provides any of these:

- a failed ClawHub package or plugin publication log
- a GitHub Actions run that calls the official package publish workflow
- an unexpected `package validate`, Inspector, upload, moderation, index, or verification result
- a package that published successfully but is not visible or verifiable
- a request to distinguish a local artifact problem from a ClawHub version or platform problem

Do not invoke for ordinary Skill content review, generic plugin implementation, catalog metadata maintenance, or download-growth analysis.

## Required evidence

Collect existing evidence before rerunning anything:

1. Explicit surface confirmation: the failing command is `clawhub package ...`, not `clawhub skill ...`.
2. Exact command, ClawHub CLI version, and reusable workflow ref.
3. Node and npm versions when packing is involved.
4. Package family and source type: folder, repository, npm artifact, or prebuilt ClawPack.
5. `package.json`, `openclaw.plugin.json`, and compatible bundle marker presence.
6. Artifact byte size and hash when an archive exists.
7. Full error text, exit code, job creation state, and relevant permissions.
8. Publish response, release ID, publication status, scan age, Inspector result, and `package verify` result when available.
9. For a source-validation regression, the exact source-validator commit and the compared source fields; rejection alone is not source evidence.

Never request tokens, cookies, authorization headers, or raw secret values.

## Diagnostic flow

### 1. Confirm the surface

Separate Package publishing from Skill publishing.

- Package commands use `clawhub package ...` and may involve package families, manifests, Inspector reports, ClawPacks, npm artifacts, publication waiting, and artifact verification.
- Skill commands use `clawhub skill ...` and belong to the Skill publishing Doctor or Release Proof Builder.

If the evidence mixes both surfaces, split the analysis and do not transfer a workaround from one path to the other without proof.

### 2. Locate the failed layer

Classify the first proven failure:

| Layer | Typical evidence |
|---|---|
| `workflow-permission` | workflow rejected before jobs are created; nested job requests a permission the caller does not grant |
| `source-resolution` | source ref, repository, path, or downloaded artifact cannot be resolved |
| `pack` | npm or ClawPack creation/parsing fails before validation |
| `family-detection` | detected family conflicts with available manifests or bundle markers |
| `inspector` | package validation or Plugin Inspector rejects the artifact |
| `upload` | request size, ticket, storage, timeout, or transport failure |
| `moderation` | artifact is held, blocked, or waiting on security review |
| `index` | publish response exists but public release/latest state is missing or stale |
| `verification` | package is public but provenance, integrity, or hash verification fails |

The nine layers define the investigation framework, not nine executable diagnoses. The current evidence map has high-confidence rules for `workflow-permission`, `source-resolution`, `pack`, `family-detection`, `upload`, `moderation`, and `verification`. Treat `inspector` and `index` as classification-only layers until each has a sourced positive fixture and explicit negative boundaries; return `UNKNOWN` instead of inventing a rule.

Do not diagnose from the last line alone. Collect all matching rule signals before choosing a diagnosis. Prefer the earliest layer with direct evidence. If multiple layers match and the evidence does not provide a complete `failureSequence`, return `UNKNOWN` rather than relying on rule order.

### 3. Apply version-aware rules

Use `references/failure-map.md`. Every rule must state one of:

- `current-release`: reproduced or documented in the latest formal release
- `fixed-in-release`: a formal release contains the fix
- `main-only-fix`: source fix exists but no formal release contains it
- `current-server`: the current service code or live server contains the defect
- `source-reproduced-at-commit`: the defect is reproduced from a named source commit, without claiming that commit is currently deployed
- `fix-merged-deployment-unverified`: the repair merged, but deployment is not proven
- `product-decision`: behavior remains unresolved by maintainers
- `unknown`: evidence is insufficient or contradictory

Do not recommend an unreleased `main` commit as a production dependency. A temporary workaround must be scoped, reversible, and labeled as temporary.

Rule applicability and fixed historical facts belong to the bundled rule map and diagnostic implementation. Treat observed CLI, npm, workflow, family, and source-validator commit values as `input`; never let caller-supplied `affected` metadata decide whether a rule matches.

### 4. Check conflict signals

Treat these as evidence conflicts, not success:

- publish exits `0`, but latest/version index does not include the release
- moderation says `CLEAN`, but publication remains hidden
- tarball exists, but the CLI says packing produced no filename
- Inspector succeeds, but upload returns 413
- GitHub reports a startup failure before any job exists

Do not bump a version merely to escape a stuck registry state. Do not create a fake native manifest to bypass a family contract.

For `CLAWPACK_STAGING_GAP`, an Inspector or local-validation success only counts when its artifact hash exactly matches the artifact that received the 413. Missing validation, failed validation, or a different hash is insufficient for a high-confidence diagnosis.

For `TRUSTED_PUBLISH_TAG_REF_REGRESSION`, require source-comparison evidence from source-validator commit `845c6d3bdb1a36573d8d28be2a8fb85a3c476720`, including the comparison of `source.ref` with `candidateSha ?? token.sha`. A bare `rejected: true` observation is insufficient.

For `PACKAGE_SECURITY_AUDIT_FIELDS_MISSING`, both `overview` and `securityAuditUrl` are required to be non-empty strings. Treat either field as malformed when it is missing, blank, or not a string, but only match when the fail-closed error names an invalid field and the exact-release trust verdict is otherwise clean.

### 5. Verify the repair

Use the narrowest applicable sequence:

```text
local structure
  → package validate
  → package publish --dry-run
  → real publish only with explicit authorization
  → definitive publication state
  → package verify
  → artifact integrity/hash match
```

A green workflow alone is not proof that the package is public or authentic. A successful publish response alone is also insufficient.

## Output contract

Return one report using `templates/package_diagnosis_report.md`:

1. Conclusion: blocked / partial / published-unverified / verified.
2. Failed layer.
3. Diagnosis code and confidence.
4. Direct evidence.
5. Version applicability.
6. Safest minimal repair.
7. Explicitly rejected shortcuts.
8. Verification steps.
9. Missing evidence.

If no rule has enough evidence, return `UNKNOWN` and specify the smallest missing fact. Do not guess.

## Safety rules

- Do not publish, install, download, or mutate registry state unless the user explicitly requests it.
- Do not bypass Plugin Inspector, moderation, trusted publishing, or artifact verification.
- Do not widen permissions beyond the exact requirement.
- Do not expose secrets in logs or reports.
- Do not convert a historical bug into a current diagnosis without checking the installed CLI/workflow version.
- Do not describe `dry-run`, upload acceptance, or a version reservation as public availability.
- Do not use a new version number as the default repair for a server-side consistency fault.

## Bundled resources

- `references/failure-map.md`: evidence signatures, version status, and safe responses.
- `templates/package_diagnosis_report.md`: stable report structure.
- `examples/three_layer_diagnosis.md`: examples that distinguish pack, contract, and upload failures.
- `examples/package_release_scan_stalled.md`: version-bounded package scan stall with explicit Skill-surface counterexamples.
- `examples/source_and_verification_failures.md`: trusted source-ref regression and fail-closed audit-response verification.
- `CHANGELOG.md`: draft evolution history.
