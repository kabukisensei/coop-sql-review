"""SQL-SCD2-CORRECT (§6): an SCD Type-2 "close" UPDATE needs a correctness review.

§6 describes the SCD Type-2 pattern as close-then-insert: an ``UPDATE`` that
stamps ``ExpirationDate`` / sets ``IsCurrent = 0`` on the current row, followed
by an ``INSERT`` of the new version. A linter can spot the close step (an
``UPDATE`` whose ``SET`` touches an ``IsCurrent`` / ``ExpirationDate`` column)
but cannot verify the full Type-2 logic is correct — so this is an
agent-judgment rule. UPDATE ``SET`` assignments are ``exp.EQ`` nodes under
``upd.args['expressions']`` whose ``.this`` is the target ``exp.Column``.

The close step is just as often written as a ``MERGE`` whose ``WHEN MATCHED
THEN UPDATE SET`` assigns those columns. In the AST that branch is a
``exp.Update`` (with no target of its own) sitting under ``When``/``Whens`` of
the ``exp.Merge``; the merge's target table lives on the ``Merge`` node. So we
scan merges separately (reporting the merge's target) and skip the merge-branch
``Update`` nodes when scanning standalone ``UPDATE`` statements, to avoid
flagging the same close twice with an empty object.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.finding import AgentReviewItem
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import dml_target

_SCD2_COLUMNS = {"iscurrent", "expirationdate"}

_NOTE = (
    "SCD2 close-then-insert detected — verify Type-2 correctness per §6 (close current row, then insert new)."
)


def _closes_scd2(assignments: list[exp.Expression]) -> bool:
    """True if any ``SET`` assignment targets an SCD2 close column."""
    return any(
        isinstance(eq, exp.EQ) and isinstance(eq.this, exp.Column) and eq.this.name.lower() in _SCD2_COLUMNS
        for eq in assignments
    )


def _inside_merge(node: exp.Expression) -> bool:
    """True if ``node`` is nested inside a ``MERGE`` (its WHEN branch)."""
    current = node.parent
    while current is not None:
        if isinstance(current, exp.Merge):
            return True
        current = current.parent
    return False


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    items: list[AgentReviewItem] = []
    for batch, upd in ctx.parsed.find_all(exp.Update):
        # MERGE close steps are reported via the Merge scan below (with the
        # merge's target); skip the branch Update to avoid a duplicate.
        if _inside_merge(upd):
            continue
        if _closes_scd2(upd.args.get("expressions") or []):
            items.append(
                ctx.review(
                    object=dml_target(upd),
                    line=ctx.parsed.node_line(batch, upd),
                    note=_NOTE,
                )
            )
    for batch, merge in ctx.parsed.find_all(exp.Merge):
        for when in merge.find_all(exp.When):
            then = when.args.get("then")
            if isinstance(then, exp.Update) and _closes_scd2(then.args.get("expressions") or []):
                items.append(
                    ctx.review(
                        object=dml_target(merge),
                        line=ctx.parsed.node_line(batch, merge),
                        note=_NOTE,
                    )
                )
                break
    return items


RULE = Rule(
    id="SQL-SCD2-CORRECT",
    title="SCD Type-2 close step needs a correctness review",
    severity="info",
    category="scd2",
    standard_ref="§6",
    tier=2,
    kind="agent",
    detect=detect,
)
