"""Deterministic guardrail G1-G5.

Every rule is a pure function over the case, so the eval can reproduce it
exactly. No rule ever invents evidence: when evidence is missing the agent
abstains; when instructions appear inside case notes they are blocked;
when a note contradicts the corpus the run pauses. PII is redacted
before any draft leaves the corpus, and a record another member alone
may see is never queried or cited (per-member isolation).

The agent is non-diagnostic by construction: it never diagnoses, treats
or makes medical claims, and any pain, injury or red-flag signal in the
request or the notes pauses the run and defers to a human coach. A
workout or health recommendation above the agent's authority — a
contraindication, or guidance with no member/coach evidence behind it —
never leaves the corpus. Conflicting signals pause the run: wearable
data contradicting a self-report, a protocol defined two ways, or a
metric that moved impossibly fast.

A permission conflict (G5) is when the case itself requires evidence
from a record in its own domain that the requester may not see. That is
distinct from a misrouted record (G3): a record from outside the case's
domain that landed in the case is flagged and ignored, never a policy
violation.
"""

from __future__ import annotations

import re

from health_guidance.inventory import BY_ID, METRICS
from health_guidance.packet import Case, CaseNote, Claim

# Maximum freshness (days since last wearable sync) a domain's records
# may carry. A record staler than its domain's ceiling is a policy
# violation (G5), not a fact to work around.
DOMAIN_MAX_STALENESS = {"recovery": 7, "strength": 7, "cardio": 7}

# G5: a resting-HR move larger than this (bpm) between two consecutive
# readings is impossible for the same member and pauses the run.
IMPOSSIBLE_HR_MOVE_BPM = 20

# G4: substrings that mark an instruction injected into a case note.
# A note containing one of these is treated as an attempt to steer the
# agent, not as corpus evidence.
INJECTION_PATTERNS = (
    "ignore the",
    "ignore all",
    "override",
    "approve anyway",
    "disregard",
    "do not flag",
    "skip the check",
    "send it anyway",
    "share it anyway",
    "mark it resolved",
    "bypass",
    "pretend",
    "confirm without asking",
    "diagnose",
    "prescribe",
)

# G5 (non-diagnostic rule): words that mark a pain, injury or red-flag
# signal. A request or note containing one pauses the run and defers to
# a human coach. "chest" alone is not a flag — "chest workout" is an
# ordinary request — only "chest pain" and "chest tightness" are.
RED_FLAG_TERMS = (
    "pain",
    "injury",
    "injured",
    "hurt",
    "hurts",
    "dizzy",
    "dizziness",
    "faint",
    "fainted",
    "numb",
    "numbness",
    "swelling",
    "bleeding",
    "breathless",
    "short of breath",
    "chest pain",
    "chest tightness",
    "sprain",
    "fracture",
    "torn",
)

# G3: PII patterns redacted before any draft leaves the corpus.
PII_PATTERNS = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL REDACTED]"),
    (
        re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"),
        "[PHONE REDACTED]",
    ),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN REDACTED]"),
)

# Fact keys a note may assert about a record.
ASSERTABLE_FACTS = (
    "resting_hr",
    "sleep_hours_7d",
    "activity_minutes_7d",
    "threshold_bpm",
)


def redact_pii(text: str) -> str:
    """G3: redact PII from text before it is quoted in any draft."""
    redacted = text
    for pattern, replacement in PII_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def scan_injection(notes: list[CaseNote]) -> list[CaseNote]:
    """G4: return the case notes that carry an injected instruction."""
    hits = []
    for note in notes:
        lowered = note.text.lower()
        if any(pattern in lowered for pattern in INJECTION_PATTERNS):
            hits.append(note)
    return hits


def scan_fabrication(claims: list[Claim]) -> list[Claim]:
    """G3: return the claims with no provenance source. They are dropped."""
    return [claim for claim in claims if not claim.source]


def cited_sources(case: Case) -> list[str]:
    """Provenance the agent is allowed to cite: sourced notes and claims."""
    sources = [note.source for note in case.notes]
    sources += [claim.source for claim in case.claims if claim.source]
    return sorted(set(sources))


def missing_evidence(case: Case) -> list[str]:
    """G3: required evidence items with no supporting record.

    Entries are ``"RID:schema"`` or ``"RID:freshness"``. An item is
    missing when the record is not among the case records, or the field
    is unknown (None) on that record.
    """
    missing = []
    by_id = {record.id: record for record in case.records}
    for entry in case.required_evidence:
        parts = entry.split(":")
        record_id, field_name = parts[0], parts[1]
        record = by_id.get(record_id)
        if record is None:
            missing.append(entry)
            continue
        if field_name == "schema" and record.schema is None:
            missing.append(entry)
        elif field_name == "freshness" and record.freshness_days is None:
            missing.append(entry)
    return missing


def _record_fact(record: object, key: str) -> object:
    """One comparable fact from a record: a top-level field or a fact."""
    if key == "data_points":
        return record.data_points
    if key == "freshness_days":
        return record.freshness_days
    if key == "owner":
        return record.owner
    return record.facts.get(key)


