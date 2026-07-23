"""Agent definitions over the policy-report-format skill's content.

The agents hold no domain knowledge in code. Everything about what a Policy Report
*is* — its field groups, attributes, characteristics, rules, statement patterns,
population and inference guidance, the canonical template — lives in the
``policy-report-format`` skill, and reaches each agent one of two ways:

- The **elicitation** agent keeps MAF progressive disclosure: a
  :class:`SkillsProvider` mounts the format skill plus the generic
  ``elicitation`` behavior skill, and the multi-turn session amortizes what
  it loads (measured 81% prompt-cache hit rate).
- The **stateless** agents — gap analysis, validation, authoring — get a
  per-agent-tailored reference pack read verbatim from the same skill files at
  construction time and inlined into the system prompt, where the prefix cache
  reuses it across calls. Their per-call tool-loop skill reads measured 62% of
  a run's full-rate tokens, which is why disclosure was retired for them — the
  evaluation and decision are recorded in
  ``kb/architecture-and-design/poc-progressive-disclosure-verdict.md``.
- The **validation** agent additionally carries one domain-neutral function
  tool (``run_skill_validation``, bound per run by
  :mod:`~foundry_agent.skill_validation`) that runs the loaded skill's OWN
  deterministic validation script — the workflow never encodes those rules
  itself.

Either way the content is repository skill files, not code: re-clustering a
field group or rewording population guidance changes this workflow's behaviour
with no change here.
"""

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from agent_framework import (
    Agent,
    AgentSession,
    ChatOptions,
    FileSkillsSource,
    SkillsProvider,
    SupportsChatGetResponse,
)
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv
from pydantic import BaseModel

from foundry_agent.models import (
    AttributeStatus,
    CapturedValue,
    ConversationTurn,
    FieldGroup,
    FieldGroups,
    GapReport,
    ValidationResult,
)
from foundry_agent.usage import RunUsage, log_usage
from foundry_agent.prompts import (
    AUTHORING_INSTRUCTIONS,
    AUTHORING_PACK,
    DISCOVERY_INSTRUCTIONS,
    ELICITATION_INSTRUCTIONS,
    ELICITATION_SKILL_DIR,
    ELICITATION_SKILL_NAME,
    FORMAT_SKILL_DIR,
    FORMAT_SKILL_NAME as FORMAT_SKILL_NAME,
    GAP_ANALYSIS_INSTRUCTIONS,
    GAP_ANALYSIS_PACK,
    REFERENCES_DIR as REFERENCES_DIR,
    VALIDATION_INSTRUCTIONS,
    VALIDATION_PACK,
    _all_groups_scope,
    _open_fields_clause,
    _skill_pack,
)

logger = logging.getLogger(__name__)


#: Prompt-cache routing keys are per STAGE, deliberately not per conversation:
#: Azure routes to cache nodes by key + prefix hash, and its guidance is a
#: stable mapping between each key and its shared prompt prefixes. What a
#: stage's requests share is that agent's instructions/tools prefix — across
#: conversations — while the hash itself tells conversations apart. Confirmed
#: supported on the v1 API surface MAF's client uses (Microsoft Learn
#: prompt-caching guide, updated 2026-07-17); Batch 4's measured
#: ``cached_tokens`` decides whether this earns its keep.
_CACHE_KEY_PREFIX = "policy-report-agent"


def _cache_key(stage: str) -> str:
    """The prompt-cache routing key for one stage's shared prompt prefix."""
    return f"{_CACHE_KEY_PREFIX}:{stage}"


def create_skills(paths: list[Path]) -> SkillsProvider:
    """Mount the policy skills an agent may load, via MAF progressive disclosure.

    The provider advertises each skill's name and description in the system
    prompt and offers ``load_skill`` / ``read_skill_resource`` tools for
    on-demand loading, so only the references an agent actually needs enter its
    context. Approvals are disabled — these skills ship in this repository.
    """
    return SkillsProvider(
        FileSkillsSource([str(path) for path in paths]),
        source_id="policy_skills",
        disable_load_skill_approval=True,
        disable_read_skill_resource_approval=True,
        disable_run_skill_script_approval=True,
    )


