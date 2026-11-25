"""Shared fixtures for the health-guidance tests."""

from __future__ import annotations

import pytest

from health_guidance.agent import GuidanceAgent
from health_guidance.inventory import BY_ID


def record_dict(record_id: str) -> dict:
    record = dict(BY_ID[record_id])
    if record.get("schema") is not None:
        record["schema"] = [dict(c) for c in record["schema"]]
    record["facts"] = dict(record.get("facts", {}))
    record["restrictions"] = list(record.get("restrictions", []))
    return record


def clean_case() -> dict:
    """A clean recovery case: M001 and M004 both satisfy it."""
    return {
        "id": "HG-T01",
        "category": "clean",
        "requester_id": "REQ-01",
        "requester_name": "Jordan Ellis",
        "request_text": "What should my training look like this week?",
        "domain": "recovery",
        "freshness_target_days": 7,
        "records": [record_dict("M001"), record_dict("M004")],
        "notes": [
            {
                "text": "Record M001: Jordan Ellis. Resting HR 58 bpm, sleep "
                "7.4h/7d, activity 210 min/7d.",
                "source": "M001",
                "asserts": {
                    "resting_hr": 58,
                    "sleep_hours_7d": 7.4,
                    "activity_minutes_7d": 210,
                },
            },
            {
                "text": "The corpus lists M001 under Coach Maya Chen.",
                "source": "M001",
                "asserts": {"owner": "Coach Maya Chen"},
            },
        ],
        "claims": [
            {
                "text": "Northbridge Wellness Collective has an active coaching "
                "agreement covering this request.",
                "source": "agreement-001",
            }
        ],
        "required_evidence": ["M001:schema", "M001:freshness"],
        "remediation_needed": [],
        "required_metrics": [],
    }


@pytest.fixture
def agent() -> GuidanceAgent:
    return GuidanceAgent(mode="stub")
