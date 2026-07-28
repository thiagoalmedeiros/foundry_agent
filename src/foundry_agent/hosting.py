"""Foundry Hosted Agent entrypoint — the production serving path.

Serves the document-authoring workflow through MAF's own hosting package
(``agent-framework-foundry-hosting``) rather than DevUI: the workflow is
wrapped in MAF's standard :class:`WorkflowAgent` and handed to
:class:`ResponsesHostServer`, which exposes an OpenAI-compatible
``/responses`` endpoint that any OpenAI SDK client can drive.

Two things the hosting infrastructure owns, which this module must therefore
NOT do (both verified against the installed package, see the plan's
lessons.md):

- **Checkpoints.** The host detects a :class:`WorkflowAgent`, manages its
  checkpoint storage itself (per-user partitioned for multi-tenant safety),
  and *raises* if the workflow already has checkpointing configured. So
  :func:`~foundry_agent.workflow.create_report_workflow` must stay
  checkpoint-free.
- **Conversation history.** The host resumes state from the checkpoint keyed
  by ``conversation_id`` / ``previous_response_id``, so no history provider
  and no in-memory conversation map belongs here — the very thing
  :mod:`~foundry_agent.chat_agent` does for the DevUI path, and the
  reason that wrapper is not used in production.

Human-in-the-loop rides the protocol as a ``request_info`` **function call**
(``WorkflowAgent.REQUEST_INFO_FUNCTION_NAME``): each elicitation pause is
emitted as a tool call the client answers with a function result, which the
host feeds back into the restored workflow.

**Chat mode** (``HOSTED_AGENT_MODE=chat``): chat-first clients — the Foundry
playground, ``azd ai agent invoke`` — render assistant *text* only, so a
``request_info`` function call shows as an empty reply (witnessed 2026-07-23:
the stream carries zero ``output_text`` events). In chat mode the host serves
:class:`~foundry_agent.chat_agent.WorkflowChatAgent` instead: every
elicitation pause becomes ordinary assistant text and the user's next message
resumes the run. Conversation state checkpoints to per-conversation file
storage every turn (``CHAT_CHECKPOINT_STORAGE_PATH``), and a restarted
process restores the paused interview from the latest checkpoint — restart
survival holds wherever that checkpoint root survives (the platform's
persistent per-session containers hosted; the plain filesystem locally).
Still assumed out of scope: clients that send no conversation id share the
``"default"`` conversation.

**Flow 2 chat mode** (``HOSTED_AGENT_MODE=chat-functional``): serves the
functional workflow (Flow 2) as a chat agent via
:class:`~foundry_agent.chat_agent_functional.FunctionalWorkflowChatAgent` — the
same plain-text-pause behavior as chat mode, but Flow 2's deterministic
``validate.py`` gate stands in for the validation agent. It is **in-memory
only**: a restart drops in-flight Flow 2 interviews, so the restart-resume
guarantee above is Flow 1 chat mode's alone. This is the surface the local
Agents Playground / Teams bridge drives when testing Flow 2 (see
``HOSTED_AGENT_MODE`` in ARCHITECTURE.md).

**Observability** is a third thing the hosting infrastructure owns: building
a :class:`~agent_framework_foundry_hosting.ResponsesHostServer` unconditionally
triggers ``azure.ai.agentserver``'s bundled OTel distro, which is the sole
authority over which ``TracerProvider`` gets installed for this process — it
wins over any provider application code might configure. This module does
not fight that; it only sets the environment defaults
(``FOUNDRY_AGENT_NAME``, ``OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT``)
that make the distro's local-dev behavior match what the real Foundry
platform already injects in production — see
:func:`_configure_local_otel_defaults`.

Run locally with ``task hosted:run`` (or ``azd ai agent run``); deploy with
``azd provision`` / ``azd deploy``.
"""

import logging
import os

from agent_framework import WorkflowAgent
from agent_framework_foundry_hosting import ResponsesHostServer
from dotenv import load_dotenv

from foundry_agent.chat_agent import WorkflowChatAgent
from foundry_agent.chat_agent_functional import FunctionalWorkflowChatAgent
from foundry_agent.checkpoint_compat import install_checkpoint_type_allowlist
from foundry_agent.workflow import DiscoveryCache, create_report_workflow
from foundry_agent.workflow_functional import create_hybrid_workflow

