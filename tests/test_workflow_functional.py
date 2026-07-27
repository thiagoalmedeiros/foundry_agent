"""Flow 2 — the functional (hybrid) interview, driven offline.

Every chat client is a stub, so these tests drive the real functional workflow
— its per-group walk, the human-in-the-loop pauses that ride the functional
API's top-of-run replay, and the deterministic validation gate + re-elicitation
loop — without live model calls. The gate runs the format skill's real
``validation/validate.py`` as a subprocess, so captured values here use the
script's sanctioned vocabulary (e.g. PA3 report status is ``Draft``, not a free
label): the deterministic gate enforces those rules literally, unlike Flow 1's
LLM validation.
"""

from foundry_agent.agents import (
    create_authoring_agent,
    create_elicitation_agent,
    run_validation_gate,
)
from foundry_agent.models import CapturedValue, ConversationTurn
from foundry_agent.workflow_functional import build_hybrid_workflow
from tests.conftest import GROUPS, STUB_DOCUMENT

# Per-group turns for the two-group stub (FG1: PA1, PA3 · FG2: PA7, PA11). An
# "open" turn holds the floor; a "close" turn marks the current group covered.
# PA3 carries a sanctioned report status ("Draft") so the deterministic gate
# passes; _FG1_CLOSE_INVALID holds a non-sanctioned one to make the gate fail.
_FG1_OPEN = ConversationTurn(
    message="Anchors what this record is and how it is classified. What should we call it?",
    conversation_complete=False,
)
_FG1_CLOSE = ConversationTurn(
    message="Got the identity — thanks.",
    conversation_complete=True,
    captured=[
        CapturedValue(attribute_id="PA1", value="Sample Record Title"),
        CapturedValue(attribute_id="PA3", value="Draft"),
    ],
)
_FG1_CLOSE_INVALID = ConversationTurn(
    message="Noted — though the status still needs pinning down.",
    conversation_complete=True,
    captured=[
        CapturedValue(attribute_id="PA1", value="Sample Record Title"),
        CapturedValue(attribute_id="PA3", value="unknown"),  # not a sanctioned status
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


def _hybrid(
    make_stub_client, make_elicitation_client, *, turns=(), clients=None, max_cycles=None
):
    """Build the functional workflow over stub clients with injected groups."""
    made = {
        "elicit": make_elicitation_client(*turns),
        "author": make_stub_client(None, text=STUB_DOCUMENT),
    }
    if clients is not None:
        clients.update(made)
    extra = {} if max_cycles is None else {"max_cycles": max_cycles}
    return build_hybrid_workflow(
        elicitation_agent=create_elicitation_agent(made["elicit"]),
        authoring_agent=create_authoring_agent(made["author"]),
        field_groups=GROUPS,
        **extra,
    )


async def test_hybrid_walks_each_group_with_a_pause_then_assembles(
    make_stub_client, make_elicitation_client
):
    """FG1 opens first, then FG2, a resume carries only the newest reply, gate passes."""
    clients: dict = {}
    workflow = _hybrid(
        make_stub_client, make_elicitation_client, turns=_WALK_BOTH, clients=clients
    )

    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    assert "Anchors what this record is" in first.data.prompt  # FG1 opens first
    assert first.data.group_index == 0

    result = await workflow.run(responses={first.request_id: "Sample Record Title"})
    second = result.get_request_info_events()[0]
    assert "core of the record" in second.data.prompt.lower()  # then FG2
    assert second.data.group_index == 1

    result = await workflow.run(responses={second.request_id: "because remote work grew"})
    assert result.get_request_info_events() == []  # both groups closed
    document = result.get_outputs()[0]
    assert document.startswith("# Report")  # the assembled document
    assert "Unresolved" not in document  # gate passed — no residual-gap appendix


async def test_hybrid_folds_captured_values_into_the_authored_content(
    make_stub_client, make_elicitation_client
):
    """Each group's captured values reach the content the assembler reads."""
    clients: dict = {}
    workflow = _hybrid(
        make_stub_client,
        make_elicitation_client,
        turns=(_FG1_CLOSE, _FG2_CLOSE),  # each group completes on open — no pauses
        clients=clients,
    )

    result = await workflow.run("hi")

    assert result.get_request_info_events() == []  # nothing to ask
    authored_content = clients["author"].prompts[-1]
    assert "PA1 — Sample Record Title" in authored_content
    assert "PA7 — Purpose text" in authored_content
    assert result.get_outputs()[0].startswith("# Report")


async def test_hybrid_reelicits_only_the_failing_group_until_the_gate_passes(
    make_stub_client, make_elicitation_client
):
    """A failed gate re-opens ONLY the group owning the missing id, then passes."""
    clients: dict = {}
    workflow = _hybrid(
        make_stub_client,
        make_elicitation_client,
        # FG1 closes with an invalid PA3, FG2 closes valid; the re-elicit of FG1
        # supplies a sanctioned PA3 so the second gate pass succeeds.
        turns=(_FG1_CLOSE_INVALID, _FG2_CLOSE, _FG1_CLOSE),
        clients=clients,
    )

    result = await workflow.run("hi")

    assert result.get_request_info_events() == []  # every turn closed on open
    # Exactly one re-elicitation, and it was FG1 (owns PA3) — not FG2.
    assert clients["elicit"].calls == 3  # FG1, FG2, then FG1 again
    assert "### FG1" in clients["elicit"].prompts[2]  # the re-elicited group is FG1
    assert "### FG2" not in clients["elicit"].prompts[2]
    document = result.get_outputs()[0]
    assert "Unresolved" not in document  # gate ultimately passed — no appendix
    assert "PA3 — Draft" in clients["author"].prompts[-1]  # the corrected value won
    assert "PA3 — unknown" not in clients["author"].prompts[-1]


async def test_hybrid_cycle_cap_terminates_with_a_residual_gap_appendix(
    make_stub_client, make_elicitation_client
):
    """A field the user never resolves stops at the cap and banks into the appendix."""
    clients: dict = {}
    workflow = _hybrid(
        make_stub_client,
        make_elicitation_client,
        # FG1's PA3 stays invalid on every (re-)elicitation, so the gate never passes.
        turns=(_FG1_CLOSE_INVALID, _FG2_CLOSE, _FG1_CLOSE_INVALID),
        clients=clients,
        max_cycles=2,
    )

    result = await workflow.run("hi")

    document = result.get_outputs()[0]
    assert "Unresolved required attributes: PA3" in document  # residual gap banked
    # 2 initial (FG1, FG2) + exactly max_cycles=2 re-elicitations of FG1 — not a runaway loop.
    assert clients["elicit"].calls == 4


async def test_validation_gate_flags_missing_and_invalid_required_attributes():
    """The deterministic gate (real validate.py, no LLM) reports the failing ids."""
    captured = {"PA1": "Title", "PA3": "unknown", "PA7": "Purpose"}  # PA3 invalid, PA11 absent
    failing = await run_validation_gate(captured, list(GROUPS.groups))
    assert "PA3" in failing  # non-sanctioned report status
    assert "PA11" in failing  # required but absent
    assert "PA1" not in failing
    assert "PA7" not in failing


async def test_validation_gate_passes_when_required_attributes_present_and_valid():
    """An empty failing list means the document clears the skill's deterministic rules."""
    captured = {"PA1": "Title", "PA3": "Draft", "PA7": "Purpose", "PA11": "Context"}
    failing = await run_validation_gate(captured, list(GROUPS.groups))
    assert failing == []


async def test_hybrid_accepts_a_message_input(make_stub_client, make_elicitation_client):
    """DevUI forwards the turn as a Message, not a str — the workflow must accept it."""
    from agent_framework import Message

    workflow = _hybrid(
        make_stub_client, make_elicitation_client, turns=(_FG1_CLOSE, _FG2_CLOSE)
    )
    # A bare Message is the exact shape the FunctionalWorkflowAgent adapter sends;
    # before the _as_text fix this raised "object of type 'Message' has no len()".
    result = await workflow.run(Message(role="user", contents=["hi"]))
    assert result.get_outputs()[0].startswith("# Report")


async def test_hybrid_accepts_a_list_of_messages(make_stub_client, make_elicitation_client):
    """A multi-message turn is flattened to text, not len()'d as a sequence of objects."""
    from agent_framework import Message

    workflow = _hybrid(
        make_stub_client, make_elicitation_client, turns=(_FG1_CLOSE, _FG2_CLOSE)
    )
    result = await workflow.run([Message(role="user", contents=["hello"])])
    assert result.get_outputs()[0].startswith("# Report")


async def test_hybrid_agent_adapter_runs_a_message_turn(
    make_stub_client, make_elicitation_client
):
    """The full DevUI path: .as_agent().run(Message) completes a turn end-to-end."""
    from agent_framework import Message

    workflow = _hybrid(
        make_stub_client, make_elicitation_client, turns=(_FG1_CLOSE, _FG2_CLOSE)
    )
    agent = workflow.as_agent(name="report-interview-functional")
    response = await agent.run(Message(role="user", contents=["hi"]))
    assert "# Report" in (response.text or "")


_FLOW1_ENV = {
    "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-test",
    "AZURE_OPENAI_API_KEY": "test-key",
}


def test_flow2_does_not_alter_flow1_or_the_hosted_path(monkeypatch):
    """Flow 2's existence must not change Flow 1's graph or move it off the hosted path."""
    for key, value in _FLOW1_ENV.items():
        monkeypatch.setenv(key, value)

    import foundry_agent.workflow_functional  # noqa: F401 — importing Flow 2 is the action under test
    from foundry_agent.workflow import create_report_workflow

    flow1 = create_report_workflow()
    assert flow1.name == "report-interview-agent"
    assert {"discovery", "elicitation", "validation", "assembler"} <= set(flow1.executors)

    # The hosted entrypoint source still wires Flow 1 only — Flow 2 is off the hosted path.
    from pathlib import Path

    import foundry_agent

    hosting_src = (Path(foundry_agent.__file__).resolve().parent / "hosting.py").read_text(
        encoding="utf-8"
    )
    assert "create_report_workflow" in hosting_src
    assert "create_hybrid_workflow" not in hosting_src
    assert "workflow_functional" not in hosting_src


def test_flow2_workflow_code_is_domain_free():
    """No attribute / characteristic / rule / group literals leak into Flow 2 code."""
    import inspect
    import re

    import foundry_agent.workflow_functional as flow2

    leaks = re.findall(r"\b(?:PA|PC|PR|FG)\d+\b", inspect.getsource(flow2))
    assert leaks == [], f"domain literals leaked into Flow 2 code: {leaks}"
