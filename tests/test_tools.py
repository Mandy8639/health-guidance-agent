"""Tests for the three allowlisted tools."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from health_guidance.packet import case_from_dict
from health_guidance.tools import (
    ALLOWED_TOOLS,
    WorkoutSubmission,
    exercise_search,
    fitting_records,
    guidance_draft,
    member_data_search,
    protocol_check,
    read_case,
    record_by_id,
)
from tests.conftest import clean_case, record_dict


def test_exactly_three_allowlisted_tools() -> None:
    assert ALLOWED_TOOLS == ("member_data_search", "protocol_check", "guidance_draft")


def test_member_data_search_returns_freshest_first() -> None:
    case = case_from_dict(clean_case())
    matches = member_data_search(case)
    assert [m.record.id for m in matches] == ["M001", "M004"]


def test_member_data_search_excludes_other_domain() -> None:
    case_data = clean_case()
    case_data["records"] = [record_dict("M002")]  # strength, case is recovery
    assert member_data_search(case_from_dict(case_data)) == []


def test_member_data_search_excludes_restricted_record() -> None:
    case_data = clean_case()
    case_data["records"] = [record_dict("M012")]  # visible to REQ-02 only
    case_data["domain"] = "strength"
    assert member_data_search(case_from_dict(case_data)) == []


def test_member_data_search_excludes_duplicates() -> None:
    case_data = clean_case()
    case_data["records"] = [record_dict("D001")]  # duplicate of M001
    assert member_data_search(case_from_dict(case_data)) == []


def test_member_data_search_excludes_unknown_schema_and_freshness() -> None:
    case_data = clean_case()
    case_data["records"] = [record_dict("M017")]  # schema unknown
    assert member_data_search(case_from_dict(case_data)) == []
    case_data["records"] = [record_dict("M006")]  # freshness unknown
    assert member_data_search(case_from_dict(case_data)) == []


def test_member_data_search_excludes_stale_records() -> None:
    case_data = clean_case()
    case_data["records"] = [record_dict("M013")]  # 10d stale, domain max 7d
    case_data["domain"] = "cardio"
    assert member_data_search(case_from_dict(case_data)) == []


def test_exercise_search_matches_muscle_keyword() -> None:
    case_data = clean_case()
    case_data["request_text"] = "I want a low-impact leg workout."
    case = case_from_dict(case_data)
    member = case.records[0]
    exercises = exercise_search(case, member)
    assert exercises
    assert all(e.muscle_group == "legs" for e in exercises)
    assert exercises[0].name == "Bodyweight squat"


def test_exercise_search_excludes_high_impact_for_restricted_member() -> None:
    case_data = clean_case()
    case_data["request_text"] = "Give me a leg workout."
    case_data["records"] = [record_dict("M005")]  # no high-impact (knee injury)
    case_data["domain"] = "strength"
    case = case_from_dict(case_data)
    exercises = exercise_search(case, case.records[0])
    assert exercises
    assert all(e.impact != "high" for e in exercises)


def test_exercise_search_without_keyword_returns_all_safe() -> None:
    case = case_from_dict(clean_case())
    exercises = exercise_search(case, case.records[0])
    assert len(exercises) == 18


def test_protocol_check_returns_validated_workout() -> None:
    case = case_from_dict(clean_case())
    check = protocol_check(case)
    assert check.safe is True
    assert check.contraindications == []
    assert check.workout is not None
    assert check.workout.exercise_id
    assert check.protocol_id == "P001"  # first corpus protocol for recovery


def test_protocol_check_flags_contraindication() -> None:
    case_data = clean_case()
    case_data["request_text"] = "Give me a high-impact leg workout."
    case_data["records"] = [record_dict("M005")]  # no high-impact (knee injury)
    case_data["domain"] = "strength"
    check = protocol_check(case_from_dict(case_data))
    assert check.safe is False
    assert len(check.contraindications) == 1
    assert "knee injury" in check.contraindications[0]
    assert check.workout is None


def test_protocol_check_raises_without_matching_member() -> None:
    case_data = clean_case()
    case_data["records"] = [record_dict("M012")]  # restricted, no match
    case_data["domain"] = "strength"
    with pytest.raises(ValueError, match="no governed member record"):
        protocol_check(case_from_dict(case_data))


def test_guidance_draft_is_draft_only() -> None:
    case = case_from_dict(clean_case())
    guidance = guidance_draft(case, "M001")
    assert guidance.status == "draft"
    assert guidance.shared is False
    assert guidance.sent is False
    assert guidance.coach_message.sent is False
    assert guidance.member_id == "M001"
    assert guidance.workout is not None


def test_guidance_draft_redacts_pii() -> None:
    case_data = clean_case()
    case_data["records"] = [record_dict("M002")]  # description carries email + phone
    case_data["domain"] = "strength"
    case_data["requester_id"] = "REQ-02"
    case_data["requester_name"] = "Priya Raman"
    case_data["required_evidence"] = ["M002:schema", "M002:freshness"]
    guidance = guidance_draft(case_from_dict(case_data), "M002")
    assert "p.raman@northbridge-wellness.example" not in guidance.summary
    assert "212-555-0147" not in guidance.summary
    assert "[EMAIL REDACTED]" in guidance.summary
    assert "[PHONE REDACTED]" in guidance.summary
    assert "p.raman@northbridge-wellness.example" not in guidance.coach_message.body


def test_guidance_draft_raises_for_non_matching_member() -> None:
    case = case_from_dict(clean_case())
    with pytest.raises(ValueError, match="not a confirmed match"):
        guidance_draft(case, "M012")


def test_workout_submission_rejects_bad_ranges() -> None:
    with pytest.raises(ValidationError):
        WorkoutSubmission(
            exercise_id="E001",
            exercise_name="Bodyweight squat",
            sets=0,
            reps=12,
            duration_min=20,
            intensity="low",
            rest_seconds=60,
        )
    with pytest.raises(ValidationError):
        WorkoutSubmission(
            exercise_id="E001",
            exercise_name="Bodyweight squat",
            sets=3,
            reps=12,
            duration_min=20,
            intensity="extreme",
            rest_seconds=60,
        )


def test_read_case_rejects_malformed_cases() -> None:
    case_data = clean_case()
    del case_data["request_text"]
    with pytest.raises(ValueError, match="missing required field"):
        read_case(case_data)
    case_data = clean_case()
    case_data["requester_id"] = "REQ-99"
    with pytest.raises(ValueError, match="unknown requester"):
        read_case(case_data)
    case_data = clean_case()
    case_data["domain"] = "nutrition"
    with pytest.raises(ValueError, match="unknown domain"):
        read_case(case_data)


def test_record_by_id() -> None:
    record = record_by_id("M001")
    assert record.id == "M001"
    assert record.kind == "member"
    with pytest.raises(ValueError, match="unknown record"):
        record_by_id("M999")


def test_fitting_records() -> None:
    records = fitting_records("REQ-01", "recovery", 7)
    assert records
    assert all(r["kind"] == "member" for r in records)
    assert all(r["domain"] == "recovery" for r in records)
    freshness = [r["freshness_days"] for r in records]
    assert freshness == sorted(freshness)  # freshest first
    assert records[0]["id"] == "M020"  # freshest recovery member (1d)
