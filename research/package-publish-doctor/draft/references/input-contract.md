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

The command writes one JSON object to stdout:

- `matched`, `diagnosis`, `layer`, `confidence`, and `versionStatus`
- `evidence` and `recommendation`
- `missingEvidence` (non-empty for `UNKNOWN`)
- caller-provided `caseId` and optional `source`

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
