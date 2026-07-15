import subprocess, os
from click.testing import CliRunner
from coop_sql_review.cli import cli

def run_test():
    cwd = "/tmp/test_git"
    os.makedirs(cwd, exist_ok=True)
    subprocess.run(["rm", "-rf", ".git", "*.sql"], cwd=cwd)
    subprocess.run(["git", "init", "-q"], cwd=cwd, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=cwd, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=cwd, check=True)
    
    with open(f"{cwd}/old.sql", "w") as f: f.write("SELECT 1;")
    subprocess.run(["git", "add", "old.sql"], cwd=cwd, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=cwd, check=True)
    
    with open(f"{cwd}/old.sql", "w") as f: f.write("SELECT 2;")
    with open(f"{cwd}/new.sql", "w") as f: f.write("SELECT 3;")
    with open(f"{cwd}/unchanged.sql", "w") as f: f.write("SELECT 4;")
    subprocess.run(["git", "add", "unchanged.sql"], cwd=cwd, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add unchanged"], cwd=cwd, check=True)

    old_cwd = os.getcwd()
    os.chdir(cwd)
    try:
        runner = CliRunner()
        result = runner.invoke(cli, ["check", "--changed", "HEAD~1"], catch_exceptions=False)
        print("HEAD~1 output:", result.output)
    finally:
        os.chdir(old_cwd)

run_test()
