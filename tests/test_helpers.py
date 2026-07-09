"""Unit tests for rules/helpers.py — the object-naming helpers.

``dml_target`` names the table a DML statement writes to; these pin the two
identity-critical behaviors: temp targets keep their ``#``/``@`` prefix
(issue #13) and the T-SQL aliased-update form resolves the alias to the real
table (issue #14). Both feed suppression fingerprints, so a wrong name here
breaks baselines/ignores, not just report cosmetics.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.helpers import dml_target


def _first_dml(sql: str, node_type) -> exp.Expression:
    parsed = parse_sql("t.sql", sql)
    (_, node), *_ = parsed.find_all(node_type)
    return node


# -- temp targets keep their prefix (issue #13) ------------------------------


def test_dml_target_preserves_temp_prefixes():
    # A temp target must never render as dbo.<name> — that collides with a real
    # table's suppression fingerprint.
    cases = {
        "INSERT INTO #staging VALUES (1);": "#staging",
        "INSERT INTO ##globals VALUES (1);": "##globals",
        "INSERT INTO @rows VALUES (1);": "@rows",
        "INSERT INTO [#Bracketed] (a) VALUES (1);": "#bracketed",
        "INSERT INTO silver.dim_x VALUES (1);": "silver.dim_x",
    }
    for sql, expected in cases.items():
        assert dml_target(_first_dml(sql, exp.Insert)) == expected, sql


# -- aliased UPDATE ... FROM resolves to the real table (issue #14) ----------

ALIASED_UPDATE = """\
UPDATE d
SET d.IsCurrent = 0, d.ExpirationDate = s.EffectiveDate
FROM silver.dim_customer AS d
JOIN silver.stg_customer AS s ON s.customer_id = d.customer_id;
"""


def test_update_alias_resolves_through_from():
    assert dml_target(_first_dml(ALIASED_UPDATE, exp.Update)) == "silver.dim_customer"


def test_update_alias_resolves_through_join_source():
    sql = (
        "UPDATE s SET s.flag = 1 "
        "FROM silver.dim_customer AS d "
        "JOIN silver.stg_customer AS s ON s.customer_id = d.customer_id;"
    )
    assert dml_target(_first_dml(sql, exp.Update)) == "silver.stg_customer"


def test_update_alias_matches_bare_table_name_in_from():
    # No alias on the source: `UPDATE t ... FROM schema.t` binds by table name.
    sql = "UPDATE dim_customer SET IsCurrent = 0 FROM silver.dim_customer WHERE 1 = 1;"
    assert dml_target(_first_dml(sql, exp.Update)) == "silver.dim_customer"


def test_update_qualified_target_is_unchanged():
    sql = "UPDATE silver.dim_x SET a = 1 WHERE b = 2;"
    assert dml_target(_first_dml(sql, exp.Update)) == "silver.dim_x"


def test_update_one_part_target_without_from_is_unchanged():
    sql = "UPDATE one_part_table SET a = 1;"
    assert dml_target(_first_dml(sql, exp.Update)) == "dbo.one_part_table"


def test_update_one_part_target_with_unrelated_from_falls_back():
    # No alias/name match in FROM -> today's behavior (a genuine one-part name).
    sql = "UPDATE t SET t.a = u.a FROM silver.other AS u;"
    assert dml_target(_first_dml(sql, exp.Update)) == "dbo.t"


def test_update_alias_does_not_capture_subquery_inner_tables():
    # The inner table of a derived-table subquery must not capture the alias.
    sql = "UPDATE d SET d.a = 1 FROM (SELECT * FROM silver.inner_t AS d) AS sub;"
    assert dml_target(_first_dml(sql, exp.Update)) == "dbo.d"


def test_update_temp_target_is_not_resolved_against_from():
    # `UPDATE #t ... FROM silver.t` — the temp table is the target; it must not
    # be "resolved" to the persisted silver.t by the name match.
    sql = "UPDATE #t SET a = s.a FROM silver.t AS s;"
    assert dml_target(_first_dml(sql, exp.Update)) == "#t"


def test_delete_alias_form_resolves_to_real_table():
    # sqlglot puts the real table on Delete.this for `DELETE d FROM ... AS d`.
    sql = "DELETE d FROM silver.dim_x AS d WHERE d.a = 1;"
    assert dml_target(_first_dml(sql, exp.Delete)) == "silver.dim_x"
