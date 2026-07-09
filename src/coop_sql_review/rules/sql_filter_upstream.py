"""SQL-FILTER-UPSTREAM (§8): a joined+filtered query may want upstream filtering.

§8 says to keep joins simple and push filtering into CTEs so joins operate on
already-filtered datasets. A ``SELECT`` that has both a ``JOIN`` and a ``WHERE``
is a candidate — but whether the filter *should* move upstream depends on row
counts and intent, which a linter can't judge. So this rule detects the
construct and hands it to the agent. We inspect each SELECT's *own* ``joins``
and ``where`` (not descendants).

**Channel hygiene (issue #17):** JOIN+WHERE is the shape of nearly every
production SELECT, so on a real estate this one rule's boilerplate drowned the
agent-review channel (~90% of all items). Two mitigations:

- the rule ships **off by default** (``default_enabled=False``, like the other
  noisy-on-real-estates rules); opt in via ``rules.yml``;
- when enabled, qualifying SELECTs are **collapsed to one item per enclosing
  object** — the note carries the count, the item's line is the first
  qualifying SELECT's, and a single-SELECT object keeps the original note
  verbatim (so those fingerprints are unchanged). The count lives in the note
  (identity stays line- and path-free), so a new JOIN+WHERE in an
  already-reviewed object changes the fingerprint and resurfaces it.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.finding import AgentReviewItem
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object

_SINGLE_NOTE = (
    "join query with a WHERE filter — consider whether filtering should move upstream into a CTE per §8."
)


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    # One item per enclosing object: {object: [count, first_line]} in first-seen
    # order (dicts preserve insertion order; min() keeps the earliest line even
    # if the walk isn't strictly document-ordered).
    groups: dict[str, list[int]] = {}
    for batch, select in ctx.parsed.find_all(exp.Select):
        has_join = bool(select.args.get("joins"))
        has_where = select.args.get("where") is not None
        if not (has_join and has_where):
            continue
        line = ctx.parsed.node_line(batch, select)
        group = groups.setdefault(enclosing_object(select), [0, line])
        group[0] += 1
        group[1] = min(group[1], line)
    items: list[AgentReviewItem] = []
    for obj, (count, first_line) in groups.items():
        note = _SINGLE_NOTE
        if count > 1:
            note = (
                f"{count} join+WHERE queries in this object — consider whether "
                "filtering should move upstream into CTEs per §8 (the line is the first one)."
            )
        items.append(ctx.review(object=obj, line=first_line, note=note))
    return items


RULE = Rule(
    id="SQL-FILTER-UPSTREAM",
    title="Joined query with a WHERE filter may want upstream filtering",
    severity="info",
    category="joins",
    standard_ref="§8",
    tier=2,
    kind="agent",
    # JOIN+WHERE is the shape of nearly every production SELECT — on by default
    # this rule drowns the curated agent channel (issue #17); opt in via rules.yml.
    default_enabled=False,
    detect=detect,
)
