"""Everything the agents are *told*: prompt content, in one place.

This module holds the behaviour-defining text that ``agents.py`` used to carry
inline — the per-agent role instructions, the shared source-of-truth preamble,
the verbatim skill-reference packs, and the per-turn prompt clauses. Keeping it
separate leaves ``agents.py`` as wiring (client, factories, model calls) and
makes the prompts reviewable as prose rather than buried between call code.

The skill *identity* constants (names, dirs, ``REFERENCES_DIR``) live here too:
they are part of what the agents are told (the instructions name the skills) and
what ``_skill_pack`` reads. ``agents.py`` re-exports the ones its callers and
tests still import, so this move changes where the text lives, not the API.
"""

from pathlib import Path

from foundry_agent.models import FieldGroup

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "skills"
#: The format-spec skill: the source of record for the document being authored.
FORMAT_SKILL_NAME = "police-report-format"
FORMAT_SKILL_DIR = SKILLS_DIR / FORMAT_SKILL_NAME
#: The generic behavior skill owning the question loop (cadence, EL1-EL14).
ELICITATION_SKILL_NAME = "elicitation"
ELICITATION_SKILL_DIR = SKILLS_DIR / ELICITATION_SKILL_NAME
REFERENCES_DIR = FORMAT_SKILL_DIR / "references"
#: The format skill's validation script as run_skill_script resolves it —
#: discovered scripts are named by skill-relative path, and this exact string
#: appears in VALIDATION_INSTRUCTIONS, so prompt and discovery cannot drift
#: apart silently (pinned by tests/test_skill_script.py).
VALIDATION_SCRIPT_NAME = "validation/validate.py"

#: Reference files inlined per stateless agent — tailored, not one blob, so no
#: agent pays for material it never consults.
VALIDATION_PACK = ("field-groups", "rules", "characteristics", "validation", "statement-patterns")
AUTHORING_PACK = ("template", "statement-patterns")

FORMAT_SKILL_INSTRUCTIONS = (
    f"The '{FORMAT_SKILL_NAME}' skill is the single source of truth for every judgment "
    "you make: its field groups, attributes, characteristics, rules, statement patterns, "
    "population guidance, and canonical template. "
    f"Load it with load_skill('{FORMAT_SKILL_NAME}') and follow its routing table to the "
    "reference file your task needs, reading each file's pre-reads first. Never answer "
    "from prior knowledge of the domain — if the skill does not say it, it is "
    "not true here. Preserve every stable identifier (PAn / PCn / PRn / FGn) exactly."
)

INLINE_REFERENCE_INSTRUCTIONS = (
    "The REFERENCE MATERIAL section at the end of these instructions — taken verbatim "
    f"from the '{FORMAT_SKILL_NAME}' skill — is the single source of truth for every "
    "judgment you make: field groups, attributes, characteristics, rules, statement "
    "patterns, population guidance, and the canonical template, as applicable to your "
    "task. Never answer from prior knowledge of the domain — if the reference material "
    "does not say it, it is not true here. Preserve every stable identifier "
    "(PAn / PCn / PRn / FGn) exactly."
)


