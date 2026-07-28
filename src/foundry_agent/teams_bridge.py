"""Teams ↔ workflow bridge — the client half.

A thin, flow-agnostic bridge that lets the local Microsoft 365 Agents Playground
drive the document-authoring workflow: it forwards each inbound Teams *message*
as one bare turn to the hosted ``/responses`` chat endpoint and relays the
assistant text back. The module has two halves — the **client half** (pure
request/response translation + the async HTTP client) and the **server half**
(the native Agents-SDK ``/api/messages`` binding that receives Playground
activities and calls the client). ``main()`` runs the server; start a chat-mode
``task hosted:run`` alongside it.

Auth is **anonymous** — the local Playground sends no bearer token, so a tiny
:class:`Connections` resolves every connection to an ``AnonymousTokenProvider``
and the JWT middleware admits token-less requests. A real Teams tenant would
supply client-credentials auth instead; that (and the app manifest / Azure Bot
registration / Dev Tunnel) is out of scope — see the plan.

**Why bare turns.** In chat mode the host's regular-agent path prepends any
stored conversation history to the agent's ``messages`` and passes no
``session``, so :class:`~foundry_agent.chat_agent.WorkflowChatAgent` keys every
turn to its in-process ``"default"`` conversation. Continuity therefore lives in
the *running server*, not in any response id — and it only holds if the bridge
sends **bare** turns (no ``previous_response_id`` / ``conversation_id``). Chaining
``previous_response_id`` would populate that history and corrupt the elicitation
answer on the second turn (verified 2026-07-27; see the plan's ``lessons.md``).
So :func:`build_request` never sets either field, and one running server serves
one conversation at a time (single-user, matching the hosted chat-mode limit).

**Reply shape.** A non-streaming ``/responses`` reply carries the assistant text
at ``output[] (type=="message", role=="assistant") -> content[]
(type=="output_text") -> text``; :func:`extract_reply` walks exactly that.

Environment (env-selected, like the rest of the app):

- ``WORKFLOW_RESPONSES_URL`` — the hosted chat endpoint (default
  ``http://localhost:8088/responses``).
- ``WORKFLOW_MODEL_NAME`` — the ``model`` label sent on each turn (default
  ``report-interview-agent``); the host serves whichever flow it was started
  with regardless, so one label works for both flows.
- ``WORKFLOW_RESPONSES_TIMEOUT_SECONDS`` — per-turn read timeout (default
  ``600``); a turn runs real model calls, and timing one out is
  interview-destroying — see :data:`DEFAULT_TIMEOUT_SECONDS`.
- ``TEAMS_BRIDGE_PORT`` — port ``/api/messages`` listens on (default ``3978``).
"""

import asyncio
import logging
import os
from collections.abc import Mapping

import httpx
from aiohttp.web import Application, Request, Response, run_app
from dotenv import load_dotenv
from microsoft_agents.activity import Activity, ActivityTypes
from microsoft_agents.hosting.aiohttp import (
    CloudAdapter,
    jwt_authorization_middleware,
    start_agent_process,
)
from microsoft_agents.hosting.core import (
    AgentApplication,
    MemoryStorage,
    TurnContext,
    TurnState,
)
from microsoft_agents.hosting.core.authorization import (
    AccessTokenProviderBase,
    AgentAuthConfiguration,
    AnonymousTokenProvider,
    ClaimsIdentity,
    Connections,
)

logger = logging.getLogger(__name__)

#: The hosted chat endpoint a `task hosted:run` (chat / chat-functional) serves.
DEFAULT_RESPONSES_URL = "http://localhost:8088/responses"
#: The ``model`` label sent on each turn — the host ignores it for agent
#: selection, so the same value drives either flow.
DEFAULT_MODEL_NAME = "report-interview-agent"
#: Per-turn HTTP timeout in seconds. Flow 1 turns measured ~30s, but a Flow 2
#: turn can run the deterministic validate.py gate, re-elicitation *and* final
#: assembly inside a single turn: 120s and 300s both timed out mid-interview
#: (witnessed). That failure is not cosmetic — the server keeps working after the
#: client gives up, so the next message hits "Workflow is already running" and
#: resets the conversation, destroying the interview. Hence a deliberately
#: generous default; tune with ``WORKFLOW_RESPONSES_TIMEOUT_SECONDS``.
DEFAULT_TIMEOUT_SECONDS = 600.0
#: Returned when a ``/responses`` payload carries no assistant text, so a turn
#: never surfaces as an empty Teams bubble.
NO_REPLY_FALLBACK = "The workflow returned no message for that turn."


