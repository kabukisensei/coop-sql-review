"""Tests for the Tier-2 agent-judgment rules:

SQL-SCD2-CORRECT (§6), SQL-EXISTS-WHY-QUALITY (§7), SQL-BRONZE-RAW-NAMES (§1),
SQL-FILTER-UPSTREAM (§8), SQL-TXN-SHORT (§9).

Each detect() returns AgentReviewItems; we cover a positive (must flag), a
negative (must not flag), and the tricky edge per rule.
"""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_bronze_raw_names import RULE as BRONZE_RULE
from coop_sql_review.rules.sql_exists_why_quality import RULE as EXISTS_RULE
from coop_sql_review.rules.sql_filter_upstream import RULE as FILTER_RULE
from coop_sql_review.rules.sql_scd2_correct import RULE as SCD2_RULE
from coop_sql_review.rules.sql_txn_short import RULE as TXN_RULE


def run(rule, sql):
    p = parse_sql("t.sql", sql)
    return (rule.check if rule.check else rule.detect)(RuleContext(rule, p))


# -- SQL-SCD2-CORRECT (§6) --------------------------------------------------

SCD2_CLOSE = """\
UPDATE silver.dim_customer
SET ExpirationDate = @effective_date,
    IsCurrent = 0
WHERE CustomerId = @customer_id
  AND IsCurrent = 1;
"""

PLAIN_UPDATE = """\
UPDATE silver.dim_customer
SET FirstName = @first_name,
    ModifiedDate = @now
WHERE CustomerId = @customer_id;
"""


def test_scd2_close_update_is_detected():
    items = run(SCD2_RULE, SCD2_CLOSE)
    assert len(items) == 1
    assert items[0].rule_id == "SQL-SCD2-CORRECT"
    assert items[0].object == "silver.dim_customer"


def test_plain_update_is_not_detected():
    assert run(SCD2_RULE, PLAIN_UPDATE) == []


def test_scd2_only_iscurrent_is_detected():
    # Edge: setting just IsCurrent (no ExpirationDate) still signals the close step.
    sql = "UPDATE silver.dim_customer SET IsCurrent = 0 WHERE CustomerId = @c;"
    assert len(run(SCD2_RULE, sql)) == 1


SCD2_MERGE_CLOSE = (
    "MERGE silver.dim_customer AS t USING src AS s "
    "ON t.CustomerId=s.CustomerId "
    "WHEN MATCHED THEN UPDATE SET IsCurrent=0 "
    "WHEN NOT MATCHED THEN INSERT (CustomerId,IsCurrent) VALUES (s.CustomerId,1);"
)


def test_scd2_merge_close_is_detected():
    # Repro: a MERGE whose WHEN MATCHED UPDATE SET closes the row is an SCD2
    # close too, reported against the merge's target table (exactly once).
    items = run(SCD2_RULE, SCD2_MERGE_CLOSE)
    assert len(items) == 1
    assert items[0].rule_id == "SQL-SCD2-CORRECT"
    assert items[0].object == "silver.dim_customer"


def test_scd2_merge_without_close_columns_is_not_detected():
    # Negative: a MERGE update that touches no SCD2 column is not a close step.
    sql = (
        "MERGE silver.dim_customer AS t USING src AS s "
        "ON t.CustomerId=s.CustomerId "
        "WHEN MATCHED THEN UPDATE SET FirstName=s.FirstName "
        "WHEN NOT MATCHED THEN INSERT (CustomerId) VALUES (s.CustomerId);"
    )
    assert run(SCD2_RULE, sql) == []


# -- SQL-EXISTS-WHY-QUALITY (§7) --------------------------------------------

EXISTS_WITH_COMMENT = """\
SELECT cust.CustomerId
FROM silver.dim_customer cust
-- Using EXISTS instead of COUNT(*) because we only need to know if at
-- least one open opportunity exists, not how many.
WHERE EXISTS (
    SELECT 1 FROM gold.fact_opportunity opp WHERE opp.CustomerId = cust.CustomerId
);
"""

EXISTS_NO_COMMENT = """\
SELECT cust.CustomerId
FROM silver.dim_customer cust
WHERE EXISTS (
    SELECT 1 FROM gold.fact_opportunity opp WHERE opp.CustomerId = cust.CustomerId
);
"""


def test_exists_with_comment_is_detected():
    items = run(EXISTS_RULE, EXISTS_WITH_COMMENT)
    assert len(items) == 1
    assert items[0].rule_id == "SQL-EXISTS-WHY-QUALITY"


def test_exists_without_comment_is_not_detected():
    # The missing-comment case belongs to SQL-EXISTS-COMMENT, not this rule.
    assert run(EXISTS_RULE, EXISTS_NO_COMMENT) == []


def test_not_exists_with_comment_is_detected():
    # Edge: exp.Exists covers NOT EXISTS too.
    sql = """\
SELECT cust.CustomerId
FROM silver.dim_customer cust
-- NOT EXISTS finds customers with no recent sales; clearer than LEFT JOIN/IS NULL.
WHERE NOT EXISTS (
    SELECT 1 FROM gold.fact_sales s WHERE s.CustomerId = cust.CustomerId
);
"""
    assert len(run(EXISTS_RULE, sql)) == 1


def test_exists_good_example_yields_exactly_one_review():
    # Repro: a canonical §7 'Good' example (comment above WHERE EXISTS) anchors
    # on the EXISTS keyword line and yields exactly one review, not zero/many.
    items = run(EXISTS_RULE, EXISTS_WITH_COMMENT)
    assert len(items) == 1
    assert items[0].line == 5  # the WHERE EXISTS line, not inside the subquery


