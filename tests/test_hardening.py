"""Input hardening: bounding a single user input against a cost-DoS.

A single user input (initial message or one reply) is bounded to
``MAX_USER_INPUT_CHARS`` so an oversized paste cannot be folded into
``run.content`` and re-sent on every later model call.

The predecessor's per-group "cross-group capture" regression (a value
settled in passing for a group other than the one in conversation) has no
equivalent here: the global pipeline runs one conversation over the whole
document, so there is no group boundary left for a value to cross — the
bug class this guarded against is now structurally impossible, not merely
untested.
"""

from foundry_agent.workflow import (
    MATERIAL_HEADING,
    MAX_USER_INPUT_CHARS,
    _cap_input,
)


def test_input_within_the_cap_is_unchanged():
    text = "a normal answer"

    assert _cap_input(text, where="test") == text


def test_oversized_input_is_truncated_with_a_marker():
    oversized = "x" * (MAX_USER_INPUT_CHARS + 5000)

    capped = _cap_input(oversized, where="test")

    assert len(capped) < len(oversized)
    assert capped.startswith("x" * 100)
    assert "[input truncated: 5000 characters omitted]" in capped


async def test_an_oversized_initial_paste_is_capped_before_it_enters_the_run(
    make_stub_client, make_elicitation_client
):
    """The cost-DoS vector: a huge initial paste must not enter run.content whole."""
    from tests.conftest import TWO_GAP_REPORT
    from tests.test_workflow import _workflow

    clients: dict = {}
    workflow = _workflow(
        make_stub_client, make_elicitation_client, gap_report=TWO_GAP_REPORT, clients=clients
    )
    huge = "PASTE " * (MAX_USER_INPUT_CHARS // 3)  # well over the cap

    await workflow.run(huge)

    analysis_prompt = clients["gap"].prompts[0]
    assert "[input truncated:" in analysis_prompt
    assert len(analysis_prompt) < len(huge)


async def test_an_oversized_mid_conversation_reply_is_capped_before_folding(
    make_stub_client, make_elicitation_client
):
    from tests.conftest import TWO_GAP_REPORT
    from tests.test_workflow import _workflow

    clients: dict = {}
    workflow = _workflow(
        make_stub_client, make_elicitation_client, gap_report=TWO_GAP_REPORT, clients=clients
    )
    result = await workflow.run("hi")
    first = result.get_request_info_events()[0]
    huge_reply = "SPEC " * (MAX_USER_INPUT_CHARS // 3)

    await workflow.run(responses={first.request_id: huge_reply})

    folded = clients["validation"].prompts[-1]
    assert MATERIAL_HEADING in folded  # it was treated as pasted material...
    assert "[input truncated:" in folded  # ...but capped first
