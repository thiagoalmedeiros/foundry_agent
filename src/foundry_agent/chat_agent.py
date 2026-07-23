"""Expose the Policy Report workflow as a conversational chat agent for DevUI.

Served raw, DevUI renders a :class:`~agent_framework.Workflow` as a run-form
plus a typed HITL panel. That surfaces the stage graph nicely, but each
elicitation pause becomes a form field — so there is nowhere to attach a
document mid-run, and the flow reads as a sequence of forms rather than a
conversation.

:class:`WorkflowChatAgent` wraps the workflow as a plain chat agent instead:
each elicitation step is returned as ordinary assistant text, and the user's
next message — typed, pasted, or with a file attached — is fed back as the
answer that resumes the run. Attachments are decoded here (see
:func:`_extract_text`), which is what lets an uploaded spec reach the workflow
as source material.

State is keyed by the DevUI conversation (``session.session_id``); a new
conversation starts a fresh workflow. The workflow's own pause/resume machinery
(``run(text)`` → ``run(responses={request_id: answer})``) is what actually
drives it, so only the presentation changes.
"""

import base64
import binascii
import hashlib
import logging
import os
import re
from collections.abc import AsyncIterable, Callable, Sequence
from pathlib import Path
from urllib.parse import unquote

from agent_framework import (
    AgentResponse,
    AgentResponseUpdate,
    BaseAgent,
    Content,
    FileCheckpointStorage,
    Message,
    ResponseStream,
    Workflow,
)

from foundry_agent.checkpoint_compat import WORKFLOW_CHECKPOINT_TYPE_NAMES

logger = logging.getLogger(__name__)

NO_OUTPUT_REPLY = "The workflow finished without producing a document."
ERROR_REPLY_PREFIX = (
    "The workflow hit an error and was reset — please send your request again "
    "to start over.\n\nDetails: "
)

#: Where chat conversations checkpoint, one subdirectory per conversation. A
#: sibling of workflow mode's ``.checkpoints`` (owned by the Foundry host), so
#: the two modes can never read each other's state. Env-tunable for
#: deployments that mount persistent storage somewhere else.
CHAT_CHECKPOINT_ROOT = Path(
    os.environ.get(
        "CHAT_CHECKPOINT_STORAGE_PATH", os.path.join(os.getcwd(), ".checkpoints", "chat")
    )
)

#: A conversation id usable as a directory name verbatim. Anything else —
#: separators, traversal dots, an oversized id — is hashed instead (see
#: :func:`_safe_segment`); the bound also keeps the path well under
#: filesystem name limits.
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _safe_segment(conversation_id: str) -> str:
    """Map a caller-supplied conversation id to a safe directory name.

    The id ultimately comes from the client (``session.session_id``), and it
    becomes a path segment under :data:`CHAT_CHECKPOINT_ROOT` — so a crafted id
    must never escape that root or collide with ``.``/``..``. Ids that are
    already safe pass through unchanged (keeping directories recognizable);
    anything else maps to its SHA-256 hex digest, which is stable, so the
    same conversation still finds its own checkpoints.
    """
    if _SAFE_SEGMENT.fullmatch(conversation_id) and conversation_id not in {".", ".."}:
        return conversation_id
    return hashlib.sha256(conversation_id.encode()).hexdigest()


async def _prune_checkpoints(
    storage: FileCheckpointStorage, workflow_name: str, *, keep_latest: bool
) -> None:
    """Drop a conversation's stale checkpoints; only the newest ever matters.

    Mirrors the Foundry host's own post-turn pruning for workflow mode: each
    turn writes fresh checkpoints, and only the latest is needed to resume.
    A finished conversation keeps nothing (``keep_latest=False``) — its run
    is over, so there is no state a restart should revive. Pruning is
    hygiene, not correctness: a failure here is logged, never allowed to
    destroy the turn's already-computed reply.
    """
    try:
        latest = await storage.get_latest(workflow_name=workflow_name) if keep_latest else None
        for checkpoint in await storage.list_checkpoints(workflow_name=workflow_name):
            if latest is None or checkpoint.checkpoint_id != latest.checkpoint_id:
                await storage.delete(checkpoint.checkpoint_id)
    except Exception:  # noqa: BLE001 - hygiene must not break the turn
        logger.warning("checkpoint pruning failed for %s", workflow_name, exc_info=True)


class _Conversation:
    """A single chat's live workflow run, its checkpoints, and its pending elicitation id."""

    def __init__(self, workflow: Workflow, storage: FileCheckpointStorage) -> None:
        self.workflow = workflow
        self.storage = storage
        self.pending_request_id: str | None = None


