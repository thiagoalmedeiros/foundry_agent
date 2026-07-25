"""Contract tests for the structured-output models."""

from foundry_agent.models import (
    CapturedValue,
    CaptureStatus,
    ConversationTurn,
    Finding,
    Severity,
    ValidationResult,
)


def test_validation_result_defaults_to_empty_gap_lists():
    result = ValidationResult(complete=True, rationale="All required attributes populated.")

    assert result.missing_attribute_ids == []
    assert result.advisory_findings == []


def test_finding_defaults_to_advisory_severity():
    finding = Finding(reference_id="PC5", summary="Names a vendor in the statement.")

    assert finding.severity is Severity.ADVISORY


def test_conversation_turn_round_trips_through_json():
    turn = ConversationTurn(
        message="What should we call this record?",
        conversation_complete=False,
        captured=[CapturedValue(attribute_id="PA1", value="REC-001")],
    )

    restored = ConversationTurn.model_validate_json(turn.model_dump_json())

    assert restored == turn
    assert restored.captured[0].status is CaptureStatus.CLOSED
