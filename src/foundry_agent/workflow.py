"""The Policy Report interview: discovery, then a per-group conversation.

Discovery reads the ``policy-report-format`` skill's field groups (FG1-FG8)
once. The interview then flows through one linear pipeline::

    discovery -> elicitation -> validation -> assembler

There is no separate gap-analysis stage: discovery's groups are the only source
of truth, and elicitation judges the content itself, one group at a time. For
each group in order, the elicitation agent drives a natural multi-turn
conversation to clarify that group's points against its **Adequacy** rules —
inferring what the content already supports, confirming it, and asking for the
rest, in plain language (never attribute ids). The LLM decides when the group is
covered, then the flow jumps to the next group (a fresh conversation carrying
the captured content forward). There is no fixed turn cap: convergence rests on
the elicitation skill's per-point give-up rule. Only after the LAST group closes
does the document go to validation — the loaded skill's OWN deterministic script
(``validation/validate.py``, run through the provider's ``run_skill_script``
tool) plus an adequacy judgment, ONCE — and then the assembler.

Because there is a single list of groups (discovery's), there is no second list
to disagree with, so the attribute-loss failure mode of the earlier per-group
design does not arise: walking every group covers every attribute.

This is the MAF workflow-build (graph API) sibling: the workflow itself carries
no domain-specific rules — the field groups, the elicitation cadence, and the
validation script are all skill content, read at runtime, so swapping the
loaded skill re-targets the whole interview with no code change.
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
    VALIDATION_SCRIPT_NAME,
    author_document,
    continue_group_conversation,
    create_authoring_agent,
    create_chat_client,
    create_discovery_agent,
    create_elicitation_agent,
    create_validation_agent,
    discover_groups,
    open_group_conversation,
    validate_document,
)
from foundry_agent.models import (
    CapturedValue,
    CaptureStatus,
    ConversationTurn,
    FieldGroup,
    FieldGroups,
    Finding,
)
from foundry_agent.usage import RunUsage

logger = logging.getLogger(__name__)

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
    #: Which discovered group the interview is currently clarifying. Elicitation
    #: walks the groups in order; this index says where it is, carried through
    #: every pause the way ``session_state`` is so a resume knows the group.
    current_group_index: int = 0
    unresolved_ids: list[str] = field(default_factory=list)
    advisory: list[dict] = field(default_factory=list)

    def group_list(self) -> list[FieldGroup]:
        """Every discovered field group, in declared order."""
        return [FieldGroup.model_validate(g) for g in self.groups]


@dataclass
class Elicited:
    """Every group is covered — hand the document to Validation."""

    run: Run


@dataclass
class Assemble:
    """Validation is done (single pass) — write the document."""

    run: Run


@dataclass
class ConversationPause:
    """One user-facing pause inside the current group's conversation."""

    prompt: str
    run: Run
    captured: list[dict] = field(default_factory=list)


class DiscoveryCache:
    """A process-scoped memo of the discovery agent's field groups.

    Owned by the serving entrypoint and shared across every conversation in a
    process, so discovery's LLM call runs once per process rather than once per
    interview — the win is interview-start latency for every interview after the
    first. Keyless by design: the format skill's content is immutable for a
    process's lifetime (repo files baked into the image; a skill edit comes with
    a restart), so a new process already starts with an empty memo and there is
    no staleness path to invalidate. When skills later load from a remote source,
    invalidation belongs there — keyed on that source's own version, not a hash
    of local file bytes computed here.
    """

    def __init__(self) -> None:
        self._groups: FieldGroups | None = None

    def get(self) -> FieldGroups | None:
        """The memoized groups, or ``None`` when discovery has not run this process."""
        return self._groups

    def set(self, groups: FieldGroups) -> None:
        """Record the discovered groups so later interviews reuse them."""
        self._groups = groups


