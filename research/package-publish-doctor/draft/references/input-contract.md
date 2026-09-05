# Offline input contract

`scripts/diagnose.py` accepts one UTF-8 JSON file containing a single object. It
does not read environment variables, repositories, registries, or network
resources.

## Top-level fields

| Field | Type | Required | Meaning |
|---|---|---:|---|
| `id` | string | recommended | Caller-defined case identifier copied to `caseId`. |
| `source` | string | no | Optional evidence reference retained only when it matches the safe source allowlist. |
| `input` | object | yes | Normalized observations used by rules. |
| `expected` | object | no | Fixture-only assertions; never used for matching. |
| `affected` | any | no | Ignored. Caller claims cannot change rule applicability. |

`input.surface` must equal `"package"`. All other fields are rule-specific and
are documented in `failure-map.md`. Preserve exact errors and version strings,
but redact account names, repository names, tokens, cookies, authorization
headers, private URLs, and secret values before writing the file.

The top-level value and `input` must be objects. A missing or non-object
`input` is an input contract error. A present object that lacks enough
diagnostic evidence, including a missing or non-package `input.surface`, is
evaluated normally and returns `UNKNOWN`.

Rule-specific fields are evidence, not structural input requirements. Wrong
types, malformed nested objects, boolean values in numeric fields, numeric
values in version fields, or unsafe collections must not raise exceptions;
they fail the affected rule predicate and conservatively return `UNKNOWN`.

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
| `source` | string or null | Safe normalized evidence reference; otherwise `null`. |

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
When the input has every declared field for exactly one known rule except one,
`missingEvidence` names that exact `input` path. This is only a collection
hint: the result remains `UNKNOWN`, and the missing value must still satisfy
the rule predicate. If multiple rules are each one field short, or all fields
are present but a value is invalid or contradictory, the command keeps the
generic evidence request rather than guessing a candidate diagnosis.

### `observedContext` allowlist

`observedContext` is empty for `UNKNOWN`. For a known diagnosis it may contain
only fields used by that diagnosis, after value-format validation:

- `clawhubVersion`: exact three-part numeric version with at most one `v`
  prefix and no redundant leading zeroes
- `npmVersion`: accepts only `v?major.minor.patch` or `v?major.x`-style
  normalized values without redundant leading zeroes and emits `major.x`;
  prerelease/build metadata is rejected
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

## Process exit contract

Exit status `0` means the JSON was parsed and evaluated; it does not mean a
known rule matched. Both a known diagnosis and `UNKNOWN` use exit status `0`
and write exactly one diagnosis JSON object to stdout with an empty stderr.

Exit status `2` means the input contract was not satisfied. Unreadable files,
invalid UTF-8, invalid JSON (including non-standard `NaN` and infinities),
non-object top-level values, a missing `input`, and a non-object `input` write
no stdout and exactly one compact JSON object to stderr:

```json
{"error": "INPUT_CONTRACT_ERROR", "message": "human-readable reason"}
```

The error does not echo the input path and does not include a Python traceback.
Argument parsing failures that occur before an input path is accepted remain
standard `argparse` errors.

Caller-provided `id` strings that cannot be encoded as UTF-8, including
isolated Unicode surrogates, are omitted as `null`; they cannot break JSON
serialization or expose a traceback.

`source` is fail-closed. The command retains only:

- the exact local label `redacted local observation`
- canonical HTTPS issue URLs under `github.com/openclaw/clawhub/issues/<id>`
- canonical HTTPS Actions run URLs under
  `github.com/bonniegeng-max/openclaw-publisher/actions/runs/<id>`

The URL must not contain userinfo, a query string, or a fragment. HTTP URLs,
private or unknown hosts and repositories, arbitrary text, malformed URLs,
and unencodable strings are emitted as `null`. The command does not attempt
to strip suspected secrets and keep the remainder, because partial
normalization can preserve sensitive path or parameter data.

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
