import subprocess
import os
from click.testing import CliRunner
from coop_sql_review.cli import cli


def test_check_changed(tmp_path):
    cwd = str(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=cwd, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=cwd, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=cwd, check=True)

    (tmp_path / "old.sql").write_text("SELECT 1;")
    subprocess.run(["git", "add", "old.sql"], cwd=cwd, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=cwd, check=True)

    (tmp_path / "old.sql").write_text("SELECT 2;")
    (tmp_path / "new.sql").write_text("SELECT 3;")
    (tmp_path / "unchanged.sql").write_text("SELECT 4;")
    subprocess.run(["git", "add", "unchanged.sql"], cwd=cwd, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add unchanged"], cwd=cwd, check=True)

    old_cwd = os.getcwd()
    os.chdir(cwd)
    try:
        runner = CliRunner()
        result = runner.invoke(cli, ["check", "--changed", "HEAD~1"], catch_exceptions=False)
        assert "files checked: 3" in result.output

        # Just untracked + modified
        subprocess.run(["git", "add", "new.sql", "old.sql"], cwd=cwd, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "commit2"], cwd=cwd, check=True)

        # nothing in working tree changed since HEAD
        result = runner.invoke(cli, ["check", "--changed"], catch_exceptions=False)
        assert "no .sql files changed since HEAD" in result.output
    finally:
        os.chdir(old_cwd)
