"""The coop-review-core wiring seams: the shim binds THIS tool, and its re-export
surface keeps resolving (so `from coop_sql_review.<shim> import X` stays valid)."""

import subprocess

from coop_sql_review import __version__


def _fake_runner(cmd, **_kwargs):
    # Stand in for git/subprocess so build_plan never shells out or hits the network.
    return subprocess.CompletedProcess(cmd, 0, stdout="0\n", stderr="")


def test_build_plan_binds_this_package_and_version():
    # The shim's whole job: build_plan() -> core.build_plan(PACKAGE_NAME, __version__).
    from coop_sql_review.upgrade import PACKAGE_NAME, build_plan

    assert PACKAGE_NAME == "coop-sql-review"
    plan = build_plan(
        fetch=lambda _n: None,
        origin=lambda _n: None,
        installed_version_of=lambda _n: "0.0.0",
        runner=_fake_runner,
    )
    assert plan.package_name == "coop-sql-review"
    assert plan.tool_installed == __version__


def test_upgrade_command_carries_this_tool_name():
    from coop_sql_review.upgrade import UpgradePlan, upgrade_command

    plan = UpgradePlan(
        package_name="coop-sql-review", install_method="pipx", checkout=None, tool_installed="x", tool_note=""
    )
    assert upgrade_command(plan) == [["pipx", "upgrade", "coop-sql-review"]]


def test_shim_reexports_still_resolve():
    # Lock the back-compat surface the shims promise (a dropped name fails here, not at a user import).
    from coop_sql_review.diagnostics import (  # noqa: F401
        BASELINE_STALE,
        CONFIG_UNKNOWN_RULE,
        DIAGNOSTIC_SEVERITIES,
        FILE_UNREADABLE,
        IGNORE_STALE,
        PARSE_DEGRADED,
        PARSE_FAILED,
        RULE_ERROR,
        Diagnostic,
    )
    from coop_sql_review.finding import SEVERITIES, at_or_above, severity_rank  # noqa: F401
    from coop_sql_review.progress import Progress, Tick, should_enable  # noqa: F401
    from coop_sql_review.standards import (  # noqa: F401
        RuleConfig,
        StandardsError,
        add_ignores,
        apply_config,
        default_config_path,
        resolve_standards_path,
        standards_info,
    )
    from coop_sql_review.suppressions import (  # noqa: F401
        is_inline_suppressed,
        load_baseline,
        scan_directives,
        write_baseline,
    )
    from coop_sql_review.upgrade import (  # noqa: F401
        DependencyStatus,
        UpgradeError,
        UpgradePlan,
        apply_plan,
        build_plan,
        classify_update,
        is_vcs_spec,
        upgrade_command,
    )
