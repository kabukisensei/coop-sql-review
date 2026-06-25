# Changelog

All notable changes to **coop-sql-review** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses [semantic versioning](https://semver.org/).
The JSON output is a machine contract (`schema_version`); breaking changes to its shape bump that
field and are called out here.

## [0.2.4] — 2026-06-25
### Fixed
- **Column nullability was inverted under `sqlglot >= 26`** — `_columns_from_schema` read
  `not allow_null`, but sqlglot flipped the `NotNullColumnConstraint` shape at 26 (a `NOT NULL`
  column now carries no `allow_null` key; an explicit `NULL` column carries `allow_null=True`).
  Nullability is now read directly as `bool(allow_null)`, with a regression test pinning
  `NOT NULL`/`NULL`/bare/`PK` so a future sqlglot bump can't silently re-invert it. The `sqlglot`
  dependency is now floored at `>=26,<31` (25.x has the inverted semantics).
### Docs
- `PUBLISHING.md` no longer says to bump `version` in `pyproject.toml` — the version is
  single-sourced from `src/coop_sql_review/__init__.py` (hatchling dynamic version); a static
  `version =` key breaks `python -m build`.
- `CLAUDE.md` `check` options now list `--color/--no-color`, `--baseline`, `--write-baseline`.
- `README.md`/`SPEC.md` note `rules --format json` (machine-readable rule inventory).

## [0.2.3] — 2026-06-22
### Changed
- **SQL-IMPLICIT-CONVERT (§C)** now flags every comparison operator (`=`, `<>`, `<`, `<=`, `>`,
  `>=`), not just `=` — §C is about *comparing* mismatched types, so range and inequality
  predicates are caught too. It also recognizes two more predicate contexts: a `HAVING` clause
  and a `MERGE ... ON` match condition (`UPDATE SET` assignments — including a MERGE
  `WHEN MATCHED ... SET` — stay excluded). Date/`datetime2` columns remain unflagged, so the §A
  SARGable `col >= 'literal'` range pattern is not a false positive.
### Fixed
- **SQL-NO-SELECT-STAR (§11)**: an idiomatic `EXISTS(SELECT *)` predicate is no longer flagged
  (the projection is discarded). Production `SELECT *` is still flagged everywhere it matters —
  top level, in a `CREATE VIEW`, in `INSERT ... SELECT`, and inside a derived-table or scalar
  subquery (§4's "Bad" pattern); only an intermediate CTE's own `SELECT *` is exempt.

## [0.2.2] — 2026-06-21
### Changed
- **Internal de-duplication**: the tool-agnostic infrastructure (progress, diagnostics, the
  severity ordering + finding fingerprint, inline/baseline suppressions, self-update, and the
  rules.yml config layer) now comes from the shared **`coop-review-core`** package (new runtime
  dependency `coop-review-core>=0.1.0`). Behavior, CLI, and the JSON contract are unchanged — fingerprints
  are byte-identical — but a fix to that shared infra now lands once instead of being copy-pasted.

## [0.2.1] — 2026-06-21
### Added
- `rules.yml` now accepts a per-rule `params:` block (tunables, e.g. thresholds) — infrastructure
  shared with coop-dax-review; no SQL rule consumes a param yet.
- Auto-created **GitHub Releases** (with generated notes) on each `v*` tag.
### Changed
- **Single-sourced the version**: `src/coop_sql_review/__init__.py` is the only place to bump;
  `pyproject.toml` derives it (hatchling dynamic version).
### Internal
- A test pins `docs/standards.md` byte-identical to the bundled `data/standards.md` (so the JSON
  `sha256` provenance can't silently drift). Added this CHANGELOG.

## [0.2.0] — 2026-06-21
### Added
- **Suppressions** for adopting on an existing estate: inline `coop-sql-review:ignore <RULE>` comments
  and a fingerprint **baseline** (`--write-baseline` / `--baseline`) that surfaces only new findings.
- Agent JSON: a stable, line-independent `fingerprint` per finding/agent-review item, a
  `schema_version`, and a `verdict` `{clean, highest_severity}`.

## [0.1.6] — 2026-06-21
### Fixed
- Console UTF-8 reconfigure now passes `newline=""` so redirected output (incl. the JSON contract)
  stays byte-identical LF on Windows.
### Added
- Validate `rules.yml` severity strings up front; a diagnostic for unknown rule ids.
- The terminal report lists agent-review items; JSON `files_checked`; a `path not found` message for
  a mistyped path.
- CI: the publish workflow fails fast if the tag doesn't match the package version.

## [0.1.5] — 2026-06-21
### Changed
- The `--format text` report is now a **sectioned, colorized** report (banner, per-file sections,
  severity badges, a SUMMARY panel). `--color/--no-color`; auto-off when piped (`NO_COLOR` honored).

## [0.1.0] – [0.1.4] — 2026-06-16 … 2026-06-17
### Added
- Initial release line: SQL standard rules over `.sql` for Microsoft Fabric DW (Tier-1/2/3 +
  agent-judgment rules, some off-by-default), a human report, and the machine JSON contract. A
  self-contained branded **HTML report** (`--format html`, opens in the browser), `--format
  markdown`, `-o/--output`, an interactive folder picker, and `upgrade`/`update` that print the
  command to run. Offline, advisory, never blocks.

[0.2.3]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.2.3
[0.2.2]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.2.2
[0.2.1]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.2.1
[0.2.0]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.2.0
[0.1.6]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.1.6
[0.1.5]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.1.5
[0.1.0]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.1.0
