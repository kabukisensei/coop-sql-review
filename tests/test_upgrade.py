"""Self-update logic (no network): classification + command shapes.

The command-shape assertions encode the playbook's hard-won gotchas
(pipx reinstall vs upgrade for VCS installs, force-reinstall for pip URLs).
"""

import subprocess
from pathlib import Path

from coop_sql_review.upgrade import (
    UpgradePlan,
    apply_plan,
    classify_update,
    is_vcs_spec,
    upgrade_command,
)


def _ok_runner(record):
    def runner(command, **kwargs):
        record.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    return runner


def test_classify_update():
    assert classify_update("1.0.0", None) == "unknown"
    assert classify_update("1.0.0", "1.0.0") == "current"
    assert classify_update("1.0.0", "1.2.0") == "safe"
    assert classify_update("1.0.0", "2.0.0") == "major"


def test_is_vcs_spec_by_scheme_not_substring():
    assert is_vcs_spec("git+https://example/x.git")
    assert not is_vcs_spec("/home/u/c++proj")  # bare '+' is not VCS
    assert not is_vcs_spec(None)


def test_pipx_vcs_uses_reinstall_not_force():
    record = []
    plan = UpgradePlan("pipx", None, "0.1.0", "note", pip_spec="git+https://e/x.git@main")
    apply_plan(plan, runner=_ok_runner(record))
    assert record[0][:2] == ["pipx", "reinstall"]


def test_pipx_pypi_uses_upgrade():
    record = []
    plan = UpgradePlan("pipx", None, "0.1.0", "note", pip_spec=None)
    apply_plan(plan, runner=_ok_runner(record))
    assert record[0][:2] == ["pipx", "upgrade"]


def test_pip_url_force_reinstalls():
    record = []
    plan = UpgradePlan("pip", None, "0.1.0", "note", pip_spec="git+https://e/x.git")
    apply_plan(plan, runner=_ok_runner(record))
    assert "--force-reinstall" in record[0]


def test_upgrade_command_pipx_pypi_is_pipx_upgrade():
    plan = UpgradePlan("pipx", None, "0.1.0", "note", pip_spec=None)
    assert upgrade_command(plan) == [["pipx", "upgrade", "coop-sql-review"]]


def test_upgrade_command_pipx_vcs_is_reinstall():
    plan = UpgradePlan("pipx", None, "0.1.0", "note", pip_spec="git+https://e/x.git@main")
    assert upgrade_command(plan) == [["pipx", "reinstall", "coop-sql-review"]]


def test_upgrade_command_pip_pypi_uses_friendly_python():
    # Display tokens, not sys.executable: a copy-pasteable `python -m pip ...`.
    plan = UpgradePlan("pip", None, "0.1.0", "note", pip_spec=None)
    assert upgrade_command(plan) == [["python", "-m", "pip", "install", "-U", "coop-sql-review"]]


def test_upgrade_command_git_checkout_pulls_then_reinstalls():
    # When upstream has new commits, pull THEN reinstall (so a non-editable
    # clone install actually updates, not just its working tree).
    checkout = Path("/repo")
    plan = UpgradePlan("git-checkout", checkout, "0.1.0", "2 new commit(s) available on the upstream branch")
    assert upgrade_command(plan) == [
        ["git", "-C", str(checkout), "pull", "--ff-only"],
        ["python", "-m", "pip", "install", "-U", str(checkout)],
    ]


def test_upgrade_command_git_checkout_no_upstream_only_reinstalls():
    # No upstream -> nothing to pull (git pull would fail); just reinstall.
    checkout = Path("/repo")
    plan = UpgradePlan("git-checkout", checkout, "0.1.0", "git checkout with no upstream remote")
    assert upgrade_command(plan) == [["python", "-m", "pip", "install", "-U", str(checkout)]]
