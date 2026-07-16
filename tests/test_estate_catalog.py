from pathlib import Path
from click.testing import CliRunner

from coop_sql_review.cli import cli

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
    import json
    
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps({
        "dbo.customers": {
            "customername": "varchar(100)"
        }
    }))

    (tmp_path / "proc.sql").write_text("""
    SELECT *
    FROM dbo.Customers
    WHERE CustomerName = 123
    """)

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path / "proc.sql"), "--schema", str(schema_file), "--format", "json"])
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
    import json
    
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(json.dumps({
        "dbo.customers": {
            "customername": "varchar(100)"
        }
    }))

    (tmp_path / "proc.sql").write_text("""
    SELECT CAST(CustomerName AS VARCHAR(50))
    FROM dbo.Customers
    """)

    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path / "proc.sql"), "--schema", str(schema_file), "--format", "json"])
    assert result.exit_code == 0
    assert "narrows CustomerName (string 100) to string(50)" in result.output
