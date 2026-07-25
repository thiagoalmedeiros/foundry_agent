"""The document-authoring interview: discovery, then a per-group conversation.

Every chat client is a stub — the tests drive the real workflow graph (the
per-group walk and its HITL pauses) without live model calls. There is no
gap-analysis stage: discovery hands the groups straight to elicitation, which
clarifies them one at a time before validation runs once.
"""

from foundry_agent.agents import (
    create_authoring_agent,
    create_elicitation_agent,
    create_validation_agent,
)
from foundry_agent.models import CaptureStatus, CapturedValue, ConversationTurn
from foundry_agent.workflow import (
    MATERIAL_HEADING,
    _is_source_material,
    build_report_workflow,
)
from tests.conftest import (
    COMPLETE_VALIDATION,
    GROUPS,
    INCOMPLETE_VALIDATION,
    INPUT_FILE,
    STUB_DOCUMENT,
)

# Per-group turns for the two-group stub (FG1: PA1, PA3 · FG2: PA7, PA11). An
# "open" turn holds the floor; a "close" turn marks the current group covered.
_FG1_OPEN = ConversationTurn(
    message="Anchors what this record is and how it is classified. What should we call it?",
    conversation_complete=False,
)
_FG1_CLOSE = ConversationTurn(
    message="Got the identity — thanks.",
    conversation_complete=True,
    captured=[
        CapturedValue(attribute_id="PA1", value="Sample Record Title"),
        CapturedValue(attribute_id="PA3", value="Security"),
    ],
)
_FG2_OPEN = ConversationTurn(
    message="Now the core of the record: why it exists and the situation demanding it.",
    conversation_complete=False,
)
_FG2_CLOSE = ConversationTurn(
    message="That covers purpose and context.",
    conversation_complete=True,
    captured=[
        CapturedValue(attribute_id="PA7", value="Purpose text"),
        CapturedValue(attribute_id="PA11", value="Context text"),
    ],
)
#: Walk both groups with a pause in each: open FG1, reply, open FG2, reply.
_WALK_BOTH = (_FG1_OPEN, _FG1_CLOSE, _FG2_OPEN, _FG2_CLOSE)


def _workflow(
    make_stub_client,
    make_elicitation_client,
    *,
    validation_result=COMPLETE_VALIDATION,
    clients=None,
    turns=(),
):
    made = {
        "elicit": make_elicitation_client(*turns),
        "validation": make_stub_client(validation_result),
    }
    if clients is not None:
        clients.update(made)
    return build_report_workflow(
        elicitation_agent=create_elicitation_agent(made["elicit"]),
        validation_agent=create_validation_agent(made["validation"]),
        authoring_agent=create_authoring_agent(make_stub_client(None, text=STUB_DOCUMENT)),
        field_groups=GROUPS,
    )


async def test_groups_are_elicited_one_at_a_time_before_validation(
    make_stub_client, make_elicitation_client
):
    """FG1 is clarified, then FG2 — and validation only runs after the LAST group."""
    clients: dict = {}
    workflow = _workflow(
        make_stub_client, make_elicitation_client, clients=clients, turns=_WALK_BOTH
    )

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    assert "Anchors what this record is" in first.data.prompt  # FG1 opens first
    assert first.data.run.current_group_index == 0
    assert clients["validation"].calls == 0  # no validation mid-groups

    result = await workflow.run(responses={first.request_id: "Sample Record Title"})
    second = result.get_request_info_events()[0]
    assert "core of the record" in second.data.prompt.lower()  # then FG2
    assert second.data.run.current_group_index == 1
    assert clients["validation"].calls == 0  # still no validation

    result = await workflow.run(responses={second.request_id: "because remote work grew"})
    assert clients["validation"].calls == 1  # validation only after the last group closed
    assert result.get_outputs()


async def test_each_group_prompt_is_scoped_to_that_group(
    make_stub_client, make_elicitation_client
):
    """A group's turn carries only its own fields and adequacy — not the whole document."""
    clients: dict = {}
    workflow = _workflow(
        make_stub_client, make_elicitation_client, clients=clients, turns=_WALK_BOTH
    )

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    await workflow.run(responses={first.request_id: "Sample Record Title"})

    fg1_prompt = clients["elicit"].prompts[0]  # opening FG1
    fg2_prompt = clients["elicit"].prompts[2]  # opening FG2
    # The group's own attribute line is scoped to that group. (The whole prompt
    # also carries the folded captured content, so assert the scoped line, not
    # bare ids — FG2's content legitimately mentions FG1's captured PA3.)
    assert "### FG1" in fg1_prompt
    assert "the user): PA1, PA3" in fg1_prompt
    assert "### FG2" in fg2_prompt
    assert "the user): PA7, PA11" in fg2_prompt


