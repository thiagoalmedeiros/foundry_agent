"""The global Policy Report interview: one pipeline pass, agent-paced throughout.

Discovery reads the ``policy-report-format`` skill's field groups (FG1-FG8)
once. The whole document then flows through one pipeline::

    discovery -> analysis -> elicitation -> validation -+-> elicitation (reopen)
                                  ^                      |
                                  +----------------------+
                                                          `-> assembler

Analysis judges every group's attributes in ONE pass — not one call per group.
Elicitation runs the whole document to closure as a *single, agent-paced,
multi-turn conversation*: the agent, guided by the elicitation skill's default
cadence (EL4), decides how many related open fields to raise per turn — never
one field at a time, never the entire remaining set at once. Validation runs
the loaded skill's OWN deterministic script (via the domain-neutral
``run_skill_validation`` tool bound in :mod:`~foundry_agent.skill_validation`)
plus its own adequacy judgment on top, then either reopens the same
conversation or advances to the assembler.

Two things make this pipeline safe to run. The conversation is bounded twice —
``MAX_ELICITATION_TURNS`` caps the exchange, and ``MAX_VALIDATION_ROUNDS`` caps
how often validation may reopen it — so a document the user cannot complete
lands in the appendix instead of looping forever. And the gap report is never
filtered against any group's declared id list: an attribute no group claims is
still elicited, and the mismatch is logged rather than acted on (see
:func:`_reclaim_unclaimed`) — an earlier per-group design lost attributes
exactly that way when two agent-produced id lists disagreed.

This is the MAF workflow-build (graph API) sibling: the workflow itself
carries no domain-specific rules — the field groups, the elicitation cadence,
and the validation script are all skill content, read at runtime, so swapping
the loaded skill re-targets the whole interview with no code change. A
sequential-orchestration sibling with deterministic discovery and code-based
validation is planned separately.
"""

import logging
import os
from dataclasses import dataclass, field, replace

from agent_framework import (
    Agent,
    AgentSession,
    Executor,
    Message,
    Workflow,
    WorkflowBuilder,
    WorkflowContext,
    handler,
    response_handler,
)

from foundry_agent.agents import (
    FORMAT_SKILL_DIR,
    analyze_gaps,
    author_document,
    continue_elicitation_conversation,
    create_authoring_agent,
    create_chat_client,
    create_discovery_agent,
    create_elicitation_agent,
    create_gap_analysis_agent,
    create_validation_agent,
    discover_groups,
    open_elicitation_conversation,
    reopen_elicitation_conversation,
    validate_document,
)
from foundry_agent.models import (
    CapturedValue,
    CaptureStatus,
    ConversationTurn,
    FieldGroup,
    FieldGroups,
    Finding,
    GapReport,
    ValidationResult,
)
from foundry_agent.skill_validation import SkillValidator, bind_skill_validation_tool, load_skill_validator
from foundry_agent.usage import RunUsage

logger = logging.getLogger(__name__)

#: How many user turns the whole-document conversation may take before the
#: flow moves on regardless. Agent-paced batching (several related fields per
#: turn) needs far fewer turns than the old one-field-per-turn design, but the
#: budget still has to cover every discovered group's attributes plus room for
#: follow-ups — 30 comfortably covers a ~32-attribute document at 3-6 fields a
#: turn. Bounds the elicitation skill's EL6 follow-up budget too: a document
#: the user cannot complete is recorded unresolved rather than asked forever.
MAX_ELICITATION_TURNS = 30

#: How many times validation may send the document back for more
#: clarification. Each round costs one validation agent call (which itself
#: makes a tool-call round-trip to run the skill's script) plus a fresh
#: elicitation exchange, so this bounds the elicitation <-> validation cycle.
MAX_VALIDATION_ROUNDS = 3