def create_chat_client() -> OpenAIChatClient:
    """Build the Azure OpenAI chat client from environment variables.

    Reads ``.env`` explicitly — the Agent Framework does not load it itself.
    Authenticates with ``AZURE_OPENAI_API_KEY`` when present, otherwise with
    Entra managed identity (``DefaultAzureCredential``) for the hosted path.

    The endpoint comes from ``AZURE_OPENAI_ENDPOINT`` (explicit, local/.env), or
    falls back to ``FOUNDRY_PROJECT_ENDPOINT`` — which the Foundry hosted
    platform injects into the container automatically, so a hosted deploy needs
    no endpoint set in ``azure.yaml`` at all. Explicit wins so a local override
    is always honoured.

    Raises:
        KeyError: No endpoint (neither ``AZURE_OPENAI_ENDPOINT`` nor
            ``FOUNDRY_PROJECT_ENDPOINT``) or the deployment name is unset.
    """
    load_dotenv()
    deployment = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME") or os.environ[
        "AZURE_OPENAI_DEPLOYMENT"
    ]
    # FOUNDRY_PROJECT_ENDPOINT is the platform-injected endpoint on the hosted
    # path (the reference warns against redeclaring it in azure.yaml's env). If
    # its URL form ever proves incompatible with azure_endpoint=, set
    # AZURE_OPENAI_ENDPOINT explicitly to override — it takes precedence here.
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT") or os.environ["FOUNDRY_PROJECT_ENDPOINT"]
    # api_version is deliberately NOT read from AZURE_OPENAI_API_VERSION: the
    # repo-wide value targets the legacy chat-completions surface and Azure
    # rejects it for this client ("API version not supported"); the framework's
    # default version is the one its API surface requires.
    #
    # Auth: an explicit AZURE_OPENAI_API_KEY (local dev / .env) takes it;
    # otherwise fall back to Entra managed identity via DefaultAzureCredential —
    # the Foundry hosted container is issued its own identity and no key, so the
    # production path authenticates without a secret in the environment.
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    if api_key:
        client = OpenAIChatClient(model=deployment, azure_endpoint=endpoint, api_key=api_key)
    else:
        from azure.identity import DefaultAzureCredential

        logger.info("no AZURE_OPENAI_API_KEY; authenticating with DefaultAzureCredential")
        client = OpenAIChatClient(
            model=deployment, azure_endpoint=endpoint, credential=DefaultAzureCredential()
        )
    # Transient-error resilience. The underlying openai SDK already retries
    # 429/5xx/connection errors with exponential backoff (default 2); a full
    # interview is ~58 model calls, so a single transient blip is likely over a
    # run and the default is thin. Raise it via the SDK's own retry config
    # (``with_options`` returns a reconfigured copy — no custom retry loop) and
    # keep it env-tunable. ``with_options`` preserves the framework's required
    # ``api_version`` default, which is why the client is built first.
    max_retries = int(os.environ.get("AZURE_OPENAI_MAX_RETRIES", "6"))
    request_timeout = float(os.environ.get("AZURE_OPENAI_TIMEOUT_SECONDS", "120"))
    client.client = client.client.with_options(
        max_retries=max_retries, timeout=request_timeout
    )
    # The framework's tool-invocation loop defaults to max_iterations=40 and an
    # unlimited max_function_calls per agent.run() call. Each skill resource read
    # returns a whole reference file with no caching, and each additional tool
    # round resends the growing conversation. The elicitation agent carries skill
    # tools and the validation agent carries the run_skill_validation tool (the
    # stateless gap-analysis/authoring agents inline their packs instead), but
    # these caps keep every agent's worst-case tool-loop cost per call bounded.
    client.function_invocation_configuration["max_iterations"] = 8
    client.function_invocation_configuration["max_function_calls"] = 12
    return client


def create_discovery_agent(
    client: SupportsChatGetResponse, skills: SkillsProvider | None = None
) -> Agent:
    """Create the Discovery agent: reads the format skill and lists its groups.

    Mounts only the format skill (not the behavior skill) via progressive
    disclosure, so the agent loads the Field Groups reference on demand
    (``load_skill`` / ``read_skill_resource``) and returns the groups as
    structured output. Replaces the deterministic parser as the active
    discovery mechanism — it tolerates whatever markdown the skill author
    wrote, which is what makes swapping the skill re-target the whole agent.
    """
    return Agent(
        client,
        DISCOVERY_INSTRUCTIONS,
        name="discovery",
        description="Reads the format skill and enumerates its field groups.",
        context_providers=[skills or create_skills([FORMAT_SKILL_DIR])],
    )


