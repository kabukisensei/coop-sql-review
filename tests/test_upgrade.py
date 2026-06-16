"""Self-update logic (no network): classification + command shapes.

The command-shape assertions encode the playbook's hard-won gotchas
(pipx reinstall vs upgrade for VCS installs, force-reinstall for pip URLs).
"""

import subprocess

from coop_sql_review.upgrade import (
    UpgradePlan,
    apply_plan,
    classify_update,
    is_vcs_spec,
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
