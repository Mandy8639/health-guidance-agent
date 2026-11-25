"""Tests for the stub reasoner's decision priority."""

from __future__ import annotations

from health_guidance.packet import case_from_dict
from health_guidance.reasoner import StubReasoner
from health_guidance.tools import member_data_search
from tests.conftest import clean_case


def _decide(**flags) -> str:
    case = case_from_dict(clean_case())
    base = {
        "injection": False,
        "fabrication": False,
        "missing": False,
        "conflicts": False,
        "violations": False,
        "remediation": False,
        "red_flag": False,
        "contraindication": False,
    }
    base.update(flags)
    return StubReasoner().decide(case, [], **base)


def test_propose_when_nothing_is_wrong() -> None:
    case = case_from_dict(clean_case())
    matches = member_data_search(case)
    assert (
        StubReasoner().decide(
            case,
            matches,
            injection=False,
            fabrication=False,
            missing=False,
            conflicts=False,
            violations=False,
            remediation=False,
            red_flag=False,
            contraindication=False,
        )
        == "PROPOSE"
    )


def test_injection_blocks_first() -> None:
    assert _decide(injection=True, conflicts=True, missing=True) == "BLOCK"


def test_conflicts_violations_and_red_flags_pause() -> None:
    assert _decide(conflicts=True) == "PAUSE"
    assert _decide(violations=True) == "PAUSE"
    assert _decide(red_flag=True) == "PAUSE"
    assert _decide(conflicts=True, missing=True) == "PAUSE"


def test_missing_remediation_fabrication_and_contraindication_hold() -> None:
    assert _decide(missing=True) == "HOLD"
    assert _decide(remediation=True) == "HOLD"
    assert _decide(fabrication=True) == "HOLD"
    assert _decide(contraindication=True) == "HOLD"


def test_no_matches_holds() -> None:
    assert _decide() == "HOLD"
