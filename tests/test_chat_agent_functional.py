"""Flow 2 served as a chat: pauses read as assistant text, not an approval panel.

These drive :class:`FunctionalWorkflowChatAgent` over stub clients — no live
model calls, no checkpoint storage — to prove the DevUI experience: a
``request_info`` pause comes back as plain assistant text, the next message
resumes the run, and separate conversations stay isolated.
"""

from types import SimpleNamespace

from foundry_agent.agents import create_authoring_agent, create_elicitation_agent
from foundry_agent.chat_agent_functional import FunctionalWorkflowChatAgent
from foundry_agent.models import CapturedValue, ConversationTurn
from foundry_agent.workflow_functional import build_hybrid_workflow
from tests.conftest import GROUPS, STUB_DOCUMENT

_FG1_OPEN = ConversationTurn(
    message="Let's start with the basics — what's the report number?",
    conversation_complete=False,
)
_FG1_CLOSE = ConversationTurn(
    message="Got the identity — thanks.",
    conversation_complete=True,
    captured=[
        CapturedValue(attribute_id="PA1", value="IR-2026-00042"),
        CapturedValue(attribute_id="PA3", value="Draft"),
    ],
)
_FG2_CLOSE = ConversationTurn(
    message="That covers purpose and context.",
    conversation_complete=True,
    captured=[
        CapturedValue(attribute_id="PA7", value="Purpose text"),
        CapturedValue(attribute_id="PA11", value="Context text"),
    ],
)


def _chat_agent(make_stub_client, make_elicitation_client, *, turns):
    """A Flow 2 chat agent whose factory builds FRESH stubs per conversation."""

    def factory():
        return build_hybrid_workflow(
            elicitation_agent=create_elicitation_agent(make_elicitation_client(*turns)),
            authoring_agent=create_authoring_agent(make_stub_client(None, text=STUB_DOCUMENT)),
            field_groups=GROUPS,
        )

    return FunctionalWorkflowChatAgent(
        factory, name="report-interview-functional", description="flow2"
    )


async def test_a_pause_is_returned_as_assistant_text(
    make_stub_client, make_elicitation_client
):
    """The first turn returns the elicitation question as text — no approval panel."""
    agent = _chat_agent(
        make_stub_client, make_elicitation_client, turns=(_FG1_OPEN, _FG1_CLOSE, _FG2_CLOSE)
    )
    session = SimpleNamespace(session_id="c1")

    response = await agent.run("hi", session=session)

    assert "report number" in response.text  # the FG1 pause prompt, as plain text
    assert "# Report" not in response.text  # the interview is not finished yet
    assert agent._conversations["c1"].pending_request_id  # a pause is recorded to resume


async def test_the_next_message_resumes_to_the_document(
    make_stub_client, make_elicitation_client
):
    """Answering the pause resumes the same instance and yields the assembled document."""
    agent = _chat_agent(
        make_stub_client, make_elicitation_client, turns=(_FG1_OPEN, _FG1_CLOSE, _FG2_CLOSE)
    )
    session = SimpleNamespace(session_id="c1")

    await agent.run("hi", session=session)  # pauses at FG1
    response = await agent.run("IR-2026-00042", session=session)  # answers → completes

    assert response.text.startswith("# Report")
    assert "c1" not in agent._conversations  # a finished conversation is dropped


async def test_conversations_are_isolated(make_stub_client, make_elicitation_client):
    """Two sessions drive independent workflow instances — one does not disturb the other."""
    agent = _chat_agent(
        make_stub_client, make_elicitation_client, turns=(_FG1_OPEN, _FG1_CLOSE, _FG2_CLOSE)
    )
    a = SimpleNamespace(session_id="a")
    b = SimpleNamespace(session_id="b")

    reply_a = await agent.run("hi", session=a)
    reply_b = await agent.run("hi", session=b)

    assert "report number" in reply_a.text
    assert "report number" in reply_b.text
    assert agent._conversations["a"].workflow is not agent._conversations["b"].workflow


async def test_stream_path_yields_assistant_text(make_stub_client, make_elicitation_client):
    """DevUI calls run(stream=True); the stream yields the pause prompt as text."""
    agent = _chat_agent(
        make_stub_client, make_elicitation_client, turns=(_FG1_OPEN, _FG1_CLOSE, _FG2_CLOSE)
    )
    session = SimpleNamespace(session_id="c1")

    stream = agent.run("hi", session=session, stream=True)
    collected = ""
    async for update in stream:
        for content in update.contents or []:
            collected += getattr(content, "text", "") or ""

    assert "report number" in collected
