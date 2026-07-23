"""Discovery reads the format skill and lists its groups — as an agent, not a parser.

The workflow-build sibling enumerates the field groups with an LLM agent that
loads the skill through progressive disclosure, replacing the deterministic
parser (kept dormant for the sequential sibling). These tests pin the agent's
mount, its structured-output request, and the helper's return — all offline
against a stub client.
"""

from agent_framework import Agent

from foundry_agent.agents import (
    FORMAT_SKILL_NAME,
    create_discovery_agent,
    discover_groups,
)
from tests.conftest import GROUPS


async def _run_once(agent: Agent) -> None:
    """One stubbed run, to make the agent hand its options to the client."""
    await agent.run("ping")


async def test_discovery_agent_mounts_the_format_skill_via_disclosure(make_stub_client):
    """Discovery reads the skill through load_skill / read_skill_resource tools."""
    client = make_stub_client(GROUPS)

    await _run_once(create_discovery_agent(client))

    instructions = client.options["instructions"]
    assert FORMAT_SKILL_NAME in instructions
    tool_names = {getattr(tool, "name", str(tool)) for tool in client.options["tools"]}
    assert "load_skill" in tool_names
    assert "read_skill_resource" in tool_names


async def test_discover_groups_requests_field_groups_structured_output(make_stub_client):
    """The helper drives the agent with response_format=FieldGroups."""
    client = make_stub_client(GROUPS)

    await discover_groups(create_discovery_agent(client))

    assert client.options["response_format"].__name__ == "FieldGroups"


async def test_discover_groups_returns_the_agents_groups_in_order(make_stub_client):
    """The helper returns exactly the groups the agent produced, in order."""
    client = make_stub_client(GROUPS)

    groups = await discover_groups(create_discovery_agent(client))

    assert [group.group_id for group in groups.groups] == [
        group.group_id for group in GROUPS.groups
    ]

