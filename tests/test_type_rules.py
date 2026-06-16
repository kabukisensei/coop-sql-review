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
