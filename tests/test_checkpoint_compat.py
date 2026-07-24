"""The interim checkpoint-allowlist shim (plan decision B).

These tests pin the shim's mechanics offline; that it actually makes an
interview survive a real process restart is witnessed live in
the predecessor project's restart-survival record.
"""

import agent_framework_foundry_hosting._responses as host_responses
from agent_framework._workflows._checkpoint_encoding import (
    decode_checkpoint_value,
    encode_checkpoint_value,
)

from foundry_agent.checkpoint_compat import (
    WORKFLOW_CHECKPOINT_TYPE_NAMES,
    install_checkpoint_type_allowlist,
)
from foundry_agent.workflow import Run


def test_type_names_cover_every_witnessed_blocked_type():
    """Both rounds of witnessed blocks: state dataclasses and nested models."""
    for name in (
        "foundry_agent.workflow:Run",
        "foundry_agent.workflow:ConversationPause",
        "foundry_agent.models:CapturedValue",
        "foundry_agent.models:CaptureStatus",
    ):
        assert name in WORKFLOW_CHECKPOINT_TYPE_NAMES


def test_install_merges_workflow_types_into_the_host_allowlist(monkeypatch, tmp_path):
    """After install, storage the host builds permits our types on top of its own."""
    captured: dict[str, list[str]] = {}

    class _FakeStorage:
        def __init__(self, storage_path, *, allowed_checkpoint_types=None, **kwargs):
            captured["allowed"] = list(allowed_checkpoint_types or [])

    monkeypatch.setattr(host_responses, "FileCheckpointStorage", _FakeStorage)

    install_checkpoint_type_allowlist()

    # The host constructs with its own narrow allowlist; our shim must add to it.
    host_responses.FileCheckpointStorage(tmp_path, allowed_checkpoint_types=["host:Type"])

    assert "host:Type" in captured["allowed"]
    assert "foundry_agent.workflow:Run" in captured["allowed"]


def test_install_is_idempotent(monkeypatch, tmp_path):
    class _FakeStorage:
        def __init__(self, storage_path, *, allowed_checkpoint_types=None, **kwargs):
            pass

    monkeypatch.setattr(host_responses, "FileCheckpointStorage", _FakeStorage)

    install_checkpoint_type_allowlist()
    once = host_responses.FileCheckpointStorage
    install_checkpoint_type_allowlist()

    assert host_responses.FileCheckpointStorage is once


def test_legacy_run_payload_with_removed_field_still_restores():
    """A Run checkpointed before ``validation_rounds`` was removed must decode.

    Checkpoints pickle state dataclasses (state dict, no ``__init__`` call), so
    an old payload carries the removed field as a stray attribute. It must
    restore cleanly and the stray must not shadow any live field — which is
    what makes single-pass validation's field removal safe across a restart.
    """
    legacy = Run(content="doc")
    legacy.__dict__["validation_rounds"] = 3  # a removed field, as an old pickle carries it

    restored = decode_checkpoint_value(
        encode_checkpoint_value(legacy),
        allowed_types=frozenset(WORKFLOW_CHECKPOINT_TYPE_NAMES),
    )

    assert isinstance(restored, Run)
    assert restored.content == "doc"
    assert restored.unresolved_ids == []  # a live field decoded to its default


def test_install_degrades_gracefully_if_the_seam_is_gone(monkeypatch, caplog):
    """A future host without the reference must warn, not crash startup."""
    monkeypatch.setattr(host_responses, "FileCheckpointStorage", None)

    install_checkpoint_type_allowlist()  # must not raise

    assert host_responses.FileCheckpointStorage is None
