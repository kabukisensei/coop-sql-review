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
    SCAN_EMPTY,  # a scan found no input files at all under a given path
    SYNTAX_ERROR,  # input that fails the tool's own syntax validation
    Diagnostic,
)

# SCAN_EMPTY / SYNTAX_ERROR now live in core (coop-review-core#1) and are
# re-exported above. For this tool, SYNTAX_ERROR is a batch a real T-SQL parser
# (sqlglot at RAISE) rejects as genuinely invalid — distinct from the
# warning-severity gaps PARSE_FAILED / PARSE_DEGRADED; it is "error" by default,
# tunable via the rules.yml `syntax_errors: error|warning|off` knob and an inline
# `coop-sql-review:ignore syntax` directive.

# Tool-local category (core treats categories as open strings, like SCAN_EMPTY
# once was): a dynamic-execution site — EXEC('...')/EXEC(@sql)/sp_executesql —
# whose string-built statements are invisible to every rule (issue #19). Severity
# "warning" by default; tunable via the rules.yml `dynamic_sql: error|warning|off`
# knob (same shape as `syntax_errors`).
DYNAMIC_SQL = "dynamic_sql"
