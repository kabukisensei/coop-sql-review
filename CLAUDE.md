# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`coop-sql-review` — an **offline, advisory** SQL standards linter for the Microsoft Fabric DW
estate. It parses `.sql` files and reports anything that doesn't match `docs/standards.md`.
Two non-negotiable invariants shape every design decision:

- **Advisory, never blocking** — it reports; it never edits, rejects, or stops anything. Exit
  code is always `0` unless the caller opts into `--strict` (then exit `2` when findings remain).
- **Offline + deterministic** — no network in the core; sorted iteration; LF newlines; `sort_keys`
  on JSON → byte-identical output across runs/OSes. (`upgrade.py` is the only networked module
  and is never imported by the core.)

Two audiences: a human console report and **machine JSON** (`--format json`) consumed by the
company analytics agent, which layers semantic judgment via the `agent_review` list.

**Status: fully built.** All ~30 rules across `RULES.md` (Tier-1/2/3 deterministic, the
agent-judgment rules, and the checkable `docs/standards-proposed-additions.md` rules §A–§F) are
implemented, adversarially verified, and green. Remaining roadmap is operational: publish to PyPI
(M6) and wire into the company analytics agent.

User-facing usage docs live in `README.md` (written for readers with little terminal experience).

## CLI commands

`check` (the main one), `rules` (list all rules), `help [command]`, `upgrade` / `update`
(self-update; the only networked command), `--version`. `check` options: `--standards`,
`--config <rules.yml>`, `--format text|json`, `--min-severity`, `--dialect`, `--log-file`,
`--strict` (opt-in CI gate → exit 2).

## Commands (dev)

```bash
# Tests / lint (run from repo root). NOTE: prefer PYTHONPATH=src over an editable install —
# `pip install -e .` writes a .pth that the local Python 3.14 venv does not process, so the
# console script / `python -m` fail to import. conftest.py puts src/ on sys.path for pytest.
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m pytest tests/test_parser.py -q     # one file
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests       # CI runs this too — easy to forget locally

# Run the CLI in dev
PYTHONPATH=src .venv/bin/python -m coop_sql_review check path/to/sql/ --format json
PYTHONPATH=src .venv/bin/python -m coop_sql_review rules

# Real packaging (what publish.yml does; works on 3.10–3.13 normally)
.venv/bin/python -m build --wheel
```

## Architecture

```
.sql files → parse (sqlglot tsql AST + raw text + line numbers + comments) → rule engine → Findings + Diagnostics → render (text + JSON)
```

Pure core, side effects only at the CLI edge. Data flows as plain dataclasses.

- **`sql_common.py`** — text/AST helpers lifted from coop-data-doc, *extended* with the two
  things this tool needs and the lineage tool didn't: `split_batches_with_lines` (tracks each
  GO-batch's file start line) and `mask_noncode` (blanks comment/string content while preserving
  every character offset and newline, so regex rules scan code only and still map to exact lines).
- **`sql_model.py` / `parser.py`** — `parse_sql()` → `ParsedFile` holding batches+AST, comments,
  extracted `SqlObject`s (with typed `ColumnDef`s), and diagnostics.
- **`finding.py` / `diagnostics.py`** — `Finding` (a standards deviation) vs `Diagnostic` (a
  *processing* problem: parse failure, opaque-command degradation, rule crash, unreadable file).
