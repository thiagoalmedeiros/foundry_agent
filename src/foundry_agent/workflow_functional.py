"""Flow 2 — the document-authoring interview as a MAF *functional* workflow.

This is the hybrid sibling to :mod:`foundry_agent.workflow` (Flow 1, the graph
``WorkflowBuilder`` pipeline). Same flow — discovery, a per-group elicitation
conversation, then the assembled document — but written with the functional API
(``@workflow`` / ``@step`` / ``get_run_context``), where the orchestration is a
plain ``async`` function using native Python control flow instead of executors
and edges. The distinguishing trait of Flow 2 is that its validation stage is a
**deterministic script gate** rather than an LLM agent: after the first walk of
every group, the skill's own ``validation/validate.py`` runs as a subprocess;
while it reports required attributes still missing, the interview re-opens
**only the groups that own those attributes** and re-runs the gate — halting
when the gate passes, or after a customizable cycle cap (``FLOW2_MAX_CYCLES``,
default 40), banking any residual gaps into a non-blocking appendix so a
stubborn field can never hang the interview.

Functional-API mechanics this module relies on (verified against
``agent-framework`` 1.11.0):

- ``request_info(...)`` suspends the workflow; the caller resumes with
  ``run(responses={request_id: value})`` and the workflow **re-executes from the
  top**. A resume carries only the *newest* response — the framework replaces the
  response map each run rather than accumulating it — so every earlier pause must
  already be resolved by the time replay reaches it.
- That makes the ``@step`` boundary load-bearing, not just an optimization: the
  ``request_info`` call lives **inside** the step that consumes its reply, so once
  a pause is answered the whole step is cached and replay short-circuits it before
  re-reaching the suspend point. Every agent call is wrapped the same way, so a
  resume never re-invokes the model for already-completed turns. Each request uses
  a **stable** ``request_id`` (``g<group>:t<turn>``) so a resume matches the pending
  request deterministically.
- The per-group conversation carries its :class:`AgentSession` forward as
  serialized state threaded through the (cached) step results, so the live turn
  after a resume still sees the prior turns' context without relying on any
  hidden mutable state.

Like Flow 1, the workflow itself holds no domain knowledge: field groups, the
elicitation cadence, and (once wired) the validation script are all skill
content read at runtime, so swapping the loaded skill re-targets the interview
with no change here.
"""

import logging
import os
from dataclasses import dataclass

from agent_framework import (
    Agent,
    AgentSession,
    FunctionalWorkflow,
    get_run_context,
    step,
    workflow,
)

from foundry_agent.agents import (
    author_document,
    continue_group_conversation,
    create_authoring_agent,
    create_chat_client,
    create_discovery_agent,
    create_elicitation_agent,
    discover_groups,
    open_group_conversation,
    run_validation_gate,
)
from foundry_agent.models import (
    CapturedValue,
    CaptureStatus,
    ConversationTurn,
    FieldGroup,
    FieldGroups,
)
from foundry_agent.usage import RunUsage
from foundry_agent.workflow import DiscoveryCache, MAX_USER_INPUT_CHARS, build_appendix

logger = logging.getLogger(__name__)

#: Env-tunable cap on the validation→elicitation loop (wired in the gate stage).
#: Named here so the constant travels with the flow it bounds; the loop that
#: reads it is added with the deterministic gate.
FLOW2_MAX_CYCLES = int(os.environ.get("FLOW2_MAX_CYCLES", "40"))

WORKFLOW_NAME = "report-interview-functional"
WORKFLOW_DESCRIPTION = (
    "Document-authoring interview (functional API): discovery reads the mounted "
    "format skill's groups, elicitation clarifies each group in turn as a natural "
    "conversation, then the assembler writes the document. The validation stage is "
    "a deterministic skill script gate rather than an LLM agent."
)


@dataclass(frozen=True)
class GroupPrompt:
    """The request payload for one human-in-the-loop pause inside a group.

    Surfaced to the caller as the request-info event's ``data``; the chat
    surface renders :attr:`prompt`, and :attr:`group_index` says which group is
    being clarified when the interview pauses.
    """

    prompt: str
    group_index: int


@dataclass(frozen=True)
class _TurnResult:
    """One elicitation turn plus the session state to carry into the next turn.

    The session is threaded as serialized state (not a live object) so it rides
    through the functional workflow's top-of-run replay inside the cached step
    result, exactly as Flow 1 threads it through its request payload.
    """

    turn: ConversationTurn
    session_state: dict