def build_request(text: str, *, model: str) -> dict[str, object]:
    """Build one **bare** ``/responses`` turn body.

    Deliberately omits ``previous_response_id`` and ``conversation_id``: chat-mode
    continuity lives in the running server's in-process conversation, and setting
    either field would make the host replay stored history into the elicitation
    answer (see the module docstring).

    Args:
        text: The user's message for this turn.
        model: The ``model`` label to send (see :data:`DEFAULT_MODEL_NAME`).

    Returns:
        A JSON-serializable request body: ``{"model", "input", "stream": False}``.
    """
    return {"model": model, "input": text, "stream": False}


def extract_reply(payload: object) -> str:
    """Pull the assistant text out of a non-streaming ``/responses`` reply.

    Concatenates the ``output_text`` of every assistant ``message`` item, in
    order. Anything else — tool calls, non-assistant items, non-text content — is
    skipped. An empty result degrades to :data:`NO_REPLY_FALLBACK` rather than an
    empty string, so the caller always has visible text to send back.

    Args:
        payload: Whatever ``response.json()`` returned — typed as ``object``
            because a non-mapping body (a bare list, say) is a real possibility
            that the guard below handles rather than raising on.

    Returns:
        The assistant reply text, or :data:`NO_REPLY_FALLBACK` when none is present.
    """
    if not isinstance(payload, Mapping):
        return NO_REPLY_FALLBACK
    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, Mapping) or content.get("type") != "output_text":
                continue
            text = content.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
    return "\n".join(parts).strip() or NO_REPLY_FALLBACK


def _timeout_seconds() -> float:
    """Resolve the per-turn HTTP timeout from the environment.

    A malformed ``WORKFLOW_RESPONSES_TIMEOUT_SECONDS`` falls back to
    :data:`DEFAULT_TIMEOUT_SECONDS` with a warning rather than crashing the
    bridge at startup.
    """
    raw = os.environ.get("WORKFLOW_RESPONSES_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "WORKFLOW_RESPONSES_TIMEOUT_SECONDS=%r is not a number; using %.0fs",
            raw,
            DEFAULT_TIMEOUT_SECONDS,
        )
        return DEFAULT_TIMEOUT_SECONDS