async def test_a_group_has_no_fixed_turn_cap(make_stub_client, make_elicitation_client):
    """A group that never completes keeps pausing — there is no MAX_ELICITATION_TURNS."""
    clients: dict = {}
    workflow = _workflow(
        make_stub_client, make_elicitation_client, clients=clients, turns=(_FG1_OPEN,)
    )

    result = await workflow.run("hi")
    request = result.get_request_info_events()[0]
    for _ in range(12):  # far more than the old cap of 4
        result = await workflow.run(responses={request.request_id: "still thinking"})
        events = result.get_request_info_events()
        assert events, "the conversation must keep pausing — no turn budget closes it"
        request = events[0]
    assert clients["validation"].calls == 0  # never forced to validation


async def test_validation_is_single_pass_banking_residual_gaps(
    make_stub_client, make_elicitation_client
):
    """Both groups auto-close, validation runs once, and a residual gap goes to the appendix."""
    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        validation_result=INCOMPLETE_VALIDATION,
        clients=clients,
        turns=(_FG1_CLOSE, _FG2_CLOSE),  # each group complete on open
    )

    result = await workflow.run("hi")

    assert result.get_request_info_events() == []  # nothing to ask
    assert clients["validation"].calls == 1  # single pass, no reopen
    assert "Unresolved required attributes: PA3" in result.get_outputs()[0]


async def test_captured_values_from_every_group_reach_validation(
    make_stub_client, make_elicitation_client
):
    """Each group folds its captured values into the content the next group and validation read."""
    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        clients=clients,
        turns=(_FG1_CLOSE, _FG2_CLOSE),
    )

    await workflow.run("hi")

    validation_prompt = clients["validation"].prompts[-1]
    assert "PA1 — Sample Record Title" in validation_prompt
    assert "PA7 — Purpose text" in validation_prompt


async def test_the_session_rides_through_a_pause(make_stub_client, make_elicitation_client):
    """A resume rebuilds the executor from the payload, so the session must ride the pause."""
    workflow = _workflow(make_stub_client, make_elicitation_client, turns=_WALK_BOTH)

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]

    assert first.data.run.session_state is not None
    assert first.data.run.session_state["session_id"]


async def test_pasted_material_reaches_validation(make_stub_client, make_elicitation_client):
    """A spec pasted as a reply is folded into the content, so validation reads it."""
    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        clients=clients,
        turns=(_FG1_OPEN, _FG1_CLOSE, _FG2_CLOSE),
    )

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    pasted = INPUT_FILE.read_text(encoding="utf-8")
    await workflow.run(responses={first.request_id: pasted})

    validation_prompt = clients["validation"].prompts[-1]
    assert MATERIAL_HEADING in validation_prompt
    assert "Meridian Quarterly Intake Brief" in validation_prompt


async def test_unresolved_attributes_reach_the_appendix(
    make_stub_client, make_elicitation_client
):
    """A point the user could not settle is recorded in the appendix, not dropped."""
    unresolved_close = ConversationTurn(
        message="We can come back to that one later.",
        conversation_complete=True,
        captured=[
            CapturedValue(attribute_id="PA3", value="unknown", status=CaptureStatus.UNRESOLVED)
        ],
    )
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        turns=(_FG1_OPEN, unresolved_close, _FG2_CLOSE),
    )

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    result = await workflow.run(responses={first.request_id: "no idea about that one"})

    document = result.get_outputs()[0]
    assert "Unresolved required attributes: PA3" in document


def test_a_long_structured_answer_is_not_mistaken_for_a_pasted_document():
    """Answers to a group's turn run long — that must not relabel them as a paste."""
    answer = "\n".join(
        [
            "- Do nothing - keep manual reconciliation, costs ~$78k/yr and carries the "
            "renewal risk.",
            "- Option 1 - add checksum retry plus a dead letter queue and alerting in the "
            "ingestion service.",
            "- Option 2 - rebuild ingestion as a streaming pipeline. Much larger effort "
            "and blocked by the firmware constraint this year.",
            "- Preferred - Option 1, because it fits the nightly batch window and needs no "
            "firmware change.",
        ]
    )
    assert len(answer) > 400  # tripped the old 400-char bound
    assert not _is_source_material(answer)


def test_a_genuinely_pasted_document_is_still_detected():
    """Raising the bar must not stop real source material being folded in."""
    assert _is_source_material(INPUT_FILE.read_text(encoding="utf-8"))
