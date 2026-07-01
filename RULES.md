# coop-sql-review — rule taxonomy

The bridge from prose `standards.md` to concrete checks. Each standard section maps to one or
more rules. **Method**: `AST` = sqlglot tree; `text` = raw lines/regex (comments, headers);
`agent` = needs judgment → emitted in `agent_review`, not auto-evaluated. **Tier 1** = build
first (high value + reliably checkable). Severities are defaults; `rules.yml`/standards.md can
override.

Some rules ship **off by default** (`SQL-ALIAS-DESCRIPTIVE`, `SQL-CTE-PREFIX`,
`SQL-HEADER-COMMENT`, `SQL-INSERT-ALIAS-MATCH`, `SQL-QUERY-LABEL`, `SQL-TABLE-LAYER-NAME`) and must
be enabled in `rules.yml` (`<RULE-ID>: {enabled: true}`); `coop-sql-review rules` marks these
`[off by default]`.

## Deterministic rules — build these

| Rule ID | § | What it flags | Sev | Method | Tier |
|---|---|---|---|---|---|
| `SQL-NO-SELECT-STAR` | 11 | `SELECT *` in a production (non-intermediate) select | warning | AST | 1 |
| `SQL-ALIAS-DESCRIPTIVE` | 2 | table alias is a single letter / < 3 chars | warning | AST | 1 |
| `SQL-TYPE-NVARCHAR` | 9 | column type `nvarchar` → use `varchar` | warning | AST | 1 |
| `SQL-TYPE-DATETIME` | 9 | type `datetime` → use `datetime2` | warning | AST | 1 |
| `SQL-TYPE-MONEY` | 9 | type `money` → use `decimal(19,4)` | warning | AST | 1 |
| `SQL-TYPE-DEPRECATED` | 9 | `text` / `ntext` / `image` → `varchar(max)`/`varbinary(max)` | warning | AST | 1 |
| `SQL-NO-ALTER-COLUMN` | 9 | `ALTER ... ALTER COLUMN` (unsupported in Fabric DW) | error | AST/text | 1 |
| `SQL-SINGLETON-INSERT` | 9 | `INSERT ... VALUES` (esp. repeated singletons) | warning | AST | 1 |
| `SQL-CTE-PREFIX` | 1 | CTE name not prefixed `cte_` | info | AST | 1 |
| `SQL-TABLE-LAYER-NAME` | 1 | created table not `layer.object` (layer ∈ bronze/silver/gold) | info | AST | 2 |
| `SQL-PREFER-CTE` | 4 | anonymous derived-table subquery in FROM (suggest a CTE) | info | AST | 2 |
| `SQL-JOIN-FILTER` | 8 | non-key predicate (literal / function / business filter) in `JOIN ... ON` | warning | AST | 2 |
| `SQL-INSERT-ALIAS-MATCH` | 3 | `INSERT`column list vs `SELECT` aliases mismatched / missing `AS` | warning | AST | 2 |
| `SQL-EXISTS-COMMENT` | 7 | `EXISTS`/`NOT EXISTS` with no preceding comment | warning | AST+text | 2 |
| `SQL-HEADER-COMMENT` | 10 | file missing header block (File/Purpose/Source/Author/Date) | info | text | 2 |
| `SQL-SILVER-PASCALCASE` | 1 | silver/gold output alias not PascalCase | info | AST | 3 |
| `SQL-DATE-FILTER-PARAM` | 11 | date/datetime literal in `WHERE` — ISO `'YYYY-MM-DD'` (optional time suffix) or compact `'YYYYMMDD'` (prefer a parameter) | info | AST | 3 |
| `SQL-QUERY-LABEL` | 9 | ETL `INSERT` without `OPTION(LABEL=...)` | info | AST/text | 3 |
| `SQL-CTAS-EXPLICIT-CAST` | 9 | CTAS with un-`CAST` aggregate outputs | info | AST | 3 |

## Agent-judgment rules — emit in `agent_review`, let the agent decide

| Rule ID | § | Why it needs judgment (tool still *detects + flags* the construct) |
|---|---|---|
| `SQL-UPSERT-CHOICE` | 5 | right pattern (CTAS / DELETE+INSERT / MERGE) depends on table size, concurrency, intent. Detect which is used; flag MERGE for a size check. |
| `SQL-SCD2-CORRECT` | 6 | close-then-insert SCD2 correctness is structural/semantic. |
| `SQL-EXISTS-WHY-QUALITY` | 7 | *presence* of a comment is checkable (above); whether it explains **why** is judgment. |
| `SQL-BRONZE-RAW-NAMES` | 1 | "preserve source names" needs the source schema to verify. |
| `SQL-FILTER-UPSTREAM` | 8 | whether filtering *should* move upstream is contextual. |
| `SQL-TXN-SHORT` | 9 | "transaction too long" isn't statically decidable. |

## Proposed-additions rules — built from `docs/standards-proposed-additions.md`

These are the *checkable* items from the proposed-additions doc; their `standard_ref` is that
doc's section letter (`§A`–`§F`), not a `standards.md` section.

| Rule ID | § | What it flags | Sev | Method |
|---|---|---|---|---|
| `SQL-SARGABILITY` | A | function or arithmetic (`col + x`) wrapping a column in a `WHERE`/`JOIN` predicate (`= <> > >= < <=`, `IN`, `BETWEEN`) — defeats indexes/stats | warning | AST |
| `SQL-ORDER-BY-IN-VIEW` | E | `ORDER BY` in a view/CTE/subquery with no `TOP` (ignored at runtime); window/`WITHIN GROUP` order excluded | warning | AST |
| `SQL-DISTINCT-SMELL` | F | `SELECT DISTINCT` (often masks a fan-out join); aggregate `DISTINCT` excluded | info | AST |
| `SQL-TRY-CAST-BRONZE` | D | `CAST` of a column when a `bronze.*` table is a read source — prefer `TRY_CAST` | info | AST |
| `SQL-IMPLICIT-CONVERT` | C | predicate comparing a column to a mismatched-type literal (type known from an in-file `CREATE`); direction-aware message — converting the COLUMN hurts SARGability, converting the LITERAL is a clarity nit | info | AST |

Proposed items **§B** (maintain statistics), **§G** (`COPY INTO` for bulk ingestion), and **§H**
(scalar UDFs in hot paths) are deferred — they need runtime/catalog context or are agent-judgment,
so no deterministic rule ships for them yet.

## Implementation notes
- The parser must keep **raw text + line numbers and comment positions** alongside the AST —
  `SQL-EXISTS-COMMENT` and `SQL-HEADER-COMMENT` need them. coop-data-doc's parsers focus on
  lineage; you'll extend them to retain comment/line spans.
- `SELECT *` is legitimate in some intermediate CTEs — scope `SQL-NO-SELECT-STAR` to the final/
  production select, or make the scope configurable.
- Build Tier 1 first; it already covers the highest-frequency real issues (types, SELECT *,
  aliases, ALTER COLUMN, singleton inserts). Tiers 2–3 add depth.
- Every rule cites its `standard_ref` (the `§` here) so findings link back to the standard.
