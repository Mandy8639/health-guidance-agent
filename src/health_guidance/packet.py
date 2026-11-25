"""Guidance case: the single input to the agent.

A case is a synthetic member request: a one-sentence request parsed
into requester, domain and wearable-freshness target, a shortlist of
candidate records drawn from the governed corpus, notes from the member
or the coach, and claims about the case. Every note and claim carries a
provenance source; a claim without a source is unsourced by construction
and the guardrail treats it as fabrication. Every record carries who may
see it: a record visible only to another member is a misrouted record,
and the agent may never query or cite it.

Records come in three kinds — member, protocol, exercise — but share
one shape. ``facts`` holds the typed values the guardrail compares
against (resting HR, sleep, activity, thresholds); a fact that is None
is unknown (missing evidence, G3). ``restrictions`` names what a member
must not do (e.g. no high-impact work after a knee injury).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from health_guidance.inventory import DOMAINS, REQUESTER_BY_ID


@dataclass(frozen=True)
class Column:
    """One column of a record."""

    name: str
    dtype: str
    nullable: bool
    pii: bool = False
    description: str = ""


@dataclass(frozen=True)
class Record:
    """One record in the governed corpus, with facts copied from it.

    ``schema`` and ``freshness_days`` are None when that fact is unknown
    (missing evidence, G3). ``requires`` names a human step that must be
    completed before any plan change (remediation). ``duplicate_of``
    names the record this one duplicates, if any. ``visible_to`` is
    "shared" or one member id: a record visible only to another member
    is never queried or cited for this case (per-member isolation, G3).
    """

    id: str
    kind: str
    domain: str
    name: str
    schema: list[Column] | None
    data_points: int | None
    freshness_days: int | None
    owner: str
    visible_to: str
    sensitivity: str
    description: str
    facts: dict = field(default_factory=dict)
    restrictions: list[str] = field(default_factory=list)
    requires: str | None = None
    duplicate_of: str | None = None


@dataclass(frozen=True)
class Metric:
    """One named metric. The same name may be defined differently in two
    domains (e.g. "recovery_threshold" in recovery vs cardio): a request
    that needs both definitions is a policy conflict (G5)."""

    name: str
    domain: str
    protocol_id: str
    definition: str


@dataclass(frozen=True)
class CaseNote:
    """One note from the member or the coach. ``source`` is the record id.

    ``asserts`` holds machine-readable facts the note claims (e.g. a
    resting heart rate). The guardrail compares them against the corpus:
    an assert that contradicts the corpus is a conflict (G5).
    """

    text: str
    source: str
    asserts: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Claim:
    """One claim about the case. ``source`` may be None (unsourced)."""

    text: str
    source: str | None


@dataclass(frozen=True)
class Case:
    """A guidance case. All fields are required; see tools.read_case."""

    id: str
    category: str
    requester_id: str
    requester_name: str
    request_text: str
    domain: str
    freshness_target_days: int
    records: list[Record] = field(default_factory=list)
    notes: list[CaseNote] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    remediation_needed: list[str] = field(default_factory=list)
    required_metrics: list[str] = field(default_factory=list)


def column_from_dict(data: dict) -> Column:
    return Column(
        name=data["name"],
        dtype=data["dtype"],
        nullable=data["nullable"],
        pii=data.get("pii", False),
        description=data.get("description", ""),
    )


def record_from_dict(data: dict) -> Record:
    schema = None
    if data.get("schema") is not None:
        schema = [column_from_dict(c) for c in data["schema"]]
    return Record(
        id=data["id"],
        kind=data["kind"],
        domain=data["domain"],
        name=data["name"],
        schema=schema,
        data_points=data.get("data_points"),
        freshness_days=data.get("freshness_days"),
        owner=data["owner"],
        visible_to=data["visible_to"],
        sensitivity=data["sensitivity"],
        description=data["description"],
        facts=dict(data.get("facts", {})),
        restrictions=list(data.get("restrictions", [])),
        requires=data.get("requires"),
        duplicate_of=data.get("duplicate_of"),
    )


def metric_from_dict(data: dict) -> Metric:
    return Metric(
        name=data["name"],
        domain=data["domain"],
        protocol_id=data["protocol_id"],
        definition=data["definition"],
    )


def case_from_dict(data: dict) -> Case:
    """Build a Case from a plain dict, validating required fields."""
    required = [
        "id",
        "category",
        "requester_id",
        "requester_name",
        "request_text",
        "domain",
        "freshness_target_days",
    ]
    for key in required:
        if key not in data or data[key] in (None, ""):
            raise ValueError(f"case is missing required field: {key}")
    if data["requester_id"] not in REQUESTER_BY_ID:
        raise ValueError(f"unknown requester: {data['requester_id']!r}")
    if data["domain"] not in DOMAINS:
        raise ValueError(f"unknown domain: {data['domain']!r}")
    records = [record_from_dict(r) for r in data.get("records", [])]
    notes = [
        CaseNote(text=n["text"], source=n["source"], asserts=dict(n.get("asserts", {})))
        for n in data.get("notes", [])
    ]
    claims = [Claim(text=c["text"], source=c.get("source")) for c in data.get("claims", [])]
    return Case(
        id=data["id"],
        category=data["category"],
        requester_id=data["requester_id"],
        requester_name=data["requester_name"],
        request_text=data["request_text"],
        domain=data["domain"],
        freshness_target_days=data["freshness_target_days"],
        records=records,
        notes=notes,
        claims=claims,
        required_evidence=list(data.get("required_evidence", [])),
        remediation_needed=list(data.get("remediation_needed", [])),
        required_metrics=list(data.get("required_metrics", [])),
    )


def column_to_dict(column: Column) -> dict:
    return {
        "name": column.name,
        "dtype": column.dtype,
        "nullable": column.nullable,
        "pii": column.pii,
        "description": column.description,
    }


def record_to_dict(record: Record) -> dict:
    return {
        "id": record.id,
        "kind": record.kind,
        "domain": record.domain,
        "name": record.name,
        "schema": [column_to_dict(c) for c in record.schema] if record.schema is not None else None,
        "data_points": record.data_points,
        "freshness_days": record.freshness_days,
        "owner": record.owner,
        "visible_to": record.visible_to,
        "sensitivity": record.sensitivity,
        "description": record.description,
        "facts": dict(record.facts),
        "restrictions": list(record.restrictions),
        "requires": record.requires,
        "duplicate_of": record.duplicate_of,
    }


def case_to_dict(case: Case) -> dict:
    """Serialise a Case back to a plain dict."""
    return {
        "id": case.id,
        "category": case.category,
        "requester_id": case.requester_id,
        "requester_name": case.requester_name,
        "request_text": case.request_text,
        "domain": case.domain,
        "freshness_target_days": case.freshness_target_days,
        "records": [record_to_dict(r) for r in case.records],
        "notes": [
            {"text": n.text, "source": n.source, "asserts": dict(n.asserts)} for n in case.notes
        ],
        "claims": [{"text": c.text, "source": c.source} for c in case.claims],
        "required_evidence": list(case.required_evidence),
        "remediation_needed": list(case.remediation_needed),
        "required_metrics": list(case.required_metrics),
    }
