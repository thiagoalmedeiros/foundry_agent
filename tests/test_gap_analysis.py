"""Gap Analysis: one pass across every discovered group, not one per group."""

import pytest
from pydantic import ValidationError

from foundry_agent.agents import (
    FORMAT_SKILL_NAME,
    GAP_ANALYSIS_INSTRUCTIONS,
    analyze_gaps,
    create_gap_analysis_agent,
)
from foundry_agent.models import AttributeStatus, GapReport
from tests.conftest import GROUPS

_REPORT = GapReport(
    classification="Security",
    attributes=[
        AttributeStatus(
            attribute_id="PA1",
            name="Policy ID",
            required=True,
            populated=False,
            gap="No policy ID present.",
        ),
        AttributeStatus(
            attribute_id="PA7",
            name="Purpose Statement",
            required=True,
            populated=True,
            inferred_value="This policy establishes mandatory VPN rules.",
            evidence="remote logins are permitted from unmanaged personal devices",
        ),
    ],
)


async def test_analyze_gaps_returns_the_structured_report(make_stub_client):
    client = make_stub_client(_REPORT)
    agent = create_gap_analysis_agent(client)

    report = await analyze_gaps(
        agent, "We keep losing fleet telemetry overnight.", GROUPS.groups
    )

    assert report == _REPORT
    assert client.options is not None
    assert client.options["response_format"] is GapReport


async def test_analysis_is_scoped_to_every_group_at_once(make_stub_client):
    """One pass judges ALL groups — the prompt must list every one, not just the first."""
    client = make_stub_client(_REPORT)
    agent = create_gap_analysis_agent(client)

    await analyze_gaps(agent, "any input", GROUPS.groups)

    prompt = client.prompts[0]
    assert "### FG1 — Identification & Classification" in prompt
    assert "### FG2 — Purpose & Context" in prompt
    assert "Attributes in scope: PA1, PA3" in prompt
    assert "Attributes in scope: PA7, PA11" in prompt
    assert "judge or address ALL of them" in prompt


async def test_agent_carries_the_format_skill_content_not_embedded_knowledge(
    make_stub_client,
):
    """The agent's domain knowledge is the inlined skill pack, not prose in code."""
    client = make_stub_client(_REPORT)
    agent = create_gap_analysis_agent(client)

    await analyze_gaps(agent, "any input", GROUPS.groups)

    instructions = client.options["instructions"]
    assert GAP_ANALYSIS_INSTRUCTIONS in instructions
    assert FORMAT_SKILL_NAME in instructions
    assert "REFERENCE MATERIAL (policy-report-format skill, verbatim)" in instructions


def test_instructions_require_covering_every_group_in_one_pass():
    """The one-pass, whole-document contract is stated, not implied."""
    assert "EVERY field group in ONE pass" in GAP_ANALYSIS_INSTRUCTIONS
    assert "Report EVERY attribute across EVERY group" in GAP_ANALYSIS_INSTRUCTIONS
    assert "do not skip a group" in GAP_ANALYSIS_INSTRUCTIONS.lower()


async def test_pattern_composed_attributes_must_be_drafted_not_asked_for(make_stub_client):
    """Having the ingredients for a statement pattern counts as a basis to infer.

    Regression: FG2 reported 0 of 2 inferred from an opening message that
    plainly supplied both, because no sentence was already phrased as the
    finished field — so the user was asked to draft what the agent could have.
    """
    client = make_stub_client(_REPORT)
    agent = create_gap_analysis_agent(client)

    await analyze_gaps(agent, "any input", GROUPS.groups)

    instructions = client.options["instructions"]
    assert "MUST BE COMPOSED, NOT FOUND" in instructions
    assert "Having the INGREDIENTS the pattern calls for IS a basis" in instructions


async def test_analyze_gaps_rejects_a_malformed_response(make_stub_client):
    client = make_stub_client(None, text="not structured")
    agent = create_gap_analysis_agent(client)

    with pytest.raises(ValidationError):
        await analyze_gaps(agent, "any input", GROUPS.groups)
