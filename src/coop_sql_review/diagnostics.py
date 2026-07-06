"""Processing diagnostics — re-exported from the shared ``coop-review-core``.

The Diagnostic model and category constants are tool-agnostic, so they live in
``coop_review_core.diagnostics`` and are re-exported here for backward-compatible
imports (``from coop_sql_review.diagnostics import Diagnostic`` still works).
"""

from coop_review_core.diagnostics import (  # noqa: F401
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

# Tool-local category (not in core yet): a scan found no .sql files at all under
# a given path — files_checked=0 must stay machine-distinguishable from "clean".
SCAN_EMPTY = "scan_empty"

# Tool-local category: a batch a real T-SQL parser (sqlglot at RAISE level)
# rejects as genuinely invalid syntax — the kind that fails Fabric's import
# ("Incorrect syntax near ..."). Distinct from the warning-severity gaps:
# PARSE_FAILED (the whole batch is opaque) and PARSE_DEGRADED (valid-but-
# unsupported syntax, e.g. ALTER COLUMN ... NOT NULL). Severity is "error" by
# default; the rules.yml `syntax_errors: error|warning|off` knob can downgrade
# or disable it, and an inline `coop-sql-review:ignore syntax` directive
# suppresses a single occurrence.
SYNTAX_ERROR = "syntax_error"
