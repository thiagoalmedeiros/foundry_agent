"""The Teams-bridge client half: bare-turn requests and reply extraction.

Fully offline: ``build_request`` / ``extract_reply`` are I/O-free, and the client
is exercised over :class:`httpx.MockTransport` so no server or network is touched.
The payload fixtures mirror the real ``/responses`` shape captured in the plan's
Batch-1 spike (``output[]`` message/assistant → ``content[]`` output_text → text).
"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from microsoft_agents.activity import ActivityTypes
from microsoft_agents.hosting.aiohttp import CloudAdapter
from microsoft_agents.hosting.core import AgentApplication

from foundry_agent.teams_bridge import (
    BUSY_REPLY,
    DEFAULT_TIMEOUT_SECONDS,
    EMPTY_INPUT_REPLY,
    ERROR_REPLY_PREFIX,
    NO_REPLY_FALLBACK,
    WorkflowResponsesClient,
    _timeout_seconds,
    build_request,
    create_bridge_application,
    extract_reply,
    handle_message_turn,
)


def _responses_payload(text: str) -> dict[str, object]:
    """A ``/responses`` body shaped like the Batch-1 capture, carrying one text reply."""
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
    }


def test_build_request_is_a_bare_turn():
    """The whole design rests on bare turns — chaining keys would replay history."""
    body = build_request("hello there", model="report-interview-agent")

    assert body == {"model": "report-interview-agent", "input": "hello there", "stream": False}
    assert "previous_response_id" not in body
    assert "conversation_id" not in body


def test_extract_reply_pulls_assistant_output_text():
    reply = extract_reply(_responses_payload("What is the report number?"))

    assert reply == "What is the report number?"


def test_extract_reply_joins_multiple_output_text_blocks():
    payload = {
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "Line one."},
                    {"type": "output_text", "text": "Line two."},
                ],
            }
        ]
    }

    assert extract_reply(payload) == "Line one.\nLine two."


def test_extract_reply_ignores_non_assistant_and_non_text_content():
    """Only assistant ``output_text`` survives — user echoes, tool calls, reasoning drop."""
    payload = {
        "output": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "output_text", "text": "echo of my input"}],
            },
            {"type": "function_call", "name": "some_tool", "arguments": "{}"},
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "reasoning", "text": "internal thought"},
                    {"type": "output_text", "text": "the visible answer"},
                ],
            },
        ]
    }

    assert extract_reply(payload) == "the visible answer"


def test_extract_reply_falls_back_when_no_assistant_text():
    assert extract_reply({"status": "completed", "output": []}) == NO_REPLY_FALLBACK
    assert extract_reply({}) == NO_REPLY_FALLBACK


async def test_client_send_posts_a_bare_turn_and_returns_the_reply():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_responses_payload("Next question?"))

    client = WorkflowResponsesClient(
        url="http://test.local/responses",
        model="report-interview-agent",
        transport=httpx.MockTransport(handler),
    )
    try:
        reply = await client.send("the burglary happened at 2am")
    finally:
        await client.aclose()

    assert reply == "Next question?"
    assert captured["url"] == "http://test.local/responses"
    assert captured["body"] == {
        "model": "report-interview-agent",
        "input": "the burglary happened at 2am",
        "stream": False,
    }


def test_timeout_seconds_reads_the_environment(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RESPONSES_TIMEOUT_SECONDS", "45")
    assert _timeout_seconds() == 45.0


def test_timeout_seconds_falls_back_when_unset_or_malformed(monkeypatch):
    """A typo must not crash the bridge at startup — it degrades to the default."""
    monkeypatch.delenv("WORKFLOW_RESPONSES_TIMEOUT_SECONDS", raising=False)
    assert _timeout_seconds() == DEFAULT_TIMEOUT_SECONDS

    monkeypatch.setenv("WORKFLOW_RESPONSES_TIMEOUT_SECONDS", "ten minutes")
    assert _timeout_seconds() == DEFAULT_TIMEOUT_SECONDS


async def test_client_send_raises_on_http_error():
    """A non-2xx propagates so the message handler can render it as visible text."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = WorkflowResponsesClient(
        url="http://test.local/responses", transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.send("hello")
    finally:
        await client.aclose()


# --------------------------------------------------------------------------- #
# Server half: message handler + serialization (offline, fake TurnContext).
# --------------------------------------------------------------------------- #


class _FakeTurnContext:
    """Minimal TurnContext stand-in capturing what the handler sends back."""

    def __init__(self, text: str, conversation_id: str = "c1") -> None:
        self.activity = SimpleNamespace(
            text=text, conversation=SimpleNamespace(id=conversation_id)
        )
        self.sent: list[str] = []
        self.typing_count = 0

    async def send_activity(self, activity_or_text: object) -> None:
        # The handler also emits a typing Activity; keep those out of `sent` so
        # the text assertions stay about what the user actually reads, and
        # record them separately so the indicator itself can be asserted.
        if getattr(activity_or_text, "type", None) == ActivityTypes.typing:
            self.typing_count += 1
            return
        self.sent.append(activity_or_text)


class _StubResponsesClient:
    """Duck-types WorkflowResponsesClient.send for handler tests.

    ``block`` (when given) is awaited inside ``send`` so a test can hold a turn
    "in flight" and drive a genuine concurrent second turn.
    """

    def __init__(
        self,
        *,
        reply: str | None = None,
        error: Exception | None = None,
        block: asyncio.Event | None = None,
    ) -> None:
        self._reply = reply
        self._error = error
        self._block = block
        self.calls: list[str] = []
        #: Set as soon as ``send`` is entered, so a test can await the turn being
        #: genuinely in flight instead of polling the lock (polling would spin
        #: forever — hanging rather than failing — if the lock were removed).
        self.started = asyncio.Event()

    async def send(self, text: str) -> str:
        self.calls.append(text)
        self.started.set()
        if self._block is not None:
            await self._block.wait()
        if self._error is not None:
            raise self._error
        return self._reply or ""