def test_exists_if_guard_is_not_detected():
    # Repro: IF EXISTS is an existence guard, not the §7 query predicate — even
    # with a comment above it, this rule must not flag it.
    sql = """\
-- guard: only seed the dimension once
IF EXISTS (SELECT 1 FROM silver.dim_customer)
    PRINT 'already seeded';
"""
    assert run(EXISTS_RULE, sql) == []


# -- SQL-BRONZE-RAW-NAMES (§1) ----------------------------------------------

BRONZE_RENAMED = """\
SELECT
    contactid AS CustomerId,
    firstname AS FirstName
FROM bronze.raw_d365_contact;
"""

BRONZE_RAW = """\
SELECT contactid, firstname, lastname
FROM bronze.raw_d365_contact;
"""

SILVER_OVER_BRONZE_CTE = """\
WITH cte_src AS (
    SELECT contactid, firstname
    FROM bronze.raw_d365_contact
)
SELECT contactid AS CustomerId, firstname AS FirstName
FROM cte_src;
"""


def test_bronze_select_with_aliases_is_detected():
    items = run(BRONZE_RULE, BRONZE_RENAMED)
    assert len(items) == 1
    assert items[0].rule_id == "SQL-BRONZE-RAW-NAMES"


def test_bronze_select_preserving_names_is_not_detected():
    assert run(BRONZE_RULE, BRONZE_RAW) == []


def test_silver_select_over_bronze_cte_is_not_detected():
    # Edge: bronze is only the source of an inner CTE; the aliasing happens in a
    # downstream SELECT that reads the CTE, not bronze directly — not flagged.
    assert run(BRONZE_RULE, SILVER_OVER_BRONZE_CTE) == []


def test_bronze_aggregate_alias_is_not_detected():
    # Repro: COUNT(*) AS row_count aliases a computed expression, not a raw
    # column rename — must not be flagged.
    assert run(BRONZE_RULE, "SELECT COUNT(*) AS row_count FROM bronze.raw") == []


def test_bronze_audit_column_alias_is_not_detected():
    # Repro: GETDATE() AS LoadedAt is a computed audit column, not a rename; the
    # plain contactid passthrough alongside it preserves the raw name.
    sql = "SELECT GETDATE() AS LoadedAt, contactid FROM bronze.raw"
    assert run(BRONZE_RULE, sql) == []


def test_bronze_column_rename_is_detected():
    # Repro: contactid AS CustomerId is a bare-column rename — still flagged.
    items = run(BRONZE_RULE, "SELECT contactid AS CustomerId FROM bronze.raw")
    assert len(items) == 1
    assert items[0].rule_id == "SQL-BRONZE-RAW-NAMES"


# -- SQL-FILTER-UPSTREAM (§8) -----------------------------------------------

JOIN_WITH_WHERE = """\
SELECT c.CustomerId, s.Revenue
FROM silver.dim_customer c
LEFT JOIN gold.fact_sales_daily s ON c.CustomerId = s.CustomerId
WHERE c.IsCurrent = 1;
"""

JOIN_NO_WHERE = """\
SELECT c.CustomerId, s.Revenue
FROM silver.dim_customer c
LEFT JOIN gold.fact_sales_daily s ON c.CustomerId = s.CustomerId;
"""


def test_join_with_where_is_detected():
    items = run(FILTER_RULE, JOIN_WITH_WHERE)
    assert len(items) == 1
    assert items[0].rule_id == "SQL-FILTER-UPSTREAM"


def test_join_without_where_is_not_detected():
    assert run(FILTER_RULE, JOIN_NO_WHERE) == []


def test_where_without_join_is_not_detected():
    sql = "SELECT CustomerId FROM silver.dim_customer WHERE IsCurrent = 1;"
    assert run(FILTER_RULE, sql) == []


def test_nested_join_where_yields_one_per_select():
    # Edge: one review per qualifying SELECT (outer + nested subquery each qualify).
    sql = """\
SELECT c.CustomerId
FROM silver.dim_customer c
JOIN gold.fact_sales s ON c.CustomerId = s.CustomerId
WHERE c.CustomerId IN (
    SELECT o.CustomerId
    FROM gold.fact_opportunity o
    JOIN gold.fact_quote q ON o.OppId = q.OppId
    WHERE o.Status = 'Open'
);
"""
    assert len(run(FILTER_RULE, sql)) == 2


# -- SQL-TXN-SHORT (§9) -----------------------------------------------------

EXPLICIT_TXN = """\
BEGIN TRANSACTION;
DELETE FROM gold.fact_sales_daily WHERE SalesDate = @process_date;
INSERT INTO gold.fact_sales_daily SELECT * FROM cte_staging;
COMMIT;
"""

NO_TXN = """\
DELETE FROM gold.fact_sales_daily WHERE SalesDate = @process_date;
INSERT INTO gold.fact_sales_daily SELECT * FROM cte_staging;
"""

TXN_IN_COMMENT = """\
-- We deliberately avoid BEGIN TRANSACTION here to keep writes auto-committed.
DELETE FROM gold.fact_sales_daily WHERE SalesDate = @process_date;
"""


def test_explicit_transaction_is_detected():
    items = run(TXN_RULE, EXPLICIT_TXN)
    assert len(items) == 1
    assert items[0].rule_id == "SQL-TXN-SHORT"
    assert items[0].object == ""
    assert items[0].line == 1


def test_no_transaction_is_not_detected():
    assert run(TXN_RULE, NO_TXN) == []


def test_begin_tran_short_form_is_detected():
    assert len(run(TXN_RULE, "BEGIN TRAN;\nDELETE FROM gold.t WHERE x = 1;\nCOMMIT;")) == 1


def test_transaction_word_in_comment_is_not_detected():
    # Edge: masked source blanks comment content, so a mention in prose never matches.
    assert run(TXN_RULE, TXN_IN_COMMENT) == []