#: A reply this large is a pasted document, not just an answer to the question
#: asked. Either bound is enough — a spec runs to thousands of characters and
#: dozens of lines.
#:
#: These are deliberately well clear of a long *answer*. An earlier 400/4 pair
#: misread a four-bullet list of alternatives (403 chars) as a pasted document
#: and filed a direct answer under "Additional material provided". A single
#: field's answer can still run to a few hundred characters over several lines
#: (e.g. a gap-analysis table or a list of alternatives), so the bar has to sit
#: above the longest plausible answer, not above the longest plausible sentence.
#: Missing a small paste costs less than mislabeling an answer: the agent still
#: reads it either way, it just is not also appended to the content for later
#: groups.
SOURCE_MATERIAL_CHARS = 1000
SOURCE_MATERIAL_LINES = 10

#: Heading under which pasted material is folded into the merged content.
MATERIAL_HEADING = "## Additional material provided"

#: Hard cap on any single user input (initial message or one reply). A real
#: Policy Report document is ~12 KB (the sample input is 11.5 KB); this leaves ample
#: headroom while bounding a cost-DoS — an oversized paste would otherwise be
#: folded into ``run.content`` and re-sent on every later model call. Oversized
#: input is truncated (with a visible marker) rather than rejected, so the
#: interview keeps flowing. Env-tunable for deployments with larger source docs.
MAX_USER_INPUT_CHARS = int(os.environ.get("MAX_USER_INPUT_CHARS", "50000"))


@dataclass
class Run:
    """The whole interview's state, carried through every stage and every pause.

    ``groups`` holds plain dicts rather than :class:`FieldGroup` instances
    because this rides in a request payload: DevUI resumes from a checkpoint,
    and what is embedded here is the only state guaranteed to come back.
    """

    content: str
    groups: list[dict] = field(default_factory=list)
    session_state: dict | None = None
    #: The gap-analysis report, computed once near the start of the run and
    #: carried through every elicitation pause the same way ``session_state``
    #: is: it is what lets a reply at any later turn recompute which fields
    #: are still open, without re-running analysis. Cleared once validation
    #: banks the run for assembly.
    report: dict | None = None
    validation_rounds: int = 1
    unresolved_ids: list[str] = field(default_factory=list)
    advisory: list[dict] = field(default_factory=list)

    def group_list(self) -> list[FieldGroup]:
        """Every discovered field group, in declared order."""
        return [FieldGroup.model_validate(g) for g in self.groups]


@dataclass
class Analyzed:
    """Analysis output: the whole document's gap report — on to Elicitation, or straight to Validation."""

    run: Run
    report: GapReport

    def needs_user_input(self) -> bool:
        """Whether anything needs confirming or asking before validation."""
        return self.report.needs_user_input()


@dataclass
class Elicited:
    """The conversation reached closure — hand it to Validation."""

    run: Run


@dataclass
class Reclarify:
    """Validation judged the document inadequate — reopen the same conversation."""

    run: Run
    result: ValidationResult


@dataclass
class Assemble:
    """Validation is satisfied, or the round budget is spent — write the document."""

    run: Run


@dataclass
class ConversationPause:
    """One user-facing pause inside the whole-document conversation."""

    prompt: str
    run: Run
    turns: int = 1
    captured: list[dict] = field(default_factory=list)


class DiscoveryExecutor(Executor):
    """Stage 1 — enumerate the format skill's field groups, once.

    An LLM Discovery agent reads the skill (``load_skill`` /
    ``read_skill_resource``) and returns its groups, tolerating whatever
    markdown the skill author wrote — which is what lets swapping the skill
    re-target the interview. Tests inject their own :class:`FieldGroups` to
    stay offline.
    """

    def __init__(
        self, agent: Agent | None = None, groups: FieldGroups | None = None
    ) -> None:
        super().__init__(id="discovery")
        self._agent = agent
        self._groups = groups

    @handler
    async def start_from_messages(
        self, messages: list[Message], ctx: WorkflowContext[Run, str]
    ) -> None:
        """Agent-facing entry point: start the interview from chat messages.

        MAF's :class:`~agent_framework.WorkflowAgent` — the wrapper the
        Foundry host requires — refuses a workflow whose start executor
        cannot accept ``list[Message]``, so this handler is what makes the
        interview hostable. It flattens the turn's text and delegates to the
        same path the plain-string entry point uses.
        """
        text = "\n\n".join(message.text for message in messages if message.text)
        await self.start(text, ctx)

    @handler
    async def start(self, message: str, ctx: WorkflowContext[Run, str]) -> None:
        """Turn the skill's declared groups into the interview's running order."""
        groups = self._groups
        if groups is None:
            if self._agent is None:
                raise ValueError(
                    "DiscoveryExecutor needs a discovery agent or injected groups"
                )
            groups = await discover_groups(self._agent)
        logger.info(
            "discovered %d field groups: %s",
            len(groups.groups),
            ", ".join(group.group_id for group in groups.groups),
        )
        await ctx.send_message(
            Run(
                content=_cap_input(message, where="initial input"),
                groups=[group.model_dump() for group in groups.groups],
            )
        )


