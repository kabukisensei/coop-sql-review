"""Tests for the §9 datatype rules:
SQL-TYPE-NVARCHAR, SQL-TYPE-DATETIME, SQL-TYPE-MONEY, SQL-TYPE-DEPRECATED.
"""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_type_nvarchar import RULE as NVARCHAR_RULE
from coop_sql_review.rules.sql_type_datetime import RULE as DATETIME_RULE
from coop_sql_review.rules.sql_type_money import RULE as MONEY_RULE
from coop_sql_review.rules.sql_type_deprecated import RULE as DEPRECATED_RULE


def run(rule, sql):
    p = parse_sql("t.sql", sql)
    return rule.check(RuleContext(rule, p))


# A table that exercises every flagged type, each on its own line so we can
# assert precise line numbers.
POSITIVE_SQL = """\
CREATE TABLE silver.thing (
    id INT NOT NULL,
    name NVARCHAR(50),
    created DATETIME,
    price MONEY,
    notes TEXT,
    notes2 NTEXT,
    blob IMAGE
);
"""

# All recommended replacement types — must produce zero findings from any rule.
NEGATIVE_SQL = """\
CREATE TABLE silver.thing (
    id INT NOT NULL,
    name VARCHAR(50),
    created DATETIME2(3),
    price DECIMAL(19, 4),
    notes VARCHAR(MAX),
    blob VARBINARY(MAX)
);
"""


def test_nvarchar_positive():
    findings = run(NVARCHAR_RULE, POSITIVE_SQL)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "SQL-TYPE-NVARCHAR"
    assert f.object == "silver.thing"
    assert f.line == 3  # the NVARCHAR(50) column line
    assert "nvarchar" in f.message


def test_datetime_positive():
    findings = run(DATETIME_RULE, POSITIVE_SQL)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "SQL-TYPE-DATETIME"
    assert f.object == "silver.thing"
    assert f.line == 4  # the DATETIME column line
    assert "datetime2" in f.message


def test_money_positive():
    findings = run(MONEY_RULE, POSITIVE_SQL)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "SQL-TYPE-MONEY"
    assert f.object == "silver.thing"
    assert f.line == 5  # the MONEY column line
    assert "decimal(19,4)" in f.message


def test_deprecated_positive():
    findings = run(DEPRECATED_RULE, POSITIVE_SQL)
    # TEXT, NTEXT (both base_type TEXT), and IMAGE → three findings.
    assert len(findings) == 3
    assert all(f.rule_id == "SQL-TYPE-DEPRECATED" for f in findings)
    assert all(f.object == "silver.thing" for f in findings)
    lines = sorted(f.line for f in findings)
    assert lines == [6, 7, 8]  # TEXT, NTEXT, IMAGE lines
    text_msgs = [f.message for f in findings if "text/ntext" in f.message]
    image_msgs = [f.message for f in findings if "image" in f.message]
    assert len(text_msgs) == 2
    assert all("varchar(max)" in m for m in text_msgs)
    assert len(image_msgs) == 1
    assert "varbinary(max)" in image_msgs[0]


def test_no_false_positives_on_recommended_types():
    # CRITICAL: datetime2(3) must NOT be flagged by SQL-TYPE-DATETIME, and the
    # other recommended replacement types must not be flagged either.
    assert run(NVARCHAR_RULE, NEGATIVE_SQL) == []
    assert run(DATETIME_RULE, NEGATIVE_SQL) == []
    assert run(MONEY_RULE, NEGATIVE_SQL) == []
    assert run(DEPRECATED_RULE, NEGATIVE_SQL) == []


def test_datetime_does_not_match_datetime2():
    # A table with only datetime2 columns — the DATETIME rule must stay silent.
    sql = """\
CREATE TABLE silver.evt (
    happened DATETIME2,
    happened_ms DATETIME2(3)
);
"""
    assert run(DATETIME_RULE, sql) == []


# --- issue #9: sibling types + the new SQL-TYPE-UNSUPPORTED rule ---------------------
from coop_sql_review.rules.sql_type_unsupported import RULE as UNSUPPORTED_RULE  # noqa: E402

SIBLING_SQL = """\
CREATE TABLE silver.s (
    a SMALLMONEY,
    b SMALLDATETIME,
    c DATETIMEOFFSET,
    d NCHAR(10)
);
"""


def test_money_flags_smallmoney():
    f = run(MONEY_RULE, SIBLING_SQL)
    assert [x.line for x in f] == [2]
    assert "smallmoney" in f[0].message


def test_datetime_flags_smalldatetime_and_datetimeoffset():
    f = run(DATETIME_RULE, SIBLING_SQL)
    assert sorted(x.line for x in f) == [3, 4]
    msgs = " ".join(x.message for x in f)
    assert "smalldatetime" in msgs and "datetimeoffset" in msgs


def test_nvarchar_flags_nchar():
    f = run(NVARCHAR_RULE, SIBLING_SQL)
    assert [x.line for x in f] == [5]
    assert "nchar" in f[0].message and "char" in f[0].message


