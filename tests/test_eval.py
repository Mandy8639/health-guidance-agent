"""Tests for the frozen eval harness."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eval.run_eval import evaluate, load_golden

HERE = Path(__file__).resolve().parents[1] / "eval"


def test_golden_set_has_48_cases() -> None:
    cases = load_golden()
    assert len(cases) == 48
    counts: dict[str, int] = {}
    for case in cases:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    assert counts == {
        "clean": 12,
        "misrouted": 8,
        "remediation": 6,
        "insufficient": 6,
        "fabrication": 6,
        "injection": 6,
        "pause": 4,
    }


def test_golden_hash_matches() -> None:
    expected = (HERE / "golden.sha256").read_text(encoding="utf-8").strip()
    actual = hashlib.sha256((HERE / "golden.json").read_bytes()).hexdigest()
    assert actual == expected


def test_eval_reproduces_the_committed_report() -> None:
    cases = load_golden()
    report = evaluate(cases)
    assert report["agreement"] == "48/48"
    assert report["false_sends"] == 0
    assert report["false_holds"] == 0
    assert report["abstention"] == "6/6"
    assert report["fabrication_blocked"] == "6/6"
    assert report["injection_blocked"] == "6/6"
    assert report["pause"] == "4/4"
    assert report["gates"] == "48/48"
    assert report["spend_usd"] == 0.0
    committed = json.loads((HERE / "report.json").read_text(encoding="utf-8"))
    assert report == committed


def test_eval_categories_match_gold_labels() -> None:
    cases = load_golden()
    report = evaluate(cases)
    assert report["by_category"]["clean"] == {"total": 12, "agree": 12}
    assert report["by_category"]["pause"] == {"total": 4, "agree": 4}
