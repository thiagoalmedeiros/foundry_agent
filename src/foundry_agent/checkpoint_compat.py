"""Interim shim: let hosted checkpoints restore this workflow's own state types.

**This is a temporary patch pending an upstream fix** (plan decision B). The
Foundry host serializes workflow checkpoints with
:class:`~agent_framework.FileCheckpointStorage`, which — for safety — only
*deserializes* a fixed allowlist of types (primitives, ``agent_framework``
internals, OpenAI types) plus one Azure role enum the host adds itself. Our
workflow puts its own dataclasses on the wire (:class:`Run`,
:class:`Analyzed`, :class:`ConversationPause`, …), so on restart the host cannot
read its own checkpoint back and the interview silently restarts from question
one (witnessed in the predecessor project's restart-survival record).

The host builds that storage internally and hardcodes its allowlist, with no
public hook to extend it. Until ``agent-framework-foundry-hosting`` accepts a
caller-supplied ``allowed_checkpoint_types`` (the upstream ask), this module
wraps the single ``FileCheckpointStorage`` reference the host constructs
through, merging this workflow's types into whatever allowlist the host
already passes. It touches only decode permissions — no serving code, no
framework behaviour beyond widening the allowlist.

Remove this module and its call in :mod:`~foundry_agent.hosting` once the
upstream package exposes the hook.
"""

import enum
import inspect
import logging

import agent_framework_foundry_hosting._responses as _host_responses
from pydantic import BaseModel

from foundry_agent import models as _models
from foundry_agent.workflow import (
    Assemble,
    ConversationPause,
    Elicited,
    Run,
)

logger = logging.getLogger(__name__)


def _model_type_names() -> tuple[str, ...]:
    """Every checkpointable structured-output type from :mod:`models`.

    The workflow's state dataclasses nest these (a :class:`ConversationPause`
    carries :class:`CapturedValue`s, which carry a :class:`CaptureStatus`, …),
    so they must be restorable too. Enumerated from the module so a new model is
    covered automatically.
    """
    return tuple(
        f"{obj.__module__}:{obj.__qualname__}"
        for obj in vars(_models).values()
        if inspect.isclass(obj)
        and obj.__module__ == _models.__name__
        and issubclass(obj, (BaseModel, enum.Enum))
    )


#: Every workflow message/state dataclass that can land in a checkpoint, plus
#: the structured-output types they nest, in ``"module:qualname"`` form.
#: Derived from the classes themselves so a rename cannot silently drop one.
_STATE_TYPES = (Run, Elicited, Assemble, ConversationPause)
WORKFLOW_CHECKPOINT_TYPE_NAMES: tuple[str, ...] = (
    *(f"{cls.__module__}:{cls.__qualname__}" for cls in _STATE_TYPES),
    *_model_type_names(),
)

#: Set on the patched class so a second install is a no-op.
_PATCH_MARKER = "_foundry_agent_allowlist_patched"


def install_checkpoint_type_allowlist() -> None:
    """Widen the host's checkpoint allowlist to cover this workflow's types.

    Idempotent. Replaces the ``FileCheckpointStorage`` name the host module
    references with a subclass that appends
    :data:`WORKFLOW_CHECKPOINT_TYPE_NAMES` to whatever ``allowed_checkpoint_types``
    the host passes at construction time.

    If the host's storage-construction shape has changed (the reference is
    gone), logs a warning rather than raising — the shim degrades to a no-op
    and restart survival regresses visibly rather than crashing startup.
    """
    base = getattr(_host_responses, "FileCheckpointStorage", None)
    if base is None:
        logger.warning(
            "checkpoint compat shim: agent_framework_foundry_hosting._responses no longer "
            "exposes FileCheckpointStorage; workflow state will NOT survive a restart. "
            "The upstream API changed — revisit the shim."
        )
        return
    if getattr(base, _PATCH_MARKER, False):
        return

    extra = WORKFLOW_CHECKPOINT_TYPE_NAMES

    class _AllowlistedCheckpointStorage(base):  # type: ignore[valid-type, misc]
        """Host checkpoint storage that also permits this workflow's types."""

        def __init__(self, storage_path, *, allowed_checkpoint_types=None, **kwargs):
            merged = [*(allowed_checkpoint_types or []), *extra]
            super().__init__(storage_path, allowed_checkpoint_types=merged, **kwargs)

    setattr(_AllowlistedCheckpointStorage, _PATCH_MARKER, True)
    _host_responses.FileCheckpointStorage = _AllowlistedCheckpointStorage
    logger.info(
        "checkpoint compat shim installed: %d workflow types added to the host allowlist",
        len(extra),
    )
