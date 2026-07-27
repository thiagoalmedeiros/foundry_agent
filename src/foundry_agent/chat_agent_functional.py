"""Serve the Flow 2 functional workflow as a conversational chat agent for DevUI.

DevUI classifies a bare :class:`~agent_framework.FunctionalWorkflow` as an
*agent* (it has no ``executors``), so its ``request_info`` pauses surface as an
"Approval Required" function-call panel instead of a chat. This wrapper is the
functional analogue of :class:`~foundry_agent.chat_agent.WorkflowChatAgent`: it
holds one functional-workflow instance **per conversation in memory** and
advances it one turn per user message — returning each ``request_info`` pause as
ordinary assistant text and resuming on the next message
(``run(text)`` → ``run(responses={request_id: answer})``).

Unlike the graph :class:`WorkflowChatAgent` it uses **no checkpoint storage**:
resume rides the functional workflow's own in-memory replay cache, kept on the
reused instance, and its checkpoint types are not in graph mode's allowlist
(feeding them to that storage raises "Checkpoint deserialization blocked for
type '…:_TurnResult'"). The trade-off is that a process restart drops in-flight
Flow 2 conversations — an accepted limit for the local DevUI showcase; hosted
serving and checkpoint parity are a separate follow-up.

State is keyed by the DevUI conversation (``session.session_id``); a new
conversation builds a fresh workflow via the injected factory.
"""

import logging
from collections.abc import AsyncIterable, Callable, Sequence

from agent_framework import (
    AgentResponse,
    AgentResponseUpdate,
    BaseAgent,
    Content,
    FunctionalWorkflow,
    Message,
    ResponseStream,
)

from foundry_agent.workflow_functional import _as_text

logger = logging.getLogger(__name__)

NO_OUTPUT_REPLY = "The workflow finished without producing a document."
ERROR_REPLY_PREFIX = (
    "The workflow hit an error and was reset — please send your request again "
    "to start over.\n\nDetails: "
)


class _FunctionalConversation:
    """One chat's live functional-workflow run and its pending elicitation id.

    The workflow instance is reused across the conversation's turns so its
    in-memory replay cache survives each pause — that is what makes resume work
    without checkpoint storage.
    """

    def __init__(self, workflow: FunctionalWorkflow) -> None:
        self.workflow = workflow
        self.pending_request_id: str | None = None


class FunctionalWorkflowChatAgent(BaseAgent):
    """Drive the Flow 2 functional workflow through multi-turn chat text.

    Args:
        workflow_factory: Builds a fresh functional-workflow instance per
            conversation (called lazily on the conversation's first message).
        name: Agent name surfaced by DevUI.
        description: Agent description surfaced by DevUI.
    """

    def __init__(
        self,
        workflow_factory: Callable[[], FunctionalWorkflow],
        *,
        name: str,
        description: str,
    ) -> None:
        super().__init__(name=name, description=description)
        self._workflow_factory = workflow_factory
        self._conversations: dict[str, _FunctionalConversation] = {}

    def run(  # type: ignore[override]
        self,
        messages: object = None,
        *,
        stream: bool = False,
        session: object = None,
        **kwargs: object,
    ) -> object:
        """Advance the conversation's workflow by one turn.

        Returns an :class:`AgentResponse` (awaitable) or, when ``stream`` is
        true, a :class:`ResponseStream` yielding a single assistant update —
        DevUI always calls this with ``stream=True``.
        """
        conversation_id = getattr(session, "session_id", None) or "default"
        user_text = _as_text(messages)

        if not stream:
            return self._run_once(conversation_id, user_text)
        return ResponseStream(
            self._stream_once(conversation_id, user_text),
            finalizer=_finalize_updates,
        )

    async def _run_once(self, conversation_id: str, user_text: str) -> AgentResponse:
        reply = await self._advance(conversation_id, user_text)
        return _assistant_response(reply)

    async def _stream_once(
        self, conversation_id: str, user_text: str
    ) -> AsyncIterable[AgentResponseUpdate]:
        reply = await self._advance(conversation_id, user_text)
        yield AgentResponseUpdate(contents=[Content.from_text(reply)], role="assistant")

    async def _advance(self, conversation_id: str, user_text: str) -> str:
        """Start or resume the workflow and return the next assistant message.

        A fresh conversation runs the workflow from the user's text; an existing
        one resumes with that text as the answer to the recorded pause. If the
        run pauses again, the pause's prompt is returned as assistant text and
        the new request id is recorded; if it finishes, the document is returned
        and the conversation is dropped. Any error is surfaced as visible
        assistant text (never an empty bubble), and the conversation is dropped
        so the next message starts over.
        """
        conversation = self._conversations.get(conversation_id)
        try:
            if conversation is None:
                conversation = _FunctionalConversation(self._workflow_factory())
                self._conversations[conversation_id] = conversation
                result = await conversation.workflow.run(user_text)
            else:
                result = await conversation.workflow.run(
                    responses={conversation.pending_request_id: user_text}
                )
        except Exception as exc:  # noqa: BLE001 - surface as chat text, not empty bubble
            self._conversations.pop(conversation_id, None)
            logger.warning("functional chat turn failed for %s", conversation_id, exc_info=True)
            return f"{ERROR_REPLY_PREFIX}{exc}"

        pending = result.get_request_info_events()
        if pending:
            conversation.pending_request_id = pending[0].request_id
            return pending[0].data.prompt

        self._conversations.pop(conversation_id, None)
        outputs = result.get_outputs()
        return outputs[0] if outputs else NO_OUTPUT_REPLY


def _assistant_response(text: str) -> AgentResponse:
    """Wrap plain text as a single-message assistant response."""
    return AgentResponse(messages=[Message("assistant", [Content.from_text(text)])])


def _finalize_updates(updates: Sequence[AgentResponseUpdate]) -> AgentResponse:
    """Collapse the streamed updates into one assistant response."""
    text = "".join(
        content.text
        for update in updates
        for content in (update.contents or [])
        if getattr(content, "text", None)
    )
    return _assistant_response(text)
