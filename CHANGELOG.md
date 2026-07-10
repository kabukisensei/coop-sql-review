# Changelog

All notable changes to **coop-sql-review** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses [semantic versioning](https://semver.org/).
The JSON output is a machine contract (`schema_version`); breaking changes to its shape bump that
field and are called out here.

## [0.10.0] — 2026-07-09
### Added
- **The §9 type rules now see CTAS projections** (issue #20). `CREATE TABLE ... AS SELECT
  CAST(x AS money) AS Amount ...` creates a persisted `money` column exactly as a column list
  would, but produced no `SQL-TYPE-*` finding — the estate's most idiomatic table-creation
  path (the one the tool itself recommends via `SQL-CTAS-EXPLICIT-CAST` and the ALTER COLUMN
  workaround) was invisible to the type rules. The parser now synthesizes `ColumnDef`s from a
  CTAS's explicit `CAST`/`TRY_CAST`/`CONVERT` projection targets (alias as the column name,
  the cast's line), so all five type rules — and the in-file size maps behind
  `SQL-NARROWING-CAST`/`SQL-IMPLICIT-CONVERT` — cover CTAS tables, including set-operation
  bodies (left branch) and CTAS inside proc bodies. Uncast projections stay un-typed (no
  guessing — that remains `SQL-CTAS-EXPLICIT-CAST`'s territory); plain column-list behavior
  and finding counts are unchanged; `--target azure-sql` still skips the Fabric-only rules.
- **Dynamic SQL is no longer a silent blind spot** (issue #19). Statements built in strings
  (`EXEC('...')`, `EXEC(@sql)`, `sp_executesql`) are invisible to every rule — and the tool
  used to say nothing about them. Each dynamic-execution site now surfaces as a `dynamic_sql`
  **warning diagnostic** (console, JSON `diagnostics`, `--log-file`), with the file and line.
  A plain procedure invocation (`EXEC silver.usp_x`) is not flagged, and mentions inside
  comments/strings can't trip the scan (it runs over the masked text). Tunable via a
  top-level `dynamic_sql: error|warning|off` key in `rules.yml` (default `warning`; `error`
  makes `--strict` gate on it; `off` hides it) — same shape as the `syntax_errors:` knob.
- **"Findings by rule" triage table** (issue #18). The console SUMMARY, the Markdown report,
  and the HTML report now break the finding counts down per rule (noisiest first, then rule
  id) — the actionable next step (`rules.yml` `enabled: false` / a severity override /
  `ignore:`) is per-rule, so the report says which rule to tune without eyeballing every file
  section. When one rule reaches 10+ findings, a one-line tip points at the `rules.yml` knobs
  (README section 7). Chrome stays ASCII and deterministic; the JSON contract is unchanged.

### Changed
- **BREAKING (one-time): the family fingerprint identity rule — JSON `schema_version` → 4**
  (issue #16; landed together with coop-dax-review#14, whose `schema_version` goes 2 → 3 with the
  **identical** construction — the family's identity rules are in lockstep again). A fingerprint
  is now `(rule_id, object-or-file-basename, fingerprint_key-or-message, occurrence ordinal)`:
  - **Occurrence ordinal** (the ratchet fix): a constant-message rule's N occurrences inside one
    object used to collapse to ONE fingerprint, so baselining a proc with one `SELECT *` silently
    suppressed every *future* `SELECT *` added to it. Occurrences are now numbered 0, 1, 2, ... in
    the deterministic sort order (stamped on the full pre-suppression result); the first
    occurrence keeps ordinal 0. Deliberate trade-off: adding/removing an occurrence *above* a
    same-identity sibling shifts the sibling's ordinal — it resurfaces (and its old baseline entry
    is reported stale, loudly); unrelated line shifts and file moves still never change an
    identity.
  - **`Finding.fingerprint_key`** (optional; empty = the message is the identity, the default): a
    rule whose display message embeds volatile detail (counts, name lists) can expose a stable
    identity core via `ctx.finding(fingerprint_key=...)`. No coop-sql-review rule needs it today;
    it exists so the family construction stays identical to coop-dax-review, whose three
    volatile-message rules set it.
  - The SARIF `partialFingerprints` KEY stays frozen at `coopFingerprint/v2` — GitHub code
    scanning matches alerts by (key, value); the *values* change with this bump (existing alerts
    close and re-open once), but the label deliberately survives so any future key change remains
    an explicit choice.

  **Migration (one-time):** every pre-v4 fingerprint stops matching — regenerate baselines and
  saved ignores once: re-run `coop-sql-review check <paths> --write-baseline baseline.json`, and
  rebuild the `rules.yml` `ignore:` list with `coop-sql-review check <paths> --save-ignores` (or
  delete the stale entries by hand). Until then the old entries surface **loudly** as `baseline` /
  `ignore_stale` warning diagnostics on every run — never a silent mismatch. Same playbook as the
  v2 (0.5.0) and v3 (0.7.0) bumps.
- **`SQL-FILTER-UPSTREAM` no longer drowns the agent-review channel** (issue #17). JOIN+WHERE
  is the shape of nearly every production SELECT, so this one rule's identical boilerplate was
  ~90% of all agent-review items on a real estate. Two changes: the rule now ships **off by
  default** (enable via `rules.yml` like the other noisy-on-real-estates rules), and when
  enabled its items are **collapsed to one per enclosing object** — the note carries the
  count ("N join+WHERE queries in this object ..."), the line points at the first qualifying
  SELECT, and a single-SELECT object keeps the original note verbatim (those fingerprints are
  unchanged).

### Fixed
- **`EXEC('...' + @var)` is no longer misreported as a syntax error** (found during issue
  #19). A concatenated dynamic-execution argument is valid T-SQL that sqlglot cannot parse;
  it now classifies as a `parse_degraded` grammar-gap warning (plus the new `dynamic_sql`
  diagnostic) instead of an error-severity `syntax_error` that would fail `--strict` on
  working estate SQL.
- **`--strict` help now names all three exit-2 conditions** (issue #18): findings at/above
  `--min-severity`, any remaining error-severity diagnostic (a real syntax error, a rule
  crash, an unreadable file), and zero files checked. The gate itself is unchanged — the
  README documented it, but a CI author reading `--help` couldn't predict that a syntax error
  fails the build. (The third part of issue #18 — reading `rules.yml` only once per run — had
  already landed with the core 0.4.0 adoption; a regression test now locks it in.)
- **`SQL-SARGABILITY` no longer contradicts `SQL-JOIN-FILTER` on COALESCE key-alignment
  joins** (issue #15). The key-alignment tolerance (`COALESCE`/`CAST`/`CONVERT`/`COLLATE`
  containing only key material, nesting included) now lives once in `rules/helpers.py`
  (`is_alignment_subtree`) and is shared by both rules: a join predicate like
  `ON COALESCE(a.id, 0) = COALESCE(b.id, 0)` — which `SQL-JOIN-FILTER` documents as
  idiomatic — is no longer flagged by `SQL-SARGABILITY` by default. Teams that want the
  strict statistics story can set `params: {flag_alignment_joins: true}` on the rule.
  Genuine join-key hits (`ON YEAR(a.d) = b.y`) still fire but now carry a join-oriented
  message ("align the key types/values upstream ... and join on bare keys") instead of the
  WHERE-clause advice ("filter the bare column with a range"), which made no sense for a
  join key. NB: the message change means join-site `SQL-SARGABILITY` findings get new
  fingerprints — re-run `--write-baseline` if you baseline them. `WHERE` behavior is
  unchanged.
- **Aliased updates are attributed to the real table, not the alias** (issue #14). For the
  idiomatic T-SQL form `UPDATE d SET ... FROM silver.dim_customer AS d JOIN ...`,
  `dml_target` now resolves the bare alias through the statement's FROM/JOIN sources, so
  rules that name the write target (`SQL-SCD2-CORRECT`, `SQL-UPSERT-CHOICE`, ...) report
  `silver.dim_customer` instead of the nonexistent `dbo.d` — and the suppression
  fingerprint no longer changes when an alias is renamed (or collides across procs that
  happen to use the same alias). A genuine one-part table name (no FROM match), qualified
  targets, temp-table targets, and `MERGE`/`DELETE` behave exactly as before.
- **`SQL-SINGLETON-INSERT` no longer flags temp-table / table-variable seeding, and temp
  objects are named faithfully** (issue #13). `INSERT INTO #staging/@rows ... VALUES` is a
  normal proc pattern — the tiny-Parquet-file rationale is about persisted user tables — so
  those inserts are skipped (top-level and inside proc bodies). And `dml_target` /
  `enclosing_object` now preserve the `#`/`##`/`@` prefix when naming a temp object instead
  of rendering it as `dbo.<name>`, so a temp target can never collide with a real table's
  suppression fingerprint. Fingerprints for findings on persisted tables are unchanged.
- **Fabric-only rules no longer fire under `--target azure-sql`** (issue #12).
  `SQL-NO-ALTER-COLUMN` (ALTER COLUMN is plain GA T-SQL on Azure SQL) and `SQL-QUERY-LABEL`
  (`OPTION(LABEL=...)` is a Fabric/Synapse-only hint Azure SQL rejects) now carry
  `targets=fabric-dw` and are skipped on azure-sql runs; `--target fabric-dw` behavior is
  unchanged, and a rule's own `rules.yml` enable/severity override is still honored where the
  rule applies. `SQL-SINGLETON-INSERT` and `SQL-TXN-SHORT` stay on both targets but their
  messages now attribute the Fabric-specific rationale ("on Fabric DW each VALUES batch lands
  a tiny Parquet file"; "on Fabric DW (snapshot-isolation only) ... on Azure SQL they hold
  locks and log space") instead of asserting it universally.

## [0.9.0] — 2026-07-09
### Changed
- **Adopt `coop-review-core` 0.4.0's consolidation layer** (issue #21; core issues #9/#10/#11/#12).
  The report scaffolding (console chrome, HTML style + logo, the machine-JSON envelope/verdict,
  the diagnostics log), the SARIF emitter, and the CLI helper cluster (display paths, TTY/color
  detection, extra-report sinks, the config write-back rule, the `syntax_errors` policy, the
  UTF-8 console shim, the `upgrade`/`update` body) now come from core instead of local copies.
  **Every output is byte-identical** before/after the swap (JSON, SARIF, text, Markdown, HTML,
  `--log-file` — verified on the fixture corpus and a syntax-error corpus); the SARIF
  `partialFingerprints` key stays frozen at `coopFingerprint/v2`. The duplicated
  `data/cooptimize-logo.png` is gone — the HTML report embeds core's single bundled copy.
  Dependency pin is now `coop-review-core>=0.4,<0.5` (capped per core's pin policy).
- **`upgrade`/`update` closing message unified across the family** (via core):
  "This tool does not update itself. To update, exit coop-sql-review and run:" — and the printed
  commands are now shlex-quoted, so a Python path with spaces stays copy-pasteable.

### Added
- **`COOP_SQL_REVIEW_CONFIG` env var** — names the config file for a whole pipeline without
  threading `--config` through every call site. A set-but-missing path is a usage error (exit 2),
  never a silent fallback; an empty value counts as unset. `--config` still wins.
- **Tool-named config file `coop-sql-review.yml`** (same schema as `rules.yml`) — the preferred
  name, so several coop-\*-review linters can hold different configs side by side in one
  directory. When both sit in one directory the tool-named file wins (a note on stderr says so).
- **Git-style parent walk-up for config discovery** — the config is found from any subdirectory
  of your repo, not just the exact folder you run from. The walk stops at the directory
  containing `.git` (a config outside the repository never silently applies), else at the
  filesystem root; the spot beside the standards file stays the final fallback.

### Deprecated
- **The shared `rules.yml` config filename.** It keeps working everywhere it worked before (same
  schema, now also found via the parent walk-up), but every coop-\*-review tool reads that name;
  discovery prints a one-line stderr nudge to rename it to `coop-sql-review.yml`.

## [0.8.0] — 2026-07-09
### Fixed
- **DDL inside procedure bodies (and other nested statements) is now visible.** The parser
  only lifted *top-level* `CREATE` statements into `SqlObject`s, but sqlglot nests a body's
  DDL under the enclosing statement's node — so a `CREATE TABLE` inside a `CREATE PROCEDURE`
  (or under an `IF ... BEGIN ... END` guard) produced **zero** findings and **zero**
  diagnostics. On an all-procs estate every §9 type rule, `SQL-TABLE-LAYER-NAME`,
  `SQL-SILVER-PASCALCASE`, and the in-file size maps under-reported silently. Each top-level
  statement is now walked with `find_all(exp.Create)` (each `Create` visited exactly once —
  top-level extraction, object order, and finding counts for top-level DDL are unchanged).
  Estates with DDL inside procs will see **new findings** on unchanged code — hence the minor
  version bump.

### Removed
- **Dead `pydantic>=2.5` dependency dropped** — nothing imported it; installs (especially
  pipx on Windows) no longer pull the large compiled wheel.

### Docs
- Fixed drift: rule count (32), fingerprint `schema_version` 3 (with the coop-dax-review v2
  divergence called out), `--format sarif`/`--sarif` documented, `SQL-NO-ALTER-COLUMN`
  severity corrected to warning everywhere.

## [0.7.1] — 2026-07-08
### Changed
- **Adopt `coop-review-core` 0.3.0.** The tool-local `SCAN_EMPTY` / `SYNTAX_ERROR` diagnostic
  categories and the syntax-ignore directive scanner (`scan_syntax_ignores` / `is_syntax_ignored`)
  now come from core (coop-review-core#1), so the whole family shares one directive grammar instead
  of drifting copies. No behavior change.
### Fixed
- **A corrupt/missing/wrong-tool `--baseline` file is now a friendly usage error (exit 2)** instead
  of silently loading an empty baseline — which used to flood every previously-baselined finding
  back with no explanation (coop-review-core#3). A baseline written by a different tool
  (`coop-dax-review`) is rejected too.

## [0.7.0] — 2026-07-08
### Added
- **SARIF 2.1.0 output** (`--format sarif`, plus a composing `--sarif <file>` sink; issue #11).
  Emits a deterministic single-run SARIF log so findings become inline PR annotations in GitHub
  code scanning / Azure DevOps. Findings map to `error`/`warning`/`note` results with
  `partialFingerprints` (GitHub dedupes across runs); agent-review items are non-blocking notes;
  error-severity diagnostics (real syntax errors) surface under a synthetic `syntax-error` rule so
  broken SQL annotates the PR line. No timestamps → byte-identical across runs. README has a
  ready-to-paste GitHub Actions `upload-sarif` snippet.
- **New rule `SQL-NARROWING-CAST`** (§I proposed; issue #10). Flags a `CAST`/`TRY_CAST`/`CONVERT`
  of a string/binary column to a SHORTER sized type — a silent truncation in T-SQL (`TRY_CAST`
  truncates identically). Source sizes come from in-file `CREATE TABLE`s (same bare-name binding
  as `SQL-IMPLICIT-CONVERT`, conflicts dropped; `MAX` = infinity). Applies to both targets; relax
  the `varchar(max) → sized` case with `params: {allow_max_to_sized: true}`.
- **`--target fabric-dw | azure-sql`** (issue #9). The linter runs against both Fabric Data
  Warehouse and Azure (serverless) SQL, which support different types. Rules that enforce a
  Fabric-DW-only table limitation are tagged and auto-skipped under `--target azure-sql`;
  resolution is `--target` > a `target:` key in `rules.yml` > default `fabric-dw`. `rules
  --format json` now carries a `targets` array per rule, and `rules` marks Fabric-only rules.
- **Fuller §9 data-type coverage** (issue #9), aligned to Microsoft's current "unsupported data
  types for tables" list:
  - `SQL-TYPE-MONEY` also flags `smallmoney`; `SQL-TYPE-DATETIME` also flags `smalldatetime` and
    `datetimeoffset`; `SQL-TYPE-NVARCHAR` also flags `nchar`.
  - New **`SQL-TYPE-UNSUPPORTED`** (warning) flags `tinyint`, `xml`, `json`, `geography`,
    `geometry`, and CLR/user-defined types (e.g. `hierarchyid`) in table columns.
  - All the above are Fabric-DW-only (skipped under `--target azure-sql`).
  - **No IDENTITY rule:** Fabric DW now *supports* `IDENTITY` columns (Preview, `bigint`-only), so
    the originally-proposed "flag all IDENTITY" rule is intentionally omitted. `docs/standards.md`
    §9 updated accordingly.
- **`SQL-TYPE-UNSUPPORTED` now also flags `vector`** (2026-07 Fabric-DW review). `VECTOR` is a real
  SQL Server 2025 type but is unsupported for Fabric DW *table* columns; it parsed cleanly before,
  so a stored vector column slipped through silently.
### Performance
- **Rule phase is ~3–4× faster** (issue #8). `ParsedFile.find_all()` re-walked the whole AST on
  every call, so the ~24 default rules did 20+ full tree traversals per file. It now builds a
  per-file node index once (one walk per statement) and serves each rule by `isinstance` filtering.
  `exists_sites()` is likewise cached so the two EXISTS rules scan the masked text once, not twice.
  Measured on the 453-file fabric-dw estate (first 200 files): rule phase **385 ms → 91 ms (−76%)**,
  findings **byte-identical**. No rule API change; `ParsedFile` stays a plain dataclass (the caches
  are lazy, `compare=False` fields, so determinism/identity are unaffected).
### Changed
- **`SQL-NO-ALTER-COLUMN` is now a `warning`, not an `error`** (2026-07 Fabric-DW review). `ALTER
  TABLE … ALTER COLUMN` is now **Preview** on Fabric DW (specific changes are supported), not
  universally unsupported — so it no longer fails `--strict` CI as an error, and its title/message
  and `docs/standards.md` §9 now say "Preview" instead of "not supported".
- **JSON `schema_version` → 3.** For a finding with an **empty** `object`, the suppression
  **fingerprint** now substitutes the file **basename** for the object part (issue #3). Several
  rules always emit `object=""` with a constant message (`SQL-EXISTS-COMMENT`,
  `SQL-EXISTS-WHY-QUALITY`, `SQL-TXN-SHORT`, `SQL-HEADER-COMMENT`), so *every* such finding across
  the whole estate previously shared **one** fingerprint — a `--baseline` (or `rules.yml` `ignore:`)
  entry accepted for one silently hid brand-new ones in other files, and no stale-entry diagnostic
  fired. The basename is still cwd/machine-independent, so baselines survive a directory/machine
  change as before. **Object-less fingerprints change**: regenerate baselines / ignore lists once
  (`--write-baseline`, or re-run `--save-ignores`). Findings *with* an object are unchanged.
### Fixed
- **Three newly-GA Fabric DW constructs no longer misreport as `syntax_error`** (2026-07 Fabric-DW
  review). `OPENROWSET(BULK … FORMAT=/DATA_SOURCE=)` (GA Apr 2025), the `OPTION (FOR TIMESTAMP AS OF
  '…')` time-travel hint, and a `MASKED WITH (FUNCTION='…')` dynamic-data-masking column are all
  valid Fabric SQL that sqlglot's tsql grammar can't fully parse. They were classified as
  error-severity `syntax_error` (tripping `--strict` CI on correct code); they are now recognized as
  known grammar gaps and reported as `parse_degraded` warnings, matching the existing CLUSTERED /
  compound-assignment handling. Signatures recorded in `sql_common._description_is_gap` and the
  AGENTS.md "sqlglot caveat" list.
- **Console and HTML reports now show `file:line` for agent-review items** (issue #6). Only the
  Markdown report carried the location; the console and HTML agent blocks showed just
  `rule (ref) · object`, so an object-less item (e.g. `SQL-TXN-SHORT`) was impossible to locate
  among many scanned files. Both now emit the same clickable `file:line` findings get (just the
  file when the line is 0); chrome stays ASCII and deterministic.
- **`--save-ignores` now writes back to the config the run actually read** instead of always a new
  `./rules.yml` (issue #7). With a team `rules.yml` beside a `--standards` file (and no `./rules.yml`),
  saving an ignore used to create a `./rules.yml` that then *silently shadowed* the standards-side
  config on every later run — severity overrides and enabled off-by-default rules vanished with no
  diagnostic. The write target now follows the resolved read path; it still never writes inside the
  installed package's bundled-standards directory, and falls back to `./rules.yml` when no config
  file exists. Explicit `--config` behavior is unchanged.
- **`SQL-EXISTS-COMMENT` no longer false-positives on a same-line explaining comment** (issue #5).
  `preceding_comment()` used a strict `0 <`, which excluded a trailing `-- why` / `/* why */` ending
  ON the `EXISTS` line — a very common way to write the §7 explanation. It now accepts a comment
  ending on the line (`0 <=`) or a block comment spanning it; the `within=3` upper bound is
  unchanged. `SQL-EXISTS-WHY-QUALITY` now correctly hands those commented sites to the agent.
- **`SQL-NO-SELECT-STAR` now flags a `SELECT *` in a derived table or scalar subquery nested
  inside a CTE** (issue #4). The exemption used `find_ancestor(CTE, Exists)`, which matched a CTE
  *anywhere* up the chain, so a production `FROM (SELECT * …) sub` sitting inside a `WITH` body was
  silently exempt — inconsistent with the same shape at top level. It now checks the NEAREST
  boundary (CTE / EXISTS / Subquery); only a CTE's own or an `EXISTS(SELECT *)` select is exempt.
- **Findings inside `CREATE PROCEDURE` bodies now carry the proc as their `object`** instead of
  `""` (issue #2). `enclosing_object()` and the parser's object extraction now unwrap sqlglot's
  `exp.StoredProcedure` wrapper, and a proc is lifted as a `SqlObject(kind="proc", …)`. Since the
  estate is almost entirely stored procedures, findings previously got `object=""`, which collapsed
  the suppression **fingerprint** to `(rule_id, message)` — so ignoring one proc's finding (inline
  directive, `--baseline`, or `rules.yml` `ignore:`) silently suppressed the same finding in every
  other proc. **Fingerprints for findings inside procedures change**: any baseline or ignore list
  recorded against the old `object=""` fingerprints needs a one-time regeneration
  (`--write-baseline`, or re-run `--save-ignores`).

## [0.6.0] — 2026-07-06
### Added
- **Real T-SQL syntax errors are now reported** — a new `syntax_error` diagnostic category
  (severity **error**). Two classes of genuinely invalid T-SQL previously passed `check` with
  **zero** parse diagnostics and only failed downstream in Fabric's import (`DmsImportDatabaseException`,
  "Incorrect syntax near 'END'"): a `CASE ... ELSE END` branch with no value, and a mangled `WITH`
  chain (a derived-table alias / `WHERE` left dangling outside a CTE's closing paren). The parser
  now parses each batch at sqlglot's `RAISE` level first (it already detected these — the tool was
  discarding the signal), records one diagnostic per structured error with its exact line, then
  re-parses tolerantly so partial analysis of the valid parts is unchanged.
- **`rules.yml` `syntax_errors:` knob** — `error` (default), `warning` (demote but keep visible),
  or `off` (drop). A downgraded syntax error still appears in the JSON `diagnostics` (only `off`
  removes it), so a coverage gap is never silent.
- **Inline `-- coop-sql-review:ignore syntax`** — silences a single syntax error on its line or the
  line above (a bare/`*` wildcard ignore covers it too); a rule-scoped ignore does not.
### Changed
- **`--strict` now also exits 2 on any error-severity diagnostic** (a real syntax error, a rule
  crash, or an unreadable file) that remains after the `syntax_errors` knob and suppressions —
  not only on findings and zero-file scans. The default exit code is still **0** (advisory).
- **The JSON `verdict` reflects error diagnostics**: `clean` is `false` (and `highest_severity` is
  `error`) when an error-severity diagnostic is present, even with zero findings — so the analytics
  agent never reads a file the parser rejected as a clean pass. `schema_version` is **unchanged**
  (additive — the `syntax_error` category and error-severity diagnostics fit the existing shape).
- **Known sqlglot false-positives on valid T-SQL degrade instead of erroring.** sqlglot's tsql
  dialect is not a complete T-SQL grammar; it raises on some *valid* constructs. Those are reported
  as `parse_degraded` **warnings**, not `syntax_error`: T-SQL compound assignment (`SET @v += x`),
  a `CLUSTERED`/`NONCLUSTERED` key or index constraint (`PRIMARY KEY CLUSTERED (col ASC)`), and
  procedure/function bodies sqlglot can only partially parse. The whole current fabric-dw estate
  (453 `.sql` files) reports **zero** `syntax_error` diagnostics; the real 2026-07-06 incident
  (a mangled CTE inside a silver-layer stored procedure) is still caught. See `AGENTS.md` "sqlglot caveat".

## [0.5.0] — 2026-07-01
### Changed
- **BREAKING (one-time): finding fingerprints no longer include the file path** —
  `schema_version` bumped to **2**. The identity is now `(rule_id, object, message)` for findings
  and `(rule_id, object, note)` for agent-review items, so baselines and `rules.yml` `ignore:`
  lists keep matching when the tool runs from a different working directory, a scheduled task, or
  another machine (the old fingerprints hashed the cwd-relative display path). Two files carrying
  the same rule + qualified object + message now share a fingerprint by design — they are the same
  logical issue, and suppressing one suppresses both. **Action: delete and regenerate any
  baseline files (`--write-baseline`) and `rules.yml` `ignore:` lists once** — old fingerprints
  will no longer match (they'd surface as stale diagnostics). Matches the identical change in
  coop-dax-review.
- **Suppressions now cover `agent_review` items** exactly like findings: inline
  `coop-sql-review:ignore` directives, `--baseline` fingerprints, and the `rules.yml` `ignore:`
  list all silence agent-review items too, and `--write-baseline` records their fingerprints. A
  baseline/ignore entry that matches only an agent-review item is not reported as stale.
- **SQL-SARGABILITY** now enforces §A's full scope: `<>` comparisons, `IN` memberships and
  `BETWEEN` ranges whose subject side wraps a column in a function (`YEAR(d) IN (2024, 2025)`),
  and arithmetic on the column side (`qty + 1 > 100`, `amount * 1.1 >= 50` — §A's `col + x`).
  Bare-column `IN`/`BETWEEN` and value-side arithmetic (`x > qty + 1`) stay clean; the finding
  message now says "function or arithmetic on a column".
- **SQL-DATE-FILTER-PARAM** now also flags hard-coded datetime literals
  (`'2026-01-01 00:00:00'`, `'2026-01-01T23:59:59.997'`) and the compact `'YYYYMMDD'` form
  (`'20260101'`) — still fullmatch-anchored, so 8-digit non-dates like `'00001234'` and free text
  containing a date never fire.
- **SQL-IMPLICIT-CONVERT** messages are now direction-aware: a string column vs a numeric literal
  keeps the "implicit conversion hurts SARGability (§C)" message (the column is converted per
  row); a numeric column vs a string literal now says the conversion of the literal is
  **harmless to SARGability** — match the literal type for clarity — instead of wrongly claiming
  a performance problem.

## [0.4.0] — 2026-07-01
### Fixed
- **`GO <count>`** (the T-SQL repeat form) is now treated as a batch separator, so statements
  after it are linted instead of being silently swallowed by the merged parse.
- **UTF-16/32 `.sql` files** (SSMS "Save with Encoding: Unicode") are decoded via their BOM and
  linted normally; a file that can't be decoded (UTF-16 without a BOM, binary, invalid bytes)
  now yields a `file_unreadable` diagnostic naming the file — never a silent zero-findings pass.
- **SQL-JOIN-FILTER** no longer flags sized `CAST`/`CONVERT` key-alignment wrappers
  (`CAST(a.id AS VARCHAR(10))`), matching the rule's documented tolerance.
- **SQL-ORDER-BY-IN-VIEW** no longer flags `ORDER BY ... OFFSET` paging inside views/subqueries
  (T-SQL honors ORDER BY with TOP, OFFSET, or FETCH).
- **SQL-EXISTS-COMMENT / SQL-EXISTS-WHY-QUALITY** recognize parenthesized guards
  (`IF (NOT EXISTS (...))`) as DDL/control guards, not §7 query predicates.
- A malformed or mis-encoded `rules.yml` (bad YAML, non-mapping root or `rules:`, unknown
  severity, non-UTF-8 file) is now a friendly one-line usage error (exit 2), never a traceback.
- `--write-baseline` to an unwritable path is a friendly one-line error instead of a traceback.

### Changed
- **Zero `.sql` files found still renders the full report** in every format/sink, with
  `files_checked: 0` and a `scan_empty` diagnostic per searched path (machine-visible typo
  detection); **`--strict` now exits 2 when zero files were checked**, so a typo'd path can't
  pass a CI gate as clean.
- An **explicit `--config` path that doesn't exist is now an error** (exit 2) instead of being
  silently ignored; auto-discovery absence stays silent, and `--save-ignores` may still name a
  new file to create.
- **`--format html` always writes a file** (default `coop-sql-review-report.html` when `-o` is
  omitted) and announces/opens it — mirroring `coop-dax-review` — instead of dumping raw HTML
  to stdout.

## [0.3.1] — 2026-07-01
### Changed
- **`check --help`** now documents the report-file flags (`--html`/`--md`) and `--save-ignores`
  with worked examples and a short "Report output" / "Ignoring findings" walkthrough, so the flags
  are discoverable from the terminal without reading the README.

## [0.3.0] — 2026-07-01
### Added
- **`rules.yml` `ignore:` list** — a human-readable, fingerprint-matched suppression that lives in
  the one writable config file (alongside the per-rule `enabled`/`severity`). Each entry needs a
  `fingerprint` (from the JSON output) plus optional `rule`/`where`/`note`. Filtered before the
  `--min-severity` floor, like the baseline; an entry that no longer matches any current finding
  emits a stale diagnostic (`rules.yml ignore: N no longer match`) so the list can't quietly rot.
- **`--save-ignores`** — after the report, an interactive checkbox (all unticked → opt-in) of this
  run's findings; the ones you tick are appended to `rules.yml`'s ignore list (de-duped by
  fingerprint, deterministic LF write) so they're silenced next run. Interactive-terminal only.
- **`--html <file>` / `--md/--markdown <file>`** — write an *extra* HTML or Markdown report
  alongside the main output; they compose with `--format` and never open a browser (scriptable
  sinks for keeping an artifact while still reading the console report).
- **`rules.yml` auto-discovery** — a `rules.yml` in the current directory is now picked up with no
  `--config` flag (so save-an-ignore-then-re-run works out of the box).
### Changed
- Requires **`coop-review-core>=0.2.0`** (new `RuleConfig.ignored_fingerprints`, `add_ignores`,
  and the `ignore_stale` diagnostic category).

## [0.2.5] — 2026-06-29
### Fixed
- **CREATE VIEW with an explicit column list was silently skipped** — `_extract_object` did not
  unwrap the `exp.Schema` target in the VIEW branch, so the view produced no `SqlObject` and every
  view-keyed rule was a no-op for it. The target is now unwrapped.
- **CTAS with a set-operation body wasn't recognized as a CTAS** — `is_ctas` only matched
  `exp.Select`, so a `CREATE TABLE AS … UNION/EXCEPT/INTERSECT …` was excluded from
  SQL-SILVER-PASCALCASE. It now matches `exp.Query` (Select and set operations).
- **SQL-NO-ALTER-COLUMN missed bracketed table names with spaces** — `ALTER COLUMN` on
  `dbo.[My Table]` is now detected (this is an `error`-severity rule guarding a hard Fabric DW
  limitation).
- **SELECT DISTINCT was reported at the batch start line** — the finding now anchors on the
  `DISTINCT`'s actual line instead of falling back to the GO-batch start.
- **Identifier helpers mis-split a bracketed name containing a literal dot** — `original_name()` /
  `qualify()` no longer break `[a.b]` into `a`/`b` (display/label correctness).
### Docs
- RULES.md: SQL-SARGABILITY no longer claims it flags "function/CASE wrapping a column" — the rule
  deliberately excludes `CASE` (CASE in a JOIN ON is handled by SQL-JOIN-FILTER §8).

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

[0.10.0]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.10.0
[0.9.0]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.9.0
[0.8.0]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.8.0
[0.7.1]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.7.1
[0.7.0]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.7.0
[0.6.0]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.6.0
[0.5.0]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.5.0
[0.4.0]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.4.0
[0.3.1]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.3.1
[0.3.0]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.3.0
[0.2.5]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.2.5
[0.2.4]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.2.4
[0.2.3]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.2.3
[0.2.2]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.2.2
[0.2.1]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.2.1
[0.2.0]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.2.0
[0.1.6]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.1.6
[0.1.5]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.1.5
[0.1.0]: https://github.com/kabukisensei/coop-sql-review/releases/tag/v0.1.0
