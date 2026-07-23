"""The hosted serving path: MAF's WorkflowAgent + ResponsesHostServer.

The spike these tests pin (the predecessor project's production-readiness spike)
is that the Policy Report workflow can be served by MAF's own hosting package
without a bespoke chat wrapper — and, crucially, that a human-in-the-loop
elicitation pause survives the translation, because the whole interview
depends on it.

The host contract has two hard requirements, both asserted here: the agent
must be a :class:`WorkflowAgent` (the host special-cases it for checkpoint
restoration), and the workflow must NOT carry its own checkpointing (the host
manages checkpoints and raises if they are already configured).
"""

from agent_framework import WorkflowAgent
from agent_framework_foundry_hosting import ResponsesHostServer

from foundry_agent.agents import (
    create_authoring_agent,
    create_elicitation_agent,
    create_gap_analysis_agent,
    create_validation_agent,
)
from foundry_agent.chat_agent import WorkflowChatAgent
from foundry_agent.hosting import AGENT_NAME, create_hosted_agent, create_hosted_chat_agent
from foundry_agent.workflow import build_policy_report_workflow
from tests.conftest import (
    CLOSING_TURN,
    COMPLETE_VALIDATION,
    GROUPS,
    OPEN_TURN,
    STUB_DOCUMENT,
    TWO_GAP_REPORT,
)

_FAKE_ENV = {
    "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-test",
    "AZURE_OPENAI_API_KEY": "test-key",
}


def _stub_workflow(make_stub_client, make_elicitation_client):
    """The real workflow graph over stubbed chat clients."""
    return build_policy_report_workflow(
        gap_agent=create_gap_analysis_agent(make_stub_client(TWO_GAP_REPORT)),
        elicitation_agent=create_elicitation_agent(
            make_elicitation_client(OPEN_TURN, CLOSING_TURN)
        ),
        validation_agent=create_validation_agent(make_stub_client(COMPLETE_VALIDATION)),
        authoring_agent=create_authoring_agent(make_stub_client(None, text=STUB_DOCUMENT)),
        field_groups=GROUPS,
    )


def test_create_hosted_agent_returns_a_workflow_agent(monkeypatch):
    """The host special-cases WorkflowAgent — a bespoke wrapper would bypass it."""
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)

    agent = create_hosted_agent()

    assert isinstance(agent, WorkflowAgent)
    assert agent.name == AGENT_NAME


def test_create_hosted_chat_agent_wraps_the_factory_lazily():
    """Chat mode (playgrounds render text only) must not build a workflow eagerly —
    construction happens per conversation, so no AZURE_OPENAI_* env is needed here."""
    agent = create_hosted_chat_agent()

    assert isinstance(agent, WorkflowChatAgent)
    assert agent.name == AGENT_NAME


def test_the_host_accepts_the_chat_agent():
    """Chat mode rides the same host: construction must not raise for a plain agent."""
    server = ResponsesHostServer(create_hosted_chat_agent())

    assert any("/responses" in getattr(route, "path", "") for route in server.routes)


def test_the_workflow_carries_no_checkpointing_of_its_own(
    make_stub_client, make_elicitation_client
):
    """The hosting infrastructure owns checkpoints and rejects a workflow that has its own."""
    workflow = _stub_workflow(make_stub_client, make_elicitation_client)

    assert not workflow._runner_context.has_checkpointing()


def test_the_host_accepts_the_workflow_agent(make_stub_client, make_elicitation_client):
    """Construction is where the host enforces its contract — it must not raise."""
    agent = WorkflowAgent(_stub_workflow(make_stub_client, make_elicitation_client))

    server = ResponsesHostServer(agent)

    assert any("/responses" in getattr(route, "path", "") for route in server.routes)


async def test_an_elicitation_pause_becomes_a_request_info_function_call(
    make_stub_client, make_elicitation_client
):
    """The interview's HITL pause must survive translation to the agent protocol.

    Every field group pauses for the user; if the pause did not surface as a
    ``request_info`` function call the client could never answer, and the
    hosted interview would stall on its first question.
    """
    agent = WorkflowAgent(_stub_workflow(make_stub_client, make_elicitation_client))

    response = await agent.run("We keep losing fleet telemetry overnight.")

    calls = [
        content
        for message in response.messages
        for content in (message.contents or [])
        if getattr(content, "name", None) == WorkflowAgent.REQUEST_INFO_FUNCTION_NAME
    ]
    assert calls, "the elicitation pause did not surface as a request_info function call"
    assert "Anchors what this policy is" in str(calls[0].arguments)
