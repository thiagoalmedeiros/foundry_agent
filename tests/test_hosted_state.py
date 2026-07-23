"""Durable state is the host's job — these tests keep it that way.

The Foundry host detects a :class:`WorkflowAgent`, manages its checkpoints
itself (per-user partitioned), and **raises** if the workflow already carries
checkpointing of its own. That makes "add checkpoint storage to the workflow"
an attractive-looking change that would break production serving outright.

These tests are the guardrail: they fail loudly if the production workflow
ever gains its own checkpointing, and they pin the host's storage contract so
a package upgrade that moves it is noticed here rather than in a deployment.
Restart survival itself is a live property — witnessed in
the predecessor project's restart-survival record.
"""

import pytest
from agent_framework import WorkflowAgent
from agent_framework_foundry_hosting import ResponsesHostServer

from foundry_agent.agents import (
    create_authoring_agent,
    create_elicitation_agent,
    create_gap_analysis_agent,
    create_validation_agent,
)
from foundry_agent.workflow import build_policy_report_workflow
from tests.conftest import (
    CLOSING_TURN,
    COMPLETE_VALIDATION,
    GROUPS,
    OPEN_TURN,
    STUB_DOCUMENT,
    TWO_GAP_REPORT,
)


def _workflow(make_stub_client, make_elicitation_client):
    return build_policy_report_workflow(
        gap_agent=create_gap_analysis_agent(make_stub_client(TWO_GAP_REPORT)),
        elicitation_agent=create_elicitation_agent(
            make_elicitation_client(OPEN_TURN, CLOSING_TURN)
        ),
        validation_agent=create_validation_agent(make_stub_client(COMPLETE_VALIDATION)),
        authoring_agent=create_authoring_agent(make_stub_client(None, text=STUB_DOCUMENT)),
        field_groups=GROUPS,
    )


def test_the_production_workflow_carries_no_checkpointing(
    make_stub_client, make_elicitation_client
):
    """Adding checkpointing here would make the host refuse to serve the agent."""
    workflow = _workflow(make_stub_client, make_elicitation_client)

    assert not workflow._runner_context.has_checkpointing()


def test_a_self_checkpointing_workflow_is_rejected_by_the_host(tmp_path):
    """Pins WHY the guardrail exists: the host rejects self-managed checkpoints.

    Built inline rather than through ``build_policy_report_workflow`` — the
    production factory must never learn to take checkpoint storage, so the
    counter-example is constructed here instead. If a future package version
    stops raising, this test fails and the guardrail above can be
    reconsidered, rather than the constraint quietly becoming folklore.
    """
    from agent_framework import (
        Executor,
        FileCheckpointStorage,
        Message,
        WorkflowBuilder,
        WorkflowContext,
        handler,
    )

    class _Echo(Executor):
        def __init__(self) -> None:
            super().__init__(id="echo")

        @handler
        async def run(self, messages: list[Message], ctx: WorkflowContext[str, str]) -> None:
            await ctx.yield_output("ok")

    checkpointed = WorkflowBuilder(
        name="checkpointed-probe",
        start_executor=_Echo(),
        checkpoint_storage=FileCheckpointStorage(tmp_path / "checkpoints"),
    ).build()

    with pytest.raises(RuntimeError, match="checkpoint storage"):
        ResponsesHostServer(WorkflowAgent(checkpointed))


def test_the_host_owns_a_checkpoint_storage_path():
    """The platform-managed location the hosted container persists across turns."""
    assert ResponsesHostServer.CHECKPOINT_STORAGE_PATH == "/.checkpoints"
