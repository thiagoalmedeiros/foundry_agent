"""The elicitation agent runs ONE whole-document conversation, agent-paced.

The workflow hands over every open field across every discovered group at
once and the agent — guided by the elicitation skill's cadence (EL4) —
decides how many related fields to raise per turn.
"""

import logging

from foundry_agent.agents import (
    ELICITATION_SKILL_NAME,
    FORMAT_SKILL_NAME,
    continue_elicitation_conversation,
    create_elicitation_agent,
    open_elicitation_conversation,
    reopen_elicitation_conversation,
)
from foundry_agent.models import (
    AttributeStatus,
    CapturedValue,
    ConversationTurn,
    GapReport,
    ValidationResult,
)
from tests.conftest import GROUPS

_GLOBAL_REPORT = GapReport(
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
            attribute_id="PA3",
            name="Policy Type",
            required=True,
            populated=False,
            gap="No policy type present.",
        ),
        AttributeStatus(
            attribute_id="PA7",
            name="Purpose Statement",
            required=True,
            populated=True,
            inferred_value="This policy establishes mandatory VPN rules.",
            evidence="remote logins are permitted from unmanaged personal devices",
        ),
        AttributeStatus(
            attribute_id="PA11",
            name="Context Narrative",
            required=True,
            populated=False,
            gap="No narrative present.",
        ),
    ],
)

_OPEN_TURN = ConversationTurn(
    message="Let's start with your Policy ID and Policy Type.",
    conversation_complete=False,
    captured=[],
)

_CLOSING_TURN = ConversationTurn(
    message="That covers everything — thank you.",
    conversation_complete=True,
    captured=[
        CapturedValue(attribute_id="PA1", value="POL-SEC-001"),
        CapturedValue(attribute_id="PA3", value="Security"),
        CapturedValue(attribute_id="PA7", value="Purpose statement text"),
        CapturedValue(attribute_id="PA11", value="Narrative text"),
    ],
)


def _session(client):
    agent = create_elicitation_agent(client)
    return agent, agent.create_session()


async def test_the_conversation_is_multi_turn_on_one_session(make_stub_client):
    """Turn two must carry turn one — that is what stops the agent re-asking."""
    client = make_stub_client(_OPEN_TURN)
    client.queue(_CLOSING_TURN)
    agent, session = _session(client)

    await open_elicitation_conversation(agent, session, GROUPS.groups, _GLOBAL_REPORT, "content")
    await continue_elicitation_conversation(
        agent, session, _GLOBAL_REPORT, [], "POL-SEC-001, and it's a Security policy."
    )

    assert client.calls == 2
    replayed = client.prompts[-1]
    assert "Anchors what this policy is and how it is classified." in replayed
    assert "POL-SEC-001, and it's a Security policy." in replayed


async def test_open_lists_every_open_field_across_every_group(make_stub_client):
    """The opening prompt spans the whole document, not one group."""
    client = make_stub_client(_OPEN_TURN)
    agent, session = _session(client)

    await open_elicitation_conversation(agent, session, GROUPS.groups, _GLOBAL_REPORT, "content")

    prompt = client.prompts[0]
    assert "PA1" in prompt
    assert "PA3" in prompt
    assert "PA7" in prompt
    assert "PA11" in prompt
    assert "never all of them at once" in prompt


async def test_the_framing_line_opens_the_conversation_without_its_document_label(
    make_stub_client,
):
    """EL12 wants the sentence; EL10 forbids the label that precedes it in the file."""
    client = make_stub_client(_OPEN_TURN)
    agent, session = _session(client)

    await open_elicitation_conversation(agent, session, GROUPS.groups, _GLOBAL_REPORT, "content")

    prompt = client.prompts[0]
    assert "Anchors what this policy is and how it is classified." in prompt
    assert "**Framing:**" not in prompt


async def test_open_returns_an_empty_turn_when_nothing_is_open(make_stub_client):
    """A fully-populated document skips the model call entirely."""
    client = make_stub_client(_OPEN_TURN)
    agent, session = _session(client)
    complete_report = GapReport(
        classification="Security",
        attributes=[
            AttributeStatus(
                attribute_id="PA1", name="Policy ID", required=True, populated=True, evidence="x"
            )
        ],
    )

    turn = await open_elicitation_conversation(
        agent, session, GROUPS.groups, complete_report, "content"
    )

    assert turn.message == ""
    assert turn.conversation_complete
    assert client.calls == 0