def _cap_input(text: str, *, where: str) -> str:
    """Bound one user input to :data:`MAX_USER_INPUT_CHARS`, truncating if larger.

    Shares Flow 1's bound so both interviews reject the same cost-DoS. Truncation
    (not rejection) keeps the interview flowing; the visible marker tells the
    model — and any reader of the assembled document — that content was dropped.

    Args:
        text: The raw user input (initial message or one reply).
        where: A short label for the log line identifying the input site.

    Returns:
        The input unchanged when within the cap, else truncated with a marker.
    """
    if len(text) <= MAX_USER_INPUT_CHARS:
        return text
    dropped = len(text) - MAX_USER_INPUT_CHARS
    logger.warning(
        "%s: input of %d chars exceeds the %d cap; truncating (%d dropped)",
        where,
        len(text),
        MAX_USER_INPUT_CHARS,
        dropped,
    )
    return f"{text[:MAX_USER_INPUT_CHARS]}\n\n[input truncated: {dropped} characters omitted]"


def _render_content(base_content: str, captured: dict[str, str]) -> str:
    """Render the interview content from the base input and the authoritative map.

    Content is rebuilt from ``captured`` each time a group is opened or the
    document is assembled — never appended incrementally — so a group re-elicited
    across gate cycles refreshes its values in place instead of stacking duplicate
    ``## Captured values`` blocks, and the assembler always reads the latest value
    for every attribute.

    Args:
        base_content: The original (capped) user input, unchanged for the run.
        captured: The ``{attribute_id: value}`` map settled so far.

    Returns:
        The base content with a single ``## Captured values`` block, or the base
        content unchanged when nothing has been captured yet.
    """
    if not captured:
        return base_content
    lines = "\n".join(f"- {attribute_id} — {value}" for attribute_id, value in captured.items())
    return f"{base_content}\n\n## Captured values\n{lines}"


def _closed_values(turn: ConversationTurn) -> dict[str, str]:
    """The ``{attribute_id: value}`` map for a group's substantively settled fields.

    Only CLOSED values count — an UNRESOLVED or SKIPPED attribute is not a
    populated field. This structured map is what the deterministic gate consumes
    (no LLM needed to parse the content back into attributes).
    """
    return {
        value.attribute_id: value.value
        for value in turn.captured
        if value.status is CaptureStatus.CLOSED
    }


