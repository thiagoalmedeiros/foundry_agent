"""Contract tests for the structured-output models."""

import pytest
from pydantic import ValidationError

from foundry_agent.models import (
    AttributeStatus,
    Finding,
    GapReport,
    Severity,
    ValidationResult,
)


def _status(attribute_id: str, *, required: bool, populated: bool) -> AttributeStatus:
    return AttributeStatus(
        attribute_id=attribute_id,
        name=f"Attribute {attribute_id}",
        required=required,
        populated=populated,
    )


def test_gap_report_round_trips_through_json():
    report = GapReport(
        classification="Security",
        attributes=[_status("PA1", required=True, populated=True)],
        findings=[Finding(reference_id="PC5", summary="Names a vendor in the statement.")],
    )

    restored = GapReport.model_validate_json(report.model_dump_json())

    assert restored == report
    assert restored.findings[0].severity is Severity.ADVISORY


def test_missing_required_returns_only_required_unpopulated_attributes():
    report = GapReport(
        classification="Opportunity",
        attributes=[
            _status("PA1", required=True, populated=True),
            _status("PA7", required=True, populated=False),
            _status("PA13", required=False, populated=False),
        ],
    )

    assert [a.attribute_id for a in report.missing_required()] == ["PA7"]


def test_validation_result_defaults_to_empty_gap_lists():
    result = ValidationResult(complete=True, rationale="All required attributes populated.")

    assert result.missing_attribute_ids == []
    assert result.advisory_findings == []


def test_gap_report_rejects_missing_classification():
    with pytest.raises(ValidationError):
        GapReport.model_validate({"attributes": []})
