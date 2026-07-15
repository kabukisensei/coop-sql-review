import pytest
import json
from pathlib import Path
from click.testing import CliRunner
from coop_sql_review.cli import cli

def test_compare_cmd(tmp_path):
    old_env = {
        "tool": "coop-sql-review",
        "findings": [
            {"fingerprint": "1", "severity": "error", "message": "msg1"},
            {"fingerprint": "2", "severity": "warning", "message": "msg2"},
        ],
        "summary": {"error": 1, "warning": 1}
    }
    new_env = {
        "tool": "coop-sql-review",
        "findings": [
            {"fingerprint": "2", "severity": "warning", "message": "msg2"},
            {"fingerprint": "3", "severity": "info", "message": "msg3"},
        ],
        "summary": {"error": 0, "warning": 1, "info": 1}
    }
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps(old_env))
    new_path.write_text(json.dumps(new_env))

    runner = CliRunner()
    result = runner.invoke(cli, ["compare", str(old_path), str(new_path), "--md", str(tmp_path / "delta.md"), "--html", str(tmp_path / "delta.html")])
    assert result.exit_code == 0
    assert "1 new" in result.output
    assert "1 fixed" in result.output
    assert "1 unchanged" in result.output

    md = (tmp_path / "delta.md").read_text()
    assert "**1 new**, **1 fixed**, 1 unchanged" in md
    
    html = (tmp_path / "delta.html").read_text()
    assert "<strong>1 new</strong>, <strong>1 fixed</strong>, 1 unchanged" in html

def test_compare_cmd_wrong_tool(tmp_path):
    old_env = {"tool": "coop-sql-review", "findings": []}
    new_env = {"tool": "coop-dax-review", "findings": []}
    old_path = tmp_path / "old.json"
    new_path = tmp_path / "new.json"
    old_path.write_text(json.dumps(old_env))
    new_path.write_text(json.dumps(new_env))

    runner = CliRunner()
    result = runner.invoke(cli, ["compare", str(old_path), str(new_path)])
    assert result.exit_code != 0
    assert "cannot compare envelopes from different tools" in result.output
