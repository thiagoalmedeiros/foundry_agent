"""Batch 1 spike: prove the human-in-the-loop pause/resume contract in DevUI.

A minimal workflow with no LLM dependency: the start executor receives free
text, pauses the run with ``ctx.request_info`` to ask the human one question,
and finishes in its ``@response_handler`` once the answer arrives — from DevUI
or from a test driving ``workflow.run(responses=...)``.

Run ``task devui`` (or ``python -m foundry_agent.spike_hitl``) and open
the printed URL; the workflow must pause on the question and resume with the
typed answer for the spike to pass.
"""

from dataclasses import dataclass

from agent_framework import (
    Executor,
    WorkflowBuilder,
    WorkflowContext,
    handler,
    response_handler,
)

DEVUI_PORT = 8090


@dataclass
class SpikeQuestion:
    """Question shown to the human while the workflow is paused."""

    prompt: str


class AskHumanExecutor(Executor):
    """Pauses the workflow to ask one question, then echoes input and answer."""

    def __init__(self) -> None:
        super().__init__(id="ask_human")
        self._received: str | None = None

    @handler
    async def start(self, message: str, ctx: WorkflowContext[str, str]) -> None:
        """Store the initial input and pause for the human's answer."""
        self._received = message
        await ctx.request_info(
            request_data=SpikeQuestion(prompt=f"You said {message!r}. What should I add?"),
            response_type=str,
        )

    @response_handler
    async def resume(
        self,
        original_request: SpikeQuestion,
        response: str,
        ctx: WorkflowContext[str, str],
    ) -> None:
        """Complete the run by combining the paused input with the answer."""
        await ctx.yield_output(f"input={self._received!r} answer={response!r}")


def build_spike_workflow():
    """Build the single-executor HITL spike workflow."""
    return WorkflowBuilder(
        name="policy-report-agent-hitl-spike",
        description="Spike: pause for one human answer, then echo input + answer.",
        start_executor=AskHumanExecutor(),
    ).build()


workflow = build_spike_workflow()


def main() -> None:
    """Serve the spike workflow in DevUI."""
    from agent_framework.devui import serve

    serve(entities=[workflow], port=DEVUI_PORT, auto_open=True, auth_enabled=False)


if __name__ == "__main__":
    main()
