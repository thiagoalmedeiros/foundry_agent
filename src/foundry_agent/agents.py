"""Agent definitions over the mounted format skill's content.

The agents hold no domain knowledge in code. Everything about what the document
*is* — its field groups, attributes, characteristics, rules, statement patterns,
population and inference guidance, the canonical template — lives in the mounted
format skill, and reaches each agent one of two ways:

- The **elicitation** agent keeps MAF progressive disclosure: a
  :class:`SkillsProvider` mounts the format skill plus the generic
  ``elicitation`` behavior skill, and the multi-turn session amortizes what
  it loads (measured 81% prompt-cache hit rate).
- The **stateless** agents — gap analysis, validation, authoring — get a
  per-agent-tailored reference pack read verbatim from the same skill files at
  construction time and inlined into the system prompt, where the prefix cache
  reuses it across calls. Their per-call tool-loop skill reads measured 62% of
  a run's full-rate tokens, which is why disclosure was retired for them (the
  predecessor project's recorded progressive-disclosure verdict).
- The **validation** agent additionally mounts the format skill's provider so
  the native ``run_skill_script`` tool can execute the loaded skill's OWN
  deterministic validation script (``validation/validate.py``, run as a
  subprocess by :func:`_run_python_skill_script`) — the workflow never encodes
  those rules itself.

Either way the content is repository skill files, not code: re-clustering a
field group or rewording population guidance changes this workflow's behaviour
with no change here.
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, TypeVar

from agent_framework import (
    Agent,
    AgentSession,
    ChatOptions,
    FileSkill,
    FileSkillScript,
    FileSkillsSource,
    SkillsProvider,
    SupportsChatGetResponse,
)
from agent_framework.openai import OpenAIChatClient
from dotenv import load_dotenv
from pydantic import BaseModel

from foundry_agent.models import (
    CapturedValue,
    ConversationTurn,
    FieldGroup,
    FieldGroups,
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
    REFERENCES_DIR as REFERENCES_DIR,
    VALIDATION_INSTRUCTIONS,
    VALIDATION_PACK,
    VALIDATION_SCRIPT_NAME,
    _all_groups_scope,
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
_CACHE_KEY_PREFIX = "report-interview-agent"


def _cache_key(stage: str) -> str:
    """The prompt-cache routing key for one stage's shared prompt prefix."""
    return f"{_CACHE_KEY_PREFIX}:{stage}"


#: Hard wall-clock cap on one skill-script subprocess. The validation script is
#: pure and finishes in milliseconds; the cap only bounds a hung interpreter.
_SCRIPT_TIMEOUT_SECONDS = float(os.environ.get("SKILL_SCRIPT_TIMEOUT_SECONDS", "30"))

#: Environment passed through to skill-script subprocesses: what a Python
#: interpreter needs to start, and nothing else — no credentials, since skill
#: scripts are pure by contract (see the skill's SECURITY.md).
_SCRIPT_ENV_KEYS = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")


def _script_argv(args: dict[str, Any] | list[Any] | None) -> list[str]:
    """Flatten the model-supplied tool arguments into subprocess argv strings.

    The tool contract asks for a list of JSON strings, but a model may send a
    dict or already-parsed JSON values; every non-string is re-serialized so
    the script always receives JSON text, positionally, in the order given.
    """
    values = list(args.values()) if isinstance(args, dict) else list(args or [])
    return [value if isinstance(value, str) else json.dumps(value) for value in values]


