"""FastAPI backend for the health-guidance agent.

A JSON API over the agent:

- ``GET /api/health`` — liveness.
- ``GET /api/cases`` — the guidance queue: every case the agent has
  seen (the 48 frozen eval cases, seeded at startup, plus any case
  submitted through the intake form), with its decision and gate state.
- ``GET /api/cases/{case_id}`` — one case, with its guidance if any.
- ``POST /api/intake`` — submit a one-sentence member request. The
  submit is gate 1: a human coach confirms the guidance may be prepared
  and queued for the coach. Nothing is sent to the member.
- ``POST /api/cases/{case_id}/apply`` — gate 2: a second explicit
  confirmation before the workout plan is changed and the guidance
  message is sent to the member. Only a PROPOSE case can be applied.
- ``GET /api/audit`` — the real audit trail: every tool call, in order.

Run: ``uvicorn health_guidance.api:app --reload`` (from the repo root,
after ``pip install -e .``).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from health_guidance.agent import AgentResult, GuidanceAgent
from health_guidance.inventory import DOMAINS, REQUESTER_BY_ID
from health_guidance.tools import fitting_records

ROOT = Path(__file__).resolve().parents[2]

app = FastAPI(title="health-guidance-agent")

_AGENT = GuidanceAgent(mode="stub")
_CASES: dict[str, dict] = {}
_INTAKE_COUNTER = 0


class IntakeRequest(BaseModel):
    """A one-sentence member request from the intake form."""

    request_text: str
    requester_id: str
    domain: str
    freshness_target_days: int


def _summarise(case: dict, result: AgentResult) -> dict:
    """The JSON view of one case and its agent result."""
    summary: dict = {
        "case_id": case["id"],
        "category": case["category"],
        "domain": case["domain"],
        "request_text": case["request_text"],
        "requester_id": case["requester_id"],
        "requester_name": case["requester_name"],
        "freshness_target_days": case["freshness_target_days"],
        "decision": result.decision,
        "published": result.published,
        "applied": result.applied,
        "sent": result.sent,
        "spend_usd": result.spend_usd,
        "gates_checked": result.gates_checked,
        "refusal": result.refusal,
        "flags": result.flags,
        "provenance": result.provenance,
        "guidance": asdict(result.guidance) if result.guidance is not None else None,
    }
    return summary


def _load_seed() -> None:
    """Seed the queue with the frozen 48-case eval set, drafted only.

    Each case is run with gate 1 approved (the guidance may be prepared
    and queued) and gate 2 denied (no plan is changed, nothing is sent).
    """
    golden_path = ROOT / "eval" / "golden.json"
    if not golden_path.exists():
        return
    cases = json.loads(golden_path.read_text(encoding="utf-8"))
    for case in cases:
        result = _AGENT.run(case, approve_guidance=True, approve_send=False)
        _CASES[case["id"]] = {"case": case, "result": result}


_load_seed()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "agent": "health-guidance-agent"}


@app.get("/api/cases")
def list_cases() -> list[dict]:
    return [_summarise(entry["case"], entry["result"]) for entry in _CASES.values()]


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict:
    entry = _CASES.get(case_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown case: {case_id}")
    summary = _summarise(entry["case"], entry["result"])
    summary["records"] = entry["case"]["records"]
    return summary


@app.post("/api/intake", status_code=201)
def submit_intake(payload: IntakeRequest) -> dict:
    """Gate 1: submit a member request; the agent drafts the guidance.

    The submit is the human coach confirming the guidance may be
    prepared and queued for the coach. Nothing is sent to the member by
    this endpoint.
    """
    global _INTAKE_COUNTER
    if not payload.request_text.strip():
        raise HTTPException(status_code=422, detail="request_text must not be empty")
    if payload.requester_id not in REQUESTER_BY_ID:
        raise HTTPException(status_code=422, detail=f"unknown requester: {payload.requester_id!r}")
    if payload.domain not in DOMAINS:
        raise HTTPException(status_code=422, detail=f"unknown domain: {payload.domain!r}")
    if payload.freshness_target_days <= 0:
        raise HTTPException(status_code=422, detail="freshness_target_days must be positive")
    _INTAKE_COUNTER += 1
    case_id = f"UI-{_INTAKE_COUNTER:03d}"
    requester = REQUESTER_BY_ID[payload.requester_id]
    records = fitting_records(payload.requester_id, payload.domain, payload.freshness_target_days)[
        :3
    ]
    case = {
        "id": case_id,
        "category": "intake",
        "requester_id": payload.requester_id,
        "requester_name": requester["name"],
        "request_text": payload.request_text.strip(),
        "domain": payload.domain,
        "freshness_target_days": payload.freshness_target_days,
        "records": records,
        "notes": [],
        "claims": [
            {
                "text": "Northbridge Wellness Collective has an active "
                "coaching agreement covering this request.",
                "source": f"agreement-{case_id}",
            }
        ],
        "required_evidence": [],
        "remediation_needed": [],
        "required_metrics": [],
    }
    result = _AGENT.run(case, approve_guidance=True, approve_send=False)
    _CASES[case_id] = {"case": case, "result": result}
    return _summarise(case, result)


@app.post("/api/cases/{case_id}/apply")
def apply_case(case_id: str) -> dict:
    """Gate 2: a second explicit confirmation before the workout plan
    is changed and the guidance message is sent to the member. Only a
    PROPOSE case can be applied."""
    entry = _CASES.get(case_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown case: {case_id}")
    if entry["result"].decision != "PROPOSE":
        raise HTTPException(
            status_code=409,
            detail=f"case {case_id} is {entry['result'].decision}: "
            "only a PROPOSE case can be applied",
        )
    result = _AGENT.run(entry["case"], approve_guidance=True, approve_send=True)
    entry["result"] = result
    return _summarise(entry["case"], result)


@app.get("/api/audit")
def audit() -> list[dict]:
    return _AGENT.audit_log()
