"""检索层门禁：chunk_id 口径 R@5 不依赖 judge，retrieval-only 也要生效。"""

from scripts.evaluation.runner import evaluate_gates


def test_gate_passes_when_above_threshold():
    skipped, violations = evaluate_gates([("recall_at_5_ids", 0.85, 0.90)])
    assert skipped == []
    assert violations == []


def test_gate_fails_when_below_threshold():
    skipped, violations = evaluate_gates([("recall_at_5_ids", 0.90, 0.8543)])
    assert skipped == []
    assert violations == [("recall_at_5_ids", 0.90, 0.8543)]


def test_gate_skips_missing_samples():
    skipped, violations = evaluate_gates([("recall_at_5_ids", 0.90, None)])
    assert skipped == ["recall_at_5_ids"]
    assert violations == []


def test_zero_threshold_disables_gate():
    skipped, violations = evaluate_gates([("context_recall", 0.0, None)])
    assert skipped == []
    assert violations == []
