"""The chat wrapper: uploads are decoded, and turns resume the right run.

Two failures this module exists to prevent. DevUI delivers a file as a content
item carrying a ``data:`` URI rather than text, so reading only ``Message.text``
loses the user's document silently. And the wrapper — not the workflow — is what
remembers which paused run a reply belongs to, so a mistake there sends an answer
to the wrong conversation or restarts a run mid-flight.
"""

import pytest
from agent_framework import Content, Message

import foundry_agent.chat_agent
from foundry_agent.agents import (
    create_authoring_agent,
    create_elicitation_agent,
    create_validation_agent,
)
from foundry_agent.chat_agent import ERROR_REPLY_PREFIX, WorkflowChatAgent, _extract_text
from foundry_agent.workflow import build_policy_report_workflow
from tests.conftest import (
    CLOSING_TURN,
    COMPLETE_VALIDATION,
    FOLLOW_UP_TURN,
    GROUPS,
    INPUT_FILE,
    OPEN_TURN,
    STUB_DOCUMENT,
)


@pytest.fixture(autouse=True)
def _isolated_checkpoint_root(tmp_path, monkeypatch):
    """Point chat checkpoints at a per-test temp dir.

    Without this, every test conversation writes real state under the repo's
    ``.checkpoints/chat/`` — and once restart-restoration exists, a stale
    checkpoint from a previous test run could be silently resumed, making the
    suite history-dependent.
    """
    monkeypatch.setattr(
        foundry_agent.chat_agent, "CHAT_CHECKPOINT_ROOT", tmp_path / "chat-checkpoints"
    )


class _Session:
    """Stand-in for the DevUI session object the agent reads an id from."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id


def _upload(data: bytes, media_type: str) -> Content:
    return Content.from_data(data, media_type=media_type)


def _agent(
    make_stub_client,
    make_elicitation_client,
    *,
    turns=(OPEN_TURN, FOLLOW_UP_TURN),
    validation_clients=None,
) -> WorkflowChatAgent:
    """A chat agent whose conversation follows up before it closes.

    The default turns make a resumed run distinguishable from a restarted one:
    a restart would replay the opening framing, a resume shows the follow-up.
    """

    def factory():
        validation_client = make_stub_client(COMPLETE_VALIDATION)
        if validation_clients is not None:
            validation_clients.append(validation_client)
        return build_policy_report_workflow(
            elicitation_agent=create_elicitation_agent(make_elicitation_client(*turns)),
            validation_agent=create_validation_agent(validation_client),
            authoring_agent=create_authoring_agent(make_stub_client(None, text=STUB_DOCUMENT)),
            field_groups=GROUPS,
        )

    return WorkflowChatAgent(factory, name="test-agent", description="test")


async def _say(agent: WorkflowChatAgent, text: object, session: str = "s1") -> str:
    """One chat turn, through the same entry point DevUI calls."""
    response = await agent.run(text, session=_Session(session))
    return response.messages[-1].text


async def test_a_reply_resumes_the_paused_run_rather_than_restarting_it(
    make_stub_client, make_elicitation_client
):
    agent = _agent(make_stub_client, make_elicitation_client)

    # The opening framing, then the agent's follow-up in the SAME conversation —
    # a restarted run would replay the framing instead.
    assert "Anchors what this policy is" in await _say(agent, "hi")
    assert "Is this mainly about protecting assets" in await _say(
        agent, "Remote Work Security Policy"
    )


async def test_separate_conversations_do_not_share_state(make_stub_client, make_elicitation_client):
    agent = _agent(make_stub_client, make_elicitation_client)

    await _say(agent, "hi", session="alice")
    assert "Is this mainly about protecting assets" in await _say(
        agent, "Remote Work Security Policy", session="alice"
    )

    # Bob's first message opens his own group 1, not alice's follow-up.
    assert "Anchors what this policy is" in await _say(agent, "hi", session="bob")


async def test_a_finished_run_returns_the_document_and_frees_the_conversation(
    make_stub_client, make_elicitation_client
):
    agent = _agent(
        make_stub_client,
        make_elicitation_client,
        # One open/close pair — the whole document is one conversation now.
        turns=(OPEN_TURN, CLOSING_TURN),
    )

    assert "Anchors what this policy is" in await _say(agent, "a full brief")
    assert "# Policy Report" in await _say(agent, "confirmed")

    # The conversation was released, so the next message starts fresh.
    assert "Anchors what this policy is" in await _say(agent, "another brief")


async def test_a_failing_workflow_is_reported_and_reset_not_left_broken():
    def exploding_factory():
        raise RuntimeError("boom")

    agent = WorkflowChatAgent(exploding_factory, name="test-agent", description="test")

    reply = await _say(agent, "hi")

    # Visible assistant text, never an empty bubble — and the dead conversation
    # is dropped so the next message can start over instead of resuming it.
    assert reply.startswith(ERROR_REPLY_PREFIX)
    assert "boom" in reply


async def test_an_uploaded_file_reaches_the_workflow_through_a_chat_turn(
    make_stub_client, make_elicitation_client
):
    """End to end: the decode path and the turn path together."""
    validation_clients: list = []
    agent = _agent(
        make_stub_client,
        make_elicitation_client,
        turns=(OPEN_TURN, CLOSING_TURN),
        validation_clients=validation_clients,
    )
    assert "Anchors what this policy is" in await _say(agent, "hi")

    await _say(
        agent,
        Message(role="user", contents=[_upload(INPUT_FILE.read_bytes(), "text/markdown")]),
    )

    # The upload was decoded and folded into the content, so validation (the
    # next stage to read run.content fresh) sees the spec, not just the reply.
    assert "Meridian Remote Work Security Assessment" in validation_clients[0].prompts[-1]


def test_uploaded_markdown_is_inlined_whole():
    spec = INPUT_FILE.read_bytes()
    message = Message(
        role="user",
        contents=[Content.from_text("here is the spec"), _upload(spec, "text/markdown")],
    )

    extracted = _extract_text(message)

    assert "here is the spec" in extracted
    # Beginning, middle and end all survive — not a truncated preview.
    assert "Meridian Remote Work Security Assessment" in extracted
    assert "ticket RW-1408" in extracted
    assert "Compliance must account for this" in extracted


def test_uploaded_document_is_long_enough_to_trigger_re_analysis():
    """The upload must read as source material, not as an answer to a question."""
    from foundry_agent.workflow import _is_source_material

    message = Message(role="user", contents=[_upload(INPUT_FILE.read_bytes(), "text/markdown")])

    assert _is_source_material(_extract_text(message))


def test_binary_upload_is_named_rather_than_silently_dropped():
    message = Message(role="user", contents=[_upload(b"%PDF-1.4 binary", "application/pdf")])

    extracted = _extract_text(message)

    assert "application/pdf" in extracted
    assert "could not be read" in extracted


def test_plain_text_message_is_unchanged():
    assert _extract_text(Message(role="user", contents=["just typing"])) == "just typing"
