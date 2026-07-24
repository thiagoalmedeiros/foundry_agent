"""Per-stage token accounting: extraction, accumulation, and agent-glue wiring."""

import logging

import pytest

from foundry_agent.agents import create_elicitation_agent, open_group_conversation
from foundry_agent.usage import RunUsage, UsageRecord, log_usage
from tests.conftest import GROUPS, OPEN_TURN


class _Response:
    """Response double carrying only the usage surface log_usage reads."""

    def __init__(self, usage_details: dict | None) -> None:
        self.usage_details = usage_details


def test_log_usage_extracts_counts_from_usage_details():
    record = log_usage(
        "analysis",
        "FG1",
        _Response(
            {
                "input_token_count": 1200,
                "output_token_count": 300,
                "cache_read_input_token_count": 800,
            }
        ),
    )

    assert record == UsageRecord(
        stage="analysis", group_id="FG1", input_tokens=1200, cached_tokens=800, output_tokens=300
    )


@pytest.mark.parametrize(
    "details",
    [None, {}, {"input_token_count": None, "output_token_count": None}],
    ids=["missing", "empty", "none-values"],
)
def test_log_usage_without_counts_records_zeros(details):
    """Stubs and providers that report no usage must not break the run."""
    record = log_usage("validation", None, _Response(details))

    assert (record.input_tokens, record.cached_tokens, record.output_tokens) == (0, 0, 0)


def test_log_usage_emits_one_structured_line(caplog):
    with caplog.at_level(logging.INFO, logger="foundry_agent.usage"):
        log_usage("elicitation", "FG2", _Response({"input_token_count": 50}))

    assert "usage stage=elicitation group=FG2 input=50 cached=0 output=0" in caplog.text


def test_log_usage_folds_the_record_into_the_run():
    usage = RunUsage()

    record = log_usage("authoring", None, _Response({"output_token_count": 900}), usage)

    assert usage.records == [record]


def test_run_usage_summary_totals_per_stage_and_overall():
    usage = RunUsage()
    usage.add(UsageRecord("analysis", "FG1", 100, 10, 20))
    usage.add(UsageRecord("analysis", "FG2", 200, 0, 30))
    usage.add(UsageRecord("authoring", None, 50, 0, 400))

    summary = usage.summary()

    assert "analysis: calls=2 input=300 cached=10 output=50" in summary
    assert "authoring: calls=1 input=50 cached=0 output=400" in summary
    assert "total: calls=3 input=350 cached=10 output=450" in summary


async def test_elicitation_turn_records_usage_for_its_stage(make_stub_client, caplog):
    """The agent glue logs every elicitation call, even when the stub reports no counts."""
    client = make_stub_client(OPEN_TURN)
    agent = create_elicitation_agent(client)
    usage = RunUsage()

    with caplog.at_level(logging.INFO, logger="foundry_agent.usage"):
        await open_group_conversation(agent, agent.create_session(), GROUPS.groups[0], "x", usage)

    assert [(r.stage, r.group_id) for r in usage.records] == [("elicitation", None)]
    assert "usage stage=elicitation group=-" in caplog.text
