"""Tests for the comment rules: SQL-EXISTS-COMMENT (§7) and
SQL-HEADER-COMMENT (§10).
"""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_exists_comment import RULE as EXISTS_RULE
from coop_sql_review.rules.sql_header_comment import RULE as HEADER_RULE


def run(rule, sql):
    p = parse_sql("t.sql", sql)
    return (rule.check if rule.check else rule.detect)(RuleContext(rule, p))


# -- SQL-EXISTS-COMMENT (§7) ------------------------------------------------

EXISTS_NO_COMMENT = """\
SELECT cust.CustomerId
FROM silver.dim_customer cust
WHERE EXISTS (
    SELECT 1 FROM gold.fact_opportunity opp WHERE opp.CustomerId = cust.CustomerId
);
"""

EXISTS_WITH_COMMENT = """\
SELECT cust.CustomerId
FROM silver.dim_customer cust
-- Using EXISTS instead of COUNT(*) because we only need to know if at
-- least one open opportunity exists, not how many.
WHERE EXISTS (
    SELECT 1 FROM gold.fact_opportunity opp WHERE opp.CustomerId = cust.CustomerId
);
"""

NOT_EXISTS_NO_COMMENT = """\
SELECT cust.CustomerId
FROM silver.dim_customer cust
WHERE NOT EXISTS (
    SELECT 1 FROM gold.fact_sales sales WHERE sales.CustomerId = cust.CustomerId
);
"""


def test_exists_without_comment_is_flagged():
    findings = run(EXISTS_RULE, EXISTS_NO_COMMENT)
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-EXISTS-COMMENT"
    # The finding anchors on the EXISTS keyword line, not the subquery body.
    assert findings[0].line == 3


def test_exists_with_comment_above_is_clean():
    assert run(EXISTS_RULE, EXISTS_WITH_COMMENT) == []


def test_not_exists_is_caught_too():
    findings = run(EXISTS_RULE, NOT_EXISTS_NO_COMMENT)
    assert len(findings) == 1


# -- SQL-EXISTS-COMMENT regression cases ------------------------------------

# Both canonical §7 "Good" examples from docs/standards.md, with the reasoning
# comment directly above the WHERE [NOT] EXISTS. These must NOT be flagged.
CANONICAL_GOOD_EXISTS = """\
SELECT cust.CustomerId, cust.FirstName
FROM silver.dim_customer cust
-- Using EXISTS instead of COUNT(*) because we only need to know if
-- at least one open opportunity exists, not how many.
-- EXISTS short-circuits on first match; COUNT(*) scans all rows.
WHERE EXISTS (
    SELECT 1
    FROM gold.fact_opportunity opp
    WHERE opp.CustomerId = cust.CustomerId
      AND opp.Status = 'Open'
      AND opp.CreatedDate >= DATEADD(day, -90, GETDATE())
);
"""

CANONICAL_GOOD_NOT_EXISTS = """\
SELECT cust.CustomerId, cust.FirstName
FROM silver.dim_customer cust
WHERE cust.IsCurrent = 1
  -- Using NOT EXISTS to find customers with no sales in the last 12 months.
  -- LEFT JOIN + IS NULL would work but NOT EXISTS is clearer intent
  -- and handles NULL CustomerIds safely.
  AND NOT EXISTS (
      SELECT 1
      FROM gold.fact_sales_daily sales
      WHERE sales.CustomerId = cust.CustomerId
        AND sales.SalesDate >= DATEADD(month, -12, GETDATE())
  );
"""

BARE_EXISTS_ONE_LINE = "WHERE EXISTS (SELECT 1 FROM u WHERE u.id=t.id)\n"

IF_EXISTS_GUARD = "IF EXISTS (SELECT 1 FROM sys.tables) DROP TABLE foo;\n"


def test_canonical_good_exists_is_clean():
    assert run(EXISTS_RULE, CANONICAL_GOOD_EXISTS) == []


def test_canonical_good_not_exists_is_clean():
    assert run(EXISTS_RULE, CANONICAL_GOOD_NOT_EXISTS) == []


