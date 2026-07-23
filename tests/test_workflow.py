"""The global Policy Report interview: one pipeline pass, agent-paced throughout.

Every chat client is a stub — the tests drive the real workflow graph
(including the HITL pauses and the validation cycle) without live model calls.
The skill's deterministic validation script is no longer wired through the
workflow: the validation agent runs it via its mounted skill provider
(``run_skill_script``), exercised directly in ``test_skill_script.py``.
"""

from foundry_agent.agents import (
    create_authoring_agent,
    create_elicitation_agent,
    create_gap_analysis_agent,
    create_validation_agent,
)
from foundry_agent.workflow import (
    MAX_ELICITATION_TURNS,
    MAX_VALIDATION_ROUNDS,
    MATERIAL_HEADING,
    _is_source_material,
    build_policy_report_workflow,
)
from tests.conftest import (
    CLOSING_TURN,
    COMPLETE_REPORT,
    COMPLETE_VALIDATION,
    FIXED_VALIDATION,
    FOLLOW_UP_TURN,
    GROUPS,
    INCOMPLETE_VALIDATION,
    INFERRED_REPORT,
    INPUT_FILE,
    MIXED_REPORT,
    OPEN_TURN,
    STALE_FINDING_VALIDATION,
    STUB_DOCUMENT,
    TWO_GAP_REPORT,
    UNRESOLVED_TURN,
)


def _workflow(
    make_stub_client,
    make_elicitation_client,
    *,
    gap_report,
    validation_result=COMPLETE_VALIDATION,
    clients=None,
    turns=(),
):
    made = {
        "gap": make_stub_client(gap_report),
        "elicit": make_elicitation_client(*turns),
        "validation": make_stub_client(validation_result),
    }
    if clients is not None:
        clients.update(made)
    return build_policy_report_workflow(
        gap_agent=create_gap_analysis_agent(made["gap"]),
        elicitation_agent=create_elicitation_agent(made["elicit"]),
        validation_agent=create_validation_agent(made["validation"]),
        authoring_agent=create_authoring_agent(make_stub_client(None, text=STUB_DOCUMENT)),
        field_groups=GROUPS,
    )


async def test_analysis_runs_once_for_the_whole_document(
    make_stub_client, make_elicitation_client
):
    """One gap-analysis pass covers every group — not one call per group."""
    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=TWO_GAP_REPORT,
        clients=clients,
    )

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]

    # The conversation opens with the first group's framing line.
    assert "Anchors what this policy is" in first.data.prompt
    assert "FG1" not in first.data.prompt
    assert clients["validation"].calls == 0
    assert clients["gap"].calls == 1  # analysis already ran, once, before this pause

    result = await workflow.run(responses={first.request_id: "Remote Work Security Policy"})

    assert result.get_outputs()
    assert clients["gap"].calls == 1  # still just the one analysis call
    assert clients["validation"].calls == 1


async def test_the_opening_turn_lists_every_open_field_across_every_group(
    make_stub_client, make_elicitation_client
):
    """The opening prompt spans the whole document — every group's open fields at once."""
    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=TWO_GAP_REPORT,
        clients=clients,
    )

    await workflow.run("hi")
    opening = clients["elicit"].prompts[0]

    assert "PA1" in opening
    assert "PA3" in opening
    assert "never all of them at once" in opening
    assert "### FG1 — Identification & Classification" in opening
    assert "PA1 and PA3 populated" in opening  # FG1's adequacy rules


async def test_the_conversation_holds_until_the_agent_closes_it(
    make_stub_client, make_elicitation_client
):
    """A reply does not end the conversation — only conversation_complete does."""
    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=TWO_GAP_REPORT,
        clients=clients,
        turns=(OPEN_TURN, FOLLOW_UP_TURN, CLOSING_TURN),
    )

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    result = await workflow.run(responses={first.request_id: "not sure"})
    follow_up = result.get_request_info_events()[0]

    assert follow_up.data.turns == 2
    assert "Is this mainly about protecting assets" in follow_up.data.prompt
    assert clients["validation"].calls == 0

    result = await workflow.run(responses={follow_up.request_id: "a problem, today"})

    # Closing the conversation finally releases it to validation.
    assert clients["validation"].calls == 1


async def test_the_conversation_carries_its_own_history_across_pauses(
    make_stub_client, make_elicitation_client
):
    """Each turn must see the earlier ones, or the agent re-asks what it just asked.

    A resume rebuilds the executor from the payload alone, so the session has
    to ride through the pause for the conversation to stay multi-turn.
    """
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=TWO_GAP_REPORT,
        turns=(OPEN_TURN, FOLLOW_UP_TURN, CLOSING_TURN),
    )

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    result = await workflow.run(responses={first.request_id: "not sure"})
    follow_up = result.get_request_info_events()[0]

    assert follow_up.data.run.session_state is not None
    assert follow_up.data.run.session_state["session_id"]


