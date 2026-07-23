"""Deterministic pre-validation checks, pinned against the live skill.

The citations each finding carries must match the ``policy-report-format`` skill's
actual wording — a check whose rule the skill no longer states is a check that
has drifted. Half of these tests read the live skill file to keep the citations
honest; the rest pin each check's pass/fail behaviour.
"""

from foundry_agent.agents import FORMAT_SKILL_DIR
from foundry_agent.mechanical_checks import captured_values, check_group
from foundry_agent.models import FieldGroup

_FIELD_GROUPS = (FORMAT_SKILL_DIR / "references" / "field-groups.md").read_text(encoding="utf-8")
_VALIDATION = (FORMAT_SKILL_DIR / "references" / "validation.md").read_text(encoding="utf-8")

# FG1 carries the two attribute-level mechanical rules (PA2 length, PA3 enum).
_FG1 = FieldGroup(
    group_id="FG1",
    name="Identification & Classification",
    heading="### FG1 — Identification & Classification",
    framing="Anchors what this policy is.",
    attribute_ids=["PA1", "PA2", "PA3", "PA4", "PA5", "PA6"],
    adequacy="PA1-PA6 populated; PA3 is exactly one of "
    "Governance/Operational/Security/Compliance; PA2 <= 10 words.",
)


def _content(**values: str) -> str:
    """Render captured-value lines the way the workflow records them."""
    return "\n".join(f"- {aid} — {value}" for aid, value in values.items())


# --- citations track the live skill -----------------------------------------


def test_classification_rule_is_still_in_the_skill():
    assert "Governance/Operational/Security/Compliance" in _FIELD_GROUPS


def test_title_length_rule_is_still_in_the_skill():
    assert "PA2 ≤ 10 words" in _FIELD_GROUPS


def test_placeholder_rule_is_still_in_the_skill():
    assert "empty, TBD, or placeholder" in _VALIDATION


# --- policy type (PA3) --------------------------------------------------------


def test_valid_classification_passes():
    assert check_group(_content(PA3="Security"), _FG1) == []


def test_classification_is_case_insensitive():
    assert check_group(_content(PA3="operational"), _FG1) == []


def test_invalid_classification_blocks_with_its_citation():
    findings = check_group(_content(PA3="Financial"), _FG1)

    assert [f.attribute_id for f in findings] == ["PA3"]
    assert findings[0].blocking
    assert "Governance/Operational/Security/Compliance" in findings[0].citation


# --- title length (PA2) --------------------------------------------------------


def test_title_within_ten_words_passes():
    assert check_group(_content(PA2="Remote Work Security Policy"), _FG1) == []


def test_title_over_ten_words_blocks():
    long_title = "A very long policy title that clearly exceeds the ten word maximum limit"
    findings = check_group(_content(PA2=long_title), _FG1)

    assert [f.attribute_id for f in findings] == ["PA2"]
    assert "10 words" in findings[0].citation


# --- placeholders ------------------------------------------------------------


def test_placeholder_value_blocks():
    findings = check_group(_content(PA1="TBD"), _FG1)

    assert any(f.attribute_id == "PA1" and f.blocking for f in findings)


def test_empty_value_blocks():
    findings = check_group(_content(PA1=""), _FG1)

    assert any(f.attribute_id == "PA1" for f in findings)


def test_a_substantive_value_is_not_a_placeholder():
    assert check_group(_content(PA1="POL-SEC-001"), _FG1) == []


def test_a_skill_sanctioned_none_is_not_a_placeholder():
    """attributes.md admits the literal 'None' for PA9 and PA15 — it must pass."""
    fg_with_pa9 = _FG1.model_copy(update={"attribute_ids": ["PA9"]})

    assert check_group(_content(PA9="None"), fg_with_pa9) == []


def test_other_placeholders_still_block_on_a_none_allowed_attribute():
    """Only the 'none' token is sanctioned for PA9 — TBD and friends still block."""
    fg_with_pa9 = _FG1.model_copy(update={"attribute_ids": ["PA9"]})
    findings = check_group(_content(PA9="TBD"), fg_with_pa9)

    assert any(f.attribute_id == "PA9" and f.blocking for f in findings)


def test_none_still_blocks_where_the_skill_does_not_sanction_it():
    """PA1 has no 'None is valid' clause — 'None' stays a placeholder there."""
    findings = check_group(_content(PA1="None"), _FG1)

    assert any(f.attribute_id == "PA1" and f.blocking for f in findings)


# --- scoping -----------------------------------------------------------------


def test_only_in_scope_attributes_are_checked():
    """A bad PA3 in the content is ignored when validating a group without PA3."""
    fg_without_pa3 = _FG1.model_copy(update={"attribute_ids": ["PA1"]})

    assert check_group(_content(PA3="Financial"), fg_without_pa3) == []


def test_captured_values_takes_the_last_value_for_a_repeated_attribute():
    content = _content(PA2="First title") + "\n" + _content(PA2="Corrected title")

    assert captured_values(content)["PA2"] == "Corrected title"
