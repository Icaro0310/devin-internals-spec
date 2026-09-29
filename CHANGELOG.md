# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-29

### Added

- `docs/SPEC.md` — canonical English spec covering the three local stores
  (`sessions.db`, `acp-messages/*.db`, `state.vscdb`), translated from
  `docs/SPEC.pt-BR.md`.
- `devin_internals.schema` — `detect_schema_version()` reads
  `refinery_schema_history` + `app_state.schema_compat_version` and raises
  `UnknownSchemaVersionError`/`SchemaDetectionError` loudly on anything it
  doesn't recognise.
- `devin_internals.fixtures` — deterministic (fixed-seed) synthetic generators
  for `sessions.db` (real v17 DDL, synthetic rows), `acp-messages` and
  `state.vscdb`.
- Tests covering fixture validity/determinism, v17 detection, and loud
  failure on unknown/missing/corrupt schemas (Windows + Linux safe).
- Real content in `README.md`/`README.pt-BR.md` (problem, prior art,
  Devin-native extra, limitations).
- Initial scaffold from `devin-repo-template`.
