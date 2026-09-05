# Offline input contract

`scripts/diagnose.py` accepts one UTF-8 JSON file containing a single object. It
does not read environment variables, repositories, registries, or network
resources.

## Top-level fields

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `id` | string | recommended | Caller-defined case identifier copied to `caseId`. |
| `source` | string | no | Optional redacted evidence reference copied to output. |
| `input` | object | yes | Normalized observations used by rules. |
| `expected` | object | no | Fixture-only assertions; never used for matching. |
| `affected` | any | no | Ignored. Caller claims cannot change rule applicability. |

`input.surface` must equal `"package"`. All other fields are rule-specific and
are documented in `failure-map.md`. Preserve exact errors and version strings,
but redact account names, repository names, tokens, cookies, authorization
headers, private URLs, and secret values before writing the file.

## Output

The command writes one JSON object to stdout with this complete schema:

| Field | Type | Contract |
|---|---|---|
| `matched` | boolean | `true` only when one deterministic rule wins. |
| `caseId` | string or null | Copy of a non-empty string `id`; otherwise `null`. |
| `diagnosis` | string | Known diagnosis code or `UNKNOWN`. |
| `conclusion` | string | `blocked`, `partial`, or `published-unverified` for the current rules. |
| `layer` | string | First proven failed layer, or `unknown`. |
| `confidence` | string | `high` for known rules; `low` for `UNKNOWN`. |
| `versionStatus` | string | Version/deployment applicability or `unknown`. |
| `observedContext` | object | Strict non-sensitive allowlist described below. |
| `evidence` | array of strings | Direct evidence supporting the result. |
| `recommendation` | string | One safest minimal response. |
| `rejectedShortcuts` | array of strings | Unsafe or misleading shortcuts rejected for this diagnosis. |
| `verificationSteps` | array of strings | Ordered, diagnosis-specific checks. |
| `doNotClaim` | array of strings | Claims not supported by the current evidence. |
| `missingEvidence` | array of strings | Empty for a match; exactly one smallest next fact for `UNKNOWN`. |
| `source` | string or null | Copy of a non-empty, caller-redacted string `source`; otherwise `null`. |

Every known diagnosis has deterministic `conclusion`, `rejectedShortcuts`,
`verificationSteps`, and `doNotClaim` values bundled with the rule. The current
conclusion mapping is:

- prerequisite failures in workflow permission, source resolution, packing,
  family detection, or upload: `blocked`
- `PACKAGE_RELEASE_SCAN_STALLED`: `partial`
- `PACKAGE_SECURITY_AUDIT_FIELDS_MISSING`: `published-unverified`

`UNKNOWN` has the same fields and uses `conclusion: "partial"` because the
evidence is incomplete and no definitive blocked state has been proven. Its
first `verificationSteps` item repeats the single `missingEvidence` item so
the next action is the smallest evidence addition, not a speculative repair.

### `observedContext` allowlist

`observedContext` is empty for `UNKNOWN`. For a known diagnosis it may contain
only fields used by that diagnosis, after value-format validation:

- `clawhubVersion`: normalized to an exact three-part numeric version
- `npmVersion`: normalized to `major.x`; prerelease/build metadata is discarded
- `workflowRef`: only the built-in known workflow ref, normalized to
  `package-publish.yml@v0.23.3` so owner and repository are omitted
- `family`: one of `skill`, `plugin`, `code-plugin`, or `bundle-plugin`
- `sourceValidatorCommit` and `sourceCommit`: 40-character hexadecimal commit
  IDs, normalized to lowercase

It never copies errors, tokens, authorization data, repository/account names,
artifact hashes, URLs, release IDs, invalid allowlisted values, fields unused
by the winning diagnosis, or arbitrary caller fields. Callers must still redact
the input file before execution. Do not add a field or accepted value shape
without a redaction and sensitivity review.

Exit status `0` means the JSON was parsed and evaluated; it does not mean a
known rule matched. Invalid JSON, an unreadable path, or a non-object top-level
value fails without attempting repair.

## Offline and safety boundary

The executable performs deterministic local classification only. It never
publishes, installs, downloads, mutates registry state, runs Git commands,
invokes ClawHub, or validates whether a historical fact is still current.
Refresh bundled rules through reviewed source changes, not caller input.

Run the anonymous example from the repository root:

```bash
python3 research/package-publish-doctor/draft/scripts/diagnose.py \
  research/package-publish-doctor/draft/examples/anonymous-input.json
```