def create_gap_analysis_agent(client: SupportsChatGetResponse) -> Agent:
    """Create the Gap Analysis agent for a single global pass, reference pack inlined."""
    return Agent(
        client,
        f"{GAP_ANALYSIS_INSTRUCTIONS}{_skill_pack(GAP_ANALYSIS_PACK)}",
        name="gap-analysis",
        description="Maps candidate content against every field group's attributes in one pass.",
    )


def create_elicitation_agent(
    client: SupportsChatGetResponse, skills: SkillsProvider | None = None
) -> Agent:
    """Create the Elicitation agent for the whole-document, agent-paced conversation.

    Mounts the format skill plus the elicitation behavior skill via
    progressive disclosure, and is instructed to run one continuous
    conversation across every discovered group, pacing its own turn-sized
    field clusters per the elicitation skill's default cadence (EL4).
    """
    return Agent(
        client,
        ELICITATION_INSTRUCTIONS,
        name="elicitation",
        description="Runs the whole document's gaps to closure as one agent-paced conversation.",
        context_providers=[skills or create_skills([FORMAT_SKILL_DIR, ELICITATION_SKILL_DIR])],
    )


def create_validation_agent(client: SupportsChatGetResponse) -> Agent:
    """Create the Validation agent with its reference pack inlined.

    Carries no tool at construction time — the ``run_skill_validation`` tool
    depends on the run's own discovered groups (unknown until Discovery has
    run), so it is bound fresh per call and passed via
    :func:`validate_document`'s ``ChatOptions(tools=[...])`` instead.
    """
    return Agent(
        client,
        f"{VALIDATION_INSTRUCTIONS}{_skill_pack(VALIDATION_PACK)}",
        name="validation",
        description="Runs the skill's own validation script, then judges adequacy "
        "across the whole document.",
    )


def create_authoring_agent(client: SupportsChatGetResponse) -> Agent:
    """Create the Authoring agent with its reference pack inlined."""
    return Agent(
        client,
        f"{AUTHORING_INSTRUCTIONS}{_skill_pack(AUTHORING_PACK)}",
        name="authoring",
        description="Writes the final Policy Report per the canonical template.",
    )


_StructuredT = TypeVar("_StructuredT", bound=BaseModel)


def _structured(response: object, model: type[_StructuredT]) -> _StructuredT:
    """Return a structured-output response as ``model``.

    When ``response_format`` is set the framework usually populates
    ``response.value`` with a parsed model instance already; this validates the
    fallback case where it comes back as a dict (or anything else) instead.
    """
    value = response.value
    return value if isinstance(value, model) else model.model_validate(value)


async def discover_groups(agent: Agent, usage: RunUsage | None = None) -> FieldGroups:
    """Enumerate the format skill's field groups via the Discovery agent.

    Raises:
        pydantic.ValidationError: The response does not conform to `FieldGroups`
            (raised by the framework when parsing the structured output).
    """
    response = await agent.run(
        "List every field group the format skill declares, in declared order.",
        options=ChatOptions(
            response_format=FieldGroups, prompt_cache_key=_cache_key("discovery")
        ),
    )
    log_usage("discovery", None, response, usage)
    return _structured(response, FieldGroups)


async def analyze_gaps(
    agent: Agent,
    candidate_text: str,
    groups: list[FieldGroup],
    usage: RunUsage | None = None,
) -> GapReport:
    """Run gap analysis over candidate content in ONE pass across every group.

    Raises:
        pydantic.ValidationError: The response does not conform to `GapReport`
            (raised by the framework when parsing the structured output).
    """
    prompt = (
        f"{_all_groups_scope(groups)}\n\n"
        f"Candidate Policy Report content:\n---\n{candidate_text}"
    )
    response = await agent.run(
        prompt,
        options=ChatOptions(response_format=GapReport, prompt_cache_key=_cache_key("analysis")),
    )
    log_usage("analysis", None, response, usage)
    return _structured(response, GapReport)