class GapAnalysisExecutor(Executor):
    """Stage 2 — judge every discovered group's attributes, in ONE pass."""

    def __init__(self, agent: Agent, usage: RunUsage | None = None) -> None:
        super().__init__(id="analysis")
        self._agent = agent
        self._usage = usage

    @handler
    async def analyze(self, message: Run, ctx: WorkflowContext[Analyzed, str]) -> None:
        """Produce a gap report covering every discovered group at once."""
        groups = message.group_list()
        report = await analyze_gaps(self._agent, message.content, groups, usage=self._usage)
        report = _reclaim_unclaimed(report, groups)
        logger.info(
            "%d groups: %d attributes judged, %d inferred, %d required and missing",
            len(groups),
            len(report.attributes),
            len(report.inferred_entries()),
            len(report.missing_required()),
        )
        await ctx.send_message(Analyzed(run=message, report=report))


class ElicitationExecutor(Executor):
    """Stage 3 — run the whole document to closure as ONE multi-turn conversation.

    The agent, not the workflow, decides how many related open fields to
    raise per turn (elicitation EL4). The :class:`AgentSession` travels
    through each pause in the payload, which is what lets the agent see its
    own earlier questions after a resume rebuilds this executor; the gap
    report travels the same way, which is what lets a reply at any later turn
    work out which fields are still open.
    """

    def __init__(self, agent: Agent, usage: RunUsage | None = None) -> None:
        super().__init__(id="elicitation")
        self._agent = agent
        self._usage = usage

    @handler
    async def open(self, message: Analyzed, ctx: WorkflowContext[Elicited, str]) -> None:
        """Open the conversation: the first group's framing, then an opening cluster."""
        session = self._agent.create_session()
        run = replace(message.run, report=message.report.model_dump())
        turn = await open_elicitation_conversation(
            self._agent, session, run.group_list(), message.report, run.content, usage=self._usage
        )
        await self._advance(run, session, turn, turns=1, ctx=ctx)

    @handler
    async def reopen(self, message: Reclarify, ctx: WorkflowContext[Elicited, str]) -> None:
        """Resume the same conversation on what validation judged inadequate."""
        session = _session(self._agent, message.run)
        report = _run_report(message.run)
        turn = await reopen_elicitation_conversation(
            self._agent, session, report, message.result, usage=self._usage
        )
        await self._advance(message.run, session, turn, turns=1, ctx=ctx)

    @response_handler
    async def reply(
        self, original_request: ConversationPause, response: str, ctx: WorkflowContext[Elicited, str]
    ) -> None:
        """Feed the reply into the conversation; pause again unless it closed."""
        answer = _cap_input(response.strip(), where="reply")
        run = original_request.run
        if _is_source_material(answer):
            if _already_folded(answer, run.content):
                # Re-folding a paste the content already carries would bill
                # validation and any later turn's analysis for a duplicate of
                # a document they have — the agent still reads the reply this
                # turn; only the second copy in the merged content is skipped.
                logger.info(
                    "%d chars of pasted material duplicate the content; not re-folding",
                    len(answer),
                )
            else:
                # A pasted spec answers attributes far beyond what was asked.
                # Folding it into the content means validation and the final
                # document both see it too.
                logger.info(
                    "%d chars of material pasted mid-conversation; folding it into the content",
                    len(answer),
                )
                run = replace(run, content=f"{run.content}\n\n{MATERIAL_HEADING}\n{answer}")
        session = _session(self._agent, run)
        report = _run_report(run)
        prior_captured = [
            CapturedValue.model_validate(value) for value in original_request.captured
        ]
        turn = await continue_elicitation_conversation(
            self._agent, session, report, prior_captured, answer, usage=self._usage
        )
        await self._advance(run, session, turn, turns=original_request.turns + 1, ctx=ctx)

    async def _advance(
        self,
        run: Run,
        session: AgentSession,
        turn: ConversationTurn,
        turns: int,
        ctx: WorkflowContext[Elicited, str],
    ) -> None:
        """Close the conversation, or pause for the next reply in the same conversation."""
        if turn.conversation_complete or turns >= MAX_ELICITATION_TURNS:
            if not turn.conversation_complete:
                logger.info(
                    "turn budget spent after %d turns; closing the conversation as it stands",
                    turns,
                )
            await ctx.send_message(Elicited(run=_capture(run, turn)))
            return
        await ctx.request_info(
            request_data=ConversationPause(
                prompt=turn.message,
                run=replace(run, session_state=session.to_dict()),
                turns=turns,
                captured=[value.model_dump() for value in turn.captured],
            ),
            response_type=str,
        )


