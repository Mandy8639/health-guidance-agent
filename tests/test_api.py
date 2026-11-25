"""Tests for the FastAPI backend."""

from __future__ import annotations

from fastapi.testclient import TestClient

from health_guidance.api import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "agent": "health-guidance-agent"}


def test_list_cases_is_the_frozen_48() -> None:
    response = client.get("/api/cases")
    assert response.status_code == 200
    cases = response.json()
    assert len(cases) == 48
    decisions = {case["case_id"]: case["decision"] for case in cases}
    assert decisions["HG-001"] == "PROPOSE"
    assert decisions["HG-013"] == "HOLD"  # first misrouted case


def test_get_one_case() -> None:
    response = client.get("/api/cases/HG-001")
    assert response.status_code == 200
    body = response.json()
    assert body["case_id"] == "HG-001"
    assert body["guidance"] is not None
    assert body["records"]


def test_get_unknown_case_is_404() -> None:
    assert client.get("/api/cases/NOPE").status_code == 404


def test_intake_clean_request_proposes() -> None:
    response = client.post(
        "/api/intake",
        json={
            "request_text": "I want a gentler workout this week.",
            "requester_id": "REQ-01",
            "domain": "recovery",
            "freshness_target_days": 7,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["decision"] == "PROPOSE"
    assert body["published"] is True
    assert body["applied"] is False  # gate 2 not yet confirmed
    assert body["sent"] is False


def test_intake_red_flag_request_pauses() -> None:
    response = client.post(
        "/api/intake",
        json={
            "request_text": "My knee hurts when I walk — what should I do?",
            "requester_id": "REQ-01",
            "domain": "recovery",
            "freshness_target_days": 7,
        },
    )
    assert response.status_code == 201
    assert response.json()["decision"] == "PAUSE"


def test_intake_validation_errors() -> None:
    base = {
        "request_text": "What should my training look like this week?",
        "requester_id": "REQ-01",
        "domain": "recovery",
        "freshness_target_days": 7,
    }
    assert client.post("/api/intake", json={**base, "request_text": "  "}).status_code == 422
    assert client.post("/api/intake", json={**base, "requester_id": "REQ-99"}).status_code == 422
    assert client.post("/api/intake", json={**base, "domain": "nutrition"}).status_code == 422
    assert client.post("/api/intake", json={**base, "freshness_target_days": 0}).status_code == 422


def test_apply_gate_two() -> None:
    created = client.post(
        "/api/intake",
        json={
            "request_text": "I want a gentler workout this week.",
            "requester_id": "REQ-01",
            "domain": "recovery",
            "freshness_target_days": 7,
        },
    )
    case_id = created.json()["case_id"]
    response = client.post(f"/api/cases/{case_id}/apply")
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is True
    assert body["sent"] is True


def test_apply_non_propose_is_409() -> None:
    response = client.post("/api/cases/HG-013/apply")  # misrouted -> HOLD
    assert response.status_code == 409


def test_apply_unknown_case_is_404() -> None:
    assert client.post("/api/cases/NOPE/apply").status_code == 404


def test_audit_trail() -> None:
    response = client.get("/api/audit")
    assert response.status_code == 200
    entries = response.json()
    assert entries
    tools = {entry["tool"] for entry in entries}
    assert tools == {"member_data_search", "protocol_check", "guidance_draft"}
    assert [entry["seq"] for entry in entries] == list(range(1, len(entries) + 1))