async def test_handle_message_turn_relays_the_reply():
    context = _FakeTurnContext("the burglary was at 2am")
    client = _StubResponsesClient(reply="What was taken?")

    await handle_message_turn(context, client, asyncio.Lock())

    assert client.calls == ["the burglary was at 2am"]
    assert context.sent == ["What was taken?"]


async def test_handle_message_turn_shows_a_typing_indicator_before_the_slow_call():
    """A turn takes 16s–2min; with no indicator the client looks unresponsive."""
    context = _FakeTurnContext("hi")
    client = _StubResponsesClient(reply="What kind of incident?")

    await handle_message_turn(context, client, asyncio.Lock())

    assert context.typing_count == 1, "the user must see the agent is working"
    assert context.sent == ["What kind of incident?"]


async def test_a_typing_indicator_failure_never_costs_the_user_their_turn():
    """Some channels reject typing activities — that must stay cosmetic."""

    class _RejectsTyping(_FakeTurnContext):
        async def send_activity(self, activity_or_text: object) -> None:
            if getattr(activity_or_text, "type", None) == ActivityTypes.typing:
                raise RuntimeError("this channel does not accept typing")
            await super().send_activity(activity_or_text)

    context = _RejectsTyping("hi")
    client = _StubResponsesClient(reply="What kind of incident?")

    await handle_message_turn(context, client, asyncio.Lock())

    assert context.sent == ["What kind of incident?"]


async def test_handle_message_turn_surfaces_client_error_as_text():
    context = _FakeTurnContext("hello")
    client = _StubResponsesClient(error=httpx.ConnectError("connection refused"))

    await handle_message_turn(context, client, asyncio.Lock())

    assert len(context.sent) == 1
    assert context.sent[0].startswith(ERROR_REPLY_PREFIX)
    assert "connection refused" in context.sent[0]


async def test_handle_message_turn_names_an_exception_with_no_message():
    """httpx.ReadTimeout stringifies to "" — the reply must still say what failed.

    Regression: the Flow 2 smoke produced a bare error prefix with nothing after
    it, because the timeout carried an empty message.
    """
    context = _FakeTurnContext("hello")
    client = _StubResponsesClient(error=httpx.ReadTimeout(""))

    await handle_message_turn(context, client, asyncio.Lock())

    assert context.sent == [f"{ERROR_REPLY_PREFIX}ReadTimeout"]
    assert not context.sent[0].endswith(": "), "the reply must not trail off after the prefix"


async def test_a_second_turn_is_refused_while_the_first_is_still_running():
    """The real serialization guarantee: a concurrent turn must not reach the workflow.

    Drives two genuinely concurrent ``handle_message_turn`` calls — the first held
    inside ``send`` — rather than pre-acquiring the lock, so removing the
    ``async with lock`` would fail this test.
    """
    lock = asyncio.Lock()
    release_first = asyncio.Event()
    client = _StubResponsesClient(reply="the answer", block=release_first)
    first_context = _FakeTurnContext("first message")
    second_context = _FakeTurnContext("second message", conversation_id="a-different-one")

    first = asyncio.create_task(handle_message_turn(first_context, client, lock))
    # Wait for the first turn to be genuinely in flight (inside the client), with a
    # bound so a regression fails the test rather than hanging the suite.
    await asyncio.wait_for(client.started.wait(), timeout=5)

    # The second turn must be refused *promptly* — it should never reach the
    # blocked client. The bound turns a lost guarantee into a fast failure rather
    # than a hung suite.
    try:
        await asyncio.wait_for(handle_message_turn(second_context, client, lock), timeout=5)
    finally:
        release_first.set()
        await first

    assert second_context.sent == [BUSY_REPLY]
    assert client.calls == ["first message"], "the second turn must not reach the workflow"
    assert first_context.sent == ["the answer"]


async def test_serialization_is_process_wide_not_per_conversation():
    """A reloaded Playground mints a NEW conversation id; it must still be refused.

    The server keys every turn to its single in-process "default" conversation, so
    a per-conversation lock would let this second turn collide and reset the run.
    """
    lock = asyncio.Lock()
    await lock.acquire()
    context = _FakeTurnContext("message from a fresh conversation", conversation_id="brand-new")
    client = _StubResponsesClient(reply="should never be produced")

    try:
        await handle_message_turn(context, client, lock)
    finally:
        lock.release()

    assert context.sent == [BUSY_REPLY]
    assert client.calls == []


async def test_handle_message_turn_rejects_empty_text_without_spending_a_turn():
    """An attachment-only activity carries no text; forwarding "" would burn a real turn."""
    context = _FakeTurnContext("   ")
    client = _StubResponsesClient(reply="should never be produced")

    await handle_message_turn(context, client, asyncio.Lock())

    assert context.sent == [EMPTY_INPUT_REPLY]
    assert client.calls == []


async def test_create_bridge_application_builds_the_app_and_exposes_its_adapter():
    """The anonymous wiring must construct offline (no network) — catches import/config drift."""
    client = WorkflowResponsesClient(
        url="http://test.local/responses",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    try:
        application = create_bridge_application(client)
    finally:
        await client.aclose()

    assert isinstance(application, AgentApplication)
    assert isinstance(application.adapter, CloudAdapter)
