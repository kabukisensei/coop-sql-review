"""SQL-TYPE-UNSUPPORTED (§9): types Fabric DW rejects for tables.

Beyond the money/datetime/nchar/deprecated-LOB rules, Microsoft's "unsupported
data types for tables" list (learn.microsoft.com/fabric/data-warehouse/data-types)
also rejects, for persisted table columns: ``tinyint``, ``xml``, ``json``,
``geography``, ``geometry``, and user-defined / CLR types (e.g. ``hierarchyid``).
Fabric DW would reject the CREATE TABLE outright, but this linter is advisory
(warning). Fabric-DW-only — Azure SQL supports these, so it's skipped under
``--target azure-sql``. (rowversion/sql_variant are deliberately NOT flagged —
they are not on the current MS unsupported-for-tables list.)
"""

from __future__ import annotations

from coop_sql_review.rules.base import FABRIC_ONLY, Rule, RuleContext
from coop_sql_review.finding import Finding

# Matched on the rendered ``data_type`` keyword (sqlglot's tsql base_type is unstable
# here — e.g. tinyint -> UTINYINT — but data_type preserves the original spelling).
_UNSUPPORTED = {
    "TINYINT": "smallint",
    "JSON": "varchar",
    "XML": "no equivalent — store as varchar, or process XML outside the warehouse",
    "GEOGRAPHY": "a (lat, long) column pair, varbinary well-known-binary, or varchar well-known-text",
    "GEOMETRY": "a (lat, long) column pair, varbinary well-known-binary, or varchar well-known-text",
    # VECTOR is a real SQL Server 2025 type but unsupported for Fabric DW tables (both
    # the data-types page and the T-SQL surface-area page). It parses cleanly as a
    # base type, so without this entry a stored vector column slips through silently.
    "VECTOR": "no equivalent — use the AI_* built-in functions instead of a stored vector column",
}


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for obj in ctx.parsed.objects:
        if obj.kind != "table":
            continue
        for col in obj.columns:
            key = col.data_type.split("(")[0].strip().upper()
            if key in _UNSUPPORTED:
                message = f"column {col.name} uses {key.lower()} — unsupported by Fabric DW for tables; use {_UNSUPPORTED[key]} (§9)."
            elif col.base_type == "USERDEFINED":
                # hierarchyid and CLR user-defined types both fold to USERDEFINED.
                message = (
                    f"column {col.name} uses a user-defined/CLR type ({col.data_type.lower()}) "
                    "— unsupported by Fabric DW for tables; model it with supported types (§9)."
                )
            else:
                continue
            findings.append(ctx.finding(line=col.line, object=f"{obj.schema}.{obj.name}", message=message))
    return findings


RULE = Rule(
    id="SQL-TYPE-UNSUPPORTED",
    title="No table types Fabric DW rejects (tinyint/xml/json/geography/geometry/CLR)",
    severity="warning",
    category="datatypes",
    standard_ref="§9",
    tier=1,
    targets=FABRIC_ONLY,
    check=check,
)
