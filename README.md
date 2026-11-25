# health-guidance-agent

A bounded personal-health guidance agent for a synthetic member
population. It takes a one-sentence member request to a governed,
coach-approved guidance draft — with a deterministic guardrail (G1–G5)
and two human gates around every run — and a FastAPI backend serving
the guidance queue and the audit trail.

It plans and drafts. **It never diagnoses, prescribes, or messages a
member.** Everything here is synthetic and stated as such.

## What it is for

This repo was built as a portfolio piece for a Future Applied AI
Engineer application: the role builds tool-calling LLM agents with
structured output, evaluation harnesses with Langfuse and rubrics
(safety, effectiveness, personalization), and owns the full
prototype → evals → deploy → monitor loop. The agent speaks that
vocabulary — Pydantic-validated tools (exercise search over a local
database, structured workout submission), a frozen rubric-scored eval,
token budgets and retry discipline in live mode. It claims **no Future
affiliation** and **no health/fitness domain or clinical experience** —
the member population, the protocols, and every record in it are
synthetic.

## How it works

```
one-sentence member request
  -> member_data_search   (governed member records the requester may
                           see, freshest first; exercise search over
                           the local database inside as its evidence
                           step)
  -> protocol_check       (coach protocol, safety guardrails,
                           contraindications, Pydantic-validated
                           structured workout submission)
  -> guidance_draft       (personal-health guidance draft for a human
                           coach to approve; non-diagnostic by
                           construction)
  -> GATE 1: a human coach confirms the guidance before it goes to
             the member
  -> GATE 2: a second explicit confirmation before any workout plan
             is changed or any message is sent to the member
```

**Exactly three allowlisted tools.** Nothing else may touch a case:

| Tool | What it does |
| --- | --- |
| `member_data_search` | Governed member records the requester may see, freshest first. Permission-filtered, domain-matched, schema and freshness known, within the domain's freshness ceiling and the case's target. |
| `protocol_check` | The coach protocol for the case's domain, safety guardrails, contraindications, and a Pydantic-validated structured workout submission. Checks only; it changes no plan and sends nothing. |
| `guidance_draft` | A personal-health guidance draft for a human coach to approve. Draft only: it never diagnoses, prescribes, or messages a member. |

**Judgment call — exercise search is not a fourth tool.** The
exercise search (`exercise_search`) runs *inside*
`member_data_search` as its evidence step: it searches the local
exercise database only, and the exercise it returns is cited in the
draft. The structured workout submission is built by `protocol_check`
and travels inside the guidance draft, and the coach message travels
inside the draft the same way. A draft that cites an exercise it cannot
show is not a draft worth approving; keeping the search inside the
tools keeps the tool surface at three and the evidence attached to the
thing being approved.

**Exactly two human gates.** (1) A human coach confirms the guidance
draft before it goes to the member. (2) A second explicit confirmation
before any workout plan is changed or any message is sent to the
member. Re-running any case with both gates denied publishes, applies,
and sends nothing — the eval checks this on all 48 cases.

**Judgment call — gate 1 is the intake submission.** In the API, the
`POST /api/intake` submit is gate 1: a human coach confirms the
guidance may be prepared and queued. Nothing is sent to the member by
that endpoint. `POST /api/cases/{case_id}/apply` is gate 2.

## The guardrail (G1–G5, deterministic)

- **G1** — No guidance goes to the member without gate 1.
- **G2** — No workout plan is changed and no message is sent without gate 2.
- **G3** — Never state a metric, workout, or protocol not in the
  corpus. Missing evidence means abstain. PII is redacted before any
  draft leaves the corpus. Per-member isolation: a record the requester
  lacks permission for is never queried or cited.
- **G4** — Instructions injected into request or corpus text are
  blocked; nothing is published.
- **G5** — Pause on policy violations and conflicting signals: a
  protocol defined two ways in two documents, permission conflicts,
  freshness breaches, a note contradicting the corpus (wearable data vs
  self-report), a metric that moved impossibly fast, and any pain,
  injury or red-flag signal — which defers to a human coach, because
  the agent is non-diagnostic by construction.

## The synthetic member population