- **`rules/`** — each rule is `sql_<name>.py` exporting `RULE = Rule(...)`; `rules/__init__.all_rules()`
  auto-discovers every `sql_*.py`. `rules/base.py` has `Rule` + `RuleContext`; `rules/helpers.py`
  has shared helpers (`enclosing_object`, `dml_target`, `projection_stars`) — neither is a rule
  module (names don't start with `sql_`).
- **`engine.py`** — runs every rule over every file; a rule that raises is isolated into a
  `Diagnostic`, never fatal. Sorts everything deterministically.
- **`standards.py`** — resolves the standards file (bundled `data/standards.md`, or `--standards`),
  computes its sha256 for the JSON, and applies an optional `rules.yml` (enable/disable + severity
  override, no rebuild needed).
- **`report.py`** — the agent JSON contract + the human console report + the `--log-file` text.

## Adding a rule

Drop `src/coop_sql_review/rules/sql_<name>.py` exporting a `RULE`; write `tests/test_<name>.py`.
Mirror `sql_no_select_star.py`. Build findings only via `ctx.finding(line=, object=, message=)`
(it stamps rule_id/severity/standard_ref). Cite the `§` of `docs/standards.md` the rule enforces.

**Line numbers — the key gotcha:** sqlglot only tags `Identifier`/`Literal`/`Star` *leaf* nodes
with `meta['line']`. `ParsedFile.node_line(batch, node)` derives a line from the earliest
line-bearing leaf under `node`, offset by the batch's file start line. For CREATE TABLE column
rules, prefer the precise `ColumnDef.line`. For statements sqlglot can't parse structurally,
use a regex over `ParsedFile.masked` + `line_of_offset()` (the "text" method).

**sqlglot caveat (v30.x):** some valid T-SQL degrades to an opaque `exp.Command` — notably
`ALTER COLUMN ... NOT NULL` and exotic type syntax. `SQL-NO-ALTER-COLUMN` is therefore text-based,
and `parser.py` emits a `parse_degraded` diagnostic so the coverage gap is never silent.

## Error handling (project requirement)

Never swallow errors. Parse failures, opaque-command degradations, and rule crashes become
`Diagnostic`s that are shown in the console report AND the JSON (`"diagnostics"` key) on every
run, and can be captured with `check --log-file <path>`. Keep messages specific and actionable
(file:line + what happened + what it means) so the user can fix the cause.

## Windows compatibility (coworkers run this on Windows — keep it working)

Carried from coop-data-doc's hard-won lessons:
- **Console encoding:** `main()` calls `_force_utf8_console()` (reconfigures stdout/stderr to
  UTF-8, `errors="replace"`) so the `§` marks and em-dashes in rule messages never raise
  `UnicodeEncodeError` on a legacy Windows console. The tool's own chrome (severity markers,
  summary lines) is kept **ASCII-only** as belt-and-suspenders — don't reintroduce `✖`/`▲`/`•`.
- **JSON is ASCII:** `json.dumps` runs with the default `ensure_ascii=True`, so `--format json`
  is safe on any code page. Keep it that way.
- **Line endings:** `parse_sql` normalizes CRLF/CR → LF up front, so line numbers are identical
  on Windows and Linux. Any file the tool *writes* uses `newline="\n"` (e.g. `--log-file`).
- **Reads:** files are read `encoding="utf-8-sig", errors="replace"` (BOM-aware, never crashes).
- **Paths:** findings show POSIX paths (`_display_path` → `.as_posix()`, relative to cwd when
  possible) so output is identical across OSes; cross-drive paths fall back to absolute.
- CI runs the full matrix on **ubuntu AND windows** × py3.10–3.13 — keep `ruff format --check`
  green (easy to forget locally).
- There are Windows-specific tests in `tests/test_windows.py` (CRLF line numbers, ASCII chrome,
  ASCII JSON) — extend them when adding output paths.

## Source documents

- `SPEC.md` — architecture, CLI, agent JSON contract, milestones M0–M6.
- `RULES.md` — full rule taxonomy (deterministic vs agent-judgment, by tier).
- `docs/standards.md` — the §-numbered standards (also bundled at `src/coop_sql_review/data/standards.md`).
- `docs/standards-proposed-additions.md` — MS/community best practices to consider (M5).
- The company CLI playbook — shared CLI conventions; the `coop-data-doc` tool — the reference
  implementation the skeleton + SQL helpers were lifted from.
