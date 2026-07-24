"""The format skill's validation script, on the MAF-native execution path.

Three layers, all against the REAL ``policy-report-format`` skill — the point
is that the script the provider advertises actually runs and returns the
domain's verdicts:

- direct ``validate()`` behavior (the domain rules themselves),
- the CLI contract (``python validate.py '<captured>' '<groups>'`` → JSON on
  stdout, exit 0; malformed argv → exit 2 + stderr),
- the subprocess runner end-to-end through ``FileSkillsSource`` discovery,
  witnessing ``run_skill_script``'s path executes the discovered script.
"""

import importlib.util
import json
import subprocess
import sys

from agent_framework import FileSkillsSource, SkillsSourceContext

from foundry_agent.agents import (
    FORMAT_SKILL_DIR,
    _run_python_skill_script,
    create_validation_agent,
    validate_document,
)
from foundry_agent.prompts import VALIDATION_INSTRUCTIONS, VALIDATION_SCRIPT_NAME
from tests.conftest import COMPLETE_VALIDATION, GROUPS

SCRIPT_PATH = FORMAT_SKILL_DIR / "validation" / "validate.py"

_spec = importlib.util.spec_from_file_location("policy_report_validate", SCRIPT_PATH)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
validate = _module.validate

# Eight groups jointly covering PA1-PA32 exactly once, like the real skill's FG1-FG8.
_GROUP_BOUNDS = [(1, 7), (7, 11), (11, 15), (15, 18), (18, 21), (21, 25), (25, 29), (29, 33)]
_GROUPS = [{"attribute_ids": [f"PA{n}" for n in range(lo, hi)]} for lo, hi in _GROUP_BOUNDS]


def _fully_valid() -> dict[str, str]:
    values = {f"PA{n}": f"substantive value {n}" for n in range(1, 33)}
    values["PA2"] = "Remote Work Security Policy"
    values["PA3"] = "Security"
    values["PA9"] = "None"
    values["PA15"] = "None"
    values["PA20"] = "No exceptions"
    return values


# --- direct validate() behavior (the domain rules themselves) ---


def test_a_fully_valid_capture_set_passes():
    assert validate(_fully_valid(), _GROUPS) == []


def test_a_missing_required_attribute_fails():
    values = _fully_valid()
    del values["PA21"]

    assert validate(values, _GROUPS) == ["PA21"]


def test_a_placeholder_value_fails():
    values = _fully_valid()
    values["PA25"] = "TBD"

    assert validate(values, _GROUPS) == ["PA25"]


def test_conditional_attribute_required_only_when_its_condition_holds():
    """PA13 is required only for a Compliance policy type."""
    security = _fully_valid()
    security["PA13"] = ""
    assert validate(security, _GROUPS) == [], "PA13 must not block a Security-type policy"

    compliance = _fully_valid()
    compliance["PA3"] = "Compliance"
    compliance["PA13"] = ""
    assert "PA13" in validate(compliance, _GROUPS), "PA13 must block a Compliance-type policy"


def test_skill_sanctioned_none_is_not_a_placeholder():
    """attributes.md admits the literal 'None' for PA9 and PA15."""
    values = _fully_valid()
    values["PA9"] = "None"
    values["PA15"] = "None"

    assert validate(values, _GROUPS) == []


def test_scope_comes_only_from_the_given_groups():
    """Only attributes the given groups claim can be reported missing."""
    assert validate({}, [{"attribute_ids": ["PA1"]}]) == ["PA1"]


# --- the CLI contract (what run_skill_script's subprocess actually invokes) ---


def _run_cli(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *argv],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_round_trip_returns_failing_ids_as_json():
    values = _fully_valid()
    del values["PA21"]

    result = _run_cli(json.dumps(values), json.dumps(_GROUPS))

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["PA21"]


def test_cli_fully_valid_returns_an_empty_json_array():
    result = _run_cli(json.dumps(_fully_valid()), json.dumps(_GROUPS))

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_cli_malformed_argv_exits_2_with_a_usage_line():
    result = _run_cli("{not json")

    assert result.returncode == 2
    assert "usage: validate.py" in result.stderr


def test_cli_wrong_json_shapes_exit_2():
    """A JSON array where the object belongs (and vice versa) is a usage error."""
    result = _run_cli(json.dumps([]), json.dumps({}))

    assert result.returncode == 2
    assert "usage: validate.py" in result.stderr


# --- the runner, end-to-end through real FileSkillsSource discovery ---


async def _discovered_validate_script():
    """The (skill, script) pair the provider would resolve for run_skill_script."""
    source = FileSkillsSource([str(FORMAT_SKILL_DIR)], script_runner=_run_python_skill_script)
    # File discovery ignores the invoking agent; the context only feeds
    # filtering/caching decorators this test does not use.
    skills = await source.get_skills(SkillsSourceContext(agent=None))
    skill = next(s for s in skills if s.frontmatter.name == "policy-report-format")
    # Discovered scripts are named by their skill-relative path.
    script = await skill.get_script("validation/validate.py")
    assert script is not None, "validation/validate.py was not discovered as a skill script"
    return skill, script


async def test_runner_executes_the_discovered_script_end_to_end():
    """DoD criterion 4: run_skill_script → subprocess → JSON verdict back."""
    skill, script = await _discovered_validate_script()
    values = _fully_valid()
    del values["PA21"]

    verdict = await _run_python_skill_script(
        skill, script, [json.dumps(values), json.dumps(_GROUPS)]
    )

    assert verdict == ["PA21"]


async def test_runner_reserializes_dict_and_parsed_json_arguments():
    """A model may send a dict of parsed values instead of a list of JSON strings."""
    skill, script = await _discovered_validate_script()

    verdict = await _run_python_skill_script(
        skill, script, {"captured_values": _fully_valid(), "groups": _GROUPS}
    )

    assert verdict == []


async def test_runner_surfaces_script_failures_as_error_strings():
    """Bad arguments come back as a retryable error string, not an exception."""
    skill, script = await _discovered_validate_script()

    verdict = await _run_python_skill_script(skill, script, ["{not json"])

    assert isinstance(verdict, str)
    assert verdict.startswith("Error:")
    assert "usage: validate.py" in verdict


async def test_runner_flags_a_dict_whose_key_order_is_wrong():
    """Dict args ride in insertion order; a flipped order must fail loudly, not misvalidate."""
    skill, script = await _discovered_validate_script()

    verdict = await _run_python_skill_script(
        skill, script, {"groups": _GROUPS, "captured_values": _fully_valid()}
    )

    assert isinstance(verdict, str)
    assert verdict.startswith("Error:")


# --- the prompt/discovery contract (drift guards) ---


async def test_prompt_names_exactly_the_discovered_script():
    """VALIDATION_INSTRUCTIONS and FileSkillsSource discovery must agree on the
    script's name — if the script moves, this is the test that fails instead of
    every live validation call."""
    _, script = await _discovered_validate_script()

    assert script.name == VALIDATION_SCRIPT_NAME
    assert VALIDATION_SCRIPT_NAME in VALIDATION_INSTRUCTIONS


async def test_validation_without_a_script_call_logs_a_warning(make_stub_client, caplog):
    """A response that never ran the script is flagged — the deterministic
    check silently not running is the failure mode the warning exists for."""
    client = make_stub_client(COMPLETE_VALIDATION)

    await validate_document(create_validation_agent(client), "any input", GROUPS.groups)

    assert "did not call run_skill_script" in caplog.text