logger = logging.getLogger(__name__)

AGENT_NAME = "report-interview-agent"
AGENT_DESCRIPTION = (
    "Document-authoring interview: one gap-analysis pass over every field group, one "
    "agent-paced elicitation conversation, and validation via the mounted format "
    "skill's own script plus adequacy judgment, then the assembled document."
)
#: Flow 2's description for chat-functional mode. Flow 2 differs from Flow 1 only
#: in its validation stage (a deterministic skill-script gate, not an agent), so
#: the served name stays :data:`AGENT_NAME` — the Teams bridge sends one model
#: string regardless of which flow the server runs.
FUNCTIONAL_AGENT_DESCRIPTION = (
    "Document-authoring interview (Flow 2, functional API): the same discovery → "
    "elicitation → assembler flow, but validation is a deterministic skill-script gate "
    "that re-elicits only the groups with missing fields until it passes."
)
#: Local port for `azd ai agent run`; the hosted platform overrides it.
DEFAULT_PORT = 8088


def create_hosted_agent() -> WorkflowAgent:
    """Wrap the document-authoring workflow as the agent the host serves.

    :class:`WorkflowAgent` is MAF's standard workflow-as-agent adapter — the
    host special-cases it for checkpoint restoration, so the workflow must
    reach the host through this type rather than a bespoke wrapper.

    Raises:
        KeyError: A required AZURE_OPENAI_* variable is unset (from the
            workflow's chat-client factory).
    """
    # No explicit DiscoveryCache is bound here on purpose: workflow mode builds
    # the workflow once, so create_report_workflow's own auto-created
    # cache already lives for the whole process. Only the chat paths, which
    # rebuild per conversation, need a cache bound above the factory.
    return WorkflowAgent(
        create_report_workflow(),
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
    )


def create_hosted_chat_agent() -> WorkflowChatAgent:
    """Wrap the workflow as a plain-text chat agent for chat-first clients.

    See the module docstring's **Chat mode** section: playground-style UIs
    render assistant text only, so the ``request_info`` protocol reads as an
    empty reply there. The wrapper takes the workflow *factory* — a fresh
    workflow per conversation, constructed lazily on the first turn — so one
    shared :class:`DiscoveryCache` is bound here, above the factory, to keep the
    discovery memo spanning conversations rather than resetting each one.
    """
    cache = DiscoveryCache()
    return WorkflowChatAgent(
        lambda: create_report_workflow(discovery_cache=cache),
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
    )


def create_hosted_functional_chat_agent() -> FunctionalWorkflowChatAgent:
    """Wrap Flow 2 (the functional workflow) as a plain-text chat agent.

    The Flow 2 sibling of :func:`create_hosted_chat_agent`: chat-first clients (the
    Foundry playground, a Teams bridge over the Agents Playground) render assistant
    *text* only, so Flow 2's ``request_info`` pauses are served as ordinary
    assistant text by :class:`FunctionalWorkflowChatAgent`. Like the Flow 1 chat
    wrapper it takes the workflow *factory* — a fresh workflow per conversation —
    so one shared :class:`DiscoveryCache` is bound here, above the factory, to keep
    the discovery memo spanning conversations.

    Unlike Flow 1 chat mode this holds each conversation **in memory only**: a
    process restart drops in-flight Flow 2 interviews (Flow 2's checkpoint types
    are outside the chat checkpoint allowlist — see
    :mod:`~foundry_agent.chat_agent_functional`), so restart-resume stays a
    Flow 1 chat-mode guarantee, and hosted checkpoint parity is a separate
    follow-up.
    """
    cache = DiscoveryCache()
    return FunctionalWorkflowChatAgent(
        lambda: create_hybrid_workflow(discovery_cache=cache),
        name=AGENT_NAME,
        description=FUNCTIONAL_AGENT_DESCRIPTION,
    )


