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
import os
import socket
from urllib.parse import urlparse

from agent_framework.devui import serve
from dotenv import load_dotenv

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


def _prepare_instrumentation() -> bool:
    """Enable OTel only when the configured OTLP collector is actually listening.

    Env-selected like every other environment concern here: point
    ``OTEL_EXPORTER_OTLP_ENDPOINT`` at a collector (``task sim:up``'s on
    :4318, the AI Toolkit's, or the Foundry Toolkit visualizer's) and DevUI
    traces flow there. But two facts force a probe-and-unset rather than a
    plain read, because ``.env`` keeps the endpoint set permanently:

    - ``agent_framework``'s ``enable_instrumentation`` defaults to **True**,
      and DevUI's executor calls ``configure_otel_providers()`` on that alone.
    - ``configure_otel_providers()`` builds trace/metric/log exporters
      whenever ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set — the ``serve()``
      ``instrumentation_enabled`` flag does not gate it.

    So a configured-but-absent collector would spam connection-refused
    retries across all three exporters (the metric reader fires on its own
    interval, with or without a turn). Unsetting the endpoint here is the one
    lever that reliably stops those exporters from being created. Returns the
    flag to pass to ``serve(instrumentation_enabled=...)``.
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False
    parsed = urlparse(endpoint)
    try:
        with socket.create_connection(
            (parsed.hostname or "localhost", parsed.port or 4318), timeout=0.5
        ):
            return True
    except OSError:
        # Drop the endpoint so DevUI's own configure_otel_providers() builds no
        # exporters either — a False serve flag alone would not stop it.
        os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        os.environ.pop("OTEL_EXPORTER_OTLP_PROTOCOL", None)
        logging.getLogger(__name__).info(
            "OTEL_EXPORTER_OTLP_ENDPOINT was set (%s) but nothing is listening there — "
            "instrumentation stays OFF for this run. Start `task sim:up` (Aspire) or "
            "`task otel:up` first to collect traces.",
            endpoint,
        )
        return False


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
    # Own .env loading explicitly (mirrors hosting.main): the instrumentation
    # gate below reads the environment BEFORE the first conversation would
    # otherwise trigger create_chat_client()'s lazy load_dotenv().
    load_dotenv()
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
        instrumentation_enabled=_prepare_instrumentation(),
    )


if __name__ == "__main__":
    main()
