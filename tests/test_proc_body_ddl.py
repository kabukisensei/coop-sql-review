"""Proc-body DDL visibility (the top-level-only Create scan regression).

sqlglot nests a procedure body's statements under the proc's own
``exp.Create`` node, so the parser's old top-level ``isinstance(e, exp.Create)``
scan never saw a ``CREATE TABLE`` inside a ``CREATE PROCEDURE`` — the §9 type
rules, SQL-TABLE-LAYER-NAME, and the in-file size maps all silently
under-reported on an all-procs estate, with **no** diagnostic. ``parse_sql``
now walks each top-level statement with ``find_all(exp.Create)``; these tests
pin that body DDL is lifted with precise lines, that the rules fire on it, and
that top-level extraction (order, count — each Create exactly once) is
unchanged.
"""

from __future__ import annotations

from pathlib import Path

from coop_sql_review.engine import run_rules
from coop_sql_review.parser import parse_sql
from coop_sql_review.rules import all_rules
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_table_layer_name import RULE as LAYER_RULE
from coop_sql_review.rules.sql_type_datetime import RULE as DATETIME_RULE
from coop_sql_review.rules.sql_type_money import RULE as MONEY_RULE
from coop_sql_review.rules.sql_type_nvarchar import RULE as NVARCHAR_RULE

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "proc_body_ddl.sql"


def _parsed():
    return parse_sql("proc_body_ddl.sql", FIXTURE.read_text(encoding="utf-8-sig"))


def _run(rule, parsed):
    return rule.check(RuleContext(rule, parsed))


def test_proc_body_tables_are_extracted_with_lines():
    parsed = _parsed()
    by_kind = [(o.kind, f"{o.schema}.{o.name}") for o in parsed.objects]
    # Exactly these four, each once (find_all must not double-visit a Create):
    # the proc itself, its two body tables, and the top-level table in batch 2.
    assert by_kind == [
        ("proc", "silver.usp_build_pricing"),
        ("table", "silver.dim_pricing"),
        ("table", "staging.price_work"),
        ("table", "gold.fact_price"),
    ]
    dim = next(o for o in parsed.objects if o.name == "dim_pricing")
    cols = {c.name: c for c in dim.columns}
    assert cols["ListPrice"].base_type == "MONEY"
    assert cols["CreatedDt"].base_type == "DATETIME"
    assert cols["Descr"].base_type == "NVARCHAR"
    # Precise file lines survive the proc nesting.
    assert cols["ListPrice"].line == 9
    assert cols["CreatedDt"].line == 10
    assert cols["Descr"].line == 11


def test_type_rules_fire_inside_proc_body():
    parsed = _parsed()
    money = _run(MONEY_RULE, parsed)
    assert [(f.file, f.line, f.object) for f in money] == [("proc_body_ddl.sql", 9, "silver.dim_pricing")]
    datetime_findings = _run(DATETIME_RULE, parsed)
    assert [(f.line, f.object) for f in datetime_findings] == [(10, "silver.dim_pricing")]
    nvarchar = _run(NVARCHAR_RULE, parsed)
    assert [(f.line, f.object) for f in nvarchar] == [(11, "silver.dim_pricing")]


def test_layer_name_fires_on_proc_body_table():
    parsed = _parsed()
    findings = _run(LAYER_RULE, parsed)
    # Only the layer-misnamed body table — silver.dim_pricing and the
    # top-level gold.fact_price are properly layered.
    assert [(f.file, f.line, f.object) for f in findings] == [("proc_body_ddl.sql", 14, "staging.price_work")]


def test_temp_table_in_proc_body_still_skipped_by_layer_rule():
    sql = "CREATE PROCEDURE silver.p AS BEGIN CREATE TABLE #work (Id INT); END"
    parsed = parse_sql("t.sql", sql)
    temp = next(o for o in parsed.objects if o.kind == "table")
    assert temp.is_temp
    assert _run(LAYER_RULE, parsed) == []


def test_top_level_extraction_unchanged():
    # The pre-fix behavior for top-level DDL: same objects, same order, no dupes.
    sql = "CREATE TABLE silver.a (Id INT);\nGO\nCREATE VIEW gold.v AS SELECT 1 AS x;\n"
    parsed = parse_sql("t.sql", sql)
    assert [(o.kind, f"{o.schema}.{o.name}") for o in parsed.objects] == [
        ("table", "silver.a"),
        ("view", "gold.v"),
    ]


def test_engine_reports_each_body_finding_exactly_once():
    # Belt-and-braces against a double-visited Create inflating finding counts.
    result = run_rules([_parsed()], all_rules())
    money = [f for f in result.findings if f.rule_id == "SQL-TYPE-MONEY"]
    assert len(money) == 1