class DiscoveryExecutor(Executor):
    """Stage 1 — enumerate the format skill's field groups, once.

    An LLM Discovery agent reads the skill (``load_skill`` /
    ``read_skill_resource``) and returns its groups, tolerating whatever
    markdown the skill author wrote — which is what lets swapping the skill
    re-target the interview. Tests inject their own :class:`FieldGroups` to
    stay offline.

    A :class:`DiscoveryCache` shared across the process's interviews lets the
    live discovery call run once and every later interview reuse its result.
    Resolution order is injected ``groups`` (the offline override) → cache hit
    → live discovery, whose result then populates the cache.
    """

    def __init__(
        self,
        agent: Agent | None = None,
        groups: FieldGroups | None = None,
        cache: DiscoveryCache | None = None,
    ) -> None:
        super().__init__(id="discovery")
        self._agent = agent
        self._groups = groups
        self._cache = cache

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
        groups = await self._resolve_groups()
        await ctx.send_message(
            Run(
                content=_cap_input(message, where="initial input"),
                groups=[group.model_dump() for group in groups.groups],
            )
        )

    async def _resolve_groups(self) -> FieldGroups:
        """Resolve the interview's field groups: injected, memoized, or discovered.

        Injected ``groups`` (the tests' offline override) win. Otherwise a
        process-scoped cache hit reuses what discovery already produced this
        process; a miss runs the discovery agent once and stores its result so
        every later interview in the process skips the call.

        Raises:
            ValueError: No injected groups, no cache hit, and no discovery agent
                to fall back on.
        """
        if self._groups is not None:
            return self._groups
        if self._cache is not None:
            cached = self._cache.get()
            if cached is not None:
                logger.info(
                    "reusing %d cached field groups: %s",
                    len(cached.groups),
                    ", ".join(group.group_id for group in cached.groups),
                )
                return cached
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
        if self._cache is not None:
            self._cache.set(groups)
        return groups


class ElicitationExecutor(Executor):
    """Stage 2 — clarify each group in turn, one multi-turn conversation at a time.

    Elicitation walks the discovered groups in order. For the current group
    (:attr:`Run.current_group_index`) the agent drives a natural conversation
    to satisfy that group's Adequacy — inferring from the content, confirming,
    and asking for the rest. When the LLM marks the group complete, its captured
    values fold into the content and the flow opens the next group's
    conversation on a fresh session; when the last group closes, the document
    goes to Validation. There is no fixed turn cap.
    """

    def __init__(self, agent: Agent, usage: RunUsage | None = None) -> None:
        super().__init__(id="elicitation")
        self._agent = agent
        self._usage = usage

    @handler
    async def open(self, message: Run, ctx: WorkflowContext[Elicited, str]) -> None:
        """Open the first group's conversation (straight from discovery, no analysis)."""
        run = message
        groups = run.group_list()
        if not groups:
            await ctx.send_message(Elicited(run=run))
            return
        session = self._agent.create_session()
        turn = await open_group_conversation(
            self._agent, session, groups[0], run.content, usage=self._usage
        )
        await self._advance(run, session, turn, ctx=ctx)

    @response_handler
    async def reply(
        self, original_request: ConversationPause, response: str, ctx: WorkflowContext[Elicited, str]
    ) -> None:
        """Feed the reply into the current group; advance or pause."""
        answer = _cap_input(response.strip(), where="reply")
        run = original_request.run
        if _is_source_material(answer):
            if _already_folded(answer, run.content):
                # Re-folding a paste the content already carries would bill
                # validation and every later group for a duplicate of a document
                # they have — the agent still reads the reply this turn; only the
                # second copy in the merged content is skipped.
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
        group = run.group_list()[run.current_group_index]
        prior_captured = [
            CapturedValue.model_validate(value) for value in original_request.captured
        ]
        turn = await continue_group_conversation(
            self._agent, session, group, prior_captured, answer, usage=self._usage
        )
        await self._advance(run, session, turn, ctx=ctx)

    async def _advance(
        self,
        run: Run,
        session: AgentSession,
        turn: ConversationTurn,
        ctx: WorkflowContext[Elicited, str],
    ) -> None:
        """Pause for the next reply in this group, or advance to the next group / validation."""
        if not turn.conversation_complete:
            await ctx.request_info(
                request_data=ConversationPause(
                    prompt=turn.message,
                    run=replace(run, session_state=session.to_dict()),
                    captured=[value.model_dump() for value in turn.captured],
                ),
                response_type=str,
            )
            return
        # The current group is covered: fold its captured values into the content.
        run = _capture(run, turn)
        groups = run.group_list()
        next_index = run.current_group_index + 1
        if next_index >= len(groups):
            await ctx.send_message(Elicited(run=replace(run, session_state=None)))
            return
        # Jump to the next group on a fresh session, carrying the captured content.
        run = replace(run, current_group_index=next_index)
        next_session = self._agent.create_session()
        next_turn = await open_group_conversation(
            self._agent, next_session, groups[next_index], run.content, usage=self._usage
        )
        await self._advance(run, next_session, next_turn, ctx=ctx)


