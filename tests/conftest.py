"""Shared test doubles and canned agent outputs — no live model calls here.

The stub values below are the vocabulary the suite is written in: each one
describes a distinct situation the flow must handle (nothing known, everything
inferable, a mix), so tests can name the situation instead of restating it.

The two-group ``GROUPS`` stands in for the format skill's FG1-FG8: two groups
is enough to prove the whole-document pipeline analyzes once, converses once,
validates, and terminates, while keeping the canned gap reports readable.
"""

from pathlib import Path
from typing import Any

import pytest
from agent_framework import ChatResponse, Message

from foundry_agent.models import (
    CapturedValue,
    CaptureStatus,
    ConversationTurn,
    FieldGroup,
    FieldGroups,
    ValidationResult,
)
#: The sample assessment a user realistically pastes or uploads mid-conversation.
INPUT_FILE = Path(__file__).resolve().parent / "fixtures" / "sample-input-file.md"

GROUPS = FieldGroups(
    groups=[
        FieldGroup(
            group_id="FG1",
            name="Identification & Classification",
            heading="### FG1 — Identification & Classification",
            framing="Anchors what this record is and how it is classified.",
            attribute_ids=["PA1", "PA3"],
            adequacy="PA1 and PA3 populated; PA3 is exactly one of "
            "the sanctioned categories.",
        ),
        FieldGroup(
            group_id="FG2",
            name="Purpose & Context",
            heading="### FG2 — Purpose & Context",
            framing="The core of the record: why it exists and the situation demanding it.",
            attribute_ids=["PA7", "PA11"],
            adequacy="PA7 follows the purpose statement pattern; "
            "PA11 is 2-5 paragraphs.",
        ),
    ]
)
GROUP_COUNT = len(GROUPS.groups)

#: The elicitation agent's opening turn: it still holds the floor.
OPEN_TURN = ConversationTurn(
    message="Anchors what this record is and how it is classified.\n\n"
    "**Record ID**\n\nSo we can refer to this later.\n\n---\n\nWhat should we call it?",
    conversation_complete=False,
)

#: A follow-up turn: the reply left something open.
FOLLOW_UP_TURN = ConversationTurn(
    message="**Record Type**\n\nThis drives what else the document needs.\n\n---\n\n"
    "Is this mainly about protecting assets, or about how work gets done?",
    conversation_complete=False,
    captured=[CapturedValue(attribute_id="PA1", value="Sample Record Title")],
)

#: The closing turn: every compulsory attribute is settled.
CLOSING_TURN = ConversationTurn(
    message="That covers what I needed here — thank you.",
    conversation_complete=True,
    captured=[
        CapturedValue(attribute_id="PA1", value="Sample Record Title"),
        CapturedValue(attribute_id="PA3", value="Security"),
    ],
)

#: The closing turn when the user could not supply one of the values.
UNRESOLVED_TURN = ConversationTurn(
    message="We can come back to that one later.",
    conversation_complete=True,
    captured=[
        CapturedValue(attribute_id="PA1", value="Sample Record Title"),
        CapturedValue(
            attribute_id="PA3", value="unknown", status=CaptureStatus.UNRESOLVED
        ),
    ],
)

COMPLETE_VALIDATION = ValidationResult(complete=True, rationale="Adequacy rules pass.")
INCOMPLETE_VALIDATION = ValidationResult(
    complete=False,
    missing_attribute_ids=["PA3"],
    rationale="Category is still not one of the sanctioned values.",
)

STUB_DOCUMENT = "# Report\n" + "\n".join(f"## PA{i} section" for i in range(1, 33))


class StubChatClient:
    """Chat client double: records each call and returns canned responses.

    Answers with the first queued response, then the second, and so on; the
    last one repeats for every further call. Use :meth:`queue` to make an agent
    answer differently on a later call — e.g. an elicitation agent that follows
    up once before closing the conversation.
    """

    def __init__(self, response: ChatResponse) -> None:
        self._responses = [response]
        self.messages: list[Any] = []
        self.options: dict[str, Any] | None = None
        self.calls = 0
        self.prompts: list[str] = []

    def queue(self, value: Any, text: str = "{}") -> None:
        """Append the response to answer with on the next unanswered call."""
        self._responses.append(
            ChatResponse(messages=Message(role="assistant", contents=[text]), value=value)
        )

    def get_response(self, messages, *, stream=False, options=None, **kwargs):
        async def _respond() -> ChatResponse:
            response = self._responses[min(self.calls, len(self._responses) - 1)]
            self.calls += 1
            self.messages = list(messages)
            self.options = dict(options or {})
            self.prompts.append(
                "\n".join(str(getattr(message, "text", "")) for message in messages)
            )
            return response

        return _respond()


@pytest.fixture
def make_stub_client():
    """Build a StubChatClient answering with the given structured value."""

    def _make(value: Any, text: str = "{}") -> StubChatClient:
        response = ChatResponse(messages=Message(role="assistant", contents=[text]), value=value)
        return StubChatClient(response)

    return _make


@pytest.fixture
def make_elicitation_client(make_stub_client):
    """Build the elicitation stub from the turns it should produce, in order.

    Every call to the elicitation agent is one conversational turn, so a test
    names the turns it wants and the last one repeats. The default is one
    open/close pair — the whole-document conversation needs exactly one full
    cycle when nothing requires a follow-up, unlike the old per-group flow's
    ``* GROUP_COUNT`` (there is only ever one conversation now).
    """

    def _make(*turns: ConversationTurn) -> StubChatClient:
        chosen = turns or (OPEN_TURN, CLOSING_TURN)
        client = make_stub_client(chosen[0])
        for turn in chosen[1:]:
            client.queue(turn)
        return client

    return _make
