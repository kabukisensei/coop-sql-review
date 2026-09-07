import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from coop_sql_review import catalog_builder
from coop_sql_review.catalog_builder import build_catalog
from coop_sql_review.cli import cli
from coop_sql_review.sql_model import ColumnDef, ParsedFile, SqlObject


def _write_query(tmp_path: Path) -> Path:
    query = tmp_path / "proc.sql"
    query.write_text("SELECT CustomerName FROM dbo.Customers WHERE CustomerName = 123\n")
    return query


def _check_with_schema(query: Path, schema: Path):
    return CliRunner().invoke(cli, ["check", str(query), "--schema", str(schema), "--format", "json"])


def test_cross_file_implicit_convert(tmp_path: Path):
    (tmp_path / "table.sql").write_text("""
    CREATE TABLE dbo.Customers (
        CustomerID INT,
        CustomerName VARCHAR(100)
    );
    """)

    (tmp_path / "proc.sql").write_text("""
    SELECT *
    FROM dbo.Customers
    WHERE CustomerName = 123
    """)

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path), "--format", "json"])
    assert result.exit_code == 0
    assert "implicit conversion hurts SARGability" in result.output
    assert "CustomerName" in result.output


def test_schema_json_implicit_convert(tmp_path: Path):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps({"dbo.customers": {"customername": "varchar(100)"}}))

    (tmp_path / "proc.sql").write_text("""
    SELECT *
    FROM dbo.Customers
    WHERE CustomerName = 123
    """)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["check", str(tmp_path / "proc.sql"), "--schema", str(schema_file), "--format", "json"]
    )
    assert result.exit_code == 0
    assert "implicit conversion hurts SARGability" in result.output
    assert "CustomerName" in result.output


def test_cross_file_narrowing_cast(tmp_path: Path):
    (tmp_path / "table.sql").write_text("""
    CREATE TABLE dbo.Customers (
        CustomerName VARCHAR(100)
    );
    """)

    (tmp_path / "proc.sql").write_text("""
    SELECT CAST(CustomerName AS VARCHAR(50))
    FROM dbo.Customers
    """)

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path), "--format", "json"])
    assert result.exit_code == 0
    assert "narrows CustomerName (string 100) to string(50)" in result.output


def test_schema_json_narrowing_cast(tmp_path: Path):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps({"dbo.customers": {"customername": "varchar(100)"}}))

    (tmp_path / "proc.sql").write_text("""
    SELECT CAST(CustomerName AS VARCHAR(50))
    FROM dbo.Customers
    """)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["check", str(tmp_path / "proc.sql"), "--schema", str(schema_file), "--format", "json"]
    )
    assert result.exit_code == 0
    assert "narrows CustomerName (string 100) to string(50)" in result.output


def test_schema_json_accepts_utf8_bom(tmp_path: Path):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps({"dbo.customers": {"customername": "varchar(100)"}}),
        encoding="utf-8-sig",
    )

    result = _check_with_schema(_write_query(tmp_path), schema_file)

    assert result.exit_code == 0
    assert "implicit conversion hurts SARGability" in result.output


@pytest.mark.parametrize(
    ("contents", "reason"),
    [
        (b"{not-json", "not valid JSON"),
        (b"[]", "root must be a JSON object"),
        (b'{"dbo.customers": []}', "must map to a JSON object"),
        (b'{"dbo.customers": {"customername": 123}}', "non-empty string SQL type"),
        (b'{"dbo.customers": {"customername": "()"}}', "invalid SQL type"),
    ],
)
def test_invalid_explicit_schema_is_path_specific_usage_error(tmp_path: Path, contents: bytes, reason: str):
    schema_file = tmp_path / "bad-schema.json"
    schema_file.write_bytes(contents)

    result = _check_with_schema(_write_query(tmp_path), schema_file)

    assert result.exit_code == 2
    assert str(schema_file) in result.output
    assert reason in result.output
    assert "Traceback" not in result.output


def test_non_utf8_explicit_schema_is_path_specific_usage_error(tmp_path: Path):
    schema_file = tmp_path / "non-utf8-schema.json"
    schema_file.write_bytes(b'{"dbo.customers": {"customername": "\xff"}}')

    result = _check_with_schema(_write_query(tmp_path), schema_file)

    assert result.exit_code == 2
    assert str(schema_file) in result.output
    assert "not valid UTF-8" in result.output
    assert "Traceback" not in result.output


def test_unreadable_explicit_schema_is_path_specific_usage_error(tmp_path: Path, monkeypatch):
    schema_file = tmp_path / "unreadable-schema.json"
    schema_file.write_text("{}")
    real_read_text = Path.read_text

    def unreadable(path, *args, **kwargs):
        if path == schema_file:
            raise PermissionError("permission denied")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(catalog_builder.Path, "read_text", unreadable)
    result = _check_with_schema(_write_query(tmp_path), schema_file)

    assert result.exit_code == 2
    assert str(schema_file) in result.output
    assert "could not be read" in result.output
    assert "Traceback" not in result.output


def test_external_and_create_table_catalogs_merge_deterministically(tmp_path: Path):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps({"dbo.customers": {"external_col": "varchar(100)", "shared": "int"}}))
    parsed = ParsedFile(
        path="table.sql",
        text="",
        masked="",
        dialect="tsql",
        objects=[
            SqlObject(
                kind="table",
                schema="dbo",
                name="customers",
                display_name="customers",
                line=1,
                columns=[
                    ColumnDef(name="local_col", data_type="BIGINT", base_type="BIGINT", line=2),
                    ColumnDef(name="shared", data_type="INT", base_type="INT", line=3),
                ],
            )
        ],
    )

    first = build_catalog([parsed], str(schema_file))
    second = build_catalog([parsed], str(schema_file))

    assert first == second
    assert sorted(first.tables["dbo.customers"]) == ["external_col", "local_col", "shared"]
    assert first.tables["dbo.customers"]["shared"].base_type == "INT"