def _ordered_targets(report: GapReport) -> list[AttributeStatus]:
    """The document's attributes that need a turn, in the report's own order.

    An attribute needs a turn when it is required-and-missing (a gap to ask
    for) or populated-with-an-inferred-value (a value to confirm). Anything
    else (optional and unpopulated) is silently skipped.

    Deliberately NOT reordered against any group's declared ``attribute_ids``:
    gap analysis is instructed to report attributes in the discovered groups'
    order already, and re-deriving order by looking each one up in a group's
    id list would silently drop any attribute no group claims — the exact
    loss :func:`~foundry_agent.workflow._reclaim_unclaimed` exists to prevent.
    """
    return [
        entry
        for entry in report.attributes
        if (entry.required and not entry.populated) or (entry.populated and entry.inferred_value)
    ]


async def open_elicitation_conversation(
    agent: Agent,
    session: AgentSession,
    groups: list[FieldGroup],
    report: GapReport,
    candidate_text: str,
    usage: RunUsage | None = None,
) -> ConversationTurn:
    """Start the whole-document conversation with the first group's framing.

    The WHOLE list of open fields across every group is handed to the agent
    in one prompt — it chooses its own turn-sized cluster from this list,
    guided by the elicitation skill's cadence, rather than the workflow
    walking a field queue.
    """
    targets = _ordered_targets(report)
    if not targets:
        return ConversationTurn(message="", conversation_complete=True, captured=[])
    opening_framing = groups[0].framing_line() if groups else ""
    prompt = (
        f"{_all_groups_scope(groups)}\n"
        "Framing line to open the conversation with verbatim (do not prefix it with any "
        f"label):\n{opening_framing}\n\n"
        f"{_open_fields_clause(targets)}\n\n"
        f"Candidate Policy Report content so far:\n---\n{candidate_text}\n---\n"
        "Produce the opening turn: the framing line, then a small, related cluster of "
        "fields chosen from the open fields above — never all of them at once."
    )
    return await _conversation_turn(agent, session, prompt, usage=usage)


async def continue_elicitation_conversation(
    agent: Agent,
    session: AgentSession,
    report: GapReport,
    prior_captured: list[CapturedValue],
    reply: str,
    usage: RunUsage | None = None,
) -> ConversationTurn:
    """Feed the user's reply into the conversation; the agent paces what comes next.

    ``prior_captured`` — what the conversation has settled so far — decides
    which fields are STILL open, computed here rather than left to the
    model's own memory: the agent's session carries the natural conversation,
    but "what remains" is always recomputed server-side.
    """
    targets = _ordered_targets(report)
    captured_ids = {value.attribute_id for value in prior_captured}
    remaining = [t for t in targets if t.attribute_id not in captured_ids]
    prompt = (
        f"The user replied:\n---\n{reply}\n---\n"
        "Judge this reply against the format skill's rules for every field it "
        "addresses — read it for EVERY value it carries, not just the fields you last "
        "asked about; a rich reply commonly settles fields you have not raised yet too.\n"
        "Return `captured` CUMULATIVELY: every value settled anywhere in this "
        "conversation so far, including ones captured on earlier turns. A value you omit "
        "is a value the document loses.\n\n"
        + (
            f"{_open_fields_clause(remaining)}\n\n"
            "Produce your next turn: choose a small, related cluster from the open "
            "fields above — never all of them at once."
            if remaining
            else "Every field is now captured, confirmed, or unresolved: set "
            "conversation_complete=true and give a brief closing line (no new question)."
        )
    )
    return await _conversation_turn(agent, session, prompt, usage=usage)