class ValidationExecutor(Executor):
    """Stage 4 — the skill's own script for presence, the agent for adequacy.

    The workflow itself never encodes a validation RULE — and holds no
    validation state either: the agent's mounted skill provider executes the
    loaded skill's own ``validation/validate.py`` through the native
    ``run_skill_script`` tool, with this run's groups arriving via the prompt.
    """

    def __init__(self, agent: Agent, usage: RunUsage | None = None) -> None:
        super().__init__(id="validation")
        self._agent = agent
        self._usage = usage

    @handler
    async def check_elicited(
        self, message: Elicited, ctx: WorkflowContext[Assemble, str]
    ) -> None:
        """Validate the document once every group has been clarified."""
        run = message.run
        groups = run.group_list()
        result = await validate_document(self._agent, run.content, groups, usage=self._usage)
        if not result.complete:
            logger.info(
                "still incomplete after the single validation pass; recording %s as unresolved",
                ", ".join(result.missing_attribute_ids) or "nothing",
            )
        following = replace(
            run,
            advisory=run.advisory + [f.model_dump() for f in result.advisory_findings],
            unresolved_ids=run.unresolved_ids
            + (result.missing_attribute_ids if not result.complete else []),
            session_state=None,
        )
        await ctx.send_message(Assemble(run=following))


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
    elicitation_agent: Agent,
    validation_agent: Agent,
    authoring_agent: Agent,
    discovery_agent: Agent | None = None,
    field_groups: FieldGroups | None = None,
    discovery_cache: DiscoveryCache | None = None,
    usage: RunUsage | None = None,
) -> Workflow:
    """Wire the pipeline: discovery, a per-group conversation, validate, assemble.

    ``field_groups`` overrides what the discovery agent reads from the format
    skill — tests inject their stub groups here so no discovery call is made.
    ``discovery_agent`` enumerates the groups live when no ``field_groups`` are
    injected. ``discovery_cache`` memoizes that live result across the process's
    interviews (see :class:`DiscoveryExecutor`) — omit it and every interview
    re-discovers. There is no gap-analysis stage: elicitation judges the content
    itself, one group at a time. The skill's deterministic validation script is
    not wired here: the validation agent executes it through its own mounted
    skill provider (``run_skill_script``). One :class:`RunUsage` is shared by
    every stage so the assembler can log the whole run's per-stage token summary;
    pass ``usage`` to observe it from outside (tests, DevUI wiring).
    """
    usage = usage if usage is not None else RunUsage()
    discovery = DiscoveryExecutor(
        agent=discovery_agent, groups=field_groups, cache=discovery_cache
    )
    elicitation = ElicitationExecutor(elicitation_agent, usage=usage)
    validation = ValidationExecutor(validation_agent, usage=usage)
    assembler = AssemblerExecutor(authoring_agent, usage=usage)
    return (
        WorkflowBuilder(
            name="policy-report-agent",
            description=(
                "Policy Report interview: discovery reads the policy-report-format "
                "skill's groups, elicitation clarifies each group in turn as a natural "
                "conversation, then a single validation pass runs the skill's own script "
                "plus adequacy judgment before the assembler writes the document."
            ),
            start_executor=discovery,
            output_from=[assembler],
        )
        # No gap-analysis stage: discovery hands the groups straight to
        # elicitation, which walks them one at a time. Validation runs once, only
        # after the last group closes (a residual gap goes to the appendix).
        .add_edge(discovery, elicitation)
        .add_edge(elicitation, validation)
        .add_edge(validation, assembler)
        .build()
    )


def create_policy_report_workflow(
    discovery_cache: DiscoveryCache | None = None,
) -> Workflow:
    """Build the interview with live Azure OpenAI agents (env-configured).

    ``discovery_cache`` is the process-scoped discovery memo. A serving
    entrypoint that builds the workflow once per conversation (the chat paths)
    passes one shared cache so the memo spans conversations; when omitted a
    fresh cache is created here, which still gives a single-build entrypoint
    (hosted workflow mode) a per-process memo.

    Raises:
        FileNotFoundError: The format skill ships no ``validation/validate.py``
            — checked here so a broken skill fails at build time, not when the
            Validation agent first tries to run it mid-interview.
    """
    script = FORMAT_SKILL_DIR / VALIDATION_SCRIPT_NAME
    if not script.is_file():
        raise FileNotFoundError(
            f"{FORMAT_SKILL_DIR.name} ships no {VALIDATION_SCRIPT_NAME} — every format "
            "skill mounted by this workflow must provide one (run via run_skill_script)"
        )
    client = create_chat_client()
    return build_policy_report_workflow(
        discovery_agent=create_discovery_agent(client),
        elicitation_agent=create_elicitation_agent(client),
        validation_agent=create_validation_agent(client),
        authoring_agent=create_authoring_agent(client),
        discovery_cache=discovery_cache if discovery_cache is not None else DiscoveryCache(),
    )