def scan_record_conflicts(case: Case) -> list[dict]:
    """G5: case-note asserts that contradict the corpus.

    Only facts the record actually knows are compared; an assert about
    an unknown fact is not a conflict. Returns one dict per contradiction.
    This is the wearable-vs-self-report check: a member's self-reported
    number that disagrees with the wearable record pauses the run.
    """
    conflicts = []
    by_id = {record.id: record for record in case.records}
    for note in case.notes:
        record = by_id.get(note.source)
        if record is None:
            continue
        for key, asserted in note.asserts.items():
            if key not in ("data_points", "freshness_days", "owner", *ASSERTABLE_FACTS):
                continue
            known = _record_fact(record, key)
            if known is not None and asserted != known:
                conflicts.append(
                    {
                        "record": record.id,
                        "field": key,
                        "asserted": asserted,
                        "corpus": known,
                    }
                )
    return conflicts


def scan_impossible_moves(case: Case) -> list[str]:
    """G5: a metric that moved impossibly fast between two readings.

    A resting heart rate that jumped by more than
    ``IMPOSSIBLE_HR_MOVE_BPM`` bpm since the previous reading cannot be
    the same member's real signal: the wearable data or the record is
    wrong, and the run pauses instead of drafting on it.
    """
    conflicts = []
    for record in case.records:
        current = record.facts.get("resting_hr")
        previous = record.facts.get("resting_hr_prev")
        if current is None or previous is None:
            continue
        if abs(current - previous) > IMPOSSIBLE_HR_MOVE_BPM:
            conflicts.append(
                f"impossible_move: {record.id} resting HR moved "
                f"{previous} -> {current} bpm "
                f"(>{IMPOSSIBLE_HR_MOVE_BPM} bpm between readings)"
            )
    return sorted(conflicts)


def scan_red_flags(case: Case) -> list[str]:
    """G5: pain, injury or red-flag signals in the request or the notes.

    Any hit defers the case to a human coach: the agent is
    non-diagnostic and never drafts guidance on a possible injury.
    """
    hits = []
    texts = [case.request_text] + [note.text for note in case.notes]
    for text in texts:
        lowered = text.lower()
        for term in RED_FLAG_TERMS:
            if term in lowered and term not in hits:
                hits.append(term)
    return sorted(hits)


def cross_member_records(case: Case) -> list[str]:
    """G3: record ids in the case that another member alone may see.

    A misrouted record is flagged, never queried or cited: per-member
    isolation means the agent may only work records its requester may see.
    """
    return [
        record.id
        for record in case.records
        if record.visible_to not in ("shared", case.requester_id)
    ]


def _protocol_conflicts(case: Case) -> list[str]:
    """G5: a required metric defined two ways across the case's records.

    The conflict is judged on the records the case actually carries: a
    metric with two distinct definitions among them means the request
    cannot be answered without disambiguation.
    """
    conflicts = []
    by_id = {record.id: record for record in case.records}
    for metric_name in case.required_metrics:
        definitions: dict[str, str] = {}
        for metric in METRICS:
            if metric["name"] != metric_name:
                continue
            if metric["protocol_id"] not in by_id:
                continue
            definitions.setdefault(metric["domain"], metric["definition"])
        if len(set(definitions.values())) > 1:
            domains = sorted(definitions)
            conflicts.append(
                f"metric_conflict: {metric_name} is defined as "
                f"'{definitions[domains[0]]}' in {domains[0]} and "
                f"'{definitions[domains[1]]}' in {domains[1]}"
            )
    return sorted(conflicts)


def _permission_conflicts(case: Case) -> list[str]:
    """G5: required evidence from a record in the case's own domain that
    the requester may not see. Records from outside the case's domain are
    misrouted records (G3), not permission conflicts."""
    conflicts = []
    for entry in case.required_evidence:
        record_id = entry.split(":")[0]
        record = BY_ID.get(record_id)
        if record is None:
            continue
        if record["domain"] != case.domain:
            continue
        if record["visible_to"] not in ("shared", case.requester_id):
            conflicts.append(
                f"permission_conflict: {record_id} is not visible to requester {case.requester_id}"
            )
    return sorted(conflicts)


def policy_violations(case: Case) -> list[str]:
    """G5: policy violations that block any auto-send.

    Case-level violations (metric and permission conflicts) always block.
    Record-level violations (staleness beyond the domain ceiling,
    freshness beyond the case's target) block only when no candidate
    record is viable: a record is viable when every computable
    constraint passes. Unknown fields never count as violations — they
    are missing evidence (G3), not policy.
    """
    violations = _protocol_conflicts(case) + _permission_conflicts(case)
    in_scope = [
        record
        for record in case.records
        if record.kind == "member"
        and record.visible_to in ("shared", case.requester_id)
        and record.domain == case.domain
    ]
    if not in_scope:
        return sorted(violations)
    record_violations: set[str] = set()
    viable = False
    for record in in_scope:
        case_violations: list[str] = []
        if record.freshness_days is not None:
            if record.freshness_days > DOMAIN_MAX_STALENESS[record.domain]:
                case_violations.append(
                    f"stale_beyond_domain_max: {record.id} is "
                    f"{record.freshness_days}d stale "
                    f"(max {DOMAIN_MAX_STALENESS[record.domain]}d for {record.domain})"
                )
            if record.freshness_days > case.freshness_target_days:
                case_violations.append(
                    f"freshness_exceeds_target: {record.id} is "
                    f"{record.freshness_days}d stale against a "
                    f"{case.freshness_target_days}d target"
                )
        if case_violations:
            record_violations.update(case_violations)
        else:
            viable = True
    if viable:
        return sorted(violations)
    return sorted(violations + sorted(record_violations))