class WorkflowResponsesClient:
    """Forward one bare chat turn to the hosted ``/responses`` endpoint.

    Holds a single :class:`httpx.AsyncClient` reused across turns. HTTP or
    transport failures propagate from :meth:`send` (via ``raise_for_status``);
    the caller — the Agents-SDK message handler — owns turning those into visible
    assistant text.

    Args:
        url: Endpoint override; defaults to ``WORKFLOW_RESPONSES_URL`` /
            :data:`DEFAULT_RESPONSES_URL`.
        model: ``model`` label override; defaults to ``WORKFLOW_MODEL_NAME`` /
            :data:`DEFAULT_MODEL_NAME`.
        timeout: Per-turn timeout override in seconds; defaults to the
            ``WORKFLOW_RESPONSES_TIMEOUT_SECONDS`` env resolution.
        transport: Optional :class:`httpx.AsyncBaseTransport` for tests
            (e.g. :class:`httpx.MockTransport`); production leaves it unset.
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url or os.environ.get("WORKFLOW_RESPONSES_URL", DEFAULT_RESPONSES_URL)
        self._model = model or os.environ.get("WORKFLOW_MODEL_NAME", DEFAULT_MODEL_NAME)
        resolved_timeout = timeout if timeout is not None else _timeout_seconds()
        # Only the READ budget needs to be generous (a turn runs model calls). A
        # 600s *connect* timeout would hang for ten minutes on a mistyped or
        # unroutable WORKFLOW_RESPONSES_URL instead of failing fast.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(resolved_timeout, connect=5.0), transport=transport
        )

    async def send(self, text: str) -> str:
        """POST one bare turn and return the assistant reply text.

        Args:
            text: The user's message for this turn.

        Returns:
            The assistant reply (or :data:`NO_REPLY_FALLBACK` if the reply is empty).

        Raises:
            httpx.HTTPStatusError: The endpoint returned a non-2xx status.
            httpx.HTTPError: The request failed at the transport level (e.g. the
                server is not running).
        """
        response = await self._client.post(self._url, json=build_request(text, model=self._model))
        response.raise_for_status()
        return extract_reply(response.json())

    async def aclose(self) -> None:
        """Close the underlying HTTP client; safe to call more than once."""
        await self._client.aclose()

    @property
    def url(self) -> str:
        """The hosted ``/responses`` endpoint this client posts to."""
        return self._url

    @property
    def model(self) -> str:
        """The ``model`` label sent on each turn."""
        return self._model


# --------------------------------------------------------------------------- #
# Server half: the native Agents-SDK /api/messages binding.
# --------------------------------------------------------------------------- #

#: Port the bridge's ``/api/messages`` listens on — the Agents Playground default.
DEFAULT_BRIDGE_PORT = 3978
#: Reply when a turn arrives while the previous turn is still in flight.
BUSY_REPLY = "Still working on your previous message — one moment, then send your next reply."
#: Prefix for the visible assistant text shown when a turn cannot be completed.
#: Deliberately failure-agnostic: this covers a decode failure or an outright bug
#: as well as an unreachable server, so it must not claim the workflow was the problem.
ERROR_REPLY_PREFIX = "The bridge could not complete that turn: "
#: Reply when an activity carries no text (an attachment-only or card-submit
#: activity). Forwarding "" would spend a real workflow turn on an empty answer.
EMPTY_INPUT_REPLY = "I only read text — please type your answer as a message."


def _describe_error(exc: Exception) -> str:
    """Render an exception as text that is never blank.

    Several httpx failures — ``ReadTimeout`` most importantly — carry an empty
    ``str()``, which rendered as a bare prefix with nothing after it (witnessed
    during the Flow 2 smoke). Prefixing the class name guarantees the reply names
    *what* went wrong.
    """
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def _conversation_id(context: TurnContext) -> str:
    """The inbound conversation id, or ``"default"`` when absent — for logging only."""
    conversation = getattr(context.activity, "conversation", None)
    return getattr(conversation, "id", None) or "default"


async def handle_message_turn(
    context: TurnContext,
    client: WorkflowResponsesClient,
    lock: asyncio.Lock,
) -> None:
    """Advance one inbound Teams message through the workflow and reply.

    Serialization is **process-wide**, not per Teams conversation, because the
    resource being protected is global: chat mode keys every turn to the server's
    single in-process ``"default"`` conversation (no ``session`` reaches the chat
    agent), so two different Teams conversations still drive *one* workflow. A
    per-conversation lock would let a reloaded Playground — which mints a fresh
    conversation id — fire a concurrent turn, hit "Workflow is already running",
    and reset the interview: exactly the collision this guard exists to prevent.

    A message arriving mid-turn therefore gets :data:`BUSY_REPLY` instead of a
    second concurrent ``/responses`` turn. Any client failure surfaces as visible
    assistant text (prefixed with :data:`ERROR_REPLY_PREFIX`), never an empty bubble.

    Args:
        context: The turn context for the inbound message activity.
        client: The client that forwards the turn to the hosted endpoint.
        lock: The process-wide turn lock shared across every turn.
    """
    conversation_id = _conversation_id(context)
    text = context.activity.text or ""
    if not text.strip():
        await context.send_activity(EMPTY_INPUT_REPLY)
        return
    if lock.locked():
        await context.send_activity(BUSY_REPLY)
        return
    async with lock:
        # A turn runs real model calls — 16s for a trivial "hi", minutes for a
        # full elicitation round. With stream=False nothing reaches the client
        # until the whole turn finishes, which reads as "the agent never
        # replied". Emit the typing indicator the channel already knows how to
        # render so the wait is visibly the agent thinking. Best-effort: a
        # channel that rejects it must not cost the user their turn. (Sent
        # directly rather than via the SDK's `application.typing` helper, whose
        # repeat loop is driven off a threading.Timer.)
        try:
            await context.send_activity(Activity(type=ActivityTypes.typing))
        except Exception:  # noqa: BLE001 - cosmetic only; never fail the turn for it
            logger.debug("typing indicator not accepted for %s", conversation_id, exc_info=True)
        try:
            reply = await client.send(text)
        except Exception as exc:  # noqa: BLE001 - surface as chat text, not an empty bubble
            logger.warning("bridge turn failed for %s", conversation_id, exc_info=True)
            reply = f"{ERROR_REPLY_PREFIX}{_describe_error(exc)}"
        await context.send_activity(reply)


class _AnonymousConnections(Connections):
    """Anonymous connection manager for the local Agents Playground (no Entra auth).

    The Playground speaks the Activity protocol without bearer tokens, so every
    connection resolves to an :class:`AnonymousTokenProvider` and the default
    configuration carries no client id — which the JWT middleware reads as
    "anonymous is allowed". A real Teams tenant would substitute a
    client-credentials :class:`Connections` here (out of scope; see the plan).
    """

    def __init__(self) -> None:
        self._provider = AnonymousTokenProvider()
        self._configuration = AgentAuthConfiguration()

    def get_connection(self, connection_name: str) -> AccessTokenProviderBase:
        return self._provider

    def get_default_connection(self) -> AccessTokenProviderBase:
        return self._provider

    def get_token_provider(
        self, claims_identity: ClaimsIdentity, service_url: str
    ) -> AccessTokenProviderBase:
        return self._provider

    def get_default_connection_configuration(self) -> AgentAuthConfiguration:
        return self._configuration


def create_bridge_application(client: WorkflowResponsesClient) -> AgentApplication:
    """Build the Agents-SDK application that serves ``/api/messages``.

    Every inbound *message* activity is advanced through
    :func:`handle_message_turn`; non-message activities have no handler and are
    ignored. One process-wide :class:`asyncio.Lock` is closed over here so
    serialization spans every turn the application handles — see
    :func:`handle_message_turn` for why the lock is not per conversation.

    The adapter is reachable afterwards as ``application.adapter`` (the SDK's own
    public property), which is what :func:`main` hands to
    :func:`start_agent_process`.

    Args:
        client: The client each turn forwards to the hosted ``/responses`` endpoint.

    Returns:
        The configured application.
    """
    connections = _AnonymousConnections()
    application = AgentApplication[TurnState](
        storage=MemoryStorage(),
        adapter=CloudAdapter(connection_manager=connections),
        connection_manager=connections,
    )
    turn_lock = asyncio.Lock()

    @application.activity(ActivityTypes.message)
    async def _on_message(context: TurnContext, _state: TurnState) -> None:
        await handle_message_turn(context, client, turn_lock)

    return application


def main() -> None:
    """Serve the Teams bridge on ``/api/messages`` for the local Agents Playground.

    Point the Microsoft 365 Agents Playground at
    ``http://localhost:<TEAMS_BRIDGE_PORT>/api/messages`` and run a chat-mode
    ``task hosted:run`` (``HOSTED_AGENT_MODE=chat`` or ``chat-functional``)
    alongside. Anonymous auth only — tenant sideload is out of scope.
    """
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # Mirror hosting.main / main: own .env loading so WORKFLOW_* / TEAMS_BRIDGE_PORT
    # are resolved before the client and server read them.
    load_dotenv()
    client = WorkflowResponsesClient()
    application = create_bridge_application(client)

    async def _messages(request: Request) -> Response | None:
        return await start_agent_process(request, application, application.adapter)

    web_app = Application(middlewares=[jwt_authorization_middleware])
    # The JWT middleware reads this; an anonymous config (no CLIENT_ID) admits the
    # Playground's token-less requests.
    web_app["agent_configuration"] = AgentAuthConfiguration()
    web_app.router.add_post("/api/messages", _messages)
    web_app.on_cleanup.append(lambda _app: client.aclose())

    port = int(os.environ.get("TEAMS_BRIDGE_PORT", DEFAULT_BRIDGE_PORT))
    logger.info(
        "Teams bridge on http://localhost:%d/api/messages → forwarding to %s (model %s)",
        port,
        client.url,
        client.model,
    )
    # Loopback-only, deliberately not env-configurable: this endpoint is
    # ANONYMOUS (see _AnonymousConnections) and spends model tokens, so binding it
    # beyond localhost would expose an unauthenticated, billable endpoint on the
    # network. Reaching it from outside is a tunnel's job, with real auth added.
    run_app(web_app, host="localhost", port=port)


if __name__ == "__main__":
    main()
