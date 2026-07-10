"""Tool self-update — bound to this package's name + version.

The planning/command logic lives in ``coop_review_core.upgrade``; here we bake in
this package's name and running version so ``build_plan()`` takes no arguments.
This is the only part of the tool that touches the network; ``check`` never
imports it.
"""

from __future__ import annotations

from coop_review_core import upgrade as _core
from coop_review_core.upgrade import (  # noqa: F401
    DependencyStatus,
    UpgradeError,
    UpgradePlan,
    classify_update,
    is_vcs_spec,
    upgrade_command,
)

from coop_sql_review import __version__

PACKAGE_NAME = "coop-sql-review"


def build_plan(**kwargs) -> UpgradePlan:
    """Plan an upgrade for this package at its running version (collaborators in
    ``kwargs`` are forwarded for tests)."""
    return _core.build_plan(PACKAGE_NAME, __version__, **kwargs)
