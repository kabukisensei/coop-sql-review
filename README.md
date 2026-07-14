# coop-sql-review

A friendly tool that **reads your `.sql` files and points out anything that doesn't follow our
SQL standards** for the Fabric data warehouse (and Azure serverless SQL — pick the target with
`--target`, see section 4). It is **advisory only** — it never changes,
rejects, or deletes anything. It just prints a report so you can fix things before committing.

It works completely **offline** (your SQL never leaves your machine) and runs the same on
**Windows and Mac**.

Part of the Cooptimize **coop suite** — if your team uses
[coop-agent](https://github.com/kabukisensei/coop-agent), `coop install` installs this plus the
sibling tools ([coop-dax-review](https://github.com/kabukisensei/coop-dax-review),
[coop-data-doc](https://github.com/kabukisensei/coop-data-doc)); `coop update` keeps them
current.

---

## 1. What you need first

- **Python 3.10 or newer.** To check what you have, open a terminal (see below) and type:
  ```
  python --version
  ```
  If that says 3.10 or higher, you're set. If it says "command not found" or an older version,
  install Python from https://www.python.org/downloads/ (tick *"Add Python to PATH"* on Windows).

- **How to open a terminal:**
  - **Windows:** press the Start button, type `Terminal`, press Enter.
  - **Mac:** press `Cmd+Space`, type `Terminal`, press Enter.

You'll type commands at the blinking prompt and press Enter after each one.

---

## 2. Install it (one time)

We use **pipx**, which keeps the tool tidy and separate from everything else on your machine.

**Step 1 — install pipx** (skip if you already have it):
```
python -m pip install --user pipx
python -m pipx ensurepath
```
**Close and reopen your terminal** after this (so it picks up the new command).

**Step 2 — install coop-sql-review:**
```
pipx install coop-sql-review
```

**Check it worked:**
```
coop-sql-review --version
```
You should see a version number like `coop-sql-review, version 0.2.0`.

> Want the very latest unreleased build instead of the PyPI release? Install straight from the
> repository:
> ```
> pipx install git+https://github.com/kabukisensei/coop-sql-review.git
> ```

---

## 3. Use it

The main command is **`check`**. Point it at a file or a folder of `.sql` files.

**Check one file:**
```
coop-sql-review check path/to/my_query.sql
```

**Check a whole folder** (it looks in sub-folders too):
```
coop-sql-review check path/to/sql-folder
```

> **Tip (don't know the path?)** Type `coop-sql-review check ` (with a trailing space), then
> **drag the file or folder from your file explorer onto the terminal window** — it pastes the
> path for you. Then press Enter.

**Or just run `coop-sql-review check` with no folder** (from inside your SQL repo). In a terminal
it shows a checklist of the folders in the current directory — everything's pre-selected, so press
**Enter** to scan it all, or use the arrow keys + **Space** to pick just the folders you want.

That's it. The tool prints a report and **always finishes successfully** — it won't block you.

---

## 4. Reading the report

A typical report looks like this:

```
========================================================================
  coop-sql-review                                   SQL standards report
========================================================================
  standards: standards.md    files checked: 1    v0.7.1

  silver/dim_customer.sql
  ----------------------------------------------------------------------
   WARN  SQL-NO-ALTER-COLUMN  §9   silver.dim_customer
         silver/dim_customer.sql:4
         ALTER COLUMN is Preview in Fabric DW — confirm the specific
         change is supported, or use the CTAS + RENAME workaround (§9).
   WARN  SQL-NO-SELECT-STAR  §11   silver.dim_customer
         silver/dim_customer.sql:12
         SELECT * in production code — list the columns explicitly
         (§11).

========================================================================
  SUMMARY    0 error   2 warning   0 info

  Findings by rule
   1  SQL-NO-ALTER-COLUMN  [warning]
   1  SQL-NO-SELECT-STAR  [warning]
========================================================================
  Advisory only - nothing was changed or blocked.
```

- Findings are grouped into a **section per file**. Each one shows a **severity badge**
  (`ERROR`/`WARN`/`INFO`), the **rule** that fired and the **§ section** of the standards, then the
  **`file:line`** location and the message. At a terminal the report is colorized; piped or
  redirected (or with `--no-color`, or `NO_COLOR` set) it falls back to plain text.
- The SUMMARY also totals **findings by rule** (noisiest first), so you can see at a glance
  *which* rule to tune when one dominates — and when a single rule racks up many findings, a
  one-line tip points you at the per-rule knobs in `rules.yml` (see §7). The Markdown and HTML
  reports carry the same "Findings by rule" section.
- **Severities:**
  - **error** — almost certainly broken. No bundled rule ships at this level today (you can raise
    any rule to `error` in `rules.yml`); a genuinely invalid file surfaces as an error-level
    `syntax_error` *diagnostic* instead (see below).
  - **warning** — against the standard; worth fixing.
  - **info** — a style/nice-to-have suggestion.
- **Diagnostics** (a separate section, if shown) are *processing* notes — e.g. "this statement
  uses syntax we couldn't fully read." They tell you where the tool's checking may be incomplete,
  so nothing fails silently.
  - A **`syntax_error`** diagnostic (severity **error**) means the SQL is *genuinely invalid* — a
    real T-SQL parser rejects it, so it would fail Fabric's import ("Incorrect syntax near …").
    It names the exact line. This is the tool's pre-push safety net for a mangled edit (a `CASE …
    ELSE END` with no value, a `WITH` chain broken by a bad find-and-replace). If you ever hit a
    false alarm on SQL you know is valid, see §7 (the `syntax_errors` knob) and §9 (`ignore syntax`).
- **Agent review** — a few checks (like "is this MERGE the right choice?") need human/agent
  judgment, so they're listed separately rather than flagged as pass/fail.

**Show only the important stuff** (hide the info-level suggestions):
```
coop-sql-review check sql-folder --min-severity warning
```

**Checking Azure SQL instead of Fabric?** Some rules flag things that only matter on Fabric
Data Warehouse: table types it doesn't allow (like `money`, `nvarchar`, `tinyint`, `xml`),
`ALTER COLUMN` (Preview there, plain T-SQL on Azure SQL), and the Fabric-only
`OPTION(LABEL=…)` hint — but Azure (serverless) SQL is fine with all of those. Add
`--target azure-sql` to skip the Fabric-only rules:
```
coop-sql-review check sql-folder --target azure-sql
```
(The default is `--target fabric-dw`. You can also put `target: azure-sql` in your `rules.yml`.)

**Big folder? Save the report to a file** so you can scroll/search it instead of watching it fly
past (a progress bar shows while it scans):
```
coop-sql-review check sql-folder --output review.html --format html
```
The tool **prints the full path** to the file it wrote and — when you're in a terminal —
**opens the HTML report in your browser automatically** (a clean, Cooptimize-branded,
self-contained page; no internet needed). Add `--no-open` if you'd rather it didn't.
You can also use `--format markdown` (open `review.md` in any editor) or plain `--output
review.txt`.

**Want a file *and* the report on screen?** `--html <file>`, `--md <file>`, and `--sarif <file>`
write an extra copy alongside whatever you're already doing (they compose with `--format`, and
unlike `--output --format html` they never open a browser) — handy for saving an artifact while
still reading the report in your terminal:
```
coop-sql-review check sql-folder --html review.html --md review.md
```

**Annotate a pull request in CI (GitHub / Azure DevOps).** `--format sarif` emits a standard
**SARIF 2.1.0** report that GitHub code scanning (and Azure DevOps) turn into inline PR
annotations on the exact lines. A ready-to-paste GitHub Actions step:
```yaml
    - name: SQL standards review
      run: coop-sql-review check sql/ --format sarif -o coop-sql-review.sarif
    - name: Upload SARIF
      uses: github/codeql-action/upload-sarif@v3
      with:
        sarif_file: coop-sql-review.sarif
```
The tool stays advisory (exit 0) unless you add `--strict`, so the SARIF annotations appear
without failing the build — add `--strict` if you want the build to go red on remaining findings.

---

## 5. All the commands

| Command | What it does |
|---|---|
| `coop-sql-review check [paths...]` | Check files/folders against the standards (the main command). |
| `coop-sql-review rules` | List every rule it checks, with severity and tier. Add `--format json` for a machine-readable inventory (id, title, severity, category, standard_ref, tier, kind, default_enabled). |
| `coop-sql-review help` | Show help. `help check` shows help for one command. |
| `coop-sql-review update` | Check for a newer version and print the command to upgrade (same as `upgrade`). |
| `coop-sql-review upgrade` | Check for a newer version and print the command to upgrade. |
| `coop-sql-review --version` | Show the installed version. |

### Options for `check`

| Option | Meaning |
|---|---|
| `-o`, `--output <file>` | Write the report to a file instead of the screen (best for big runs). |
| `--html <file>` | *Also* write a self-contained HTML report to this file (composes with `--format`; it's an extra copy, and never opens a browser). |
| `--md <file>` | *Also* write a Markdown report to this file (composes with `--format`; an extra copy). |
| `--format text\|json\|markdown\|html` | `text` (default) for the screen, `html` for a clean browser report (always written to a file — `coop-sql-review-report.html` in the current folder unless you give `-o`), `markdown` for a readable file, `json` for tools/the agent. |
| `--open` / `--no-open` | Whether to open an HTML report in your browser when it's written. Default: opens automatically when you're in a terminal; `--no-open` to skip. |
| `--color` / `--no-color` | Force colored or plain text output. Default: auto — colored at a terminal, plain when piped or redirected (also honors `NO_COLOR`). |
| `--min-severity error\|warning\|info` | Hide findings below this level. Default `info` (show all). |
| `--baseline <file>` | Hide findings **and agent-review items** already recorded in this baseline file — only **new** ones appear (see §9). |
| `--write-baseline <file>` | Record the current findings and agent-review items to this baseline file (then report as usual). |
| `--save-ignores` | After the report, interactively tick findings to add to your `rules.yml` ignore list, so they're silenced next run (see §9). |
| `--standards <file>` | Check against a specific standards file (default: the built-in copy). |
| `--config <file.yml>` | Turn rules on/off, change their severity, or list ignored findings (see §7). A `coop-sql-review.yml` (or `rules.yml`) in the current folder — or a parent folder, or named by the `COOP_SQL_REVIEW_CONFIG` environment variable — is picked up automatically, so `--config` is optional. (A `--config` path that doesn't exist is an error, so a typo can't silently drop your overrides.) |
| `--log-file <file>` | Also write the diagnostics (parse problems, errors) to a file. |
| `--strict` | Exit with an error code if any finding **at or above `--min-severity`** remains — for CI gates (see §6). Also fails on a **real syntax error** (or any other error-level diagnostic, e.g. an unreadable file) and when **no `.sql` files were checked at all**, so a typo'd path or a broken file can't pass silently. |
| `--dialect <name>` | SQL dialect to parse (default `tsql`, which fits Fabric). |

Run `coop-sql-review rules` any time to see the current full list of checks.

---

## 6. Use it in CI (optional)

By default the tool **never fails a build** (it's advisory). If a team *wants* a gate, add
`--strict` with a severity floor — it then exits with an error code when something at/above that
level is found, when a **real syntax error** is detected (invalid SQL that would fail Fabric's
import), **or when no `.sql` files were found/checked at all** (so a typo'd folder path fails the
gate instead of passing as “clean”):

```
coop-sql-review check sql-folder --strict --min-severity warning
```

For a machine-readable report (e.g. to attach to a build or feed the company agent):
```
coop-sql-review check sql-folder --format json > sql-review.json
```

---

## 7. Customising the rules (optional)

Create a small `rules.yml` to turn rules on/off or change their severity — no reinstall needed:

```yaml
rules:
  SQL-DISTINCT-SMELL:
    enabled: false            # turn a rule off
  SQL-NO-SELECT-STAR:
    severity: error           # treat SELECT * as an error instead of a warning
  SQL-TABLE-LAYER-NAME:
    enabled: true             # turn ON a rule that's off by default
```

Then:
```
coop-sql-review check sql-folder --config rules.yml
```

> **Tip:** the config file is picked up **automatically** — you can drop the `--config` flag
> entirely. The tool looks for a `coop-sql-review.yml` (preferred name), then a `rules.yml`, in
> the folder you run from and then its parent folders (stopping at your repo's root). You can
> also point the `COOP_SQL_REVIEW_CONFIG` environment variable at a config file — handy in CI.
> The shared `rules.yml` name still works everywhere it used to, but every coop-\*-review tool
> reads it; renaming yours to `coop-sql-review.yml` makes it specific to this tool (the tool
> prints a gentle reminder when it finds a `rules.yml`).

**Some rules ship turned off by default** because they're noisy on estates with different house
styles — turn any on in `rules.yml` (as above) if your team follows that convention:
- `SQL-HEADER-COMMENT` (§10) — every file must start with a File/Purpose/… header block.
- `SQL-TABLE-LAYER-NAME` (§1) — tables/views must live in a `bronze`/`silver`/`gold` schema.
- `SQL-CTE-PREFIX` (§1) — CTE names must start with `cte_`.
- `SQL-ALIAS-DESCRIPTIVE` (§2) — table aliases must be 3+ char descriptive abbreviations.
- `SQL-INSERT-ALIAS-MATCH` (§3) — each `INSERT…SELECT` column must be aliased `AS <target>`.
- `SQL-QUERY-LABEL` (§9) — ETL inserts should carry `OPTION(LABEL=…)`.
- `SQL-FILTER-UPSTREAM` (§8) — join+WHERE queries the reviewing agent should consider
  filtering upstream. Nearly every production SELECT has this shape, so on a real estate the
  rule flooded the agent-review list; when you turn it on, it reports one line per
  procedure/object (with a count) rather than one per query.

Run `coop-sql-review rules` to see which rules are off by default (marked `[off by default]`).

**Real syntax errors** (invalid SQL a T-SQL parser rejects) are reported as `error`-level
diagnostics by default. If your estate uses valid T-SQL the underlying parser can't handle and you
get a false alarm, dial it down with a top-level `syntax_errors:` key in `rules.yml`:

```yaml
syntax_errors: warning   # error (default) | warning (demote but keep) | off (hide)
```

`warning` still shows the line in the report and JSON (just not as an error, so it won't fail
`--strict`); `off` hides it entirely. To silence a single spot instead, use the inline
`ignore syntax` comment in §9.

**Dynamic SQL** (`EXEC('…')`, `EXEC(@sql)`, `sp_executesql`) can't be checked — statements
built in strings are invisible to every rule. So the tool never pretends it looked: each
dynamic-execution site is reported as a `dynamic_sql` **warning diagnostic** (a plain
procedure call like `EXEC silver.usp_x` is *not* flagged). Tune it with a top-level
`dynamic_sql:` key in `rules.yml`, same shape as `syntax_errors:`:

```yaml
dynamic_sql: off   # warning (default) | error (fail --strict on it) | off (hide)
```

To check against the team's canonical standards file directly:
```
coop-sql-review check sql-folder --standards path/to/sql-standards.md
```

---

## 8. Keeping it up to date

```
coop-sql-review update
```
This checks whether a newer version exists and **prints the exact command to run** to upgrade
(for most people: `pipx upgrade coop-sql-review`). It's the only command that uses the internet.

It doesn't upgrade in place: a program can't reliably replace its own files while it's running,
so just **open a new terminal and run the command it shows you**. (`update` and `upgrade` are the
same command; add `--check` to only report whether an update is available, without printing the
upgrade command.)

---

## 9. Adopting on an existing code base (suppressions)

Three deterministic, never-blocking ways to silence findings you've already triaged, so a legacy
estate doesn't make every run noisy. All three also cover **agent-review items** (constructs
flagged for the analytics agent, like a `MERGE` detected by `SQL-UPSERT-CHOICE`) — an accepted
construct isn't re-raised on every run:

- **Inline** — a comment on a finding's line (or the line directly above it):
  ```sql
  -- coop-sql-review:ignore SQL-NO-SELECT-STAR reason: legacy view, rewrite scheduled
  SELECT * FROM dbo.legacy_view;
  ```
  List several rule ids (`ignore SQL-A, SQL-B`), or a bare `ignore` / `*` to silence every rule on
  that line. The `reason:` text is for humans; the parser ignores it. To silence a **real syntax
  error** on a line you know is fine (a parser false alarm), use the keyword `syntax`:
  ```sql
  -- coop-sql-review:ignore syntax reason: valid T-SQL the parser can't read
  SET @rows += 1;
  ```
- **Baseline (ratchet)** — record today's findings and agent-review items, then surface only *new* ones:
  ```sh
  coop-sql-review check sql-folder --write-baseline sql-baseline.json   # once, to capture the status quo
  coop-sql-review check sql-folder --baseline sql-baseline.json         # thereafter: only new findings appear
  ```
  The baseline keys on each finding's stable `fingerprint` (also in the JSON), which is independent
  of line numbers **and file paths** — edits above a statement don't disturb it, and neither does
  running the tool from a different folder (or machine) than the one that wrote the baseline. A
  baseline entry that no longer matches anything (you fixed it) is reported as a diagnostic;
  re-run `--write-baseline` to prune. Repeats of the same issue inside one object each get their
  own fingerprint (numbered in file order), so a baseline never hides a *new* repeat added later.

  > **One-time migration (schema_version 4):** the fingerprint identity changed in this release
  > (an occurrence ordinal now discriminates repeats — coordinated with coop-dax-review's
  > schema 3, one family rule). Delete and regenerate any baseline files and `rules.yml`
  > `ignore:` lists written by earlier versions once:
  > `coop-sql-review check <paths> --write-baseline baseline.json` and re-run
  > `coop-sql-review check <paths> --save-ignores`. Until then, old entries are reported loudly
  > as stale diagnostics on every run — nothing goes silently missing.
- **`rules.yml` ignore list** — a human-readable list of individual findings to silence, kept
  right in your `rules.yml` (the one file you edit). Add an `ignore:` block of fingerprints:
  ```yaml
  ignore:
    - fingerprint: 1a2b3c4d5e6f      # from the JSON output (each finding carries one)
      rule: SQL-NO-SELECT-STAR       # optional, for humans
      where: silver/dim_customer.sql:12
      note: legacy view, rewrite scheduled
  ```
  The easy way to build it: run `check` with **`--save-ignores`** — after the report, it shows a
  checkbox of this run's findings (all unticked), and the ones you tick are written into your
  `rules.yml` ignore list for you:
  ```
  coop-sql-review check sql-folder --save-ignores
  ```
  Re-run and they're gone. Like the baseline, an ignore entry that no longer matches any current
  finding is flagged as a diagnostic (`rules.yml ignore: ... no longer match`) so the list doesn't
  quietly rot. (If a `rules.yml` sits in the current folder it's found automatically; otherwise
  point `--config` at it. `--save-ignores` needs an interactive terminal.)

---

## 10. Troubleshooting

- **`coop-sql-review: command not found`** — you likely skipped `pipx ensurepath`, or didn't
  reopen the terminal. Run `python -m pipx ensurepath`, then close and reopen the terminal.
- **`externally-managed-environment` error on install** — that's why we use **pipx** (above)
  instead of plain `pip`. Use the pipx steps in §2.
- **It conflicts with another tool's packages** — pipx isolates coop-sql-review so this shouldn't
  happen; if you installed with plain `pip`, uninstall and reinstall with pipx.
- **Windows: odd characters in the report** — the tool prints UTF-8 and is tested on Windows; if
  your console looks garbled, use Windows Terminal (the default on Windows 11).
- **"No .sql files found"** — double-check the folder path; the tool only reads files ending in
  `.sql`. The report still renders (with `files checked: 0` and a `scan_empty` diagnostic), and
  `--strict` treats a zero-file run as a failure.

---

## For developers & AI agents

- Architecture, the rule engine, and how to add a rule: see **`AGENTS.md`** (the canonical
  agent/developer guide; `CLAUDE.md` just imports it).
- What to build and why: **`SPEC.md`**; the full rule taxonomy: **`RULES.md`**.
- The standards being enforced: **`docs/standards.md`** (bundled with the tool).
- Run the tests: `make test` (= `PYTHONPATH=src python -m pytest -q`) · lint: `make lint`.

This tool reuses the proven skeleton and conventions from the company's `coop-data-doc` tool
and shared CLI playbook.
