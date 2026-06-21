# Changelog

All notable changes to **coop-sql-review** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses [semantic versioning](https://semver.org/).
The JSON output is a machine contract (`schema_version`); breaking changes to its shape bump that
field and are called out here.

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

[0.2.1]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.2.1
[0.2.0]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.2.0
[0.1.6]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.1.6
[0.1.5]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.1.5
[0.1.0]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.1.0
