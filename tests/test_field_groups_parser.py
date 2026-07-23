"""The discovery parser, pinned against the LIVE skill file — and loud on drift.

Half of these tests parse the real ``field-groups.md`` so any re-clustering in
the skill that the parser cannot follow fails the suite instead of silently
mis-sequencing the interview. The other half mutate a copy of the live text to
prove each structural expectation fails loudly rather than being absorbed.
"""

from pathlib import Path

import pytest

from foundry_agent.field_groups_parser import FIELD_GROUPS_REFERENCE, parse_field_groups

LIVE_TEXT = FIELD_GROUPS_REFERENCE.read_text(encoding="utf-8")


def _mutated(tmp_path: Path, *pairs: tuple[str, str]) -> Path:
    """A copy of the live reference with each mutation applied (every one must occur)."""
    text = LIVE_TEXT
    for old, new in pairs:
        assert old in text, f"mutation target not in the live file: {old!r}"
        text = text.replace(old, new)
    target = tmp_path / "field-groups.md"
    target.write_text(text, encoding="utf-8")
    return target


def test_live_reference_declares_fg1_to_fg8_in_order():
    groups = parse_field_groups()

    assert [group.group_id for group in groups.groups] == [f"FG{n}" for n in range(1, 9)]


def test_live_reference_covers_pa1_to_pa32_exactly_once():
    groups = parse_field_groups()

    claimed = [aid for group in groups.groups for aid in group.attribute_ids]
    assert sorted(claimed, key=lambda aid: int(aid.removeprefix("PA"))) == [
        f"PA{n}" for n in range(1, 33)
    ]
    assert len(claimed) == len(set(claimed))


def test_live_reference_yields_complete_groups():
    """Every field the interview consumes is present and label-free where used."""
    fg1 = parse_field_groups().groups[0]

    assert fg1.name == "Identification & Classification"
    assert fg1.heading == "### FG1 — Identification & Classification"
    assert fg1.framing_line().startswith("Let's pin down what this policy is called")
    assert not fg1.framing_line().startswith("**")
    assert "Governance/Operational/Security/Compliance" in fg1.adequacy
    assert fg1.attribute_ids == ["PA1", "PA2", "PA3", "PA4", "PA5", "PA6"]


def test_range_entries_are_expanded_one_id_per_entry(tmp_path):
    """A range string in the source must come out expanded, never verbatim."""
    fg1_row = (
        "| Attributes | PA1 Policy ID, PA2 Title, PA3 Policy Type, PA4 Status, "
        "PA5 Version, PA6 Policy Owner |"
    )
    path = _mutated(tmp_path, (fg1_row, "| Attributes | PA1–PA6 |"))

    fg1 = parse_field_groups(path).groups[0]

    assert fg1.attribute_ids == [f"PA{n}" for n in range(1, 7)]


def test_the_live_file_already_exercises_a_range_entry():
    """FG6 is declared as ``PA21–PA24`` in the live file — it must arrive expanded."""
    fg6 = parse_field_groups().groups[5]

    assert fg6.attribute_ids == [f"PA{n}" for n in range(21, 25)]


def test_missing_framing_line_fails_loudly(tmp_path):
    path = _mutated(
        tmp_path,
        ("**Framing:** Give me the story behind this policy", "Give me the story behind this policy"),
    )

    with pytest.raises(ValueError, match="FG3.*Framing"):
        parse_field_groups(path)


def test_reworded_heading_fails_loudly(tmp_path):
    """An em-dash swapped for a hyphen must raise, not drop the group."""
    path = _mutated(tmp_path, ("### FG2 — Purpose & Scope", "### FG2 - Purpose & Scope"))

    with pytest.raises(ValueError, match="malformed field-group heading"):
        parse_field_groups(path)


def test_attribute_claimed_by_two_groups_fails_loudly(tmp_path):
    path = _mutated(
        tmp_path,
        (
            "| Attributes | PA7 Purpose Statement, PA8 Scope of Application, "
            "PA9 Exclusions, PA10 Effective Date |",
            "| Attributes | PA7 Purpose Statement, PA8 Scope of Application, "
            "PA9 Exclusions, PA10 Effective Date, PA1 Policy ID |",
        ),
        (
            "| FG2 — Purpose & Scope | PA7–PA10 |",
            "| FG2 — Purpose & Scope | PA7–PA10, PA1 |",
        ),
    )

    with pytest.raises(ValueError, match="more than one group.*PA1"):
        parse_field_groups(path)


def test_attribute_in_no_group_fails_loudly(tmp_path):
    path = _mutated(
        tmp_path,
        (
            "| Attributes | PA15 Key Terms, PA16 Related Policies, PA17 External References |",
            "| Attributes | PA33 Key Terms, PA16 Related Policies, PA17 External References |",
        ),
        (
            "| FG4 — Definitions & References | PA15–PA17 |",
            "| FG4 — Definitions & References | PA33, PA16, PA17 |",
        ),
    )

    with pytest.raises(ValueError, match="no group.*PA15"):
        parse_field_groups(path)


def test_section_disagreeing_with_coverage_map_fails_loudly(tmp_path):
    path = _mutated(
        tmp_path,
        ("| FG2 — Purpose & Scope | PA7–PA10 |", "| FG2 — Purpose & Scope | PA7–PA9 |"),
    )

    with pytest.raises(ValueError, match="FG2.*coverage map"):
        parse_field_groups(path)


def test_missing_coverage_map_fails_loudly(tmp_path):
    path = _mutated(tmp_path, ("### Group → attribute coverage map", "### Group memberships"))

    with pytest.raises(ValueError, match="coverage map"):
        parse_field_groups(path)


def test_unrecognised_attribute_entry_fails_loudly(tmp_path):
    path = _mutated(
        tmp_path,
        (
            "| Attributes | PA15 Key Terms, PA16 Related Policies, PA17 External References |",
            "| Attributes | key terms and references |",
        ),
    )

    with pytest.raises(ValueError, match="FG4.*unrecognised attribute entry"):
        parse_field_groups(path)
