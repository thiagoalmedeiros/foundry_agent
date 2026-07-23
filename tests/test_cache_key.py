"""Prompt-cache routing: every stage's requests carry that stage's stable key.

The key is per stage (not per conversation) because Azure routes by key +
prefix hash and wants a stable mapping between a key and its shared prompt
prefixes — and what a stage's requests share is the agent's instructions/tools
prefix. These tests pin that each agent-glue call hands the key to the client.
"""

from foundry_agent.agents import (
    analyze_gaps,
    author_document,
    create_authoring_agent,
    create_elicitation_agent,
    create_gap_analysis_agent,
    create_validation_agent,
    open_elicitation_conversation,
    validate_document,
)
from foundry_agent.skill_validation import bind_skill_validation_tool
from tests.conftest import (
    COMPLETE_VALIDATION,
    GROUPS,
    OPEN_TURN,
    STUB_DOCUMENT,
    TWO_GAP_REPORT,
    VALIDATOR,
)


async def test_analysis_requests_carry_the_analysis_key(make_stub_client):
    client = make_stub_client(TWO_GAP_REPORT)

    await analyze_gaps(create_gap_analysis_agent(client), "any input", GROUPS.groups)

    assert client.options["prompt_cache_key"] == "policy-report-agent:analysis"


async def test_elicitation_requests_carry_the_elicitation_key(make_stub_client):
    client = make_stub_client(OPEN_TURN)
    agent = create_elicitation_agent(client)

    await open_elicitation_conversation(
        agent, agent.create_session(), GROUPS.groups, TWO_GAP_REPORT, "content"
    )

    assert client.options["prompt_cache_key"] == "policy-report-agent:elicitation"


async def test_validation_requests_carry_the_validation_key(make_stub_client):
    client = make_stub_client(COMPLETE_VALIDATION)
    tool = bind_skill_validation_tool(VALIDATOR, [g.model_dump() for g in GROUPS.groups])

    await validate_document(create_validation_agent(client), "any input", GROUPS.groups, tool)

    assert client.options["prompt_cache_key"] == "policy-report-agent:validation"


async def test_authoring_requests_carry_the_authoring_key(make_stub_client):
    client = make_stub_client(None, text=STUB_DOCUMENT)

    await author_document(create_authoring_agent(client), "validated content")

    assert client.options["prompt_cache_key"] == "policy-report-agent:authoring"
