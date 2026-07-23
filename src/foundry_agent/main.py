"""DevUI entrypoint serving the Policy Report workflow as a chat agent.

Run ``task devui`` (or ``python -m foundry_agent.main``). Requires the
AZURE_OPENAI_* variables — resolved by ``load_dotenv`` from this package's
``.env`` or any parent directory's (the repo root works).

The workflow is served through :class:`WorkflowChatAgent`, so DevUI hosts it
as a chat: elicitation arrives as ordinary assistant text and the user answers
— or uploads a document — in the next message. The wrapper keeps the workflow
live in-process and resumes it itself rather than relying on DevUI's
checkpoint-based ``workflow_hil_response`` path.
"""

import argparse
import logging

from agent_framework.devui import serve

from foundry_agent.chat_agent import WorkflowChatAgent
from foundry_agent.workflow import create_policy_report_workflow

DEVUI_PORT = 8090

AGENT_NAME = "policy-report-agent"
AGENT_DESCRIPTION = (
    "Policy Report flow: discovery, one gap-analysis pass, an agent-paced "
    "elicitation conversation confirming what was inferred and asking the rest, "
    "validation, then the assembled Policy Report document."
)


def create_policy_report_agent() -> WorkflowChatAgent:
    """Wrap the workflow as the chat agent DevUI hosts."""
    return WorkflowChatAgent(
        create_policy_report_workflow, name=AGENT_NAME, description=AGENT_DESCRIPTION
    )


def main() -> None:
    """Serve the Policy Report workflow in DevUI."""
    # Uvicorn only configures its own loggers; without this the package's INFO
    # records — including the per-stage token usage lines the cost work relies
    # on — are silently dropped in the served process.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # DevUI logs every raw request body at INFO — with INFO now enabled, that
    # would write users' pasted documents verbatim into the server log.
    logging.getLogger("agent_framework_devui._server").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        type=int,
        default=DEVUI_PORT,
        help=f"Port for the DevUI server (default {DEVUI_PORT}).",
    )
    args = parser.parse_args()
    # auth_enabled=False: DevUI's default dev-token auth 401s the auto-opened
    # browser (it never receives the token); the server binds to 127.0.0.1 only.
    serve(
        entities=[create_policy_report_agent()],
        port=args.port,
        auto_open=True,
        auth_enabled=False,
    )


if __name__ == "__main__":
    main()
