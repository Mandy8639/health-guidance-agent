"""The guidance agent: two human gates around three allowlisted tools."""

from __future__ import annotations

from dataclasses import dataclass, field

from health_guidance import guardrail
from health_guidance.reasoner import LiveReasoner, StubReasoner
from health_guidance.tools import (
    ALLOWED_TOOLS,
    Draft,
    Guidance,
    guidance_draft,
    member_data_search,
    protocol_check,
    read_case,
)


@dataclass(frozen=True)
class AgentResult:
    """Everything one agent run produces (or refuses to produce)."""

    case_id: str
    decision: str  # PROPOSE | HOLD | PAUSE | BLOCK | REFUSED
    guidance: Guidance | None = None
    draft: Draft | None = None
    flags: dict = field(default_factory=dict)
    published: bool = False
    applied: bool = False
    sent: bool = False
    provenance: list[str] = field(default_factory=list)
    spend_usd: float = 0.0
    gates_checked: list[str] = field(default_factory=list)
    refusal: str = ""


class GuidanceAgent:
    """Bounded personal-health guidance agent."""

    def __init__(self, mode: str = "stub", live_model: str | None = None) -> None:
        if mode not in ("stub", "live"):
            raise ValueError(f"unknown mode: {mode!r}")
        self.mode = mode
        self._live = LiveReasoner(model=live_model) if mode == "live" else None
        self.audit: list[dict] = []

    def _log(self, tool: str, case_id: str, detail: str) -> None:
        """Every tool call is written to the agent's audit log (G3), so
        the API's audit view shows the real trail of every run."""
        self.audit.append(
            {
                "seq": len(self.audit) + 1,
                "tool": tool,
                "case_id": case_id,
                "detail": detail,
            }
        )

    def audit_log(self) -> list[dict]:
        """A copy of the audit trail: every tool call, in order."""
        return [dict(entry) for entry in self.audit]

    def plan(self) -> list[str]:
        """The tool plan, fixed and allowlisted. Gate 1 approves this plan."""
        return list(ALLOWED_TOOLS)

    def run(
        self,
        case_data: dict,
        *,
        approve_guidance: bool,
        approve_send: bool,
    ) -> AgentResult:
        case = read_case(case_data)
        if not approve_guidance:
            return AgentResult(
                case_id=case.id,
                decision="REFUSED",
                refusal="guidance gate not approved: no tool ran",
                gates_checked=["guidance"],
            )
        matches = member_data_search(case)
        self._log("member_data_search", case.id, f"{len(matches)} matching member record(s)")
        check = protocol_check(case) if matches else None
        if check is not None:
            self._log(
                "protocol_check",
                case.id,
                f"protocol {check.protocol_id}, safe={check.safe}, "
                f"contraindications={len(check.contraindications)}",
            )
        injected = guardrail.scan_injection(case.notes)
        fabricated = guardrail.scan_fabrication(case.claims)
        missing = guardrail.missing_evidence(case)
        conflicts = guardrail.scan_record_conflicts(case) + guardrail.scan_impossible_moves(case)
        red_flags = guardrail.scan_red_flags(case)
        violations = guardrail.policy_violations(case)
        misrouted = guardrail.cross_member_records(case)
        duplicates = [record.id for record in case.records if record.duplicate_of is not None]
        flags = {
            "injection": [note.text for note in injected],
            "fabrication": [claim.text for claim in fabricated],
            "missing_evidence": missing,
            "record_conflicts": conflicts,
            "red_flags": red_flags,
            "policy_violations": violations,
            "misrouted": misrouted,
            "duplicates": duplicates,
            "contraindications": check.contraindications if check is not None else [],
            "member_records": [match.record.id for match in matches],
            "protocol_checked": check.protocol_id if check is not None else None,
        }
        if self.mode == "live":
            assert self._live is not None
            decision, cost = self._live.decide(case, matches)
            spend = cost
        else:
            decision = StubReasoner().decide(
                case,
                matches,
                injection=bool(injected),
                fabrication=bool(fabricated),
                missing=bool(missing),
                conflicts=bool(conflicts),
                violations=bool(violations),
                remediation=bool(case.remediation_needed),
                red_flag=bool(red_flags),
                contraindication=bool(flags["contraindications"]),
            )
            spend = 0.0
        guidance = None
        draft = None
        published = False
        applied = False
        sent = False
        if decision == "PROPOSE" and matches:
            # Gate 1 (G1): the guidance draft is issued only because a
            # human coach confirmed it. Gate 2 (G2): the workout plan is
            # changed and the message sent to the member only with the
            # second explicit confirmation.
            best = matches[0].record
            guidance = guidance_draft(case, best.id)
            self._log("guidance_draft", case.id, f"draft for member {best.id}")
            draft = guidance.coach_message
            published = True
            applied = bool(approve_send)
            sent = bool(approve_send)
        return AgentResult(
            case_id=case.id,
            decision=decision,
            guidance=guidance,
            draft=draft,
            flags=flags,
            published=published,
            applied=applied,
            sent=sent,
            provenance=guardrail.cited_sources(case),
            spend_usd=spend,
            gates_checked=["guidance", "send"],
        )
