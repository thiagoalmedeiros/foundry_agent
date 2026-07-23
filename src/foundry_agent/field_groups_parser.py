"""Strict parser for the format skill's Field Groups reference.

STATUS — dormant in the workflow-build sibling. The active workflow now
discovers groups with an LLM agent (:func:`foundry_agent.agents.discover_groups`)
that tolerates whatever markdown a skill author writes; this strict,
format-sensitive parser is retained for the planned sequential-orchestration
sibling, where deterministic, drift-loud discovery is the point. It is still
exercised by ``tests/test_field_groups_parser.py`` so it stays correct.

This parser reads ``field-groups.md`` directly: zero tokens, deterministic, and
the skill-owns-the-content decoupling survives because the file, not this code,
still declares the groups.

What code must NOT do is absorb the file's structure silently. A reworded
heading or a re-clustered attribute that this parser half-reads would
mis-sequence the whole interview while looking healthy — the same failure
class the scoped-to-nothing bug in workflow.py's history came from. So every
expectation is checked loudly: malformed headings, missing Framing/Attributes/
Adequacy fields, a missing coverage map, disagreement between a group's own
attribute row and the coverage map, and any attribute claimed twice or not at
all each raise ``ValueError`` naming the offending piece.
"""

import re
from pathlib import Path

from foundry_agent.agents import FORMAT_SKILL_DIR
from foundry_agent.models import FieldGroup, FieldGroups

#: The reference file this parser pins: the format skill's own group catalogue.
FIELD_GROUPS_REFERENCE = FORMAT_SKILL_DIR / "references" / "field-groups.md"

_FG_PREFIX = re.compile(r"^###\s+FG")
_HEADING = re.compile(r"^### (FG\d+) — (.+?)\s*$")
_ATTRIBUTES_ROW = re.compile(r"^\| Attributes \| (.+?) \|\s*$")
_MAP_ROW = re.compile(r"^\| (FG\d+) [^|]*\| ([^|]+?) \|\s*$")
_SINGLE_ID = re.compile(r"^PA(\d+)$")
_RANGE_ID = re.compile(r"^PA(\d+)\s*[–-]\s*(?:PA)?(\d+)$")


def parse_field_groups(path: Path | None = None) -> FieldGroups:
    """Read the field groups the reference file declares, in declared order.

    Args:
        path: The Field Groups reference to parse; defaults to the format
            skill's own ``references/field-groups.md``.

    Returns:
        Every declared group with its heading, framing line, adequacy rules,
        and attribute ids (ranges expanded, one id per entry).

    Raises:
        ValueError: The file does not match the expected structure, a group
            disagrees with the coverage map, or the groups do not cover every
            attribute exactly once.
        OSError: The file cannot be read.
    """
    lines = (path or FIELD_GROUPS_REFERENCE).read_text(encoding="utf-8").splitlines()
    groups = [_parse_group(heading, block) for heading, block in _group_blocks(lines)]
    if not groups:
        raise ValueError("field-groups reference declares no '### FGn — <name>' sections")
    _check_against_coverage_map(groups, _coverage_map(lines))
    _check_exactly_once_coverage(groups)
    return FieldGroups(groups=groups)


def _group_blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Split out each ``### FGn — <name>`` section's heading and body lines."""
    blocks: list[tuple[str, list[str]]] = []
    body: list[str] | None = None
    for line in lines:
        if line.startswith("### ") or line.startswith("## "):
            body = None
        if _FG_PREFIX.match(line):
            if not _HEADING.match(line):
                raise ValueError(
                    f"malformed field-group heading (expected '### FGn — <name>'): {line!r}"
                )
            body = []
            blocks.append((line, body))
            continue
        if body is not None:
            body.append(line)
    return blocks


def _parse_group(heading: str, body: list[str]) -> FieldGroup:
    """Build one group from its section, failing loudly on any missing field."""
    match = _HEADING.match(heading)
    if match is None:  # _group_blocks only admits matching headings.
        raise ValueError(f"malformed field-group heading: {heading!r}")
    group_id, name = match.groups()
    framing = _only_line(body, "**Framing:**", group_id)
    attributes_row = _attributes_row(body, group_id)
    adequacy = _paragraph(body, "**Adequacy:**", group_id)
    return FieldGroup(
        group_id=group_id,
        name=name,
        heading=heading,
        framing=framing,
        attribute_ids=_expand_ids(attributes_row, group_id),
        adequacy=adequacy,
    )


