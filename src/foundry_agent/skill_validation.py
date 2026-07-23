"""The workflow's only touch of a skill's validation script — domain-neutral.

The RULES a validation script enforces are skill content
(``<format skill>/validation/validate.py``, e.g.
:mod:`skills.policy-report-format.validation.validate`), not code here. This
module only knows how to *load* that script and *bind* it to one run's
discovered groups as a plain callable the Validation agent can call as a tool
— swap the loaded skill and its own validation rules travel with it; this
module contains no attribute ids, enums, or thresholds of its own.

Security: importing and executing a skill's script is safe ONLY because
skills ship inside this repository and are trusted — see the mounted format
skill's own ``validation/SECURITY.md``. Never point this at a skill from an
untrusted source without first sandboxing the import.
"""

import importlib.util
from collections.abc import Callable
from pathlib import Path
from typing import Protocol


class SkillValidator(Protocol):
    """The contract a skill's ``validation/validate.py`` module must expose."""

    def validate(self, captured_values: dict[str, str], groups: list[dict]) -> list[str]:
        """Return the attribute ids that fail the skill's deterministic rules."""
        ...


def load_skill_validator(skill_dir: Path) -> SkillValidator:
    """Import a skill's ``validation/validate.py`` and return the loaded module.

    Called ONCE, at workflow-build time, so a skill that ships no validation
    script — or one that fails to import — fails fast at startup rather than
    partway through an interview.

    Raises:
        FileNotFoundError: The skill ships no ``validation/validate.py``.
        ImportError: The script could not be loaded.
        AttributeError: The loaded module has no top-level ``validate`` function.
    """
    path = skill_dir / "validation" / "validate.py"
    if not path.is_file():
        raise FileNotFoundError(
            f"{skill_dir.name} ships no validation/validate.py — every format skill "
            "mounted by this workflow must provide one"
        )
    spec = importlib.util.spec_from_file_location(f"{skill_dir.name}_validate", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load a module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "validate", None)):
        raise AttributeError(f"{path} has no top-level 'validate' function")
    return module  # type: ignore[return-value]


def bind_skill_validation_tool(
    validator: SkillValidator, groups: list[dict]
) -> Callable[[dict[str, str]], list[str]]:
    """Bind the loaded validator to one run's discovered groups as a plain tool function.

    Cheap and pure (no I/O) — call it fresh for each validation turn with that
    run's own ``groups``, then pass the result to the Validation agent via
    ``ChatOptions(tools=[...])``. The Agent Framework derives the tool's name
    and schema from the function's signature and docstring, so both matter to
    the model, not just to a human reader.
    """

    def run_skill_validation(captured_values: dict[str, str]) -> list[str]:
        """Run the format skill's own deterministic validation rules.

        Args:
            captured_values: Every attribute id and its current value, as
                extracted from the candidate content — e.g.
                {"<id>": "<value>", ...} keyed by the format skill's own
                attribute ids. Include every attribute the content populates,
                not only the ones you suspect are wrong.

        Returns:
            The attribute ids that fail the skill's deterministic rules —
            missing, a placeholder, or a broken format rule (e.g. a title
            over the word cap). An empty list means every deterministic
            rule passes.
        """
        return validator.validate(captured_values, groups)

    return run_skill_validation
