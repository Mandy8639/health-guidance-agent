"""The three allowlisted tools. Nothing else may touch a case.

1. member_data_search — governed member records the requester may
   see, freshest first. Exercise search over the local exercise database
   runs inside it as its evidence step (``exercise_search``, a helper,
   not a tool): it finds exercises for the request over governed data
   only, so the draft is the only place an exercise can be prescribed
   from.
2. protocol_check — the coach protocol for the case's domain, safety
   guardrails, contraindications, and a Pydantic-validated structured
   workout submission. Checks only; it changes no plan and sends
   nothing.
3. guidance_draft — a personal-health guidance draft for a human coach
   to approve. Draft only: it never diagnoses, prescribes, or messages
   a member. The structured workout submission travels inside the draft,
   and the coach message travels inside the draft too.

The exercise search and the protocol check are helpers of the tools,
not a fourth tool: keeping the tool surface at three keeps the evidence
attached to the thing being approved.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from health_guidance import guardrail
from health_guidance.inventory import EXERCISES, PROTOCOLS, RECORDS
from health_guidance.packet import (
    Case,
    Record,
    case_from_dict,
    record_from_dict,
    record_to_dict,
)

ALLOWED_TOOLS = (
    "member_data_search",
    "protocol_check",
    "guidance_draft",
)

MESSAGE_PURPOSES = (
    "request_approval",
    "request_info",
    "escalation_notice",
)

# Request words that mark a high-impact intent. A member whose
# restrictions forbid high-impact work gets a contraindication, not a
# workout, when the request asks for it.
HIGH_IMPACT_KEYWORDS = (
    "high-impact",
    "high impact",
    "jump",
    "jumps",
    "sprint",
    "plyometric",
    "box jump",
)

# Request words mapped to the muscle group they ask about.
MUSCLE_KEYWORDS = {
    "leg": "legs",
    "legs": "legs",
    "chest": "chest",
    "shoulder": "shoulders",
    "shoulders": "shoulders",
    "back": "back",
    "core": "core",
    "glute": "glutes",
    "glutes": "glutes",
    "cardio": "cardio",
    "run": "cardio",
    "running": "cardio",
    "swim": "full-body",
    "yoga": "full-body",
    "stretch": "full-body",
}


@dataclass(frozen=True)
class MemberMatch:
    """One member record that can satisfy the case, with its source."""

    record: Record
    source: str


@dataclass(frozen=True)
class Exercise:
    """One exercise from the local database."""

    id: str
    name: str
    muscle_group: str
    impact: str
    equipment: str
    duration_min: int
    difficulty: int


class WorkoutSubmission(BaseModel):
    """A structured workout submission. Pydantic-validated: ranges are
    enforced here, and the agent only ever submits an exercise the
    exercise search returned for this member."""

    exercise_id: str
    exercise_name: str
    sets: int = Field(ge=1, le=6)
    reps: int = Field(ge=1, le=30)
    duration_min: int = Field(ge=5, le=120)
    intensity: str = Field(pattern="^(low|moderate|high)$")
    rest_seconds: int = Field(ge=30, le=300)


@dataclass(frozen=True)
class ProtocolCheck:
    """The result of protocol_check. Check only: it changes no plan and
    sends nothing. ``workout`` is None when the request is
    contraindicated or no safe exercise exists."""

    protocol_id: str
    protocol_name: str
    contraindications: list[str]
    safe: bool
    workout: WorkoutSubmission | None


@dataclass(frozen=True)
class Draft:
    """A drafted message to the member's coach. ``sent`` is always
    False: it sends nothing."""

    to_coach: str
    to_requester_id: str
    purpose: str
    subject: str
    body: str
    sent: bool = False


@dataclass(frozen=True)
class Guidance:
    """A drafted personal-health guidance. Status is always 'draft': it
    shares nothing with the member and changes no plan.

    ``shared`` and ``sent`` are always False on the draft itself —
    only human confirmations (gates 1 and 2) may flip them on the agent
    result. The guidance is non-diagnostic by construction: it cites
    member/coach evidence only, and any pain, injury or red-flag signal
    pauses the run before a draft is ever built.
    """

    member_id: str
    requester_id: str
    summary: str
    workout: WorkoutSubmission | None
    protocol_id: str
    steps: list[str]
    coach_message: Draft
    status: str = "draft"
    shared: bool = False
    sent: bool = False


def member_data_search(case: Case) -> list[MemberMatch]:
    """Tool 1: member records that can satisfy the case, freshest first.

    A record matches only when every fact is known and passes: it is a
    member record, visible to the case's requester (per-member
    isolation), its domain matches, its schema and freshness are known,
    and its freshness is within its domain's ceiling and the case's
    target. Unknown facts exclude the record (G3) rather than being
    guessed.
    """
    matches = []
    for record in case.records:
        if record.kind != "member":
            continue
        if record.visible_to not in ("shared", case.requester_id):
            continue
        if record.domain != case.domain:
            continue
        if record.duplicate_of is not None:
            continue
        if record.schema is None or record.freshness_days is None:
            continue
        if record.freshness_days > guardrail.DOMAIN_MAX_STALENESS[record.domain]:
            continue
        if record.freshness_days > case.freshness_target_days:
            continue
        matches.append(MemberMatch(record=record, source=record.id))
    matches.sort(key=lambda match: (match.record.freshness_days or 0, match.record.id))
    return matches


def exercise_search(case: Case, member: Record) -> list[Exercise]:
    """Exercise search over the local database (helper, not a tool).

    Exercises are matched by muscle-group keywords in the request; with
    no keyword every exercise is a candidate. High-impact exercises are
    excluded for a member whose restrictions forbid them. The search
    never invents an exercise: it returns only rows from the corpus.
    """
    request = case.request_text.lower()
    wanted = {group for word, group in MUSCLE_KEYWORDS.items() if word in request}
    high_impact_forbidden = any("high-impact" in r.lower() for r in member.restrictions)
    results = []
    for data in EXERCISES:
        facts = data["facts"]
        if wanted and facts["muscle_group"] not in wanted:
            continue
        if high_impact_forbidden and facts["impact"] == "high":
            continue
        results.append(
            Exercise(
                id=data["id"],
                name=data["name"],
                muscle_group=facts["muscle_group"],
                impact=facts["impact"],
                equipment=facts["equipment"],
                duration_min=facts["duration_min"],
                difficulty=facts["difficulty"],
            )
        )
    results.sort(key=lambda exercise: (exercise.difficulty, exercise.id))
    return results


def _protocol_for_domain(case: Case) -> dict | None:
    """The protocol record in the case for the case's domain, if any."""
    for record in case.records:
        if record.kind == "protocol" and record.domain == case.domain:
            return {
                "id": record.id,
                "name": record.name,
                "facts": record.facts,
            }
    return None


