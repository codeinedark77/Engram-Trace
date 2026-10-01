from __future__ import annotations

from .models import TraceRecord


def replay_chain(records: list[TraceRecord]) -> str:
    """Render a correlation_id's full trace chain as a readable markdown
    timeline, indenting child decisions under the parent that spawned them."""
    if not records:
        return "_(no records for this correlation id)_"

    by_id = {r.trace_id: r for r in records}
    lines = [f"## Decision chain — {records[0].correlation_id}", ""]

    for r in records:
        depth = 0
        cursor = r
        seen = set()
        while cursor.parent_trace_id and cursor.parent_trace_id in by_id and cursor.parent_trace_id not in seen:
            seen.add(cursor.parent_trace_id)
            cursor = by_id[cursor.parent_trace_id]
            depth += 1
        indent = "  " * depth
        outcome = r.outcome.value if hasattr(r.outcome, "value") else r.outcome
        reasoning = f" — _{r.reasoning}_" if r.reasoning else ""
        lines.append(f"{indent}- `[{r.timestamp}]` **{r.agent_id}** → {r.decision} ({outcome}){reasoning}")

    return "\n".join(lines)