class ValidationExecutor(Executor):
    """Stage 4 — the skill's own script for presence, the agent for adequacy.

    The workflow itself never encodes a validation RULE — it only imports the
    loaded skill's script (once, at build time, via
    :func:`~foundry_agent.skill_validation.load_skill_validator`) and binds it
    fresh to this run's discovered groups as a tool the agent calls.
    """

    def __init__(self, agent: Agent, validator: SkillValidator, usage: RunUsage | None = None) -> None:
        super().__init__(id="validation")
        self._agent = agent
        self._validator = validator
        self._usage = usage

    @handler
    async def check_elicited(
        self, message: Elicited, ctx: WorkflowContext[Reclarify | Assemble, str]
    ) -> None:
        """Validate a document that went through the conversation."""
        await self._validate(message.run, ctx)

    @handler
    async def check_analyzed(
        self, message: Analyzed, ctx: WorkflowContext[Reclarify | Assemble, str]
    ) -> None:
        """Validate a document analysis judged already complete — nothing to confirm or ask."""
        run = replace(message.run, report=message.report.model_dump())
        await self._validate(run, ctx)

    async def _validate(self, run: Run, ctx: WorkflowContext[Reclarify | Assemble, str]) -> None:
        """Reopen the conversation, or bank what it produced and move to assembly."""
        groups = run.group_list()
        tool = bind_skill_validation_tool(self._validator, run.groups)
        result = await validate_document(self._agent, run.content, groups, tool, usage=self._usage)
        if result.complete or run.validation_rounds >= MAX_VALIDATION_ROUNDS:
            if not result.complete:
                logger.info(
                    "still incomplete after %d round(s); recording %s as unresolved",
                    run.validation_rounds,
                    ", ".join(result.missing_attribute_ids) or "nothing",
                )
            following = replace(
                run,
                advisory=run.advisory + [f.model_dump() for f in result.advisory_findings],
                unresolved_ids=run.unresolved_ids
                + (result.missing_attribute_ids if not result.complete else []),
                session_state=None,
                report=None,
            )
            await ctx.send_message(Assemble(run=following))
            return
        logger.info(
            "inadequate (%s); reopening for round %d of %d",
            result.rationale,
            run.validation_rounds + 1,
            MAX_VALIDATION_ROUNDS,
        )
        # This round's advisory findings are deliberately dropped: the next
        # round re-judges the whole document from scratch, so banking them
        # here would leave the appendix reporting a defect *and* the later
        # note saying it was fixed. Only the pass that closes the run is
        # recorded.
        await ctx.send_message(
            Reclarify(run=replace(run, validation_rounds=run.validation_rounds + 1), result=result)
        )