UNSUPPORTED_SQL = """\
CREATE TABLE silver.u (
    a TINYINT,
    b XML,
    c JSON,
    d GEOGRAPHY,
    e GEOMETRY,
    f HIERARCHYID,
    g VECTOR(1536)
);
"""


def test_unsupported_flags_all_table_breaking_types():
    f = run(UNSUPPORTED_RULE, UNSUPPORTED_SQL)
    assert sorted(x.line for x in f) == [2, 3, 4, 5, 6, 7, 8]
    assert all(x.rule_id == "SQL-TYPE-UNSUPPORTED" for x in f)
    joined = " ".join(x.message for x in f)
    # vector is a SQL Server 2025 type unsupported for Fabric DW tables (§9).
    for kw in ("tinyint", "xml", "json", "geography", "geometry", "user-defined/CLR", "vector"):
        assert kw in joined


def test_unsupported_no_false_positives_on_supported_types():
    sql = "CREATE TABLE s.t (a INT, b VARCHAR(20), c DECIMAL(19,4), d DATETIME2, e VARBINARY(8), g BIGINT IDENTITY);"
    assert run(UNSUPPORTED_RULE, sql) == []


def test_identity_is_not_flagged_by_any_type_rule():
    # Fabric DW now SUPPORTS IDENTITY (bigint, Preview) — no type rule should flag it.
    sql = "CREATE TABLE s.t (id BIGINT IDENTITY NOT NULL, name VARCHAR(50));"
    for rule in (NVARCHAR_RULE, DATETIME_RULE, MONEY_RULE, DEPRECATED_RULE, UNSUPPORTED_RULE):
        assert run(rule, sql) == []


def test_type_rules_are_tagged_fabric_only():
    from coop_sql_review.rules.base import FABRIC_ONLY

    for rule in (NVARCHAR_RULE, DATETIME_RULE, MONEY_RULE, UNSUPPORTED_RULE):
        assert rule.targets == FABRIC_ONLY


# --- CTAS projections pin types the §9 rules must see (issue #20) -----------

CTAS_SQL = """\
CREATE TABLE silver.dim_price AS
SELECT CAST(x.amount AS money) AS Amount,
       CAST(x.d AS datetime)   AS CreatedDt
FROM bronze.raw_prices AS x;
"""


def test_ctas_cast_to_money_and_datetime_fire_with_object_and_lines():
    # The issue's sample: a CTAS creating money/datetime columns fired NOTHING.
    money = run(MONEY_RULE, CTAS_SQL)
    assert len(money) == 1
    assert money[0].object == "silver.dim_price"
    assert money[0].line == 2  # the CAST(... AS money) projection's line
    assert "Amount" in money[0].message
    dt = run(DATETIME_RULE, CTAS_SQL)
    assert len(dt) == 1
    assert dt[0].object == "silver.dim_price"
    assert dt[0].line == 3
    assert "CreatedDt" in dt[0].message


def test_ctas_recommended_types_and_uncast_projections_stay_clean():
    sql = (
        "CREATE TABLE silver.dim_price AS\n"
        "SELECT CAST(x.amount AS decimal(19, 4)) AS Amount,\n"
        "       TRY_CAST(x.d AS datetime2(3)) AS CreatedDt,\n"
        "       x.name AS PriceName\n"
        "FROM bronze.raw_prices AS x;\n"
    )
    for rule in (NVARCHAR_RULE, DATETIME_RULE, MONEY_RULE, DEPRECATED_RULE, UNSUPPORTED_RULE):
        assert run(rule, sql) == []


def test_ctas_try_cast_and_convert_targets_are_seen():
    sql = (
        "CREATE TABLE silver.t AS SELECT TRY_CAST(a AS smallmoney) AS A, "
        "CONVERT(nvarchar(50), b) AS B FROM s.x;"
    )
    assert len(run(MONEY_RULE, sql)) == 1
    assert len(run(NVARCHAR_RULE, sql)) == 1


def test_ctas_set_operation_body_uses_left_branch():
    sql = (
        "CREATE TABLE silver.t AS\n"
        "SELECT CAST(a AS money) AS Amount FROM s.x\n"
        "UNION ALL\n"
        "SELECT CAST(b AS money) AS Amount FROM s.y;\n"
    )
    findings = run(MONEY_RULE, sql)
    assert len(findings) == 1  # one output column -> one finding, from the left branch
    assert findings[0].object == "silver.t"


def test_ctas_inside_proc_body_is_seen():
    sql = (
        "CREATE OR ALTER PROCEDURE silver.p AS\n"
        "BEGIN\n"
        "    CREATE TABLE silver.t AS SELECT CAST(a AS money) AS Amount FROM s.x;\n"
        "END\n"
    )
    findings = run(MONEY_RULE, sql)
    assert len(findings) == 1
    assert findings[0].object == "silver.t"


def test_create_table_with_column_list_behavior_unchanged():
    # A plain column list must not gain or lose findings from the CTAS path.
    findings = run(MONEY_RULE, POSITIVE_SQL)
    assert len(findings) == 1
    assert findings[0].line == 5  # the `price MONEY` column line, as before
