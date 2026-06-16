# coop-sql-review

A friendly tool that **reads your `.sql` files and points out anything that doesn't follow our
SQL standards** for the Fabric data warehouse. It is **advisory only** — it never changes,
rejects, or deletes anything. It just prints a report so you can fix things before committing.

It works completely **offline** (your SQL never leaves your machine) and runs the same on
**Windows and Mac**.

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
You should see a version number like `coop-sql-review, version 0.1.0`.

> Not published to PyPI yet? Install straight from the repository instead:
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

That's it. The tool prints a report and **always finishes successfully** — it won't block you.

---

## 4. Reading the report

A typical report looks like this:

```
silver/dim_customer.sql
  ! silver/dim_customer.sql:12  [warning] SQL-NO-SELECT-STAR (§11)
      SELECT * in production code — list the columns explicitly (§11).
  x silver/dim_customer.sql:4   [error] SQL-NO-ALTER-COLUMN (§9)
      ALTER COLUMN is not supported in Fabric DW — use the CTAS + RENAME workaround (§9).

Checked 1 file(s): 1 error, 1 warning.
Advisory only - nothing was changed or blocked.
```

- Each line shows **`file:line`**, a **severity**, the **rule** that fired, and the **§ section**
  of the standards it comes from.
- **Severities:**
  - **error** — almost certainly broken in Fabric (e.g. `ALTER COLUMN`, which Fabric rejects).
  - **warning** — against the standard; worth fixing.
  - **info** — a style/nice-to-have suggestion.
- **Diagnostics** (a separate section, if shown) are *processing* notes — e.g. "this statement
  uses syntax we couldn't fully read." They tell you where the tool's checking may be incomplete,
  so nothing fails silently.
- **Agent review** — a few checks (like "is this MERGE the right choice?") need human/agent
  judgment, so they're listed separately rather than flagged as pass/fail.

**Show only the important stuff** (hide the info-level suggestions):
```
coop-sql-review check sql-folder --min-severity warning
```

---

## 5. All the commands

| Command | What it does |
|---|---|
| `coop-sql-review check [paths...]` | Check files/folders against the standards (the main command). |
| `coop-sql-review rules` | List every rule it checks, with severity and tier. |
| `coop-sql-review help` | Show help. `help check` shows help for one command. |
| `coop-sql-review update` | Update the tool to the newest version (same as `upgrade`). |
| `coop-sql-review upgrade` | Update the tool to the newest version. |
| `coop-sql-review --version` | Show the installed version. |

### Options for `check`

| Option | Meaning |
|---|---|
| `--min-severity error\|warning\|info` | Hide findings below this level. Default `info` (show all). |
| `--format text\|json` | `text` (default) for humans, `json` for tools/the agent. |
| `--standards <file>` | Check against a specific standards file (default: the built-in copy). |
| `--config <rules.yml>` | Turn rules on/off or change their severity (see §7). |
| `--log-file <file>` | Also write the diagnostics (parse problems, errors) to a file. |
| `--strict` | Exit with an error code if any finding **at or above `--min-severity`** remains — for CI gates (see §6). |
| `--dialect <name>` | SQL dialect to parse (default `tsql`, which fits Fabric). |

Run `coop-sql-review rules` any time to see the current full list of checks.

---

## 6. Use it in CI (optional)

By default the tool **never fails a build** (it's advisory). If a team *wants* a gate, add
`--strict` with a severity floor — it then exits with an error code when something at/above that
level is found:

```
coop-sql-review check sql-folder --strict --min-severity warning
```

For a machine-readable report (e.g. to attach to a build or feed the company agent):
```
coop-sql-review check sql-folder --format json > sql-review.json
```

---

## 7. Customising the rules (optional)

Create a small `rules.yml` to disable a rule or change its severity — no reinstall needed:

```yaml
rules:
  SQL-DISTINCT-SMELL:
    enabled: false          # turn this rule off
  SQL-NO-SELECT-STAR:
    severity: error         # treat SELECT * as an error instead of a warning
```

Then:
```
coop-sql-review check sql-folder --config rules.yml
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
This updates the tool (and safe dependency updates) to the latest version. It's the only command
that uses the internet.

---

## 9. Troubleshooting

- **`coop-sql-review: command not found`** — you likely skipped `pipx ensurepath`, or didn't
  reopen the terminal. Run `python -m pipx ensurepath`, then close and reopen the terminal.
- **`externally-managed-environment` error on install** — that's why we use **pipx** (above)
  instead of plain `pip`. Use the pipx steps in §2.
- **It conflicts with another tool's packages** — pipx isolates coop-sql-review so this shouldn't
  happen; if you installed with plain `pip`, uninstall and reinstall with pipx.
- **Windows: odd characters in the report** — the tool prints UTF-8 and is tested on Windows; if
  your console looks garbled, use Windows Terminal (the default on Windows 11).
- **"No .sql files found"** — double-check the folder path; the tool only reads files ending in
  `.sql`.

---

## For developers & AI agents

- Architecture, the rule engine, and how to add a rule: see **`CLAUDE.md`**.
- What to build and why: **`SPEC.md`**; the full rule taxonomy: **`RULES.md`**.
- The standards being enforced: **`docs/standards.md`** (bundled with the tool).
- Run the tests: `PYTHONPATH=src python -m pytest -q` · lint: `ruff check src tests`.

This tool reuses the proven skeleton and conventions from the company's `coop-data-doc` tool
and shared CLI playbook.
