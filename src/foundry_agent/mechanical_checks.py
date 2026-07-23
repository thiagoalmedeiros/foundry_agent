"""Deterministic pre-checks — SUPERSEDED, kept dormant, not imported by workflow.py.

STATUS — superseded in the workflow-build sibling by
``skills/policy-report-format/validation/validate.py``: the same deterministic
rules now live in the SKILL (domain content, not workflow code), executed by
the Validation agent through ``skill_validation.run_skill_validation`` rather
than as a workflow-level pre-check. Kept here, unwired, only as a historical
reference of the rules' original code form; do not import it from
``workflow.py`` — a fresh domain fork should author its rules directly in its
skill's ``validation/validate.py``, not by resurrecting this module.

Some adequacy rules are mechanical: a word count, an enum membership, a
placeholder scan. Judging those with a model call is wasteful and
non-deterministic, so this module checked them in code first. A blocking
mechanical failure reopened the group with no validation call at all; advisory
findings rode into the validation prompt so the model did not re-derive them.

Every check cites the exact skill text it enforces — this is written fresh from
the ``policy-report-format`` skill, not ported from any existing validator. If
the skill's wording changes, the citations here are what a reviewer checks
against.

The checks read the structured values the interview records into the merged
content (the ``- PAn — value`` lines :func:`_capture` writes), so they judge the
same captured answers the model would.
"""

import re
from dataclasses import dataclass

from foundry_agent.models import FieldGroup

#: Line format the workflow records a captured value in (``- PA2 — My Title``).
#: The value group is ``.*`` (not ``.+``) so an empty recorded value still
#: parses — it is then caught as a placeholder rather than silently ignored.
_CAPTURED_LINE = re.compile(r"^- (PA\d+) — (.*)$", re.MULTILINE)

#: FG1 adequacy (field-groups.md): "PA3 is exactly one of
#: Governance/Operational/Security/Compliance".
_CLASSIFICATIONS = frozenset({"governance", "operational", "security", "compliance"})

#: validation.md, the placeholder test (PC10): "Is any required attribute
#: empty, TBD, or placeholder?" Values that are placeholders rather than
#: substantive answers.
_PLACEHOLDERS = frozenset({"tbd", "todo", "n/a", "na", "none", "placeholder", "-", "?", "xxx"})

#: Attributes whose skill definition admits the literal value "None":
#: attributes.md PA9 — "'None' is a valid value; an unstated exclusion is
#: not" — and PA15 — "'None' only when the statements use no specialized
#: terms" (restated in FG2/FG4 adequacy). For these, the "none" placeholder
#: token does not apply; every other token (TBD, empty, …) still blocks.
_NONE_ALLOWED = frozenset({"PA9", "PA15"})

#: FG1 adequacy (field-groups.md): "PA2 ≤ 10 words".
_TITLE_MAX_WORDS = 10


@dataclass(frozen=True)
class MechanicalFinding:
    """One deterministic adequacy violation, with the skill text it enforces."""

    attribute_id: str
    citation: str
    message: str
    blocking: bool


def captured_values(content: str) -> dict[str, str]:
    """Extract ``{attribute_id: value}`` from the content's recorded-value lines.

    Later lines win, mirroring how a re-answered attribute overwrites an
    earlier value as the interview folds captures into the content.
    """
    return {match.group(1): match.group(2).strip() for match in _CAPTURED_LINE.finditer(content)}


def check_group(content: str, group: FieldGroup) -> list[MechanicalFinding]:
    """Run every deterministic check that applies to this group's attributes.

    Returns findings in a stable order; an empty list means nothing mechanical
    is wrong (the model still judges the substantive rules).
    """
    values = captured_values(content)
    in_scope = set(group.attribute_ids)
    findings: list[MechanicalFinding] = []

    if "PA3" in in_scope and "PA3" in values:
        findings.extend(_check_classification(values["PA3"]))
    if "PA2" in in_scope and "PA2" in values:
        findings.extend(_check_title_length(values["PA2"]))
    findings.extend(_check_placeholders(values, in_scope))
    return findings


def _check_classification(value: str) -> list[MechanicalFinding]:
    """PA3 must be exactly one of Governance / Operational / Security / Compliance."""
    if value.strip().lower() in _CLASSIFICATIONS:
        return []
    return [
        MechanicalFinding(
            attribute_id="PA3",
            citation="field-groups.md FG1 Adequacy: PA3 is exactly one of "
            "Governance/Operational/Security/Compliance",
            message=f"Policy type {value!r} is not one of Governance, Operational, "
            "Security, or Compliance.",
            blocking=True,
        )
    ]


def _check_title_length(value: str) -> list[MechanicalFinding]:
    """PA2 (Title) must be ≤ 10 words."""
    words = len(value.split())
    if words <= _TITLE_MAX_WORDS:
        return []
    return [
        MechanicalFinding(
            attribute_id="PA2",
            citation="field-groups.md FG1 Adequacy: PA2 ≤ 10 words",
            message=f"Title is {words} words; the limit is {_TITLE_MAX_WORDS}.",
            blocking=True,
        )
    ]


def _check_placeholders(values: dict[str, str], in_scope: set[str]) -> list[MechanicalFinding]:
    """No in-scope attribute may be answered with a placeholder / TBD."""
    findings: list[MechanicalFinding] = []
    for attribute_id in sorted(in_scope & values.keys()):
        normalized = values[attribute_id].strip().lower()
        tokens = _PLACEHOLDERS - {"none"} if attribute_id in _NONE_ALLOWED else _PLACEHOLDERS
        if not normalized or normalized in tokens:
            findings.append(
                MechanicalFinding(
                    attribute_id=attribute_id,
                    citation="validation.md, the placeholder test (PC10): any required "
                    "attribute empty, TBD, or placeholder",
                    message=f"{attribute_id} is a placeholder ({values[attribute_id]!r}), "
                    "not a substantive value.",
                    blocking=True,
                )
            )
    return findings