def protocol_check(case: Case) -> ProtocolCheck:
    """Tool 2: the coach protocol, safety guardrails, contraindications,
    and a Pydantic-validated structured workout submission.

    The check runs only on a case with a matching governed member
    record. It checks only: it changes no plan and sends nothing. A
    request that asks for work a member restriction forbids is a
    contraindication, and the submission is withheld.
    """
    matches = member_data_search(case)
    if not matches:
        raise ValueError("no governed member record matches this case")
    member = matches[0].record
    protocol = _protocol_for_domain(case)
    if protocol is None:
        defaults = [p for p in PROTOCOLS if p["domain"] == case.domain]
        if not defaults:
            raise ValueError(f"no protocol for domain {case.domain!r}")
        protocol = {"id": defaults[0]["id"], "name": defaults[0]["name"], "facts": {}}
    request = case.request_text.lower()
    contraindications = []
    if any(keyword in request for keyword in HIGH_IMPACT_KEYWORDS):
        for restriction in member.restrictions:
            if "high-impact" in restriction.lower():
                contraindications.append(f"High-impact work is contraindicated: {restriction}.")
    workout = None
    if not contraindications:
        exercises = exercise_search(case, member)
        if exercises:
            best = exercises[0]
            workout = WorkoutSubmission(
                exercise_id=best.id,
                exercise_name=best.name,
                sets=3,
                reps=12,
                duration_min=best.duration_min,
                intensity=best.impact,
                rest_seconds=60,
            )
    return ProtocolCheck(
        protocol_id=protocol["id"],
        protocol_name=protocol["name"],
        contraindications=contraindications,
        safe=not contraindications,
        workout=workout,
    )


