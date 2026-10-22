# CREDENTIALS-TOML.md — spec of `<data>/credentials.toml`

The CLI's credential file. Devin-owned and **read-only** for all tooling —
this spec exists so readers can locate it, parse it safely, and keep its
contents out of every log, export and model context.

Marks: **(verified YYYY-MM-DD)** = inspected live on that date ·
**(contract)** = pinned by `src/devin_internals/paths.py`.

## 1. Location

Canonical: `<data>/credentials.toml` — beside `cli/sessions.db` under the
data root (`~/.local/share/devin` on Linux, `%APPDATA%\devin` on Windows,
`~/Library/Application Support/devin` on macOS).

Resolution — **(contract)** `paths.credentials_toml_candidates()`:

1. `DEVIN_DATA_DIR` override (via `resolve()`/`default_data_dir`)
2. `<data>/credentials.toml` — canonical
3. `<config>/credentials.toml` — unified/fixture layouts keep it beside the
   UI stores

The file may be **absent** on web-only installs — absence is a valid state,
not an error. Observed mode `0600` on Linux **(verified 2026-10-22)**;
readers should expect owner-only permissions and must not widen them.

## 2. Format

Flat TOML — no `[table]` headers, one `key = "value"` string scalar per line
**(verified 2026-10-22, Linux)**.

### Verified keys

| key | type | sensitivity | notes |
|---|---|---|---|
| `windsurf_api_key` | string | **secret** — never print, log, export or feed to a model | the CLI's API credential; key name predates the Devin rebrand |
| `api_server_url` | string | endpoint URL — low sensitivity, still not published | |
| `devin_webapp_host` | string | endpoint host — low sensitivity | |
| `devin_api_url` | string | endpoint URL — low sensitivity | |

Key *names* are structure and may appear in docs; everything to the right of
`=` is row content and is never published — the same rule `docs/SCHEMA.md`
applies to store rows.

## 3. Reader rules

1. **Parse as TOML** (`tomllib` on Python ≥3.11); do not regex the file —
   quoting and comment edge cases make that fragile.
2. **Ignore unknown keys** — Cognition can add keys any release; a reader
   must not fail on a superset.
3. **Missing file is valid** — return an empty/absent result, never invent a
   file.
4. **Never write.** No ecosystem tool creates, edits or deletes
   `credentials.toml`; session material is Devin's contract surface. If a
   tool needs an API key it takes it from its own config or env, not by
   parsing this file.
5. **Secret hygiene** — the file is covered by the repo's redact/secret
   scanning; test fixtures that need the *shape* write synthetic keys like
   `[fixture]`/`synthetic = true` (see `install_states.py` corpus builders),
   never real key formats.

## 4. What is deliberately not documented

- **Key values** — including the endpoint URLs. They are instance data, not
  contract.
- **Write semantics** — how/when Devin rotates `windsurf_api_key`, whether
  edits are picked up live, and the file's behaviour under concurrent CLI
  sessions are all **unverified**; treat as opaque.
- **Other credential stores** — Desktop auth lives in the Electron
  safeStorage/Chromium surface, not in this file; out of scope.

## 5. Drift signal

There is no version field. If a future release adds a `[table]` section or
renames the key set, this doc and `paths.credentials_toml_candidates()` get
updated together — same drift protocol as `docs/SCHEMA-VERSIONS.md` §4.
