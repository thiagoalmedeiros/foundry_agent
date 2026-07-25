"""The elicitation agent clarifies ONE field group at a time.

Discovery hands the groups straight to elicitation (there is no gap-analysis
stage); for each group the agent drives a natural multi-turn conversation
against that group's Adequacy, then the flow jumps to the next group.
"""

import logging

from foundry_agent.agents import (
    ELICITATION_INSTRUCTIONS,
    ELICITATION_SKILL_NAME,
    FORMAT_SKILL_NAME,
    continue_group_conversation,
    create_elicitation_agent,
    open_group_conversation,
)
from foundry_agent.models import CapturedValue, ConversationTurn
from tests.conftest import GROUPS

_FG1 = GROUPS.groups[0]  # Identification & Classification (PA1, PA3)

_OPEN_TURN = ConversationTurn(
    message="Anchors what this record is and how it is classified.\n\nWhat should we call it?",
    conversation_complete=False,
    captured=[],
)

_CLOSING_TURN = ConversationTurn(
    message="That covers this group — thank you.",
    conversation_complete=True,
    captured=[
        CapturedValue(attribute_id="PA1", value="REC-001"),
        CapturedValue(attribute_id="PA3", value="Security"),
    ],
)


def _session(client):
    agent = create_elicitation_agent(client)
    return agent, agent.create_session()


async def test_open_scopes_the_prompt_to_the_current_group(make_stub_client):
    """The opening prompt covers THIS group's fields and adequacy — not other groups'."""
    client = make_stub_client(_OPEN_TURN)
    agent, session = _session(client)

    await open_group_conversation(agent, session, _FG1, "content")

    prompt = client.prompts[0]
    assert _FG1.heading in prompt
    assert "PA1" in prompt and "PA3" in prompt  # this group's attributes
    assert "PA7" not in prompt and "PA11" not in prompt  # FG2's are out of scope
    assert _FG1.adequacy in prompt


async def test_open_uses_the_framing_line_without_its_label(make_stub_client):
    """EL12 wants the framing sentence; EL10 forbids the label that precedes it."""
    client = make_stub_client(_OPEN_TURN)
    agent, session = _session(client)

    await open_group_conversation(agent, session, _FG1, "content")

    prompt = client.prompts[0]
    assert _FG1.framing_line() in prompt
    assert "**Framing:**" not in prompt


async def test_continue_feeds_the_reply_for_cumulative_capture(make_stub_client):
    client = make_stub_client(_CLOSING_TURN)
    agent, session = _session(client)

    await continue_group_conversation(
        agent, session, _FG1, [], "REC-001, and it's a Category A record."
    )

    prompt = client.prompts[-1]
    assert "The user replied" in prompt
    assert "CUMULATIVELY" in prompt
    assert "REC-001, and it's a Category A record." in prompt


async def test_the_conversation_is_multi_turn_on_one_session(make_stub_client):
    """Turn two carries turn one — the same session replays the opening."""
    client = make_stub_client(_OPEN_TURN)
    client.queue(_CLOSING_TURN)
    agent, session = _session(client)

    await open_group_conversation(agent, session, _FG1, "content")
    await continue_group_conversation(agent, session, _FG1, [], "REC-001, Security.")

    assert client.calls == 2
    replayed = client.prompts[-1]
    assert _FG1.framing_line() in replayed  # the opening turn, replayed via the session
    assert "REC-001, Security." in replayed


async def test_continue_closes_when_the_group_is_covered(make_stub_client):
    client = make_stub_client(_CLOSING_TURN)
    agent, session = _session(client)

    turn = await continue_group_conversation(agent, session, _FG1, [], "all set")

    assert turn.conversation_complete
    assert [v.attribute_id for v in turn.captured] == ["PA1", "PA3"]


async def test_the_elicitation_agent_mounts_both_skills(make_stub_client):
    """The agent needs the format skill's field reference and the behavior skill's cadence."""
    client = make_stub_client(_OPEN_TURN)
    agent, session = _session(client)

    await open_group_conversation(agent, session, _FG1, "content")

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
        await open_group_conversation(agent, session, _FG1, "content")

    assert any("did not call load_skill" in r.message for r in caplog.records)


async def test_a_turn_is_returned_as_the_structured_contract(make_stub_client):
    client = make_stub_client(_CLOSING_TURN)
    agent, session = _session(client)

    turn = await open_group_conversation(agent, session, _FG1, "content")

    assert client.options["response_format"] is ConversationTurn
    assert turn.conversation_complete
    assert [v.attribute_id for v in turn.captured] == ["PA1", "PA3"]


async def test_the_elicitation_turn_runs_at_low_reasoning_effort(make_stub_client):
    """Fast turns: the elicitation call asks the Responses API for low reasoning (DoD).

    The Responses API's structured-output path takes ``reasoning={"effort": ...}``,
    not the Chat-Completions ``reasoning_effort=`` form (the latter is rejected
    live — witnessed in the Batch 3 run).
    """
    client = make_stub_client(_OPEN_TURN)
    agent, session = _session(client)

    await open_group_conversation(agent, session, _FG1, "content")

    assert client.options["reasoning"] == {"effort": "low"}


def test_elicitation_instructions_forbid_inventing_load_bearing_facts():
    """Elicitation now owns inference, so the must-ask guardrail lives on its instructions.

    The generic discipline is in code; the specific must-ask fields stay in the
    format skill's inference guidance, mounted by the agent — never in the prompt.
    """
    text = ELICITATION_INSTRUCTIONS.lower()
    assert "never invent" in text
    assert "load-bearing fact" in text
    assert "ask for those" in text
