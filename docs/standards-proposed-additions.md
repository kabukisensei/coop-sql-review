# SQL Standards — proposed additions (review before merging)

Microsoft Fabric / T-SQL community best practices **not yet covered** by `standards.md`.
Kept separate so your authored canon stays pristine — merge in whatever you agree with.
"Checkable" = the deterministic tool can enforce it; others are agent-judgment.

## A. SARGability — avoid functions on filtered columns (Checkable, high value)
Wrapping a filtered/joined column in a function defeats predicate pushdown and statistics.
```sql
-- Avoid: non-SARGable (function on the column)
WHERE YEAR(SalesDate) = 2026
-- Prefer: range predicate on the bare column
WHERE SalesDate >= '2026-01-01' AND SalesDate < '2027-01-01'
```
Rule idea: `SQL-SARGABILITY` (warning) — flag `func(col)` / `col + x` on a column used in
`WHERE`/`JOIN`. *Source: standard T-SQL perf guidance.*

## B. Maintain statistics on join/filter columns (Agent/info)
Fabric DW relies on statistics for good plans; create/refresh stats on high-cardinality join
and filter keys. Hard to verify statically → `agent_review`. *Source: Fabric DW guidance.*

## C. Avoid implicit conversions in predicates (Checkable-ish, info)
Comparing mismatched types forces conversions and kills SARGability (e.g. `varchar` column vs
`int` literal). Rule idea: `SQL-IMPLICIT-CONVERT` where column type is known from a CREATE in
scope.

## D. Prefer `TRY_CONVERT` / `TRY_CAST` when parsing external/bronze text (Checkable, info)
Raw bronze values fail hard with `CAST`; `TRY_CAST` yields NULL instead of aborting the load.
Rule idea: `SQL-TRY-CAST-BRONZE` — `CAST(` on a `bronze.*` source column.

## E. No `ORDER BY` in views / CTEs / subqueries (Checkable, warning)
`ORDER BY` there is ignored (or only valid with TOP) and misleads readers.
Rule idea: `SQL-ORDER-BY-IN-VIEW`.

## F. `SELECT DISTINCT` as a band-aid for bad joins (Checkable, info)
`DISTINCT` often masks a fan-out join bug. Flag for a second look.
Rule idea: `SQL-DISTINCT-SMELL`.

## G. Bulk ingestion: prefer `COPY INTO` over row-by-row loads (Agent/info)
For external-file ingestion, `COPY INTO` beats many `INSERT`s. Complements the existing
singleton-insert rule. *Source: Fabric DW load guidance.*

## H. Scalar UDFs in `WHERE`/`SELECT` at scale (Checkable if UDF is known, info)
Scalar UDFs serialize execution. Flag known-UDF calls in hot paths.

---
*Microsoft references already cited in `standards.md` §14 (skills-for-fabric). When the
reviewer adds a rule for any item above, cite the section here as its `standard_ref`.*