One synthetic wellness collective (Northbridge Wellness Collective),
four requester members, ~40 members, ~30 coach protocols and ~18
exercises across three training domains (recovery, strength, cardio),
plus two duplicate records that are never queried directly. Wearable
time-series (resting heart rate, sleep, activity) sit on each member
record. Four records carry unknown/missing fields (unknown freshness,
unknown schema) — the agent must never guess them. The source data is
messy on purpose: descriptions carry PII (redacted before any draft),
and the "recovery_threshold" protocol is defined two ways — resting HR
above 70 bpm means a rest day in recovery, above 78 bpm in cardio — so
a request that needs both definitions pauses.

## Verified numbers

Frozen 48-case eval, deterministic, seed 42. Stub reasoner only;
$0.00 spend. Golden set hash-locked (`eval/golden.sha256`); the eval
refuses to run on a tampered set.

| Metric | Result |
| --- | --- |
| Agreement with analyst gold labels | **48/48 (100%)** |
| False auto-sends | **0** |
| False holds | **0** |
| Abstention (insufficient evidence) | **6/6** |
| Fabrication blocked | **6/6** |
| Injection blocked | **6/6** |
| Pause detection (policy violations) | **4/4** |
| Gates checked | **48/48** |
| Stub spend | **$0.00** |

Eval split: clean 12, misrouted/duplicate 8, remediation 6,
insufficient-evidence 6, fabrication 6, injection 6, pause 4.

| Check | Result |
| --- | --- |
| Tests | **85 passed** |
| Ruff check + format | clean |
| Golden set SHA-256 | `1fb3c488b198225a31d713e682f4c5ae841ae57ce911cf61591a61b6f89a58aa` |
| MCP stdio smoke test | initializes as `health-guidance-agent`, `tools/list` shows exactly 3 tools |
| API end-to-end (live HTTP) | intake → PROPOSE draft, gate 2 → applied & sent, audit 99 entries over 3 tools |

## Reproduce

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
pip install ruff pytest     # dev only
ruff check . && ruff format --check .
pytest -q                   # 85 tests
python eval/run_eval.py     # stub eval; reproduces eval/report.json exactly
```

Rebuild the golden set (deterministic, seed 42) and re-hash it:

```bash
python eval/build_golden.py
sha256sum eval/golden.json  # must match eval/golden.sha256
```

## API

```bash
uvicorn health_guidance.api:app --reload
# GET  /api/health                 -> {"status": "ok", "agent": "health-guidance-agent"}
# GET  /api/cases                  -> the guidance queue (48 frozen cases, seeded)
# GET  /api/cases/{case_id}        -> one case, with its guidance if any
# POST /api/intake                 -> gate 1: submit a member request, draft guidance
# POST /api/cases/{case_id}/apply  -> gate 2: apply the plan change, send the message
# GET  /api/audit                  -> the audit trail: every tool call, in order
```

## MCP server

Stdio JSON-RPC 2.0, no external dependencies, exposing exactly the
three tools:

```bash
python -m health_guidance.mcp_server
# {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {...}}
# {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
```

It initializes under the name `health-guidance-agent`.

## Live mode (optional, never used by the eval)

Haiku only (`claude-haiku-4-5`, $1/$5 per million tokens), a $1.00/day
spend ledger, unknown models refused, refuses without an
`ANTHROPIC_API_KEY`. Install with `pip install '.[live]'`. Only the
refusal paths are tested — live mode has never called a real API in
this repo.

```bash
ANTHROPIC_API_KEY=... python -c "
from health_guidance.agent import GuidanceAgent
agent = GuidanceAgent(mode='live')
"
```

## Honest limits

- **Synthetic eval.** The 48 cases are frozen and synthetic; 48/48
  measures the stub reasoner against those cases, not real-world
  performance.
- **One signal per case.** Each eval case carries exactly one
  distinguishing signal, by design. Real requests carry several at
  once, and the stub has not been measured on those.
- **Live mode never called a real API.** Only its refusal paths are
  tested (no key, unknown model, cap reached, package absent). Live
  decision quality is unmeasured.
- **No Future affiliation.** No health/fitness domain or clinical
  experience, and no Future product knowledge. The population is
  synthetic; the eval method reuses frozen-eval practice, not any
  Future system.
- **Non-diagnostic by construction.** The agent drafts general
  training guidance for a human coach to approve. It does not diagnose,
  treat, or make medical claims, and it defers to a human coach on any
  pain, injury or red-flag signal. It is not a medical device and must
  not be used as one.
- **The workout submission is a structured template, not a
  prescription.** Sets, reps and duration are Pydantic-validated
  ranges over corpus exercises; a coach must approve the draft before
  anything reaches a member.