async def reopen_elicitation_conversation(
    agent: Agent,
    session: AgentSession,
    report: GapReport,
    result: ValidationResult,
    usage: RunUsage | None = None,
) -> ConversationTurn:
    """Resume the conversation on what validation judged still inadequate.

    Falls back to the bare attribute id for anything validation named that
    analysis' report never carried — a mismatch worth surfacing rather than
    silently masking.
    """
    by_id = {entry.attribute_id: entry for entry in report.attributes}
    targets = [
        by_id.get(aid)
        or AttributeStatus(attribute_id=aid, name=aid, required=True, populated=False)
        for aid in result.missing_attribute_ids
    ]
    findings = "\n".join(
        f"- {finding.reference_id}: {finding.summary}" for finding in result.advisory_findings
    )
    if not targets:
        return ConversationTurn(message="", conversation_complete=True, captured=[])
    prompt = (
        "Validation judged the document not yet adequate.\n"
        f"Rationale: {result.rationale}\n"
        f"Findings:\n{findings or '(none)'}\n\n"
        f"{_open_fields_clause(targets)}\n\n"
        "Continue the same conversation: choose a small, related cluster from the "
        "still-inadequate fields above — never all of them at once."
    )
    return await _conversation_turn(agent, session, prompt, usage=usage)


async def _conversation_turn(
    agent: Agent, session: AgentSession, prompt: str, usage: RunUsage | None = None
) -> ConversationTurn:
    """Run one turn of the whole-document conversation; warn if the skill was NEVER loaded.

    A skill loaded on an earlier turn of this session is already in the
    conversation the agent replays — reloading it every turn would only
    duplicate the reference content into context. So the warning fires only
    when neither this turn nor any earlier session turn loaded it.
    """
    response = await agent.run(
        prompt,
        session=session,
        options=ChatOptions(
            response_format=ConversationTurn, prompt_cache_key=_cache_key("elicitation")
        ),
    )
    log_usage("elicitation", None, response, usage)
    if not _loaded_skill(response, ELICITATION_SKILL_NAME) and not _skill_loaded_in_session(
        session, ELICITATION_SKILL_NAME
    ):
        logger.warning(
            "elicitation agent did not call load_skill('%s') at any point in this session; "
            "the question loop is running without the skill's cadence and invariants",
            ELICITATION_SKILL_NAME,
        )
    return _structured(response, ConversationTurn)


def _loaded_skill(response: object, skill_name: str) -> bool:
    """Whether the run's messages contain a load_skill call for the named skill."""
    for message in getattr(response, "messages", []) or []:
        for content in getattr(message, "contents", []) or []:
            if getattr(content, "name", None) == "load_skill" and skill_name in str(
                getattr(content, "arguments", "")
            ):
                return True
    return False


def _skill_loaded_in_session(session: AgentSession, skill_name: str) -> bool:
    """Whether any turn recorded in this session already loaded the named skill.

    Reads the session's serialized in-memory history — the same state the
    workflow carries through pauses — so a load on turn one still counts on
    turn ten after a resume rebuilt everything.
    """
    state = session.to_dict().get("state") or {}
    messages = (state.get("in_memory") or {}).get("messages") or []
    for message in messages:
        for content in message.get("contents") or []:
            if content.get("name") == "load_skill" and skill_name in str(
                content.get("arguments", "")
            ):
                return True
    return False


async def validate_document(
    agent: Agent,
    candidate_text: str,
    groups: list[FieldGroup],
    validation_tool: Callable[[dict[str, str]], list[str]],
    usage: RunUsage | None = None,
) -> ValidationResult:
    """Judge the whole document: the skill's own script for presence, the agent for adequacy.

    ``validation_tool`` is bound to this run's discovered groups by
    :func:`~foundry_agent.skill_validation.bind_skill_validation_tool` and
    passed per-call rather than baked into the agent at construction — the
    workflow, not this function, owns the skill's validation script.
    """
    prompt = (
        f"{_all_groups_scope(groups)}\n\n"
        f"Candidate Policy Report content:\n---\n{candidate_text}"
    )
    response = await agent.run(
        prompt,
        options=ChatOptions(
            response_format=ValidationResult,
            tools=[validation_tool],
            prompt_cache_key=_cache_key("validation"),
        ),
    )
    log_usage("validation", None, response, usage)
    return _structured(response, ValidationResult)


async def author_document(
    agent: Agent, candidate_text: str, usage: RunUsage | None = None
) -> str:
    """Write the final Policy Report from validated candidate content."""
    response = await agent.run(
        candidate_text, options=ChatOptions(prompt_cache_key=_cache_key("authoring"))
    )
    log_usage("authoring", None, response, usage)
    return response.text
