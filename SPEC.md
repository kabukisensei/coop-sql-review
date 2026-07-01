# coop-sql-review — build spec

## What it is
An **offline, advisory SQL standards linter** for our Fabric DW estate. It parses `.sql`
files, checks each object/statement against `docs/standards.md` (our standards + Microsoft/
Fabric best practices), and surfaces anything that doesn't match. **Advisory, never
blocking** — it reports; it never edits, rejects, or stops anything. Human reports (a sectioned,
colorized terminal report, Markdown, or a self-contained branded HTML file) and **machine JSON for
the agent**.

## Who runs it
- A developer, on changed SQL before committing (or in CI as a non-failing report).
- The company analytics agent, which calls it and layers semantic judgment on top.

## Reuse — do NOT start from scratch
- **Skeleton**: follow the company CLI playbook and copy the proven bones from
  the `coop-data-doc` tool: hatchling `pyproject.toml`, `.github/workflows/ci.yml`
  (ubuntu+windows × py3.10–3.13), `publish.yml` (PyPI trusted publishing), `upgrade.py`
  (self-update), `progress.py`, ruff config, `src/` layout, pure-core/IO-at-edges.
- **SQL parsing**: lift from coop-data-doc `src/coop_data_doc/parsers/sql_objects.py`,
  `sql_procs.py`, `sql_common.py` — sqlglot (tsql) AST + regex fallback; already extracts
  CREATE TABLE columns/types, CTEs, INSERT/MERGE/UPDATE targets, table refs. Copy them now;
  factor a shared `company-bi-core` library later only if duplication bites.
- **Output**: reuse coop-data-doc `diagnostics.py` (severity classification + console + JSON
  + markdown renderers). The Finding/severity model is already solved.

## Architecture
```
.sql files → parse (sqlglot AST + raw text w/ line numbers) → rule engine → Findings → render (text/json/markdown/html)
```
- **Rule** = `{id, title, severity, category, standard_ref, check(parsed, ctx) -> [Finding]}`,
  each a deterministic built-in.
- **standards.md drives configuration**: which rules are on + their parameters. Keep
  standards.md human prose; map sections → rule-ids in a small `rules.yml` (or YAML
  front-matter in standards.md). Editing standards.md / rules.yml changes behavior with no
  rebuild — that satisfies "update the standards anytime."
- **Judgment rules** the engine can't evaluate are emitted in an `agent_review` list (rule-id
  + location + note) so the agent handles them — never silently dropped.

See `RULES.md` for the full taxonomy (deterministic vs agent-judgment, with tiers).

## CLI
```
coop-sql-review check [PATHS...] --standards <path> [--config <path>]
                      [--format text|json|markdown|html] [-o/--output <path>] [--open/--no-open]
                      [--color/--no-color] [--min-severity info|warning|error] [--dialect tsql]
                      [--log-file <path>] [--strict]
coop-sql-review rules [--format text|json]   # list rules, enabled state, and which require the agent
coop-sql-review upgrade                # prints the command to update; never self-applies (alias: update)
coop-sql-review --version
```
- Default exit code **0** (advisory). `--strict` exits **2** when any reported finding remains
  (after the `--min-severity` filter) — or when **zero files were checked** (typo'd path) — for
  teams who *opt in* to a CI gate. Default non-blocking.
- `--standards` points at the canonical file (e.g. the company standards repo's
  `sql-standards.md`); the bundled `docs/standards.md` is the default/fallback.
- The default text report is a sectioned terminal report (banner, one section per file with
  `ERROR`/`WARN`/`INFO` badges, a `SUMMARY` panel); colorized at an interactive terminal and plain
  ASCII when piped / redirected / `--no-color` / `NO_COLOR`.
- `--format html` writes a self-contained, branded HTML file, prints its path, and (when
  interactive, unless `--no-open`) opens it in the browser; `--format markdown`/text honor `-o`.
- Running `check` with no paths in an interactive terminal opens a folder picker.

## Agent integration contract (how it "wires in" later)
`--format json` emits (stable keys, sorted, deterministic):
```json
{
  "tool": "coop-sql-review", "schema_version": 1, "version": "x.y.z",
  "standards": {"path": "...", "sha256": "..."},
  "files_checked": 12,
  "verdict": {"clean": false, "highest_severity": "warning"},
  "findings": [
    {"rule_id":"SQL-NO-SELECT-STAR","severity":"warning","file":"silver/dim_customer.sql",
     "line":12,"object":"silver.dim_customer","message":"SELECT * in production code","standard_ref":"§11",
     "fingerprint":"7ae42b710c08"}
  ],
  "summary": {"error":0,"warning":3,"info":5},
  "agent_review": [
    {"rule_id":"SQL-UPSERT-CHOICE","file":"...","line":20,"object":"...","note":"MERGE detected — judge appropriateness per §5","standard_ref":"§5"}
  ],
  "diagnostics": [
    {"severity":"warning","category":"parse_failed","file":"...","line":0,"message":"...","rule_id":""}
  ]
}
```
The agent consumes `findings` directly and reasons about `agent_review` items using the prose
standards. Same two-audience pattern as coop-data-doc (machine + human).

## Build milestones
- **M0** — scaffold from the playbook (package, CLI stub, ci, publish, upgrade, ruff).
- **M1** — wire in the SQL parser (lift from coop-data-doc); produce a parsed model per file
  (objects, columns+types, CTEs, statements, **comments with line numbers**).
- **M2** — rule engine + the Tier-1 deterministic rules in `RULES.md`.
- **M3** — diagnostics output (text + JSON), advisory exit codes.
- **M4** — standards-driven enable/config (`rules.yml` ↔ standards.md sections).
- **M5** — Microsoft/Fabric best-practice rules (see `docs/standards-proposed-additions.md`).
- **M6** — package + publish (trusted publishing) ✅ *done — published on PyPI* + wire into the agent (remaining).

## Kickoff (paste into a NEW session launched from this folder)
> Building **coop-sql-review**, an offline advisory SQL standards linter for our Fabric DW.
> Read the company CLI playbook, this folder's `SPEC.md` + `RULES.md`, and
> `docs/standards.md`. Reuse the coop-data-doc skeleton and lift its SQL parser
> (`src/coop_data_doc/parsers/sql_*.py`) and `diagnostics.py`. Start at M0: scaffold the
> project, then implement the Tier-1 deterministic rules from `RULES.md`.

## Hard requirements (carry from coop-data-doc)
- **Non-blocking**: never modify or reject SQL; only report.
- **Offline + deterministic**: no network in the core; LF newlines; sorted iteration; pure
  rule functions returning Findings.
- Keep `docs/standards.md` in sync with the canonical company standards copy (or point
  `--standards` straight at that file).