async def test_continue_narrows_the_open_list_to_what_is_not_yet_captured(make_stub_client):
    """Already-captured fields must not be re-listed as open."""
    client = make_stub_client(_CLOSING_TURN)
    agent, session = _session(client)
    prior_captured = [
        CapturedValue(attribute_id="PA1", value="POL-SEC-001"),
        CapturedValue(attribute_id="PA3", value="Security"),
    ]

    await continue_elicitation_conversation(
        agent, session, _GLOBAL_REPORT, prior_captured, "POL-SEC-001, and it's Security."
    )

    prompt = client.prompts[-1]
    # "PA1" alone is unsafe to assert absent — "PA11" (still open) contains it
    # as a substring, so check the exact rendered "id name" pair instead.
    assert "PA1 Policy ID" not in prompt
    assert "PA3 Policy Type" not in prompt
    assert "PA7 Purpose Statement" in prompt
    assert "PA11 Context Narrative" in prompt


async def test_continue_closes_the_conversation_when_nothing_remains(make_stub_client):
    client = make_stub_client(_CLOSING_TURN)
    agent, session = _session(client)
    prior_captured = [
        CapturedValue(attribute_id=aid, value="x") for aid in ("PA1", "PA3", "PA7", "PA11")
    ]

    await continue_elicitation_conversation(
        agent, session, _GLOBAL_REPORT, prior_captured, "all done"
    )

    assert "conversation_complete=true" in client.prompts[-1]


async def test_a_reply_is_read_for_every_value_it_carries(make_stub_client):
    client = make_stub_client(_CLOSING_TURN)
    agent, session = _session(client)

    await continue_elicitation_conversation(
        agent, session, _GLOBAL_REPORT, [], "PA1 is X, Version 0.1, and the type is Security."
    )

    prompt = client.prompts[-1]
    assert "EVERY value it carries" in prompt
    assert "CUMULATIVELY" in prompt


async def test_reopen_names_validations_missing_ids(make_stub_client):
    client = make_stub_client(_OPEN_TURN)
    agent, session = _session(client)
    result = ValidationResult(
        complete=False,
        missing_attribute_ids=["PA3"],
        rationale="Policy type is still not one of Governance/Operational/Security/Compliance.",
    )

    await reopen_elicitation_conversation(agent, session, _GLOBAL_REPORT, result)

    prompt = client.prompts[-1]
    assert "PA3" in prompt
    assert "Policy type is still not one of" in prompt
    assert "never all of them at once" in prompt


async def test_reopen_falls_back_for_an_id_analysis_never_reported(make_stub_client):
    """A mismatch between validation and analysis is surfaced, not silently dropped."""
    client = make_stub_client(_OPEN_TURN)
    agent, session = _session(client)
    result = ValidationResult(
        complete=False, missing_attribute_ids=["PA99"], rationale="unexpected"
    )

    await reopen_elicitation_conversation(agent, session, _GLOBAL_REPORT, result)

    assert "PA99" in client.prompts[-1]


async def test_reopen_returns_an_empty_turn_when_validation_names_nothing(make_stub_client):
    client = make_stub_client(_OPEN_TURN)
    agent, session = _session(client)
    result = ValidationResult(complete=True, missing_attribute_ids=[], rationale="all good")

    turn = await reopen_elicitation_conversation(agent, session, _GLOBAL_REPORT, result)

    assert turn.conversation_complete
    assert client.calls == 0


async def test_the_elicitation_agent_mounts_both_skills(make_stub_client):
    """The agent needs the format skill's field reference and the behavior skill's cadence."""
    client = make_stub_client(_OPEN_TURN)
    agent, session = _session(client)

    await open_elicitation_conversation(agent, session, GROUPS.groups, _GLOBAL_REPORT, "content")

    instructions = client.options["instructions"]
    assert FORMAT_SKILL_NAME in instructions
    assert ELICITATION_SKILL_NAME in instructions
    tool_names = {getattr(tool, "name", str(tool)) for tool in client.options["tools"]}
    assert "load_skill" in tool_names
    assert "read_skill_resource" in tool_names


async def test_skipping_the_skill_load_emits_a_warning(make_stub_client, caplog):
    client = make_stub_client(_OPEN_TURN)
    agent, session = _session(client)

    with caplog.at_level(logging.WARNING, logger="foundry_agent.agents"):
        await open_elicitation_conversation(
            agent, session, GROUPS.groups, _GLOBAL_REPORT, "content"
        )

    assert any("did not call load_skill" in r.message for r in caplog.records)


async def test_a_turn_is_returned_as_the_structured_contract(make_stub_client):
    client = make_stub_client(_CLOSING_TURN)
    agent, session = _session(client)

    turn = await open_elicitation_conversation(
        agent, session, GROUPS.groups, _GLOBAL_REPORT, "content"
    )

    assert client.options["response_format"] is ConversationTurn
    assert turn.conversation_complete
    assert [value.attribute_id for value in turn.captured] == ["PA1", "PA3", "PA7", "PA11"]