class AssemblerExecutor(Executor):
    """Stage 5 — write the document and append what remains open."""

    def __init__(self, agent: Agent, usage: RunUsage | None = None) -> None:
        super().__init__(id="assembler")
        self._agent = agent
        self._usage = usage

    @handler
    async def assemble(self, message: Assemble, ctx: WorkflowContext[str, str]) -> None:
        """Author the Policy Report and yield it."""
        document = await author_document(self._agent, message.run.content, usage=self._usage)
        if self._usage is not None:
            logger.info("%s", self._usage.summary())
        appendix = build_appendix(
            message.run.unresolved_ids,
            [Finding.model_validate(item) for item in message.run.advisory],
        )
        await ctx.yield_output(f"{document}{appendix}" if appendix else document)


def _cap_input(text: str, *, where: str) -> str:
    """Bound one user input to :data:`MAX_USER_INPUT_CHARS`, truncating if larger.

    Truncation (not rejection) keeps the interview flowing; the visible marker
    tells the model — and any reader of the assembled document — that content
    was dropped, so a truncated paste is never silently mistaken for complete.
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


def _session(agent: Agent, run: Run) -> AgentSession:
    """Restore the conversation, or start one if the state is gone."""
    if run.session_state:
        return AgentSession.from_dict(run.session_state)
    return agent.create_session()


def _run_report(run: Run) -> GapReport:
    """Restore the run's gap report, computed once at analysis time.

    This is what lets a reply at any later turn work out which fields are
    still open without re-running analysis — the report travels through the
    run's pauses in ``run.report`` the same way the conversation travels in
    ``run.session_state``.

    Raises:
        ValueError: ``run`` is not mid-conversation (the report was never
            set, or was already cleared once validation banked the run).
    """
    if run.report is None:
        raise ValueError("report missing from run state — not mid-conversation")
    return GapReport.model_validate(run.report)


def _capture(run: Run, turn: ConversationTurn) -> Run:
    """Fold the finished conversation's captured values into the content being built."""
    recorded = [
        f"- {value.attribute_id} — {value.value}"
        for value in turn.captured
        if value.status is not CaptureStatus.SKIPPED
    ]
    unresolved = [
        value.attribute_id for value in turn.captured if value.status is CaptureStatus.UNRESOLVED
    ]
    content = run.content
    if recorded:
        content = f"{content}\n\n## Captured values\n" + "\n".join(recorded)
    return replace(run, content=content, unresolved_ids=run.unresolved_ids + unresolved)


def _reclaim_unclaimed(report: GapReport, groups: list[FieldGroup]) -> GapReport:
    """Keep gaps no discovered group claims, rather than dropping them.

    The gap report's ids and every group's own id list are both
    agent-produced, and this is where an earlier per-group design silently
    lost attributes when the two disagreed. Nothing is filtered out here —
    the log records the mismatch so it stays observable, and the attribute
    is still elicited.
    """
    claimed = {aid for group in groups for aid in group.attribute_ids}
    stray = [a.attribute_id for a in report.attributes if a.attribute_id not in claimed]
    if stray:
        logger.warning(
            "gap report named %s, which no discovered group claims; eliciting them "
            "anyway rather than dropping them",
            ", ".join(stray),
        )
    return report


def build_appendix(unresolved_ids: list[str], findings: list[Finding]) -> str:
    """Render the still-open attributes and advisory findings, deduplicated."""
    lines: list[str] = []
    if unresolved_ids:
        lines.append(
            "- Unresolved required attributes: " + ", ".join(dict.fromkeys(unresolved_ids))
        )
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        key = (finding.reference_id, finding.summary)
        if key not in seen:
            seen.add(key)
            lines.append(f"- {finding.reference_id}: {finding.summary}")
    return "\n\n## Advisory findings\n" + "\n".join(lines) if lines else ""


