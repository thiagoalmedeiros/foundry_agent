"""Police Incident Report validation — SKILL content, executed via ``run_skill_script``.

This module carries the *police-report* domain's deterministic acceptance
rules: which attributes are Required (a fixed two-level model — Required or
Optional, no conditional tier), which placeholder values do not count, and the
two closed-value fields (report status, case disposition). It lives in the
skill — not in ``src/foundry_agent`` — so the workflow stays domain-free: swap
the loaded skill and its own ``validate`` travels with it.

Contract: the Validation agent runs this file through the skill provider's
native ``run_skill_script`` tool, which executes it as a subprocess::

    python validate.py '<captured_values JSON>' '<groups JSON>'

stdout is a JSON array of the failing attribute ids (exit 0 — validation
findings are data, not process failure); malformed arguments exit 2 with a
one-line error on stderr so the calling agent can retry with corrected
arguments. The pure :func:`validate` stays importable and knows nothing about
the Agent Framework; ``__main__`` only wraps it.

Security: the framework's script runner executes this file as a subprocess.
That is acceptable ONLY because skills ship inside this repository and are
trusted — the same stance that disables ``SkillsProvider`` tool approvals for
in-repo skills. See ``SECURITY.md`` in this directory before mounting any
skill from an untrusted source.
"""

#: Values that fill a slot without informing (definitions.md "Placeholder").
_PLACEHOLDERS = frozenset({"tbd", "todo", "n/a", "na", "none", "placeholder", "-", "?", "xxx"})

#: Attributes attributes.md marks Optional — never Required, never blocking.
_OPTIONAL = frozenset({"PA9", "PA10", "PA12", "PA13", "PA14", "PA16", "PA20"})

#: PA3 Report Status must be exactly one of these (definitions.md, FG1 adequacy).
_REPORT_STATUSES = frozenset({"draft", "under review", "approved", "closed"})

#: PA17 Case Disposition must be exactly one of these (definitions.md).
_DISPOSITIONS = frozenset(
    {
        "open",
        "active",
        "cleared by arrest",
        "cleared by exception",
        "unfounded",
        "inactive",
        "referred",
        "closed",
    }
)


def validate(captured_values: dict[str, str], groups: list[dict]) -> list[str]:
    """Return the attribute ids that fail this domain's deterministic rules.

    An id is returned when a Required attribute is absent or holds a placeholder
    value, or when a present value breaks a closed-value rule (a report status
    or case disposition outside its sanctioned set). An empty list means every
    deterministic rule passes — the calling agent still judges substantive
    adequacy on top of this.

    Args:
        captured_values: ``{attribute_id: value}`` the interview has recorded.
        groups: The discovered groups, each a mapping carrying an
            ``"attribute_ids"`` sequence — the universe of attributes in play.
            Plain mappings (not framework objects) keep this script portable.

    Returns:
        The failing attribute ids, de-duplicated and ordered numerically
        (``PA2`` before ``PA10``).
    """
    in_scope = {aid for group in groups for aid in group.get("attribute_ids", [])}
    failing = {
        attribute_id
        for attribute_id in _required_ids(in_scope)
        if _is_placeholder(captured_values.get(attribute_id, ""))
    }

    status = captured_values.get("PA3", "").strip()
    if status and status.lower() not in _REPORT_STATUSES:
        failing.add("PA3")

    disposition = captured_values.get("PA17", "").strip()
    if disposition and disposition.lower() not in _DISPOSITIONS:
        failing.add("PA17")

    return sorted(failing, key=_order)


def _required_ids(in_scope: set[str]) -> set[str]:
    """The in-scope attributes that must be populated.

    Two-level model: everything in scope is Required except the Optional
    attributes (attributes.md). There is no conditional tier — a field that
    applies only to some incidents is Optional and never blocks.
    """
    return {attribute_id for attribute_id in in_scope if attribute_id not in _OPTIONAL}


def _is_placeholder(value: str) -> bool:
    """Whether ``value`` is empty or a placeholder token."""
    normalized = value.strip().lower()
    return not normalized or normalized in _PLACEHOLDERS


def _order(attribute_id: str) -> tuple[int, str]:
    """Sort key ordering ``PA2`` before ``PA10`` (numeric, not lexical)."""
    suffix = attribute_id.removeprefix("PA")
    return (int(suffix), "") if suffix.isdigit() else (2**31, attribute_id)


if __name__ == "__main__":
    import json
    import sys

    try:
        captured_values = json.loads(sys.argv[1])
        groups = json.loads(sys.argv[2])
        if not isinstance(captured_values, dict) or not isinstance(groups, list):
            raise ValueError("captured_values must be a JSON object and groups a JSON array")
    except (IndexError, ValueError) as error:
        print(
            f"usage: validate.py '<captured_values JSON object>' '<groups JSON array>' — {error}",
            file=sys.stderr,
        )
        sys.exit(2)
    print(json.dumps(validate(captured_values, groups)))