async def test_validation_reopens_the_conversation_when_inadequate(
    make_stub_client, make_elicitation_client
):
    """An inadequate document goes back to the same conversation."""
    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=TWO_GAP_REPORT,
        validation_result=INCOMPLETE_VALIDATION,
        clients=clients,
        turns=(OPEN_TURN, CLOSING_TURN, OPEN_TURN, CLOSING_TURN),
    )

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    result = await workflow.run(responses={first.request_id: "Remote Work Security Policy"})
    reopened = result.get_request_info_events()[0]

    assert reopened.data.run.validation_rounds == 2
    assert clients["validation"].calls == 1
    # The reopening prompt names what validation judged still missing.
    assert "PA3" in clients["elicit"].prompts[-1]
    assert "Policy type is still not one of" in clients["elicit"].prompts[-1]


async def test_a_document_that_cannot_be_completed_is_banked_not_looped(
    make_stub_client, make_elicitation_client
):
    """The round budget must release a document the user cannot finish."""
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=TWO_GAP_REPORT,
        validation_result=INCOMPLETE_VALIDATION,  # never satisfied
    )

    result = await workflow.run("hi")
    request = result.get_request_info_events()[0]
    for _ in range(MAX_VALIDATION_ROUNDS):
        result = await workflow.run(responses={request.request_id: "still no idea"})
        events = result.get_request_info_events()
        if not events:
            break
        request = events[0]

    # Validation never passed, but the interview still terminated, and what it
    # could not settle is reported rather than silently dropped.
    document = result.get_outputs()[0]
    assert "Unresolved required attributes: PA3" in document


async def test_a_stuck_conversation_ends_at_the_turn_budget(
    make_stub_client, make_elicitation_client
):
    """An agent that never sets conversation_complete must not hold the floor forever."""
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=TWO_GAP_REPORT,
        turns=(OPEN_TURN,),  # never closes
    )

    result = await workflow.run("hi")
    request = result.get_request_info_events()[0]
    for _ in range(MAX_ELICITATION_TURNS - 1):
        result = await workflow.run(responses={request.request_id: "hmm"})
        events = result.get_request_info_events()
        if not events:
            break
        request = events[0]

    # The turn budget forced the conversation closed and validation ran —
    # COMPLETE_VALIDATION (the default) means it terminates with a document.
    document = result.get_outputs()[0]
    assert document.startswith("# Policy Report")


async def test_inferred_values_reach_the_agent_for_confirmation_not_re_asking(
    make_stub_client, make_elicitation_client
):
    """What analysis read out of the input is confirmed, never asked from scratch."""
    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=INFERRED_REPORT,
        clients=clients,
    )

    await workflow.run("a long pasted brief covering everything")
    opening = clients["elicit"].prompts[0]

    # Both inferred values are in the SAME opening prompt — the agent picks its
    # own cluster from the full open-field list, not fed one at a time.
    assert "This policy establishes mandatory VPN and device rules" in opening
    assert "CONFIRM" in opening
    assert "PA11" in opening


async def test_a_document_with_nothing_to_ask_skips_the_conversation(
    make_stub_client, make_elicitation_client
):
    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=COMPLETE_REPORT,
        clients=clients,
    )

    result = await workflow.run("a fully specified draft document")

    # Nothing to confirm and nothing to ask: straight through to the document.
    assert result.get_request_info_events() == []
    assert clients["elicit"].calls == 0
    assert clients["validation"].calls == 1
    assert len(result.get_outputs()) == 1


async def test_partial_inference_still_opens_the_conversation(
    make_stub_client, make_elicitation_client
):
    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=MIXED_REPORT,
        clients=clients,
    )

    await workflow.run("a brief covering the identifier but not the classification")
    opening = clients["elicit"].prompts[0]

    assert "PA1 Policy ID — CONFIRM: POL-SEC-001" in opening
    assert "PA3 Policy Type" in opening


async def test_captured_values_are_folded_into_the_content_for_validation_to_read(
    make_stub_client, make_elicitation_client
):
    """Validation must see what the conversation captured, not just the original input."""
    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=TWO_GAP_REPORT,
        clients=clients,
    )

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    await workflow.run(responses={first.request_id: "Remote Work Security Policy"})

    validation_prompt = clients["validation"].prompts[-1]
    assert "PA1 — Remote Work Security Policy" in validation_prompt
    assert "PA3 — Security" in validation_prompt


