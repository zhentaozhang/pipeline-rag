"""P1-2：索引对账任务的孤儿计算逻辑"""

from app.document.tasks.reconcile import _compute_orphans


def test_compute_orphans_finds_stale_ids():
    stored = {1, 2, 3, 4}
    valid = {1, 3}
    assert _compute_orphans(stored, valid) == [2, 4]


def test_compute_orphans_empty_when_consistent():
    assert _compute_orphans({1, 2}, {1, 2}) == []
    assert _compute_orphans(set(), {1, 2}) == []


def test_compute_orphans_all_orphans():
    assert _compute_orphans({1, 2}, set()) == [1, 2]