class WorkflowChatAgent(BaseAgent):
    """Drive a Policy Report workflow through multi-turn chat text.

    Args:
        workflow_factory: Builds a fresh workflow instance per conversation.
        name: Agent name surfaced by DevUI.
        description: Agent description surfaced by DevUI.
        checkpoint_root: Overrides :data:`CHAT_CHECKPOINT_ROOT` as the parent
            directory for per-conversation checkpoints (tests point this at a
            temp dir; production uses the default).
    """

    def __init__(
        self,
        workflow_factory: Callable[[], Workflow],
        *,
        name: str,
        description: str,
        checkpoint_root: str | Path | None = None,
    ) -> None:
        super().__init__(name=name, description=description)
        self._workflow_factory = workflow_factory
        self._checkpoint_root = Path(checkpoint_root) if checkpoint_root is not None else None
        self._conversations: dict[str, _Conversation] = {}

    def _checkpoint_storage_for(self, conversation_id: str) -> FileCheckpointStorage:
        """Per-conversation checkpoint storage, safe to build from a client-supplied id.

        The allowlist is the same one the workflow-mode shim installs
        (:data:`~foundry_agent.checkpoint_compat.WORKFLOW_CHECKPOINT_TYPE_NAMES`)
        — here it is simply passed at construction, because this storage is
        our own; no monkeypatching is involved. The root is resolved at call
        time so a test can repoint :data:`CHAT_CHECKPOINT_ROOT` before any
        conversation starts.
        """
        root = self._checkpoint_root if self._checkpoint_root is not None else CHAT_CHECKPOINT_ROOT
        return FileCheckpointStorage(
            root / _safe_segment(conversation_id),
            allowed_checkpoint_types=list(WORKFLOW_CHECKPOINT_TYPE_NAMES),
        )

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
        user_text = _extract_text(messages)

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

        On any failure the conversation is dropped and the error is returned as
        visible assistant text so the user's next message restarts the workflow
        cleanly instead of resuming a broken run (and never sees an empty bubble).
        """
        conversation = self._conversations.get(conversation_id)
        try:
            if conversation is None:
                conversation = _Conversation(
                    self._workflow_factory(), self._checkpoint_storage_for(conversation_id)
                )
                self._conversations[conversation_id] = conversation
                result = await conversation.workflow.run(
                    user_text, checkpoint_storage=conversation.storage
                )
            else:
                result = await conversation.workflow.run(
                    responses={conversation.pending_request_id: user_text},
                    checkpoint_storage=conversation.storage,
                )
        except Exception as exc:  # noqa: BLE001 - surface as chat text, not empty bubble
            self._conversations.pop(conversation_id, None)
            return f"{ERROR_REPLY_PREFIX}{exc}"

        pending = result.get_request_info_events()
        if pending:
            conversation.pending_request_id = pending[0].request_id
            await _prune_checkpoints(
                conversation.storage, conversation.workflow.name, keep_latest=True
            )
            return pending[0].data.prompt

        self._conversations.pop(conversation_id, None)
        await _prune_checkpoints(conversation.storage, conversation.workflow.name, keep_latest=False)
        outputs = result.get_outputs()
        return outputs[0] if outputs else NO_OUTPUT_REPLY


def _extract_text(messages: object) -> str:
    """Flatten DevUI's message input (str, Message, or a sequence) to text.

    Attached files are flattened in alongside the typed text: a user who
    uploads a document mid-conversation is supplying source material for the
    workflow to read, and dropping it would silently lose their input.
    """
    if messages is None:
        return ""
    if isinstance(messages, str):
        return messages
    if isinstance(messages, Message):
        return "\n\n".join(
            part for part in (messages.text or "", _extract_attachments(messages)) if part
        )
    if isinstance(messages, Sequence):
        return "\n".join(_extract_text(item) for item in messages)
    return getattr(messages, "text", "") or ""


def _extract_attachments(message: Message) -> str:
    """Render any uploaded text-bearing files as labeled document blocks.

    DevUI delivers an upload as a content item carrying a ``data:`` URI (see
    ``Content.from_data``), not raw bytes and not text. Binary formats (PDF,
    images) carry no decodable text and are named but not inlined, so the
    reply says what arrived instead of failing mutely.
    """
    blocks: list[str] = []
    for content in getattr(message, "contents", None) or []:
        if getattr(content, "text", None):
            continue  # already covered by Message.text
        uri = getattr(content, "uri", None)
        if not uri:
            continue
        media_type = getattr(content, "media_type", "") or ""
        name = _attachment_name(content)
        decoded = _decode_data_uri(uri) if _is_texty(media_type, name) else None
        if decoded:
            blocks.append(f"### Uploaded document: {name}\n{decoded}")
        else:
            blocks.append(
                f"### Uploaded document: {name} "
                f"(type {media_type or 'unknown'} — text could not be read)"
            )
    return "\n\n".join(blocks)


def _decode_data_uri(uri: str) -> str:
    """Decode a ``data:`` URI's payload to text, or "" if that is not possible."""
    if not uri.startswith("data:") or "," not in uri:
        return ""
    header, _, payload = uri.partition(",")
    try:
        raw = base64.b64decode(payload) if header.endswith(";base64") else unquote(payload).encode()
    except (ValueError, binascii.Error):
        return ""
    return raw.decode("utf-8", errors="replace").strip()


def _attachment_name(content: object) -> str:
    """Best available filename for an attachment."""
    for attribute in ("filename", "name"):
        value = getattr(content, attribute, None)
        if value:
            return str(value)
    properties = getattr(content, "additional_properties", None) or {}
    return str(properties.get("filename") or properties.get("name") or "attachment")


def _is_texty(media_type: str, name: str) -> bool:
    """Whether the payload is plain enough to inline as text."""
    if media_type.startswith("text/"):
        return True
    if media_type in {"application/json", "application/x-yaml", "application/yaml"}:
        return True
    return name.lower().endswith(
        (".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".csv", ".rst")
    )


def _assistant_response(text: str) -> AgentResponse:
    return AgentResponse(messages=[Message("assistant", [Content.from_text(text)])])


def _finalize_updates(updates: Sequence[AgentResponseUpdate]) -> AgentResponse:
    text = "".join(
        content.text
        for update in updates
        for content in (update.contents or [])
        if getattr(content, "text", None)
    )
    return _assistant_response(text)