async def test_pasted_material_is_folded_in_for_validation_to_read(
    make_stub_client, make_elicitation_client
):
    """A spec pasted mid-conversation must reach validation, not just the reply."""
    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=TWO_GAP_REPORT,
        clients=clients,
    )

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    pasted = INPUT_FILE.read_text(encoding="utf-8")
    await workflow.run(responses={first.request_id: pasted})

    validation_prompt = clients["validation"].prompts[-1]
    assert "## Additional material provided" in validation_prompt
    assert "Meridian Remote Work Security Assessment" in validation_prompt


async def test_re_pasted_material_is_folded_only_once(
    make_stub_client, make_elicitation_client
):
    """The same spec pasted twice must reach validation as one copy.

    The core state — captured values including the classification — must
    survive the trim untouched.
    """
    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=TWO_GAP_REPORT,
        clients=clients,
        turns=(OPEN_TURN, FOLLOW_UP_TURN, CLOSING_TURN),
    )
    pasted = INPUT_FILE.read_text(encoding="utf-8")

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    result = await workflow.run(responses={first.request_id: pasted})
    second = result.get_request_info_events()[0]
    await workflow.run(responses={second.request_id: pasted})  # same spec again

    final_validation = clients["validation"].prompts[-1]
    assert final_validation.count("## Additional material provided") == 1
    assert "PA1 — Remote Work Security Policy" in final_validation
    assert "PA3 — Security" in final_validation


async def test_genuinely_new_material_still_folds_alongside_the_first(
    make_stub_client, make_elicitation_client
):
    """Deduplication must drop only re-pastes, never distinct documents."""
    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=TWO_GAP_REPORT,
        clients=clients,
        turns=(OPEN_TURN, FOLLOW_UP_TURN, CLOSING_TURN),
    )
    first_doc = INPUT_FILE.read_text(encoding="utf-8")
    second_doc = "\n".join(f"- Requirement line {n} of the follow-up spec." for n in range(40))

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    result = await workflow.run(responses={first.request_id: first_doc})
    second = result.get_request_info_events()[0]
    await workflow.run(responses={second.request_id: second_doc})

    final_validation = clients["validation"].prompts[-1]
    assert final_validation.count("## Additional material provided") == 2
    assert "Requirement line 39" in final_validation


async def test_findings_from_a_superseded_round_do_not_reach_the_appendix(
    make_stub_client, make_elicitation_client
):
    """A defect the next round fixes must not be reported alongside its own fix.

    Regression: advisory findings were banked on every validation pass, so a
    round-1 complaint survived into the document even after round 2 passed —
    the appendix carried both the round-1 complaint and the later note saying
    it was fixed.
    """
    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=TWO_GAP_REPORT,
        validation_result=STALE_FINDING_VALIDATION,  # round 1: inadequate
        clients=clients,
        turns=(OPEN_TURN, CLOSING_TURN, OPEN_TURN, CLOSING_TURN),
    )
    clients["validation"].queue(FIXED_VALIDATION)  # round 2: passes, clean

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    result = await workflow.run(responses={first.request_id: "Remote Work Security Policy"})
    reopened = result.get_request_info_events()[0]
    assert reopened.data.run.validation_rounds == 2  # the reopen really happened
    result = await workflow.run(responses={reopened.request_id: "a horizon of 12 months"})

    document = result.get_outputs()[0]
    assert "PR10" not in document
    assert "## Advisory findings" not in document


async def test_a_long_structured_answer_is_not_mistaken_for_a_pasted_document(
    make_stub_client, make_elicitation_client
):
    """Answers to a batched turn run long — that must not relabel them as a paste."""
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

    clients: dict = {}
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=TWO_GAP_REPORT,
        clients=clients,
        turns=(OPEN_TURN, FOLLOW_UP_TURN, CLOSING_TURN),
    )
    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    result = await workflow.run(responses={first.request_id: answer})
    events = result.get_request_info_events()
    await workflow.run(responses={events[0].request_id: "closing it out"})

    # It was treated as an ordinary answer, never folded into the content as
    # source material.
    assert MATERIAL_HEADING not in clients["validation"].prompts[-1]


async def test_a_genuinely_pasted_document_is_still_detected(
    make_stub_client, make_elicitation_client
):
    """Raising the bar must not stop real source material being folded in."""
    assert _is_source_material(INPUT_FILE.read_text(encoding="utf-8"))


async def test_unresolved_attributes_reach_the_appendix(
    make_stub_client, make_elicitation_client
):
    workflow = _workflow(
        make_stub_client,
        make_elicitation_client,
        gap_report=TWO_GAP_REPORT,
        turns=(OPEN_TURN, UNRESOLVED_TURN),
    )

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    result = await workflow.run(responses={first.request_id: "no idea about that one"})

    document = result.get_outputs()[0]
    assert "## Advisory findings" in document
    assert "Unresolved required attributes: PA3" in document
