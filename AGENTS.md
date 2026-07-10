# AGENTS.md

Canonical guide for **any** coding agent (Claude Code, the Pi-based agent, Kimi/Hermes) and for
human developers working in this repository. `CLAUDE.md` is just `@AGENTS.md` — keep this file
authoritative; don't fork guidance between the two.

## What this is

`coop-sql-review` — an **offline, advisory** SQL standards linter for the Microsoft Fabric DW
estate. It parses `.sql` files and reports anything that doesn't match `docs/standards.md`.
Two non-negotiable invariants shape every design decision:

- **Advisory, never blocking** — it reports; it never edits, rejects, or stops anything. Exit
  code is always `0` unless the caller opts into `--strict` (then exit `2` when findings remain,
  when **any error-severity diagnostic** remains — a real syntax error, a rule crash, an unreadable
  file — or when **zero files were checked**, so a typo'd path can't pass CI as "clean"). The
  canonical exit-code table is family-wide and lives in
  [coop-review-core's AGENTS.md, "Exit-code contract (family-wide)"](https://github.com/kabukisensei/coop-review-core/blob/main/AGENTS.md#exit-code-contract-family-wide)
  — 0 advisory / 1 friendly tool failure / 2 usage + `--strict` / 130 interrupt; this tool
  implements it exactly, no local redefinitions.
- **Offline + deterministic** — no network in the core; sorted iteration; LF newlines; `sort_keys`
  on JSON → byte-identical output across runs/OSes. (`upgrade.py` is the only networked module
  and is never imported by the core.)

Two audiences: a human console report and **machine JSON** (`--format json`) consumed by the
company analytics agent, which layers semantic judgment via the `agent_review` list.

**Status: fully built.** All 32 rules across `RULES.md` (Tier-1/2/3 deterministic, the
agent-judgment rules, and the checkable `docs/standards-proposed-additions.md` rules §A–§F) are
implemented, adversarially verified, and green (full suite passing). Published to PyPI (live
via the `v*`-tag trusted-publishing workflow). Remaining roadmap is operational: wire into the
company analytics agent.

User-facing usage docs live in `README.md` (written for readers with little terminal experience).

## CLI commands

`check` (the main one), `rules` (list all rules), `help [command]`, `upgrade` / `update`
(the only networked command), `--version`. `check` options: `--standards`,
`--config <rules.yml>`, `--format text|json|markdown|html|sarif`, `-o/--output <file>`,
`--html <file>` / `--md/--markdown <file>` / `--sarif <file>` (extra report sinks — compose with
`--format`, never open a browser; core's `cliutils.write_extra_report`), `--open/--no-open`, `--color/--no-color`,
`--min-severity`, `--baseline`, `--write-baseline`, `--save-ignores` (interactive; see below),
`--dialect`, `--target fabric-dw|azure-sql`, `--log-file`, `--strict` (opt-in CI gate →
exit 2). A stderr-only, TTY-gated progress bar (`progress.py`) shows during the parse phase.

**SQL target (`--target`).** The linter runs against BOTH Microsoft Fabric Data Warehouse and
Azure (serverless) SQL. Some §9 rules enforce a Fabric-DW-only limitation (types Fabric DW
rejects but Azure SQL accepts — `SQL-TYPE-MONEY`/`-DATETIME`/`-NVARCHAR`/`-UNSUPPORTED`; the
Preview-only `ALTER COLUMN` — `SQL-NO-ALTER-COLUMN`) or a Fabric-only syntax surface
(`OPTION(LABEL=...)` — `SQL-QUERY-LABEL`); each carries `targets=FABRIC_ONLY` (`rules/base.py`).
Rules kept on both targets must not assert Fabric-specific facts as universal — attribute the
rationale in the message ("on Fabric DW ..."), as `SQL-SINGLETON-INSERT`/`SQL-TXN-SHORT` do. Resolution: `--target` flag > a `target:` key in
`rules.yml` > default `fabric-dw`; a rule outside the active target is skipped (filtered in
`cli.py` after `apply_config`, so a rule's own enable/severity override is still honored when it
applies). `rules --format json` includes a `targets` array. NB: **IDENTITY columns are now
supported** in Fabric DW (Preview, `bigint` only) — there is deliberately no rule flagging them.
`check` with no PATHS in an interactive terminal shows a questionary folder-picker
(`cli._interactive_pick_paths`); non-TTY falls back to scanning `.`.

### Non-interactive / harness behavior (read this before scripting the CLI)

Verified in `cli.py` — this is what happens when an agent, cron job, or CI pipe runs the tool:

- **`check` with no PATHS and no TTY silently scans `.` recursively for `*.sql`.** The folder
  picker only appears when BOTH stdin and stdout are TTYs (`cli._stdio_interactive`); otherwise
  the empty path list becomes `[Path(".")]`. **Never run a bare `coop-sql-review check` from a
  harness** — in a home directory or monorepo it will walk everything under the cwd. Always pass
  explicit paths.
- **`--save-ignores` requires an interactive terminal** (questionary checkbox). Don't use it from
  a harness; edit `rules.yml`'s `ignore:` list directly instead.
- **The browser never opens for agents.** `cli._should_open_report` gates auto-open to
  `--format html` + interactive TTY; pass `--no-open` anyway if you want it explicit.
- **The written report path is echoed to stderr unconditionally** (not TTY-gated), so a piped run
  can find the file. Parse stderr for it, or better: pass `-o <known-path>`.
- **Exit codes:** the family-wide contract (see core's AGENTS.md link above): `0` advisory;
  `--strict` trips (findings at/above `--min-severity`, any remaining error-severity diagnostic
  — e.g. a `syntax_error` — or zero files checked) and usage errors → `2`; unwritable output
  sink → `1`; Ctrl-C → `130`.

**Config discovery** is core's family-wide `discover_config` (core 0.4.0, coop-review-core#12),
wrapped by `cli._discover_config_path`. First hit wins:

1. `--config <file>` — an **explicit path that doesn't exist is a usage error (exit 2)**, except
   under `--save-ignores`, where the flag also names the file to CREATE (that exemption is
   tool-side; core doesn't know the flag).
2. The `COOP_SQL_REVIEW_CONFIG` env var — points a whole CI pipeline at one config without
   threading `--config` through every call site. Set-but-missing is a usage error too; empty
   counts as unset.
3. A **git-style walk** from the cwd up through its parents: in each directory
   `coop-sql-review.yml` (the preferred, tool-specific name) first, then `rules.yml` as the
   **deprecated** shared fallback. The walk checks the directory containing a `.git` entry and
   stops — a config outside the repository never silently applies.
4. The conventional spot beside the standards file (may not exist → empty config).

`rules.yml` keeps working (same schema — tool-named files use the identical schema), but
discovery returns human-facing notes (a deprecation nudge; a shadowing note when both files sit
in one directory) that `check` prints as **stderr one-liners** — never on stdout, so the machine
formats stay byte-identical. Auto-discovery absence stays silent. All config load problems (bad
YAML, non-mapping root/`rules:`, unknown severity, non-UTF-8 file) go through
`cli._load_rule_config` (core's `load_config_friendly` + `parse_syntax_errors_knob`, one read),
which turns them into one-line usage errors naming the file — never a traceback.
`cli._config_write_path` (used by `--save-ignores`) is core's `config_write_path`: `--config` if
given, else the config this run actually READ (so an ignore is appended to the file that
configured the run), else `./rules.yml` — never the bundled standards dir in the package.

**`upgrade`/`update` are advisory too — they never self-apply.** They query PyPI to report
whether a newer release exists, then *print* the command to run (`upgrade.upgrade_command(plan)`,
per install method — e.g. `pipx upgrade coop-sql-review`); the user runs it in a fresh terminal.
Rationale: a running program can't reliably replace its own files (its console-script `.exe` is
locked on Windows). `upgrade.apply_plan` (the actual subprocess runner) is retained as tested
library API but is no longer invoked by the CLI; `upgrade_command` mirrors the command(s)
`apply_plan` would run — a list (git-checkout pulls then reinstalls; one command otherwise) — with
display-friendly tokens (`python` over `sys.executable`). `--check` reports status only.

**HTML report (`--format html`)** is self-contained and Cooptimize-branded: `report.to_html`
inlines the CSS (brand palette: navy `#004068`, accent `#e84028`, green gradient) and base64-embeds
the logo — no network, all dynamic text HTML-escaped. The style block and logo are core's
(`coop_review_core.report.HTML_STYLE` / `logo_data_uri()` — the family's single bundled copy;
this repo no longer ships its own). `--format html` **always writes
a file** (mirrors coop-dax-review): to `-o` if given, else `cli._DEFAULT_HTML_NAME`
(`coop-sql-review-report.html`) in the current directory — never a raw dump to stdout. When any
report file is written (`-o` or the html default), `check` echoes the resolved POSIX path to
stderr **unconditionally** (not gated on the progress bar) so a piped run or agent can find the
file; an HTML report is then opened in the browser via `cli._open_report` — gated by
`cli._should_open_report` to `fmt == "html"` + interactive TTY, with `--open`/`--no-open`
overriding. Opening is best-effort (failure prints a note, never fatal).

**Off-by-default rules:** `Rule.default_enabled=False` ships a rule but excludes it from runs
unless `rules.yml` has `enabled: true` for it (see `standards.apply_config`). Currently off by
default (noisy on estates with different house styles): `SQL-HEADER-COMMENT`,
`SQL-TABLE-LAYER-NAME`, `SQL-CTE-PREFIX`, `SQL-ALIAS-DESCRIPTIVE`, `SQL-INSERT-ALIAS-MATCH`,
`SQL-QUERY-LABEL`, `SQL-FILTER-UPSTREAM` (issue #17 — it drowned the agent channel; when
enabled it also collapses to one item per enclosing object). `rules` marks them
`[off by default]`.

## Environment

- Works fully headless on Linux (and macOS/Windows) — no GUI needed; the browser/`--open` paths
  auto-disable off-TTY, and only `upgrade` touches the network.
- Python: create the venv with **Python 3.13** (3.10–3.13 supported; **avoid 3.14** — its venvs
  don't process editable-install `.pth` files, which is one reason this repo installs
  non-editable + `PYTHONPATH=src`). `make setup` uses whatever `python3` resolves to; if
  `python3 --version` prints 3.14+, rebuild explicitly:
  `rm -rf .venv && python3.13 -m venv .venv && .venv/bin/python -m pip install ".[dev]" build`,
  then `git config core.hooksPath .githooks` (together that's `make setup`, interpreter pinned).
- Before starting any work: `git fetch && git pull --ff-only`. If the pull fails, or
  `git status --porcelain` prints changes you didn't make yourself, **stop and report** — never
  stash, reset, or commit around them (another agent or human may share this tree).
- Secrets: **none in this repo and none needed** — PyPI publishing is tokenless trusted
  publishing (GitHub OIDC), and the tool itself is offline.

## Commands (dev)

A `Makefile` wraps the canonical invocations — prefer it so the PYTHONPATH idiom is never typed
wrong:

| Target | What it runs |
|---|---|
| `make setup` | create `.venv`, install `".[dev]" build` (non-editable), activate `.githooks` |
| `make test` | `PYTHONPATH=src .venv/bin/python -m pytest -q` → expect **all tests passing** (zero failures/errors; `390 passed` as of v0.5.0 — the count grows) |
| `make test-local-core` | same suite, but the sibling `coop-review-core` checkout's `src` shadows the installed core (default `$HOME/Developer/coop-review-core/src`; override with `CORE_SRC=`) |
| `make lint` | `ruff check src tests` + `ruff format --check src tests` (CI runs both) → expect `All checks passed!` then `<N> files already formatted` |
| `make build` | `.venv/bin/python -m build --wheel` → `dist/coop_sql_review-<ver>-py3-none-any.whl` |
| `make release-check` | `scripts/release_check.py` — version wiring + CHANGELOG entry (see below) |

Windows has no `make`: run the underlying commands, swapping `.venv/bin/` → `.venv\Scripts\`.

```bash
# Tests / lint (run from repo root). NOTE: prefer PYTHONPATH=src over an editable install —
# `pip install -e .` writes a .pth that a Python 3.14 venv does not process, so the
# console script / `python -m` fail to import (use 3.13 — see Environment).
# conftest.py puts src/ on sys.path for pytest.
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

## Testing against local coop-review-core

The `.venv` holds a **non-editable installed** `coop-review-core` (0.4.0) — edits in the
`coop-review-core` checkout **next to this repo** are invisible to this tool until core is
re-published and reinstalled. (The coop-* repos are assumed cloned side by side under one parent
directory — on Aaron's Mac `~/Developer`, which is what `$HOME/Developer` below means; if yours
differ, pass `CORE_SRC=<path-to-core>/src` to make, or substitute the path in the PYTHONPATH
commands.) **Never `pip install -e` the core (or this repo) into the venv** — editable installs
are unreliable on Python 3.14 venvs (the `.pth` isn't processed). Shadow on
`PYTHONPATH` instead; it's the same idiom the tests already use, with one extra entry in front:

```bash
make test-local-core
# = PYTHONPATH="$HOME/Developer/coop-review-core/src:$PWD/src" .venv/bin/python -m pytest -q
# expected: identical result to `make test` — same count, all passing
```

Same pattern for the CLI:

```bash
PYTHONPATH="$HOME/Developer/coop-review-core/src:$PWD/src" \
  .venv/bin/python -m coop_sql_review check path/to/sql/
```

Verify the shadow took (must print a path inside the `coop-review-core` checkout, NOT site-packages):

```bash
PYTHONPATH="$HOME/Developer/coop-review-core/src:$PWD/src" \
  .venv/bin/python -c "import coop_review_core; print(coop_review_core.__file__)"
```

After each coop-review-core release, resync the venv so bare `pytest` keeps working (a stale
installed core has broken test collection before):

```bash
.venv/bin/python -m pip install -U coop-review-core
```

Release order is core-first: publish `coop-review-core`, then this tool (`pyproject.toml` pins
`coop-review-core>=0.4,<0.5` — capped; raise the cap alongside each new core minor).

## sqlglot version pin

`pyproject.toml` pins `sqlglot>=26,<31`. The floor is 26 because the parser relies on the >=26
`NotNullColumnConstraint` `allow_null` semantics — 25.x is inverted, which yields wrong column
nullability. The cap is one below the next major past the verified one (30.x; check the exact
patch with `.venv/bin/pip show sqlglot`) to avoid silent breaks: parser output shifts between
sqlglot majors, and the rules and `parse_degraded` diagnostics are tuned to 30.x behavior (e.g.
`ALTER COLUMN ... NOT NULL` degrading to an opaque `exp.Command`). The `RAISE`-level `syntax_error`
detection and the `_is_sqlglot_gap` classifier were verified on **30.12.0** and re-run green on the
**26.33.0** floor (identical fixture lines/categories), so the pin range stands; if you change the
classifier, re-run `tests/test_syntax_errors.py` on both ends of the pin before widening it. To upgrade: raise the cap by
one major, run the full suite (`make test`) and `make lint`, and fix any rule whose AST shapes
moved before widening further. Upgrades are **on-demand, not scheduled**: raise the cap only when
(a) a rule or parser fix needs something from a newer sqlglot, (b) a security advisory lands
against the pinned range, or (c) the pin blocks installing alongside another tool. Never bump it
as routine maintenance — every major requires the full re-verification above, and the pinned
range keeps working regardless.

## Version: single source + release checks

The ONLY version lives in `src/coop_sql_review/__init__.py` (`__version__`). `pyproject.toml`
deliberately has **no** `version =` key: it declares `dynamic = ["version"]` and
`[tool.hatch.version] path = "src/coop_sql_review/__init__.py"`, so hatchling reads
`__version__` at build time. **Never add a static `version =` to `[project]`** — it conflicts
with `dynamic` and breaks `python -m build` (see `PUBLISHING.md`). `scripts/release_check.py`
guards this wiring mechanically:

```bash
make release-check
```

Expected output (all `ok:` lines, exit 0):

```
ok: __version__ = 0.5.0 (src/coop_sql_review/__init__.py)
ok: pyproject [project] declares dynamic version, no static version key
ok: [tool.hatch.version] path -> src/coop_sql_review/__init__.py
ok: CHANGELOG.md has a '## [0.5.0]' entry
warn: git tag v0.5.0 already exists — bump __version__ before the next release
release-check: OK
```

(The `warn:` line only appears when the current `__version__` is already tagged/released; it
never fails the check.) Any `FAIL:` line exits 1 — fix the named file before releasing.

**Pre-commit hook.** `.githooks/pre-commit` runs the same wiring check
(`scripts/release_check.py --pre-commit`) on every commit. One-time activation per clone:

```bash
git config core.hooksPath .githooks
```

Verify: `git config core.hooksPath` prints `.githooks`. (`make setup` does this for you.
Emergency bypass: `git commit --no-verify` — then fix the wiring immediately.)

**Publishing** is tag-driven: push a `v<version>` tag and `publish.yml` builds, smoke-tests the
wheel, verifies the tag matches `__version__` (mismatch fails the build), publishes via PyPI
trusted publishing, and creates the GitHub Release. Human steps in `PUBLISHING.md`.

**Release guardrails** (the tag push IS the publish — treat tags as live ordnance):

- Never create or push a `v*` tag unless Aaron explicitly asked for a release **naming the
  version** in the current conversation. Never infer a release from a clean working tree, a
  version bump you notice, or green CI — real incident (2026-07-02): an agent cut a spurious
  empty release off a "clean tree" signal while another agent shared the same tree.
- Never move, delete, or reuse an existing `v*` tag — PyPI refuses re-uploads of a version; a
  botched release means the next patch number.
- Suite ordering: `coop-review-core` releases **first**, then this tool (its pyproject pins
  `coop-review-core>=...`). A suite release is **not done** until the `coop-website` repo is
  synced + pushed — `versions.json` updated first, then both of its check scripts print `PASS`
  (procedure: coop-website's `AGENTS.md`, "Release-time procedure").
- Verify after tagging: the `Publish to PyPI` workflow run is green (repo → Actions tab) and
  `python -m pip index versions coop-sql-review` (networked) lists the new version.

## Architecture

**Shared core:** the tool-agnostic infrastructure lives in the published
[`coop-review-core`](https://github.com/kabukisensei/coop-review-core) package (runtime dep,
pinned `>=0.4,<0.5` — capped per core's pin policy; bump the cap with each core release). The
local `progress.py`, `diagnostics.py`, `suppressions.py`, `upgrade.py`, and `standards.py` are
**thin shims** re-exporting / forwarding to core (baking in this tool's name); `finding.py` sources
`SEVERITIES`/`severity_rank`/`at_or_above`/`fingerprint` from `coop_review_core.severity` but keeps
the tool's own `Finding`/`AgentReviewItem`. Since core 0.4.0 (issue #21) the consolidation goes
further: `report.py` renders through `coop_review_core.report` (console chrome, HTML style + the
ONE bundled logo, the JSON envelope/verdict/diagnostics log, and the SARIF emitter — this tool
supplies its finding/agent JSON shapes, layouts, and SARIF driver metadata), and `cli.py` uses
`coop_review_core.cliutils` (display paths, TTY/color detection, extra-report sinks, the config
write-back rule, the `syntax_errors` policy, the UTF-8 console shim, the shared `upgrade`/`update`
body) plus `coop_review_core.config`'s `discover_config`/`load_config_friendly`. Fix shared infra
in `coop-review-core`; keep the parser, rules, Rule/RuleContext/Result, and `standards.md` here.

```
.sql files → parse (sqlglot tsql AST + raw text + line numbers + comments) → rule engine → Findings + Diagnostics → render (text/json/markdown/html)
```

Pure core, side effects only at the CLI edge. Data flows as plain dataclasses.

- **`sql_common.py`** — text/AST helpers lifted from coop-data-doc, *extended* with the two
  things this tool needs and the lineage tool didn't: `split_batches_with_lines` (tracks each
  GO-batch's file start line) and `mask_noncode` (blanks comment/string content while preserving
  every character offset and newline, so regex rules scan code only and still map to exact lines).
- **`sql_model.py` / `parser.py`** — `parse_sql()` → `ParsedFile` holding batches+AST, comments,
  extracted `SqlObject`s (with typed `ColumnDef`s — from the CREATE TABLE column list, or for a
  CTAS synthesized from the projections' explicit `CAST`/`TRY_CAST`/`CONVERT` targets, issue
  #20), and diagnostics. Each batch is parsed via
  `sql_common.parse_batch_strict` (sqlglot at `RAISE` first to catch genuine syntax errors, then a
  tolerant `IGNORE` re-parse for partial analysis); `_record_parse_diagnostics` turns real errors
  into `syntax_error` diagnostics and known sqlglot grammar-gaps on valid T-SQL into
  `parse_degraded` warnings (see the sqlglot caveat below).
- **`finding.py` / `diagnostics.py`** — `Finding` (a standards deviation) vs `Diagnostic` (a
  *processing* problem: **real syntax error** (`syntax_error`, severity `error`), parse failure,
  opaque-command/grammar-gap degradation, rule crash, unreadable file). The `syntax_error` category
  is tool-local (core treats categories as open strings, like `scan_empty`).
- **`rules/`** — each rule is `sql_<name>.py` exporting `RULE = Rule(...)`; `rules/__init__.all_rules()`
  auto-discovers every `sql_*.py`. `rules/base.py` has `Rule` + `RuleContext`; `rules/helpers.py`
  has shared helpers (`enclosing_object`, `dml_target`, `projection_stars`) — neither is a rule
  module (names don't start with `sql_`).
- **`engine.py`** — runs every rule over every file; a rule that raises is isolated into a
  `Diagnostic`, never fatal. Sorts everything deterministically.
- **`standards.py`** — resolves the standards file (bundled `data/standards.md`, or `--standards`),
  computes its sha256 for the JSON, and applies an optional `rules.yml` (enable/disable + severity
  override, no rebuild needed).
- **`report.py`** — the agent JSON contract + the sectioned, colorizable console report
  (`console_lines`) + the Markdown (`to_markdown`) and branded self-contained HTML (`to_html`)
  reports + the `--log-file` text. The JSON carries `schema_version`, a `verdict`, `files_checked`,
  and a stable `fingerprint` per finding/agent-review item.
- **`suppressions.py`** — inline `coop-sql-review:ignore <RULE>` comments (the finding's line or the
  line above; bare/`*` = all) and a fingerprint **baseline** (`--write-baseline` / `--baseline`) for
  ratcheting on a legacy estate. Both filter findings **and `agent_review` items** in `check` before
  the `--min-severity` floor (`--write-baseline` records agent fingerprints too). Fingerprints are
  path- and line-free, and follow the **family identity rule** — IDENTICAL in coop-dax-review
  (which adds its `model` component) since schema_version 4 here / 3 there:
  `(rule_id, object-or-file-basename, fingerprint_key-or-message/note, occurrence ordinal)`.
  An empty `object` falls back to the file **basename** (object-less findings in different files
  don't collapse to one fingerprint); a rule whose message embeds volatile detail (counts, name
  lists) sets a stable `fingerprint_key` via `ctx.finding(fingerprint_key=...)` (no sql rule needs
  one yet — dax's three volatile-message rules do); and the **occurrence ordinal** (0-based,
  stamped by the engine in the deterministic sort order on the full pre-suppression result)
  discriminates N same-identity occurrences, so baselining a proc with one `SELECT *` never
  silently suppresses a FUTURE `SELECT *` added to it (issue #16's ratchet hole). Deliberate
  trade-off: adding/removing an occurrence above a same-identity sibling shifts the sibling's
  ordinal — it resurfaces and its old baseline entry goes stale **loudly**; unrelated line shifts
  and file moves still never change an identity. The SARIF `partialFingerprints` KEY stays frozen
  at `coopFingerprint/v2` (GitHub matches alerts by key+value; the values changed at v4, the label
  deliberately did not — see `report.py`).
- **`rules.yml` `ignore:` list** — a third, human-readable suppression: fingerprint-matched entries
  living in the writable `rules.yml` (`RuleConfig.ignored_fingerprints` from core). `check` filters
  findings and `agent_review` items right after the baseline block, before the `--min-severity`
  floor; an entry that matches no current finding **or agent-review item** emits an `IGNORE_STALE`
  diagnostic. `--save-ignores` runs an interactive checkbox
  (`cli._save_ignores_interactive` → `_pick_findings_to_ignore`, all unticked/opt-in; tool-specific
  `_finding_ignore_label`/`_finding_ignore_entry` builders) and appends the picks via
  `standards.add_ignores` (core's deterministic, LF, de-duped writer). Interactive-terminal only.

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

**sqlglot caveat — syntax errors vs grammar gaps (`syntax_error` detection).** Parsing at
`ErrorLevel.RAISE` catches genuinely invalid T-SQL (the 2026-07-06 escapes: a `CASE … ELSE END`
with no value → `Expected END after CASE`; a mangled `WITH` → `column does not support CTE`), but
sqlglot's tsql dialect is **not** a complete T-SQL grammar and also raises on some *valid*
constructs. `sql_common._is_sqlglot_gap` decides real-error vs gap **conservatively — genuine
breakage wins every tie** (a batch is a gap only when there is no un-representable statement, i.e.
no `None` in the tolerant recovery, *and* every error description is a known gap). Real errors
become `syntax_error` (severity `error`); known gaps become `parse_degraded` (severity `warning`),
so working estate SQL is never reported as broken and a misclassified real error is still surfaced
(as a warning) — never silent. The known valid-T-SQL gaps found on the fabric-dw estate
(2026-07-06, sqlglot 30.12.0), each recorded with its signature in `_description_is_gap`:
- **Compound assignment** — `SET @v += x` (and `-= *= /= %= &= |= ^=`) → `Required keyword: 'this'
  missing for …EQ/Neg…`. Detected by the `SET @v <op>=` construct in the batch.
- **`CLUSTERED`/`NONCLUSTERED` key or index** — `PRIMARY KEY CLUSTERED ([col] ASC)` → `Expecting )`
  + `'buckets' missing for …ClusteredByProperty`. Detected by the `CLUSTERED` keyword in the batch.
- **`OPENROWSET(BULK …)`** — the external-file query/ingest surface (GA on Fabric DW, Apr 2025):
  `SELECT … FROM OPENROWSET(BULK '…', FORMAT='PARQUET')` → `Expecting )` on the named-option arg
  list. Detected by the `OPENROWSET(` keyword. (Added 2026-07 Fabric-DW review.)
- **`OPTION (FOR TIMESTAMP AS OF '…')`** — statement-level time travel (GA): → `Unknown option FOR
  TIMESTAMP` + `Expecting )`, with the SELECT recovering cleanly. Detected by `FOR TIMESTAMP AS OF`.
- **`MASKED WITH (FUNCTION='…')`** — dynamic data masking in CREATE/ALTER TABLE: degrades the whole
  statement to an opaque `Command` with a lone `Expecting )`. Detected by the `MASKED WITH` keyword.
- **`EXEC('…' + @var)` / `EXEC(@a + @b)`** — a concatenated dynamic-execution argument →
  `Expecting )` on the `+` (recovery still yields the `Execute` node, so `had_none` stays False;
  a single-literal/-variable `EXEC(...)` parses fine and never reaches the classifier). Detected
  by the `EXEC(`/`EXECUTE(` construct. (Found during issue #19; the site also gets a
  `dynamic_sql` diagnostic either way.)
- **Procedure/function bodies** sqlglot can only partially parse — a lone generic
  `Invalid expression / Unexpected token` with no `None` in recovery (e.g. `SET NOCOUNT ON;` before
  a trailing `UPDATE … END`). The mangled-CTE-in-a-proc incident (2026-07-06) is **not**
  a gap: it raises the definitive `column does not support CTE` alongside the generic message.

When a new estate false-positive appears (a valid construct reported as `syntax_error`), reproduce
it minimally, add a precise signature to `_description_is_gap` (or the operator/keyword regexes),
and record it here. The escape hatches for one-off cases: the `rules.yml` `syntax_errors:
error|warning|off` knob (global) and an inline `-- coop-sql-review:ignore syntax` directive (one
line). Re-validate the whole estate (§ below) after any change to the classifier.

## Error handling (project requirement)

Never swallow errors. Real syntax errors (`syntax_error`, severity `error`), parse failures,
opaque-command/grammar-gap degradations, dynamic-execution sites (`dynamic_sql`, severity
`warning` — string-built statements no rule can see; the `EXEC(`/`sp_executesql` scan in
`parser.py`, tunable via the rules.yml `dynamic_sql: error|warning|off` knob), and rule crashes
become `Diagnostic`s that are shown in the console report AND the JSON (`"diagnostics"` key) on
every run, and can be captured with `check --log-file <path>`. Keep messages specific and actionable (file:line + what happened + what
it means) so the user can fix the cause. Syntax-error diagnostic messages are **ASCII-only and
single-line** (they use sqlglot's structured `description`/`line`/`col`, never its rendered message
with ANSI underlines and a SQL snippet) so JSON stays deterministic and the console stays
cp1252-safe. A `syntax_error` demoted by `syntax_errors: warning` or `ignore syntax` must still be
visible in JSON unless set to `off` — a coverage gap is never silent.

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
- **Reads:** `.sql` files are read BOM-aware via `cli._decode_sql_bytes`: a UTF-16/32 BOM selects
  that codec (SSMS "Save with Encoding: Unicode" files are linted normally); everything else is
  `utf-8-sig`. Invalid bytes still decode (with replacements) but surface a `file_unreadable`
  warning diagnostic; NUL-riddled text (UTF-16 saved without a BOM, or binary) is skipped with an
  error diagnostic instead of parsing into garbage — a coverage gap is never silent, and reads
  never crash.
- **Paths:** findings show POSIX paths (`_display_path` → `.as_posix()`, relative to cwd when
  possible) so output is identical across OSes; cross-drive paths fall back to absolute.
- CI runs the full matrix on **ubuntu AND windows** × py3.10–3.13 — keep `ruff format --check`
  green (easy to forget locally).
- There are Windows-specific tests in `tests/test_windows.py` (CRLF line numbers, ASCII chrome,
  ASCII JSON) — extend them when adding output paths.
- **No filesystem symlinks in this repo, ever** — the team checks out on Windows.

## Source documents

- `SPEC.md` — architecture, CLI, agent JSON contract, milestones M0–M6.
- `RULES.md` — full rule taxonomy (deterministic vs agent-judgment, by tier).
- `docs/standards.md` — the §-numbered standards (also bundled at `src/coop_sql_review/data/standards.md`).
- `docs/standards-proposed-additions.md` — MS/community best practices to consider (M5).
- `PUBLISHING.md` — one-time GitHub/PyPI setup + the tag-driven release steps.
- `CHANGELOG.md` — Keep-a-Changelog format; every release gets a `## [x.y.z]` entry
  (`make release-check` enforces this).
- The company CLI playbook — shared CLI conventions; the `coop-data-doc` tool — the reference
  implementation the skeleton + SQL helpers were lifted from.

## Working the backlog (agents)

This repo's work queue is its GitHub issues labeled **`agent:ready`**:
`gh issue list --label agent:ready --state open`. Each issue is self-contained
(Context / Problem / Proposed fix / Acceptance criteria). Rules of engagement:

- Read this file fully first; take ONE issue at a time (oldest first unless one
  blocks another).
- Implement to the acceptance criteria; run the full test suite + lint before
  every commit; commit with `Fixes #N` so the issue closes on push.
- Never push tags, release, or bump versions — Aaron releases (see the release
  rules above).
- An open issue WITHOUT the `agent:ready` label is waiting on a human decision —
  leave it alone.
- Fingerprint-identity changes are a FAMILY affair: coop-sql-review and
  coop-dax-review share one identity construction (see `suppressions.py` above)
  and must bump together (as #16 + dax#14 did), never fork.
