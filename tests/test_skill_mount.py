"""The mounted format lives in skill files — reaching agents two ways, never in code.

The elicitation agent keeps MAF progressive disclosure (its multi-turn session
amortizes what it loads). The stateless agents — validation and authoring —
carry a per-agent reference pack inlined verbatim from the same skill files at
construction time (the predecessor project's recorded progressive-disclosure
evaluation led here). Validation additionally mounts the format skill's provider
— not for disclosure, but so the native ``run_skill_script`` tool can execute
the skill's own validation script. These tests pin the mounts, that each pack is
tailored and verbatim from the live files, and that no agent restates domain
knowledge in code.
"""

import pytest
from agent_framework import Agent

from foundry_agent.agents import (
    AUTHORING_PACK,
    ELICITATION_SKILL_DIR,
    ELICITATION_SKILL_NAME,
    FORMAT_SKILL_DIR,
    FORMAT_SKILL_NAME,
    REFERENCES_DIR,
    VALIDATION_PACK,
    create_authoring_agent,
    create_elicitation_agent,
    create_validation_agent,
)
from tests.conftest import GROUPS

STATELESS = [
    (create_validation_agent, VALIDATION_PACK),
    (create_authoring_agent, AUTHORING_PACK),
]


async def _run_once(agent: Agent) -> None:
    """One stubbed run, just to make the agent hand its options to the client."""
    await agent.run("ping")


def test_both_skills_exist_on_disk_with_a_skill_md():
    assert (FORMAT_SKILL_DIR / "SKILL.md").is_file()
    assert (ELICITATION_SKILL_DIR / "SKILL.md").is_file()


def test_the_format_skill_owns_the_field_groups_the_interview_walks():
    """The group sequence is content, not code — it must be readable from the skill.

    Asserted domain-neutrally: whatever format skill is mounted, its field-groups
    reference declares an ``### FG1 —`` heading and closes with the coverage line.
    """
    field_groups = (FORMAT_SKILL_DIR / "references" / "field-groups.md").read_text(
        encoding="utf-8"
    )

    assert "### FG1 —" in field_groups
    assert "covered exactly once." in field_groups


async def test_the_elicitation_agent_keeps_progressive_disclosure(make_stub_client):
    """Elicitation still mounts both skills through the provider's tools."""
    client = make_stub_client(GROUPS)

    await _run_once(create_elicitation_agent(client))

    instructions = client.options["instructions"]
    assert FORMAT_SKILL_NAME in instructions
    assert ELICITATION_SKILL_NAME in instructions
    tool_names = {getattr(tool, "name", str(tool)) for tool in client.options["tools"]}
    assert "load_skill" in tool_names
    assert "read_skill_resource" in tool_names


@pytest.mark.parametrize(("factory", "pack"), STATELESS, ids=["validation", "authoring"])
async def test_stateless_agents_carry_their_pack_verbatim(make_stub_client, factory, pack):
    """Each pack file's live content is inlined whole — content, not paraphrase."""
    client = make_stub_client(GROUPS)

    await _run_once(factory(client))

    instructions = client.options["instructions"]
    for name in pack:
        live = (REFERENCES_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
        assert live in instructions, f"{name}.md not inlined verbatim"


async def test_the_authoring_agent_carries_no_skill_tools(make_stub_client):
    """The disclosure tool loop is gone for authoring — the measured cost."""
    client = make_stub_client(GROUPS)

    await _run_once(create_authoring_agent(client))

    tool_names = {
        getattr(tool, "name", str(tool)) for tool in client.options.get("tools") or []
    }
    assert "load_skill" not in tool_names
    assert "read_skill_resource" not in tool_names


async def test_the_validation_agent_mounts_the_provider_for_its_script(make_stub_client):
    """Validation keeps its inline pack but mounts the format skill so the
    native ``run_skill_script`` tool can execute ``validation/validate.py``."""
    client = make_stub_client(GROUPS)

    await _run_once(create_validation_agent(client))

    tool_names = {getattr(tool, "name", str(tool)) for tool in client.options["tools"]}
    assert "run_skill_script" in tool_names


def test_packs_are_tailored_not_one_blob():
    """No agent pays for material it never consults."""
    assert "template" in AUTHORING_PACK
    assert "template" not in VALIDATION_PACK
    assert "rules" in VALIDATION_PACK
    assert "rules" not in AUTHORING_PACK


async def test_only_the_elicitation_agent_carries_the_behavior_skill(make_stub_client):
    """The question loop belongs to elicitation; the stateless agents must not see it."""
    elicit_client = make_stub_client(GROUPS)
    validation_client = make_stub_client(GROUPS)

    await _run_once(create_elicitation_agent(elicit_client))
    await _run_once(create_validation_agent(validation_client))

    assert ELICITATION_SKILL_NAME in elicit_client.options["instructions"]
    assert ELICITATION_SKILL_NAME not in validation_client.options["instructions"]


def _first_attribute_name() -> str:
    """The human name in the first ``| PAn | <name> | …`` row of the mounted skill."""
    for line in (REFERENCES_DIR / "attributes.md").read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) >= 4 and cells[1].startswith("PA") and cells[1][2:].isdigit():
            return cells[2]
    return ""


async def test_the_elicitation_agent_does_not_hardcode_attribute_definitions(
    make_stub_client,
):
    """Elicitation's own instructions never restate the skill's attribute prose.

    Domain-neutral: a distinctive attribute name from whatever format skill is
    mounted must not appear in the prompt — the elicitation agent reads it via
    load_skill, not by inlining. The stateless agents DO inline the reference
    files verbatim by design (pinned above); for elicitation the guarantee is
    absence.
    """
    client = make_stub_client(GROUPS)

    await _run_once(create_elicitation_agent(client))

    instructions = client.options["instructions"]
    first_name = _first_attribute_name()
    assert first_name, "no attribute name parsed from the mounted skill"
    assert first_name not in instructions