def coach_message(case: Case, member: Record, purpose: str) -> Draft:
    """Build a message draft to the member's coach. It is never sent.

    The body cites corpus facts only — never a fact the corpus does
    not know — and any PII quoted from the record is redacted before
    the draft leaves the corpus (G3).
    """
    if purpose not in MESSAGE_PURPOSES:
        raise ValueError(f"unknown message purpose: {purpose!r}")
    description = guardrail.redact_pii(member.description)
    if purpose == "request_approval":
        subject = f"Guidance to approve — {member.name} ({member.id})"
        body = (
            f"Hello {member.owner}, please review this guidance draft for "
            f"{case.requester_name} ('{case.request_text}'). "
            f"Corpus note: {description} The draft is non-diagnostic and "
            "changes no plan until you confirm it — nothing is sent to the "
            "member until a second confirmation. "
            f"Freshness target: {case.freshness_target_days}d."
        )
    elif purpose == "request_info":
        subject = f"More information needed — {member.name} ({member.id})"
        body = (
            f"Hello {member.owner}, we need one more detail to draft guidance "
            f"for {case.requester_name} ('{case.request_text}'). "
            f"Corpus note: {description} Could you confirm which protocol "
            "this should follow?"
        )
    else:  # escalation_notice
        subject = f"Escalation — {member.name} ({member.id})"
        body = (
            f"Hello {member.owner}, {member.id} ({member.name}) has been "
            "escalated to a human coach for review. "
            f"Corpus note: {description} We will update you once they have "
            "looked at it."
        )
    return Draft(
        to_coach=member.owner,
        to_requester_id=case.requester_id,
        purpose=purpose,
        subject=subject,
        body=body,
    )


def guidance_draft(case: Case, member_id: str) -> Guidance:
    """Tool 3: draft personal-health guidance for one matching member.

    The guidance is a draft: it shares nothing with the member and
    changes no plan. Only a member returned by member_data_search may
    be drafted. The structured workout submission travels inside the
    draft (built by protocol_check), and the coach message travels
    inside the draft too.
    """
    matches = {match.record.id: match for match in member_data_search(case)}
    if member_id not in matches:
        raise ValueError(f"member {member_id!r} is not a confirmed match for this case")
    member = matches[member_id].record
    check = protocol_check(case)
    steps = [
        f"Answer the request with the governed member record {member.id} "
        f"({member.name}): resting HR "
        f"{member.facts.get('resting_hr')} bpm, sleep "
        f"{member.facts.get('sleep_hours_7d')}h/7d, activity "
        f"{member.facts.get('activity_minutes_7d')} min/7d.",
    ]
    if check.workout is not None:
        steps.append(
            f"Structured workout submission (Pydantic-validated): "
            f"{check.workout.exercise_name} ({check.workout.exercise_id}), "
            f"{check.workout.sets}x{check.workout.reps}, "
            f"{check.workout.duration_min} min, {check.workout.intensity} intensity."
        )
    steps.append(f"Protocol followed: {check.protocol_name} ({check.protocol_id}).")
    if member.requires:
        steps.append(f"Pre-change step (human): {member.requires}")
    steps.append(
        "Coach confirmation required before sharing with the member, and a "
        "second confirmation before any plan change or message is sent."
    )
    summary = guardrail.redact_pii(member.description)
    return Guidance(
        member_id=member.id,
        requester_id=case.requester_id,
        summary=summary,
        workout=check.workout,
        protocol_id=check.protocol_id,
        steps=steps,
        coach_message=coach_message(case, member, "request_approval"),
    )


def read_case(data: dict) -> Case:
    """Load and validate a case. Raises ValueError if malformed."""
    return case_from_dict(data)


def record_by_id(record_id: str) -> Record:
    """Look a corpus record up by id (for tests and the MCP server)."""
    for data in RECORDS:
        if data["id"] == record_id:
            return record_from_dict(data)
    raise ValueError(f"unknown record: {record_id!r}")


def fitting_records(requester_id: str, domain: str, freshness_target_days: int) -> list[dict]:
    """Records that can satisfy a request, with every fact known."""
    case = case_from_dict(
        {
            "id": "HG-FIT",
            "category": "clean",
            "requester_id": requester_id,
            "requester_name": "fit check",
            "request_text": "fit check",
            "domain": domain,
            "freshness_target_days": freshness_target_days,
            "records": [
                {
                    **r,
                    "schema": None if r.get("schema") is None else [dict(c) for c in r["schema"]],
                }
                for r in RECORDS
            ],
        }
    )
    return [record_to_dict(m.record) for m in member_data_search(case)]
