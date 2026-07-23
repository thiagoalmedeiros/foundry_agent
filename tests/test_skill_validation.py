"""The workflow's binding to a skill's validation script — domain-neutral.

Exercised against the REAL ``policy-report-format`` skill (via conftest's
``VALIDATOR``), not a fake — the module's whole job is to import and run
exactly this kind of file correctly.
"""

import pytest

from foundry_agent.agents import FORMAT_SKILL_DIR
from foundry_agent.skill_validation import bind_skill_validation_tool, load_skill_validator
from tests.conftest import VALIDATOR

_GROUPS = [
    {"attribute_ids": [f"PA{n}" for n in range(1, 7)]},
    {"attribute_ids": [f"PA{n}" for n in range(7, 11)]},
    {"attribute_ids": [f"PA{n}" for n in range(11, 15)]},
    {"attribute_ids": [f"PA{n}" for n in range(15, 18)]},
    {"attribute_ids": [f"PA{n}" for n in range(18, 21)]},
    {"attribute_ids": [f"PA{n}" for n in range(21, 25)]},
    {"attribute_ids": [f"PA{n}" for n in range(25, 29)]},
    {"attribute_ids": [f"PA{n}" for n in range(29, 33)]},
]


def _fully_valid() -> dict[str, str]:
    values = {f"PA{n}": f"substantive value {n}" for n in range(1, 33)}
    values["PA2"] = "Remote Work Security Policy"
    values["PA3"] = "Security"
    values["PA9"] = "None"
    values["PA15"] = "None"
    values["PA20"] = "No exceptions"
    return values


def test_load_skill_validator_returns_a_module_with_validate():
    validator = load_skill_validator(FORMAT_SKILL_DIR)

    assert callable(validator.validate)


def test_load_skill_validator_raises_when_the_skill_ships_no_script(tmp_path):
    with pytest.raises(FileNotFoundError, match="validation/validate.py"):
        load_skill_validator(tmp_path)


def test_bind_skill_validation_tool_returns_a_named_callable():
    tool = bind_skill_validation_tool(VALIDATOR, _GROUPS)

    assert tool.__name__ == "run_skill_validation"
    assert tool.__doc__  # the docstring IS the tool description an LLM reads


def test_bind_skill_validation_tool_docstring_carries_no_domain_example():
    """The tool description is what the LLM reads — it must stay skill-agnostic."""
    tool = bind_skill_validation_tool(VALIDATOR, _GROUPS)

    assert "PA1" not in tool.__doc__
    assert "Remote Work" not in tool.__doc__


def test_a_fully_valid_capture_set_passes():
    tool = bind_skill_validation_tool(VALIDATOR, _GROUPS)

    assert tool(_fully_valid()) == []


def test_a_missing_required_attribute_fails():
    tool = bind_skill_validation_tool(VALIDATOR, _GROUPS)
    values = _fully_valid()
    del values["PA21"]

    assert tool(values) == ["PA21"]


def test_a_placeholder_value_fails():
    tool = bind_skill_validation_tool(VALIDATOR, _GROUPS)
    values = _fully_valid()
    values["PA25"] = "TBD"

    assert tool(values) == ["PA25"]


def test_conditional_attribute_required_only_when_its_condition_holds():
    """PA13 is required only for a Compliance policy type."""
    tool = bind_skill_validation_tool(VALIDATOR, _GROUPS)

    security = _fully_valid()
    security["PA13"] = ""
    assert tool(security) == [], "PA13 must not block a Security-type policy"

    compliance = _fully_valid()
    compliance["PA3"] = "Compliance"
    compliance["PA13"] = ""
    assert "PA13" in tool(compliance), "PA13 must block a Compliance-type policy"


def test_skill_sanctioned_none_is_not_a_placeholder():
    """attributes.md admits the literal 'None' for PA9 and PA15."""
    tool = bind_skill_validation_tool(VALIDATOR, _GROUPS)
    values = _fully_valid()
    values["PA9"] = "None"
    values["PA15"] = "None"

    assert tool(values) == []


def test_bound_tool_is_independent_per_call_groups():
    """Two tools bound to different group sets must not share state."""
    narrow_groups = [{"attribute_ids": ["PA1"]}]
    tool = bind_skill_validation_tool(VALIDATOR, narrow_groups)

    # Only PA1 is in scope for this binding — nothing else can be reported missing.
    assert tool({}) == ["PA1"]