def _create_agent_for_mode(
    mode: str,
) -> WorkflowAgent | WorkflowChatAgent | FunctionalWorkflowChatAgent:
    """Select the served agent for a ``HOSTED_AGENT_MODE`` value.

    The mode string is normalized here (stripped, lower-cased) so callers may
    pass the raw environment value. Three surfaces over the one workflow:

    - ``chat`` — Flow 1 as a plain-text chat agent (per-turn file checkpoints,
      restart resume).
    - ``chat-functional`` — Flow 2 as a plain-text chat agent (in-memory only).
    - anything else (default ``workflow``) — Flow 1 as MAF's
      :class:`WorkflowAgent` for machine clients, with human-in-the-loop as a
      ``request_info`` function call.
    """
    normalized = mode.strip().lower()
    if normalized == "chat":
        return create_hosted_chat_agent()
    if normalized == "chat-functional":
        return create_hosted_functional_chat_agent()
    if normalized not in ("", "workflow"):
        # Falling through to workflow mode silently would serve machine-client
        # `request_info` function calls to a chat client, which renders as empty
        # replies — a typo like "chat-func" must not look like it worked.
        logger.warning(
            "unrecognized HOSTED_AGENT_MODE %r — serving the default workflow mode "
            "(expected 'workflow', 'chat', or 'chat-functional')",
            mode,
        )
    return create_hosted_agent()


def _configure_local_otel_defaults() -> None:
    """Give the hosting SDK's own OTel distro correct local-dev defaults.

    ``ResponsesHostServer(...)`` construction (below) unconditionally
    triggers ``azure.ai.agentserver``'s bundled OTel distro — it is the sole
    authority over which ``TracerProvider`` gets installed for this process,
    so this function never configures OTel itself. It only sets the two
    environment variables the distro reads, so local dev resolves the same
    way the real platform's own injected variables already do in
    production:

    - ``FOUNDRY_AGENT_NAME`` drives the ``service.name`` resource attribute
      the distro builds (it ignores ``OTEL_SERVICE_NAME`` entirely and
      otherwise falls back to the hardcoded literal ``"azure.ai.agentserver"``).
      The real platform injects this; locally it's unset, so ``setdefault``
      fills it from :data:`AGENT_NAME` — a no-op wherever the platform
      already provides it.
    - ``OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`` is the distro's
      own sensitive-data gate. The distro's instrumentor activation runs
      *inside* ``ResponsesHostServer.__init__`` — after anything application
      code could set — so it always has the final say. Only sync it from
      this package's own ``ENABLE_SENSITIVE_DATA`` convention when that
      variable is *explicitly* present: production has neither variable set
      today, and syncing from an unset (defaulted) value would silently
      flip the distro's current default (capture on) to off.
    """
    os.environ.setdefault("FOUNDRY_AGENT_NAME", AGENT_NAME)
    if "ENABLE_SENSITIVE_DATA" in os.environ:
        sensitive = os.environ["ENABLE_SENSITIVE_DATA"].strip().lower() not in ("false", "0")
        os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = (
            "true" if sensitive else "false"
        )


def main() -> None:
    """Serve the document-authoring workflow over the Foundry Responses protocol."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # Own this explicitly rather than relying on the incidental load_dotenv()
    # call inside agents.py's create_chat_client() — this package's Taskfile
    # has no dotenv directive of its own, so nothing else guarantees .env is
    # loaded before the environment reads below.
    load_dotenv()
    _configure_local_otel_defaults()
    # Interim shim (plan decision B): let hosted checkpoints restore this
    # workflow's own state types, so an interview survives a restart. Remove
    # once agent-framework-foundry-hosting exposes an allowlist hook.
    install_checkpoint_type_allowlist()
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    # _create_agent_for_mode owns normalization, so the raw value is passed through.
    mode = os.environ.get("HOSTED_AGENT_MODE", "workflow")
    agent = _create_agent_for_mode(mode)
    server = ResponsesHostServer(agent)
    # Log the served agent's type, not the requested mode string: an unrecognized
    # mode falls back to workflow mode, and echoing the request would misreport that.
    logger.info(
        "serving %s on port %d via the Foundry Responses protocol (%s)",
        AGENT_NAME,
        port,
        type(agent).__name__,
    )
    server.run(port=port)


if __name__ == "__main__":
    main()