def _only_line(body: list[str], label: str, group_id: str) -> str:
    """The single line carrying the labelled field, verbatim."""
    found = [line.strip() for line in body if line.strip().startswith(label)]
    if len(found) != 1:
        raise ValueError(f"{group_id}: expected exactly one '{label}' line, found {len(found)}")
    return found[0]


def _attributes_row(body: list[str], group_id: str) -> str:
    """The ``| Attributes | ... |`` table row's cell content."""
    rows = [m.group(1) for line in body if (m := _ATTRIBUTES_ROW.match(line.strip()))]
    if len(rows) != 1:
        raise ValueError(
            f"{group_id}: expected exactly one '| Attributes | ... |' row, found {len(rows)}"
        )
    return rows[0]


def _paragraph(body: list[str], label: str, group_id: str) -> str:
    """The labelled paragraph: its line plus continuation lines up to a blank."""
    for index, line in enumerate(body):
        if line.strip().startswith(label):
            collected = [line.strip()[len(label) :].strip()]
            for continuation in body[index + 1 :]:
                if not continuation.strip():
                    break
                collected.append(continuation.strip())
            paragraph = " ".join(part for part in collected if part)
            if not paragraph:
                raise ValueError(f"{group_id}: '{label}' paragraph is empty")
            return paragraph
    raise ValueError(f"{group_id}: no '{label}' paragraph found")


def _expand_ids(cell: str, group_id: str) -> list[str]:
    """Expand a comma-separated attribute cell to one id per entry, in order.

    Entries may be ``PA4``, ``PA4 Status``, or a range like
    ``PA21–PA24``; anything else is drift this parser must not absorb. A range
    with spaces around the dash (``PA21 – PA24``) is NOT supported — its tail
    would be dropped here, but the exactly-once coverage check then fails
    loudly on the missing ids, so it cannot pass silently.
    """
    ids: list[str] = []
    for entry in cell.split(","):
        token = entry.split()[0] if entry.split() else ""
        if single := _SINGLE_ID.match(token):
            ids.append(f"PA{single.group(1)}")
        elif spread := _RANGE_ID.match(token):
            start, end = int(spread.group(1)), int(spread.group(2))
            if end <= start:
                raise ValueError(f"{group_id}: attribute range {token!r} is not ascending")
            ids.extend(f"PA{number}" for number in range(start, end + 1))
        else:
            raise ValueError(f"{group_id}: unrecognised attribute entry {entry.strip()!r}")
    return ids


def _coverage_map(lines: list[str]) -> dict[str, list[str]]:
    """The 'Group → attribute coverage map' table, group id → expanded ids."""
    in_map = False
    mapping: dict[str, list[str]] = {}
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("###"):
            in_map = "coverage map" in stripped.lower()
            continue
        if in_map and (row := _MAP_ROW.match(stripped)):
            group_id = row.group(1)
            mapping[group_id] = _expand_ids(row.group(2), group_id)
    if not mapping:
        raise ValueError("no 'Group → attribute coverage map' table found")
    return mapping


def _check_against_coverage_map(
    groups: list[FieldGroup], coverage: dict[str, list[str]]
) -> None:
    """Each group's own attribute row must agree with the map's claim for it."""
    section_ids = {group.group_id for group in groups}
    if section_ids != set(coverage):
        raise ValueError(
            "group sections and coverage map disagree on which groups exist: "
            f"sections={sorted(section_ids)} map={sorted(coverage)}"
        )
    for group in groups:
        if set(group.attribute_ids) != set(coverage[group.group_id]):
            raise ValueError(
                f"{group.group_id}: section lists {sorted(group.attribute_ids)} but the "
                f"coverage map claims {sorted(coverage[group.group_id])}"
            )


def _check_exactly_once_coverage(groups: list[FieldGroup]) -> None:
    """Every attribute belongs to exactly one group, with no holes in the set."""
    claimed: list[str] = [aid for group in groups for aid in group.attribute_ids]
    duplicates = sorted({aid for aid in claimed if claimed.count(aid) > 1})
    if duplicates:
        raise ValueError(f"attributes claimed by more than one group: {', '.join(duplicates)}")
    numbers = sorted(int(aid.removeprefix("PA")) for aid in claimed)
    missing = sorted(set(range(1, numbers[-1] + 1)) - set(numbers))
    if missing:
        raise ValueError(
            "attributes belonging to no group: " + ", ".join(f"PA{n}" for n in missing)
        )