def _already_folded(answer: str, content: str) -> bool:
    """Whether this pasted material already appears in the content, whitespace aside.

    Only an exact (normalized) re-paste is dropped — the core state the trim
    must preserve (original input, every captured value) is never touched,
    and genuinely new material still folds in.
    """
    return _normalized(answer) in _normalized(content)


def _normalized(text: str) -> str:
    """Text with all whitespace runs collapsed, for duplicate detection."""
    return " ".join(text.split())


def _is_source_material(answer: str) -> bool:
    """Whether a reply is pasted material rather than an answer to the questions asked.

    Users answer a question about one cluster of fields by pasting a whole
    spec. That is not an answer to the fields just raised — it is new input
    for the whole document, and validation and the final document both have
    to see it.
    """
    return len(answer) >= SOURCE_MATERIAL_CHARS or answer.count("\n") >= SOURCE_MATERIAL_LINES


def build_policy_report_workflow(
    *,
    gap_agent: Agent,
    elicitation_agent: Agent,
    validation_agent: Agent,
    authoring_agent: Agent,
    validator: SkillValidator,
    discovery_agent: Agent | None = None,
    field_groups: FieldGroups | None = None,
    usage: RunUsage | None = None,
) -> Workflow:
    """Wire the global pipeline: one analysis pass, one conversation, validate, assemble.

    ``field_groups`` overrides what the discovery agent reads from the format
    skill — tests inject their stub groups here so no discovery call is made.
    ``discovery_agent`` enumerates the groups live when no ``field_groups`` are
    injected. ``validator`` is the skill's loaded validation script (see
    :func:`~foundry_agent.skill_validation.load_skill_validator`) — loaded
    once by the caller so a broken skill fails at build time, not mid-run.
    One :class:`RunUsage` is shared by every stage so the assembler can log
    the whole run's per-stage token summary; pass ``usage`` to observe it
    from outside (tests, DevUI wiring).
    """
    usage = usage if usage is not None else RunUsage()
    discovery = DiscoveryExecutor(agent=discovery_agent, groups=field_groups)
    analysis = GapAnalysisExecutor(gap_agent, usage=usage)
    elicitation = ElicitationExecutor(elicitation_agent, usage=usage)
    validation = ValidationExecutor(validation_agent, validator, usage=usage)
    assembler = AssemblerExecutor(authoring_agent, usage=usage)
    return (
        WorkflowBuilder(
            name="policy-report-agent",
            description=(
                "Global Policy Report interview: discovery reads the policy-report-format "
                "skill's groups, one gap-analysis pass judges every attribute across every "
                "group, a single agent-paced conversation runs elicitation to closure, "
                "then validation runs the skill's own script plus adequacy judgment — "
                "reopening the conversation on inadequacy or advancing to the assembler."
            ),
            start_executor=discovery,
            output_from=[assembler],
        )
        .add_edge(discovery, analysis)
        .add_edge(analysis, elicitation, condition=lambda m: m.needs_user_input())
        .add_edge(analysis, validation, condition=lambda m: not m.needs_user_input())
        .add_edge(elicitation, validation)
        # Validation closes the cycle two ways: back for more clarification, or
        # out to the assembler. There is no "advance to the next group" branch
        # any more — analysis runs once, for the whole document.
        .add_edge(validation, elicitation, condition=lambda m: isinstance(m, Reclarify))
        .add_edge(validation, assembler, condition=lambda m: isinstance(m, Assemble))
        .build()
    )


def create_policy_report_workflow() -> Workflow:
    """Build the interview with live Azure OpenAI agents (env-configured)."""
    client = create_chat_client()
    validator = load_skill_validator(FORMAT_SKILL_DIR)
    return build_policy_report_workflow(
        discovery_agent=create_discovery_agent(client),
        gap_agent=create_gap_analysis_agent(client),
        elicitation_agent=create_elicitation_agent(client),
        validation_agent=create_validation_agent(client),
        authoring_agent=create_authoring_agent(client),
        validator=validator,
    )