def build_hybrid_workflow(
    *,
    elicitation_agent: Agent,
    authoring_agent: Agent,
    discovery_agent: Agent | None = None,
    field_groups: FieldGroups | None = None,
    discovery_cache: DiscoveryCache | None = None,
    usage: RunUsage | None = None,
    max_cycles: int = FLOW2_MAX_CYCLES,
) -> FunctionalWorkflow:
    """Build the functional interview: discovery, a per-group conversation, gate, assemble.

    Mirrors :func:`foundry_agent.workflow.build_report_workflow`'s injectable
    shape so tests stay offline — ``field_groups`` overrides live discovery, and
    the agents are passed in. There is no validation agent: Flow 2's validation
    stage is the deterministic :func:`~foundry_agent.agents.run_validation_gate`
    script gate wired into the re-elicitation loop below.

    Args:
        elicitation_agent: Drives each group's clarifying conversation.
        authoring_agent: Writes the final document from the gathered content.
        discovery_agent: Enumerates the skill's field groups live when no
            ``field_groups`` are injected.
        field_groups: Injected groups that skip live discovery (tests).
        discovery_cache: Process-scoped memo so live discovery runs once across
            the process's interviews; omit it and every interview re-discovers.
        usage: Shared per-stage token accounting; a fresh one is made if omitted.
        max_cycles: Hard cap on validation→re-elicitation cycles before the loop
            exits with a residual-gap appendix. Defaults to :data:`FLOW2_MAX_CYCLES`;
            tests pass a small value to prove the backstop terminates the loop.

    Returns:
        The decorated :class:`FunctionalWorkflow`, ready to ``run``.
    """
    usage = usage if usage is not None else RunUsage()

    @step(name="discover")
    async def discovery_step() -> FieldGroups:
        """Resolve the interview's field groups: injected, memoized, or discovered."""
        if field_groups is not None:
            return field_groups
        if discovery_cache is not None:
            cached = discovery_cache.get()
            if cached is not None:
                logger.info("reusing %d cached field groups", len(cached.groups))
                return cached
        if discovery_agent is None:
            raise ValueError(
                "build_hybrid_workflow needs a discovery agent or injected field_groups"
            )
        groups = await discover_groups(discovery_agent, usage=usage)
        logger.info(
            "discovered %d field groups: %s",
            len(groups.groups),
            ", ".join(group.group_id for group in groups.groups),
        )
        if discovery_cache is not None:
            discovery_cache.set(groups)
        return groups

    @step(name="open_turn")
    async def open_turn_step(group: FieldGroup, content: str) -> _TurnResult:
        """Open one group's conversation on a fresh session."""
        session = elicitation_agent.create_session()
        turn = await open_group_conversation(
            elicitation_agent, session, group, content, usage=usage
        )
        return _TurnResult(turn=turn, session_state=session.to_dict())

    @step(name="ask_continue")
    async def ask_continue_step(
        group: FieldGroup,
        session_state: dict,
        prior_captured: list[CapturedValue],
        prompt: str,
        request_id: str,
        group_index: int,
    ) -> _TurnResult:
        """Pause for the user's reply, then feed it into the group's conversation.

        The ``request_info`` pause lives here, inside the step, so that once the
        reply arrives the whole step is cached — a later resume short-circuits it
        instead of re-suspending on a pause the caller has already answered.
        """
        ctx = get_run_context()
        if ctx is None:
            raise RuntimeError("ask_continue_step must run inside a functional workflow")
        reply = await ctx.request_info(
            GroupPrompt(prompt=prompt, group_index=group_index),
            response_type=str,
            request_id=request_id,
        )
        capped = _cap_input(reply.strip(), where="reply")
        session = AgentSession.from_dict(session_state)
        turn = await continue_group_conversation(
            elicitation_agent, session, group, prior_captured, capped, usage=usage
        )
        return _TurnResult(turn=turn, session_state=session.to_dict())

    @step(name="assemble")
    async def assemble_step(content: str) -> str:
        """Author the final document from the gathered content."""
        document = await author_document(authoring_agent, content, usage=usage)
        logger.info("%s", usage.summary())
        return document

    async def run_group(
        group: FieldGroup, group_index: int, content: str, *, cycle: int
    ) -> dict[str, str]:
        """Clarify one group to completion, pausing for each reply it needs.

        ``cycle`` namespaces the request ids so a group re-opened in a later gate
        cycle never collides with its earlier pauses (``c<cycle>:g<group>:t<turn>``).

        Returns the structured ``{attribute_id: value}`` map of what this group
        settled — the orchestrator folds it into the authoritative capture map.
        """
        result = await open_turn_step(group, content)
        turn_index = 0
        while not result.turn.conversation_complete:
            result = await ask_continue_step(
                group,
                result.session_state,
                result.turn.captured,
                result.turn.message,
                f"c{cycle}:g{group_index}:t{turn_index}",
                group_index,
            )
            turn_index += 1
        return _closed_values(result.turn)

    def _groups_owning(failing: list[str], groups: list[FieldGroup]) -> list[tuple[int, FieldGroup]]:
        """The ``(index, group)`` pairs whose attributes include a failing id."""
        wanted = set(failing)
        return [
            (index, group)
            for index, group in enumerate(groups)
            if wanted & set(group.attribute_ids)
        ]

    @workflow(name=WORKFLOW_NAME, description=WORKFLOW_DESCRIPTION)
    async def hybrid_report_workflow(message: str) -> str:
        """Walk every group, gate on the skill's script, re-elicit until it passes.

        No ``ctx`` parameter is needed here: the human-in-the-loop pauses live
        inside :func:`ask_continue_step`, which reaches the active context through
        :func:`get_run_context`.
        """
        base_content = _cap_input(message, where="initial input")
        groups = (await discovery_step()).groups
        # The authoritative {attribute_id: value} map — the deterministic gate's
        # input, and what the content is rendered from (never parsed back out of it).
        captured: dict[str, str] = {}
        for group_index, group in enumerate(groups):
            content = _render_content(base_content, captured)
            captured.update(await run_group(group, group_index, content, cycle=0))

        # Deterministic gate loop: run the skill's script, and while it reports
        # required attributes still missing, re-open only the groups that own them.
        # The cycle cap is the harness's own termination guarantee — a field the
        # user never resolves banks into the appendix instead of looping forever.
        failing = await run_validation_gate(captured, groups)
        cycle = 0
        while failing and cycle < max_cycles:
            cycle += 1
            targets = _groups_owning(failing, groups)
            logger.info(
                "gate cycle %d/%d: re-eliciting %d group(s) for missing %s",
                cycle,
                max_cycles,
                len(targets),
                ", ".join(failing),
            )
            for group_index, group in targets:
                content = _render_content(base_content, captured)
                captured.update(await run_group(group, group_index, content, cycle=cycle))
            failing = await run_validation_gate(captured, groups)
        if failing:
            logger.info(
                "gate still failing after %d cycle(s); banking %s to the appendix",
                max_cycles,
                ", ".join(failing),
            )

        document = await assemble_step(_render_content(base_content, captured))
        appendix = build_appendix(failing, [])
        return f"{document}{appendix}" if appendix else document

    return hybrid_report_workflow


def create_hybrid_workflow(
    discovery_cache: DiscoveryCache | None = None,
) -> FunctionalWorkflow:
    """Build the functional interview with live Azure OpenAI agents (env-configured).

    The Flow 2 counterpart to :func:`foundry_agent.workflow.create_report_workflow`,
    minus the validation agent — Flow 2 validates with a deterministic script gate.
    ``discovery_cache`` is the process-scoped discovery memo; when omitted a fresh
    one is created here so a single-build entrypoint still gets a per-process memo.
    """
    client = create_chat_client()
    return build_hybrid_workflow(
        discovery_agent=create_discovery_agent(client),
        elicitation_agent=create_elicitation_agent(client),
        authoring_agent=create_authoring_agent(client),
        discovery_cache=discovery_cache if discovery_cache is not None else DiscoveryCache(),
    )
