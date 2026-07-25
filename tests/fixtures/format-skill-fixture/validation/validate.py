"""Minimal domain-neutral validation script — a test fixture, not a real skill.

Exists only so the workflow's ``run_skill_script`` machinery has a real script to
discover and execute: it returns the in-scope attribute ids whose captured value
is empty or a placeholder. No domain rules, no enums — validating a real domain
skill's content is out of scope for this repo. Mirrors the CLI contract every
format skill's ``validation/validate.py`` must honour (JSON on stdout / exit 0;
malformed argv / exit 2 + stderr).
"""

_PLACEHOLDERS = frozenset({"", "tbd", "todo", "n/a", "-", "?"})


def validate(captured_values: dict[str, str], groups: list[dict]) -> list[str]:
    """Return the in-scope attribute ids whose value is empty or a placeholder.

    In-scope order is preserved (deduplicated) so the CLI output is deterministic.
    """
    in_scope = [aid for group in groups for aid in group.get("attribute_ids", [])]
    return [
        attribute_id
        for attribute_id in dict.fromkeys(in_scope)
        if captured_values.get(attribute_id, "").strip().lower() in _PLACEHOLDERS
    ]


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