async def _run_python_skill_script(
    skill: FileSkill, script: FileSkillScript, args: dict[str, Any] | list[Any] | None = None
) -> Any:
    """Run a file-based skill script as a subprocess — the framework ships no runner.

    Satisfies the :class:`agent_framework.SkillScriptRunner` protocol.
    Executes ONLY scripts discovered inside this repository's ``skills/`` tree
    (see the mounted skill's ``validation/SECURITY.md`` for the trust stance).
    Errors come back as strings, matching the provider's own error style, so
    the calling agent can correct its arguments and retry instead of crashing
    the run.
    """
    path = Path(script.full_path)
    env = {key: value for key in _SCRIPT_ENV_KEYS if (value := os.environ.get(key))}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(path),
        *_script_argv(args),
        cwd=str(path.parent),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=_SCRIPT_TIMEOUT_SECONDS
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        return (
            f"Error: script '{script.name}' timed out after {_SCRIPT_TIMEOUT_SECONDS:g}s."
        )
    if process.returncode != 0:
        detail = stderr.decode(errors="replace").strip() or f"exit code {process.returncode}"
        return f"Error: script '{script.name}' failed — {detail}"
    output = stdout.decode(errors="replace").strip()
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return output


def create_skills(paths: list[Path]) -> SkillsProvider:
    """Mount the skills an agent may load, via MAF progressive disclosure.

    The provider advertises each skill's name and description in the system
    prompt and offers ``load_skill`` / ``read_skill_resource`` /
    ``run_skill_script`` tools, so only the references an agent actually needs
    enter its context and a skill's own scripts (e.g. the format skill's
    ``validate.py``) run through :func:`_run_python_skill_script`. Approvals
    are disabled — these skills ship in this repository.
    """
    return SkillsProvider(
        FileSkillsSource(
            [str(path) for path in paths], script_runner=_run_python_skill_script
        ),
        source_id="report_skills",
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
    # tools and the validation agent runs the skill's validation script through
    # run_skill_script (the stateless gap-analysis/authoring agents inline their
    # packs instead), but these caps keep every agent's worst-case tool-loop
    # cost per call bounded.
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


def create_validation_agent(
    client: SupportsChatGetResponse, skills: SkillsProvider | None = None
) -> Agent:
    """Create the Validation agent: reference pack inlined, format skill mounted.

    The provider is mounted for its native ``run_skill_script`` tool — the
    agent executes the skill's own ``validation/validate.py`` with this run's
    captured values and groups (both already in its prompt). The inline
    reference pack stays: the mount serves the script, not disclosure.
    """
    return Agent(
        client,
        f"{VALIDATION_INSTRUCTIONS}{_skill_pack(VALIDATION_PACK)}",
        name="validation",
        description="Runs the skill's own validation script, then judges adequacy "
        "across the whole document.",
        context_providers=[skills or create_skills([FORMAT_SKILL_DIR])],
    )


def create_authoring_agent(client: SupportsChatGetResponse) -> Agent:
    """Create the Authoring agent with its reference pack inlined."""
    return Agent(
        client,
        f"{AUTHORING_INSTRUCTIONS}{_skill_pack(AUTHORING_PACK)}",
        name="authoring",
        description="Writes the final document per the canonical template.",
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


async def open_group_conversation(
    agent: Agent,
    session: AgentSession,
    group: FieldGroup,
    content: str,
    usage: RunUsage | None = None,
) -> ConversationTurn:
    """Open the conversation for ONE field group.

    The agent judges what the content already supports for this group's fields,
    presents inferred values for confirmation and asks for what is missing, in
    plain stakeholder language (never attribute ids). It sets
    ``conversation_complete`` when this group's Adequacy is satisfied.
    """
    prompt = (
        f"Field group to clarify now: {group.heading}\n"
        "Open with this framing line verbatim (no label prefix):\n"
        f"{group.framing_line()}\n\n"
        "Attributes in this group (internal ids — NEVER shown to the user): "
        f"{', '.join(group.attribute_ids)}\n"
        f"Adequacy — what 'done' means for this group:\n{group.adequacy}\n\n"
        f"Content gathered so far:\n---\n{content}\n---\n"
        "Drive a natural conversation to clarify THIS group's points: infer what the "
        "content already supports and present it for confirmation, ask for what is "
        "missing, in plain stakeholder language. Set conversation_complete=true when "
        "this group's Adequacy is satisfied."
    )
    return await _conversation_turn(agent, session, prompt, usage=usage)


async def continue_group_conversation(
    agent: Agent,
    session: AgentSession,
    group: FieldGroup,
    prior_captured: list[CapturedValue],
    reply: str,
    usage: RunUsage | None = None,
) -> ConversationTurn:
    """Feed the user's reply into the CURRENT group's conversation.

    ``prior_captured`` is what this group has settled so far; the agent returns
    the cumulative captured set and sets ``conversation_complete`` when the
    group's Adequacy holds.
    """
    settled = ", ".join(value.attribute_id for value in prior_captured) or "(none yet)"
    prompt = (
        f"Still clarifying this group: {group.heading}\n"
        f"Adequacy — what 'done' means for this group:\n{group.adequacy}\n\n"
        f"Already settled this group: {settled}\n"
        f"The user replied:\n---\n{reply}\n---\n"
        "Judge the reply against this group's Adequacy for every field it addresses. "
        "Return `captured` CUMULATIVELY — every value settled for this group so far, "
        "keyed by its exact attribute id. If this group's Adequacy is now satisfied, "
        "set conversation_complete=true with a brief closing line; otherwise continue "
        "clarifying this group's remaining points in plain language (never show ids)."
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
            response_format=ConversationTurn,
            prompt_cache_key=_cache_key("elicitation"),
            # Low reasoning effort keeps each conversational turn fast: judging one
            # reply against the current group's adequacy — or answering a greeting
            # or clarifying question — needs no deep multi-second reasoning pass.
            # This client speaks the OpenAI Responses API, whose structured-output
            # (.parse) path takes reasoning={"effort": ...}; the Chat-Completions
            # `reasoning_effort=` form is rejected there (witnessed live).
            reasoning={"effort": "low"},
        ),
    )
    log_usage("elicitation", None, response, usage)
    if not _called_tool(
        response, "load_skill", ELICITATION_SKILL_NAME
    ) and not _skill_loaded_in_session(session, ELICITATION_SKILL_NAME):
        logger.warning(
            "elicitation agent did not call load_skill('%s') at any point in this session; "
            "the question loop is running without the skill's cadence and invariants",
            ELICITATION_SKILL_NAME,
        )
    return _structured(response, ConversationTurn)


def _called_tool(response: object, tool_name: str, argument_fragment: str) -> bool:
    """Whether the run's messages contain a ``tool_name`` call mentioning ``argument_fragment``."""
    for message in getattr(response, "messages", []) or []:
        for content in getattr(message, "contents", []) or []:
            if getattr(content, "name", None) == tool_name and argument_fragment in str(
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
    usage: RunUsage | None = None,
) -> ValidationResult:
    """Judge the whole document: the skill's own script for presence, the agent for adequacy.

    The deterministic check arrives through the agent's mounted skill
    provider (``run_skill_script`` on the format skill's
    ``validation/validate.py``); the prompt carries everything the agent
    needs to pass — the group scope and the candidate content.
    """
    prompt = (
        f"{_all_groups_scope(groups)}\n\n"
        f"Candidate document content:\n---\n{candidate_text}"
    )
    response = await agent.run(
        prompt,
        options=ChatOptions(
            response_format=ValidationResult,
            prompt_cache_key=_cache_key("validation"),
        ),
    )
    log_usage("validation", None, response, usage)
    if not _called_tool(response, "run_skill_script", VALIDATION_SCRIPT_NAME):
        logger.warning(
            "validation agent did not call run_skill_script('%s'); the skill's "
            "deterministic presence check did not run — this verdict is adequacy "
            "judgment only",
            VALIDATION_SCRIPT_NAME,
        )
    return _structured(response, ValidationResult)


async def author_document(
    agent: Agent, candidate_text: str, usage: RunUsage | None = None
) -> str:
    """Write the final document from validated candidate content."""
    response = await agent.run(
        candidate_text, options=ChatOptions(prompt_cache_key=_cache_key("authoring"))
    )
    log_usage("authoring", None, response, usage)
    return response.text
