"""Chat conversations survive a process restart via the default file checkpoints.

The wrapper checkpoints every turn; these tests pin the read-back half: a NEW
agent instance — what a restarted process builds — resumes a paused
conversation from its latest checkpoint instead of restarting the interview,
and conversations never leak into each other's state. Default file storage
only, on purpose: that is the mechanism the Foundry platform preserves
(plans/local-deploy-sim — deploy parity means no parallel storage backend).

The resume proof is behavioral, not textual: a resumed run must NOT re-run
gap analysis (its report is restored state), and its elicitation call must be
a continuation prompt, not the opening one.
"""

from foundry_agent.agents import (
    create_authoring_agent,
    create_elicitation_agent,
    create_validation_agent,
)
from foundry_agent.chat_agent import ERROR_REPLY_PREFIX, WorkflowChatAgent
from foundry_agent.workflow import build_policy_report_workflow
from tests.conftest import (
    CLOSING_TURN,
    COMPLETE_VALIDATION,
    FOLLOW_UP_TURN,
    GROUPS,
    OPEN_TURN,
    STUB_DOCUMENT,
)


class _Session:
    """Stand-in for the DevUI session object the agent reads an id from."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id


def _make_agent(
    make_stub_client,
    make_elicitation_client,
    checkpoint_root,
    *,
    turns=(OPEN_TURN, FOLLOW_UP_TURN),
):
    """A chat agent over a shared checkpoint root, exposing each conversation's clients.

    ``clients`` collects one ``{"elicitation": ...}`` dict per
    factory call (one call per conversation), so a test can assert which
    stages actually ran — the discriminator between a resume and a restart.
    """
    clients: list[dict] = []

    def factory():
        elicitation_client = make_elicitation_client(*turns)
        clients.append({"elicitation": elicitation_client})
        return build_policy_report_workflow(
            elicitation_agent=create_elicitation_agent(elicitation_client),
            validation_agent=create_validation_agent(make_stub_client(COMPLETE_VALIDATION)),
            authoring_agent=create_authoring_agent(make_stub_client(None, text=STUB_DOCUMENT)),
            field_groups=GROUPS,
        )

    agent = WorkflowChatAgent(
        factory, name="test-agent", description="test", checkpoint_root=checkpoint_root
    )
    return agent, clients


async def _say(agent: WorkflowChatAgent, text: str, session: str = "s1") -> str:
    response = await agent.run(text, session=_Session(session))
    return response.messages[-1].text


async def test_resumes_after_restart(make_stub_client, make_elicitation_client, tmp_path):
    """A rebuilt agent over the same checkpoint root continues the paused run."""
    root = tmp_path / "chat-checkpoints"
    first, _ = _make_agent(make_stub_client, make_elicitation_client, root)
    assert "Anchors what this policy is" in await _say(first, "hi")

    # The restart: a brand-new agent instance, empty conversation cache, same root.
    second, clients = _make_agent(
        make_stub_client, make_elicitation_client, root, turns=(CLOSING_TURN,)
    )
    reply = await _say(second, "Remote Work Security Policy, type Security")

    assert reply == STUB_DOCUMENT, "the resumed run should close and produce the document"
    assert "The user replied" in clients[0]["elicitation"].prompts[0], (
        "the resumed turn must be a continuation prompt, not a fresh group opening"
    )


async def test_conversations_are_isolated(make_stub_client, make_elicitation_client, tmp_path):
    """Two conversations checkpoint separately and each resumes only its own state."""
    root = tmp_path / "chat-checkpoints"
    first, _ = _make_agent(make_stub_client, make_elicitation_client, root)
    await _say(first, "hi", session="alice")
    await _say(first, "hi", session="bob")
    assert (root / "alice").is_dir() and (root / "bob").is_dir()

    second, clients = _make_agent(
        make_stub_client, make_elicitation_client, root, turns=(CLOSING_TURN,)
    )
    assert await _say(second, "everything you need", session="alice") == STUB_DOCUMENT
    assert await _say(second, "everything you need", session="bob") == STUB_DOCUMENT
    assert len(clients) == 2, "each conversation restores through its own workflow"
    assert all("The user replied" in entry["elicitation"].prompts[0] for entry in clients), (
        "each conversation must resume as a continuation, not a fresh opening"
    )


async def test_error_clears_checkpoint(make_stub_client, make_elicitation_client, tmp_path):
    """A broken run's checkpoint cannot be resurrected — the error path clears it.

    Without the clear, the next message (or a restart) would restore the same
    broken state and loop on the error forever.
    """
    root = tmp_path / "chat-checkpoints"

    def factory():
        elicitation_client = make_stub_client(OPEN_TURN)
        elicitation_client.queue({"not": "a ConversationTurn"})  # second turn blows up parsing
        return build_policy_report_workflow(
            elicitation_agent=create_elicitation_agent(elicitation_client),
            validation_agent=create_validation_agent(make_stub_client(COMPLETE_VALIDATION)),
            authoring_agent=create_authoring_agent(make_stub_client(None, text=STUB_DOCUMENT)),
            field_groups=GROUPS,
        )

    broken = WorkflowChatAgent(
        factory, name="test-agent", description="test", checkpoint_root=root
    )
    assert "Anchors what this policy is" in await _say(broken, "hi")
    assert (await _say(broken, "boom")).startswith(ERROR_REPLY_PREFIX)

    checkpoint_files = list((root / "s1").rglob("*")) if (root / "s1").exists() else []
    assert not [p for p in checkpoint_files if p.is_file()], (
        "the broken run's checkpoints must be cleared on the error path"
    )

    # And the next process starts FRESH — the opening framing, not a resume.
    fresh, clients = _make_agent(make_stub_client, make_elicitation_client, root)
    assert "Anchors what this policy is" in await _say(fresh, "hi")
    assert "Field group to clarify now" in clients[0]["elicitation"].prompts[0], (
        "a fresh start opens the first group, not a resume"
    )