def test_bare_exists_flagged_at_keyword_line():
    findings = run(EXISTS_RULE, BARE_EXISTS_ONE_LINE)
    assert len(findings) == 1
    assert findings[0].line == 1


def test_if_exists_guard_is_not_flagged():
    assert run(EXISTS_RULE, IF_EXISTS_GUARD) == []


# -- SQL-HEADER-COMMENT (§10) -----------------------------------------------

NO_HEADER = """\
CREATE TABLE silver.dim_customer (
    CustomerId INT NOT NULL
);
"""

WITH_HEADER = """\
/*
  File: silver/dim_customer.sql
  Purpose: Clean and deduplicate customer data
  Source: bronze.raw_d365_contact
  Author: Aaron Jennings
  Date: 2026-06-01
*/
CREATE TABLE silver.dim_customer (
    CustomerId INT NOT NULL
);
"""

# A comment that isn't a real header (no File/Purpose) should not satisfy §10.
TRIVIAL_COMMENT = """\
-- quick scratch table
CREATE TABLE silver.dim_customer (
    CustomerId INT NOT NULL
);
"""


def test_missing_header_is_flagged():
    findings = run(HEADER_RULE, NO_HEADER)
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-HEADER-COMMENT"
    assert findings[0].line == 1
    assert findings[0].object == ""


def test_header_block_is_clean():
    assert run(HEADER_RULE, WITH_HEADER) == []


def test_trivial_top_comment_does_not_count_as_header():
    assert len(run(HEADER_RULE, TRIVIAL_COMMENT)) == 1


def test_empty_file_is_skipped():
    assert run(HEADER_RULE, "") == []
    assert run(HEADER_RULE, "   \n\n") == []


# -- SQL-HEADER-COMMENT regression cases ------------------------------------

# A line-comment header (-- File: / -- Purpose:) must satisfy §10.
LINE_COMMENT_HEADER = """\
-- File: x
-- Purpose: y
SELECT 1;
"""

# Substring matching previously passed this (profileuser/purposeful/datafile),
# but there is no real File/Purpose, so word-boundary matching must flag it.
SUBSTRING_DECOY = """\
/* profileuser and purposeful refactoring of datafile */
SELECT 1;
"""

# Straight into DDL with no header at all.
NO_HEADER_DDL = """\
CREATE TABLE silver.dim_customer (
    CustomerId INT NOT NULL
);
"""


def test_line_comment_header_is_clean():
    assert run(HEADER_RULE, LINE_COMMENT_HEADER) == []


def test_substring_decoy_is_flagged():
    findings = run(HEADER_RULE, SUBSTRING_DECOY)
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-HEADER-COMMENT"


def test_file_starting_in_ddl_is_flagged_once_at_line_one():
    findings = run(HEADER_RULE, NO_HEADER_DDL)
    assert len(findings) == 1
    assert findings[0].line == 1


def test_parenthesized_if_not_exists_guard_not_flagged():
    # REGRESSION (FP): a parenthesized IF (NOT EXISTS (...)) DDL guard is still
    # a control-flow existence guard, not the query predicate §7 is about.
    sql = (
        "IF (NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 't'))\n"
        "BEGIN\n"
        "    CREATE TABLE dbo.t (a int);\n"
        "END\n"
    )
    assert run(EXISTS_RULE, sql) == []


def test_parenthesized_while_exists_guard_not_flagged():
    sql = "WHILE (EXISTS (SELECT 1 FROM dbo.queue))\nBEGIN\n    DELETE TOP (10) FROM dbo.queue;\nEND\n"
    assert run(EXISTS_RULE, sql) == []


def test_parenthesized_where_not_exists_predicate_still_flagged():
    # The loosened guard lookback must not classify a parenthesized WHERE
    # predicate as a guard — §7 still applies there.
    sql = (
        "SELECT cust.CustomerId\n"
        "FROM silver.dim_customer cust\n"
        "WHERE (NOT EXISTS (SELECT 1 FROM gold.fact_sales s WHERE s.CustomerId = cust.CustomerId));\n"
    )
    assert len(run(EXISTS_RULE, sql)) == 1
