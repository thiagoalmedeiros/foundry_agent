"""Prompt-cache routing: every stage's requests carry that stage's stable key.

The key is per stage (not per conversation) because Azure routes by key +
prefix hash and wants a stable mapping between a key and its shared prompt
prefixes — and what a stage's requests share is the agent's instructions/tools
prefix. These tests pin that each agent-glue call hands the key to the client.
"""

from foundry_agent.agents import (
    author_document,
    create_authoring_agent,
    create_elicitation_agent,
    create_validation_agent,
    open_group_conversation,
    validate_document,
)
from tests.conftest import (
    COMPLETE_VALIDATION,
    GROUPS,
    OPEN_TURN,
    STUB_DOCUMENT,
)


async def test_elicitation_requests_carry_the_elicitation_key(make_stub_client):
    client = make_stub_client(OPEN_TURN)
    agent = create_elicitation_agent(client)

    await open_group_conversation(agent, agent.create_session(), GROUPS.groups[0], "content")

    assert client.options["prompt_cache_key"] == "report-interview-agent:elicitation"


async def test_validation_requests_carry_the_validation_key(make_stub_client):
    client = make_stub_client(COMPLETE_VALIDATION)

    await validate_document(create_validation_agent(client), "any input", GROUPS.groups)

    assert client.options["prompt_cache_key"] == "report-interview-agent:validation"


async def test_authoring_requests_carry_the_authoring_key(make_stub_client):
    client = make_stub_client(None, text=STUB_DOCUMENT)

    await author_document(create_authoring_agent(client), "validated content")

    assert client.options["prompt_cache_key"] == "report-interview-agent:authoring"
