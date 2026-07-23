"""Policy Report validation — SKILL content, executed via ``run_skill_script``.

This module carries the *policy-report* domain's deterministic acceptance
rules: which attributes are required (including the conditional ones), which
placeholder values do not count, the title word cap, and the policy-type enum.
It lives in the skill — not in ``src/foundry_agent`` — so the workflow stays
domain-free: swap the loaded skill and its own ``validate`` travels with it.

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

#: Attributes whose skill definition admits the literal value "None"
#: (attributes.md PA9 Exclusions, PA15 Key Terms). For these, "none" is a
#: substantive answer; every other placeholder token still fails.
_NONE_ALLOWED = frozenset({"PA9", "PA15"})

#: PA3 Policy Type must be exactly one of these (definitions.md, FG1 adequacy).
_POLICY_TYPES = frozenset({"governance", "operational", "security", "compliance"})

#: Attributes attributes.md marks Optional — never required, never blocking.
_OPTIONAL = frozenset({"PA16", "PA17", "PA19", "PA24", "PA30", "PA32"})

#: PA2 Title word cap (FG1 adequacy: "PA2 <= 10 words").
_TITLE_MAX_WORDS = 10


def validate(captured_values: dict[str, str], groups: list[dict]) -> list[str]:
    """Return the attribute ids that fail this domain's deterministic rules.

    An id is returned when a required attribute is absent or holds a placeholder
    value, or when a present value breaks a deterministic rule (the title over
    the word cap, or a policy type outside the enum). An empty list means every
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
        for attribute_id in _required_ids(in_scope, captured_values)
        if _is_placeholder(attribute_id, captured_values.get(attribute_id, ""))
    }

    title = captured_values.get("PA2", "").strip()
    if title and len(title.split()) > _TITLE_MAX_WORDS:
        failing.add("PA2")

    policy_type = captured_values.get("PA3", "").strip()
    if policy_type and policy_type.lower() not in _POLICY_TYPES:
        failing.add("PA3")

    return sorted(failing, key=_order)


def _required_ids(in_scope: set[str], captured: dict[str, str]) -> set[str]:
    """The in-scope attributes that must be populated for this input.

    Everything in scope is required except the Optional attributes and any
    conditional attribute whose condition does not hold for the captured
    content (attributes.md): PA13 only when the policy type is Compliance,
    PA27 only when PA20 allows exceptions, PA28 only when the policy type is
    Security or Compliance.
    """
    policy_type = captured.get("PA3", "").strip().lower()
    exceptions = captured.get("PA20", "").strip().lower()
    exceptions_allowed = bool(exceptions) and "no exception" not in exceptions

    required: set[str] = set()
    for attribute_id in in_scope:
        if attribute_id in _OPTIONAL:
            continue
        if attribute_id == "PA13" and policy_type != "compliance":
            continue
        if attribute_id == "PA27" and not exceptions_allowed:
            continue
        if attribute_id == "PA28" and policy_type not in {"security", "compliance"}:
            continue
        required.add(attribute_id)
    return required


def _is_placeholder(attribute_id: str, value: str) -> bool:
    """Whether ``value`` is empty or a placeholder for this attribute."""
    normalized = value.strip().lower()
    if not normalized:
        return True
    tokens = _PLACEHOLDERS - {"none"} if attribute_id in _NONE_ALLOWED else _PLACEHOLDERS
    return normalized in tokens


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