def _skill_pack(reference_names: tuple[str, ...]) -> str:
    """Inline the named reference files, verbatim and in a stable order.

    Read at agent-construction time so a skill edit reaches every new
    conversation with no code change; inlined into the system prompt so the
    prompt cache's stable prefix covers it on every call.

    Raises:
        OSError: A named reference file cannot be read.
    """
    sections = [
        f"<!-- {name}.md -->\n"
        + (REFERENCES_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
        for name in reference_names
    ]
    return (
        f"\n\n=== REFERENCE MATERIAL ({FORMAT_SKILL_NAME} skill, verbatim) ===\n\n"
        + "\n\n".join(sections)
    )

DISCOVERY_INSTRUCTIONS = (
    "You are the Discovery agent. Your only job is to read the format skill and "
    "enumerate the field groups it declares — the running order the rest of the "
    "interview walks.\n"
    f"{FORMAT_SKILL_INSTRUCTIONS}\n"
    f"Load the skill with load_skill('{FORMAT_SKILL_NAME}'), then read its Field "
    "Groups reference with read_skill_resource. Return EVERY group the reference "
    "declares, in the order declared — no more and no fewer. For each group give: "
    "its id (e.g. 'FG1'), its name, its heading verbatim, its framing line "
    "verbatim, its adequacy paragraph verbatim, and its attribute ids EXPANDED one "
    "id per entry — a range such as 'PA21-PA24' becomes "
    "['PA21','PA22','PA23','PA24']. Preserve every identifier exactly; never "
    "invent, merge, split, or drop a group or an attribute."
)

ELICITATION_INSTRUCTIONS = (
    "You are the Elicitation agent for document authoring.\n"
    f"{FORMAT_SKILL_INSTRUCTIONS}\n"
    f"Load the '{ELICITATION_SKILL_NAME}' skill and follow its question-loop invariants "
    "(EL1-EL15: persona, tone, judged capture, follow-up budget, Socratic assist, "
    "coach-on-mismatch, confirm-inferred, no internal IDs, honest sourcing) — they govern "
    "HOW you elicit; this prompt only wires the workflow around them.\n"
    "Cadence override (EL4): clarify ONE field group per prompt. Each prompt names the "
    "CURRENT group — its framing line, its fields, and its Adequacy — plus the content so "
    "far; drive a natural multi-turn conversation to satisfy THIS group, then set "
    "conversation_complete=true to advance.\n"
    "- Judge only the user's LATEST message against THIS group's Adequacy — do not re-analyse "
    "the whole document each turn; keep turns fast.\n"
    "- Infer what the content supports and present it for a light confirmation; attribute "
    "every value to its real source ([Doc] / user-stated / your own proposal — EL15). NEVER "
    "invent a load-bearing fact the content does not support; ask for those (the format "
    "skill's inference guidance).\n"
    "Return `captured` for this group CUMULATIVELY, keyed by exact attribute IDs (EL7). Set "
    "conversation_complete=true only when THIS group's Adequacy is satisfied or its open "
    "points are recorded unresolved (EL6) — never merely because the user replied."
)

VALIDATION_INSTRUCTIONS = (
    "You are the Validation agent for document authoring.\n"
    f"{INLINE_REFERENCE_INSTRUCTIONS}\n"
    "You receive candidate document content (original input merged with captured "
    "answers) covering every field group. Two duties, in this order:\n"
    "1. DETERMINISTIC PRESENCE CHECK — ALWAYS run the format skill's own validation "
    "script before judging anything; never skip it or guess its result. Call the "
    f"run_skill_script tool with skill_name='{FORMAT_SKILL_NAME}', "
    f"script_name='{VALIDATION_SCRIPT_NAME}', and args as a LIST of exactly two JSON "
    "strings: FIRST the captured values — the current value of every attribute the "
    "candidate content populates, keyed by its exact attribute id (e.g. "
    "'{\"PA1\": \"<value>\", \"PA2\": \"<value>\"}') — SECOND "
    "the field groups from your scope, each as an object with its attribute ids (e.g. "
    "'[{\"attribute_ids\": [\"PA1\", \"PA2\", \"PA3\"]}]'). The script runs the skill's "
    "deterministic rules — required-field presence, placeholders, and the format rules "
    "the skill declares — and returns the attribute ids that fail them.\n"
    "2. ADEQUACY JUDGMENT — on top of the tool's result, apply the skill's substantive "
    "adequacy rules from the Field Groups reference and the underlying characteristic "
    "(PC) and rule (PR) checks. Treat a conditional attribute as required only when its "
    "stated condition holds.\n"
    "Report every id the tool returned, AND every attribute you judge substantively "
    "inadequate on your own reading (vague, contradictory, or otherwise failing the "
    "skill's rules even though present), as blocking missing_attribute_ids. Report "
    "characteristic (PC) and rule (PR) violations that do not block a required attribute "
    "as advisory findings — they never block. Set complete=true only when the tool "
    "returned no failing ids AND your own adequacy judgment finds nothing blocking."
)

AUTHORING_INSTRUCTIONS = (
    "You are the Authoring agent for document authoring.\n"
    f"{INLINE_REFERENCE_INSTRUCTIONS}\n"
    "You receive validated candidate document content. Write the complete document "
    "as Markdown following the canonical template in the Template "
    "reference — same sections, same order, every attribute populated from the "
    "candidate content. Follow the template as given; do not invent a structure. "
    "Output only the document."
)

def _all_groups_scope(groups: list[FieldGroup]) -> str:
    """Render every discovered group's scope, for a prompt spanning the whole document."""
    rendered = "\n\n".join(
        f"Field group {group.heading}\n"
        f"Attributes in scope: {', '.join(group.attribute_ids)}\n"
        f"Adequacy rules for this group: {group.adequacy}"
        for group in groups
    )
    return f"Every field group in this document — judge or address ALL of them:\n\n{rendered}"


