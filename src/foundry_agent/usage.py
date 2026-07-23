"""Per-stage token accounting for one workflow run.

Every agent call is logged as one structured line — stage, field group,
input / cached / output token counts — and folded into a :class:`RunUsage`
accumulator so the assembler can log a per-stage summary when the run ends.
This is what makes cost attributable per stage and prompt-cache behaviour
observable (``cached > 0``) instead of assumed.

The counts come from ``AgentResponse.usage_details`` (an ``agent_framework``
``UsageDetails`` TypedDict; verified against agent-framework 1.11.0). A stub
or provider that reports no usage yields zeros rather than an error — the
absence of numbers is itself worth seeing in the log.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass

from opentelemetry import trace

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class UsageRecord:
    """Token counts for a single agent call."""

    stage: str
    group_id: str | None
    input_tokens: int
    cached_tokens: int
    output_tokens: int


class RunUsage:
    """Accumulates one run's :class:`UsageRecord` entries and totals them."""

    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    def add(self, record: UsageRecord) -> None:
        """Fold one call's counts into the run."""
        self.records.append(record)

    def summary(self) -> str:
        """One line per stage with call and token totals, then the run total."""
        by_stage: dict[str, list[UsageRecord]] = defaultdict(list)
        for record in self.records:
            by_stage[record.stage].append(record)
        lines = [_totals_line(stage, records) for stage, records in by_stage.items()]
        lines.append(_totals_line("total", self.records))
        return "run usage — " + "; ".join(lines)


def _totals_line(label: str, records: list[UsageRecord]) -> str:
    """One summary line: call count and token sums for the given records."""
    return (
        f"{label}: calls={len(records)} "
        f"input={sum(r.input_tokens for r in records)} "
        f"cached={sum(r.cached_tokens for r in records)} "
        f"output={sum(r.output_tokens for r in records)}"
    )


def log_usage(
    stage: str, group_id: str | None, response: object, usage: RunUsage | None = None
) -> UsageRecord:
    """Log one agent call's token counts and record them against the run.

    Args:
        stage: Workflow stage that made the call (``analysis``, ``elicitation``,
            ``validation``, ``authoring``).
        group_id: Field group in scope, or ``None`` for group-less stages.
        response: The agent response; its ``usage_details`` mapping is read if
            present, and missing or ``None`` counts are recorded as zero.
        usage: Run accumulator to fold the record into, if one is tracking.

    Returns:
        The record that was logged.
    """
    details = getattr(response, "usage_details", None) or {}
    record = UsageRecord(
        stage=stage,
        group_id=group_id,
        input_tokens=details.get("input_token_count") or 0,
        cached_tokens=details.get("cache_read_input_token_count") or 0,
        output_tokens=details.get("output_token_count") or 0,
    )
    logger.info(
        "usage stage=%s group=%s input=%d cached=%d output=%d",
        record.stage,
        record.group_id or "-",
        record.input_tokens,
        record.cached_tokens,
        record.output_tokens,
    )
    _annotate_span(record)
    if usage is not None:
        usage.add(record)
    return record


def _annotate_span(record: UsageRecord) -> None:
    """Attach this call's token counts to the active OTel span.

    In a hosted run the active span is the agent/chat operation MAF already
    traces, so the per-stage counts land alongside its gen-ai attributes in
    App Insights — the same numbers the log line carries, now queryable.
    ``set_attribute`` on the default non-recording span is a safe no-op, so
    this costs nothing offline (tests, DevUI without an exporter).
    """
    span = trace.get_current_span()
    if not span.is_recording():
        return
    span.set_attribute("foundry_agent.usage.stage", record.stage)
    if record.group_id is not None:
        span.set_attribute("foundry_agent.usage.group", record.group_id)
    span.set_attribute("foundry_agent.usage.input_tokens", record.input_tokens)
    span.set_attribute("foundry_agent.usage.cached_tokens", record.cached_tokens)
    span.set_attribute("foundry_agent.usage.output_tokens", record.output_tokens)
