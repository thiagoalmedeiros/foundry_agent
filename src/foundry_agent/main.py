"""DevUI entrypoint serving the document-authoring workflow as a chat agent.

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
from foundry_agent.chat_agent_functional import FunctionalWorkflowChatAgent
from foundry_agent.workflow import DiscoveryCache, create_report_workflow
from foundry_agent.workflow_functional import create_hybrid_workflow

DEVUI_PORT = 8090

AGENT_NAME = "report-interview-agent"
AGENT_DESCRIPTION = (
    "Document-authoring flow: discovery, one gap-analysis pass, an agent-paced "
    "elicitation conversation confirming what was inferred and asking the rest, "
    "validation, then the assembled document."
)

HYBRID_AGENT_NAME = "report-interview-functional"
HYBRID_AGENT_DESCRIPTION = (
    "Flow 2 (functional API): the same discovery → elicitation → assembler flow, "
    "but the validation stage is a deterministic skill-script gate that re-elicits "
    "only the groups with missing fields until the script passes or a cycle cap is hit."
)


def create_report_agent() -> WorkflowChatAgent:
    """Wrap the workflow as the chat agent DevUI hosts.

    DevUI builds a fresh workflow per conversation (via the factory), so one
    shared :class:`DiscoveryCache` is bound here — above the factory — to keep
    the discovery memo spanning conversations instead of resetting each time.
    """
    cache = DiscoveryCache()
    return WorkflowChatAgent(
        lambda: create_report_workflow(discovery_cache=cache),
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
    )


def create_hybrid_agent() -> FunctionalWorkflowChatAgent:
    """Wrap Flow 2 (the functional hybrid workflow) as the chat agent DevUI hosts.

    Uses :class:`FunctionalWorkflowChatAgent` rather than the raw
    ``FunctionalWorkflow.as_agent()`` so each elicitation pause reads as ordinary
    assistant text — a normal DevUI chat — instead of a per-turn "Approval
    Required" panel (which is how DevUI renders a bare functional workflow's
    ``request_info``). A shared :class:`DiscoveryCache` is bound above the
    factory, which the wrapper calls once per conversation, so the discovery memo
    spans conversations. In-memory only: a process restart drops in-flight Flow 2
    conversations (hosted/checkpoint parity is a separate follow-up).
    """
    cache = DiscoveryCache()
    return FunctionalWorkflowChatAgent(
        lambda: create_hybrid_workflow(discovery_cache=cache),
        name=HYBRID_AGENT_NAME,
        description=HYBRID_AGENT_DESCRIPTION,
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
    """Serve the document-authoring workflow in DevUI.

    Default: the workflow is served as a chat agent (each elicitation pause reads
    as assistant text). Pass ``--workflow`` to serve the RAW :class:`Workflow`
    instead — DevUI detects it as a workflow (it has ``executors``) and renders
    its stage-graph plus a typed human-in-the-loop panel, which is the view for
    watching how the internal graph executes one executor at a time (discovery →
    analysis → elicitation → validation → assembler). Pass ``--functional`` to
    serve Flow 2 — the functional-API hybrid workflow with a deterministic script
    gate — as an agent instead. All paths need the AZURE_OPENAI_* variables.
    """
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
    parser.add_argument(
        "--workflow",
        action="store_true",
        help="Serve the raw Workflow (DevUI stage-graph + typed HITL panel) instead "
        "of the chat agent, to inspect how the internal graph executes.",
    )
    parser.add_argument(
        "--functional",
        action="store_true",
        help="Serve Flow 2, the functional-API hybrid workflow (deterministic "
        "script gate), as an agent instead of the default graph workflow.",
    )
    args = parser.parse_args()
    if args.functional:
        entity = create_hybrid_agent()
    elif args.workflow:
        entity = create_report_workflow()
    else:
        entity = create_report_agent()
    # auth_enabled=False: DevUI's default dev-token auth 401s the auto-opened
    # browser (it never receives the token); the server binds to 127.0.0.1 only.
    serve(
        entities=[entity],
        port=args.port,
        auto_open=True,
        auth_enabled=False,
        instrumentation_enabled=_prepare_instrumentation(),
    )


if __name__ == "__main__":
    main()
