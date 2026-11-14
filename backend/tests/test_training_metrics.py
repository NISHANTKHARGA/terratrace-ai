"""Training metrics must be real computations, verified on known inputs."""
from __future__ import annotations

import numpy as np
import pytest

from app.training.metrics import (
    accuracy,
    binary_metrics,
    bootstrap_ci,
    confusion_counts,
    f1_score,
    iou,
    precision,
    recall,
    specificity,
    train_val_split,
)


def test_confusion_counts_known_example():
    y_true = [1, 1, 0, 0, 1, 0, 1, 0]
    y_pred = [1, 0, 0, 1, 1, 0, 1, 1]
    assert confusion_counts(y_true, y_pred) == {"tp": 3, "fp": 2, "fn": 1, "tn": 2}


def test_precision_recall_f1_iou_match_hand_values():
    y_true = [1, 1, 0, 0, 1, 0, 1, 0]
    y_pred = [1, 0, 0, 1, 1, 0, 1, 1]
    assert precision(y_true, y_pred) == pytest.approx(3 / 5)
    assert recall(y_true, y_pred) == pytest.approx(3 / 4)
    assert f1_score(y_true, y_pred) == pytest.approx(2 * (0.6 * 0.75) / (0.6 + 0.75))
    assert iou(y_true, y_pred) == pytest.approx(3 / (3 + 2 + 1))
    assert accuracy(y_true, y_pred) == pytest.approx(5 / 8)
    assert specificity(y_true, y_pred) == pytest.approx(2 / 4)


def test_perfect_and_worst_case_predictions():
    y = [0, 0, 1, 1]
    assert f1_score(y, y) == 1.0
    assert iou(y, y) == 1.0
    assert f1_score(y, [1, 1, 0, 0]) == 0.0
    assert precision(y, [0, 0, 0, 0]) == 0.0  # undefined → reported as 0, not a crash


def test_binary_metrics_carries_counts_and_scores():
    m = binary_metrics([1, 0, 1, 0], [1, 1, 0, 0])
    for key in ("precision", "recall", "f1", "iou", "accuracy", "specificity"):
        assert 0.0 <= m[key] <= 1.0
    assert m["tp"] + m["fp"] + m["fn"] + m["tn"] == 4


def test_empty_inputs_are_rejected_rather_than_invented():
    with pytest.raises(ValueError):
        confusion_counts([], [])
    with pytest.raises(ValueError):
        precision([1, 0], [1])


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        accuracy([1, 0, 1], [1, 0])


def test_train_val_split_is_deterministic_and_disjoint():
    a_tr, a_va = train_val_split(100, val_fraction=0.3, seed=42)
    b_tr, b_va = train_val_split(100, val_fraction=0.3, seed=42)
    assert np.array_equal(a_tr, b_tr) and np.array_equal(a_va, b_va)
    assert set(a_tr).isdisjoint(a_va)
    assert a_tr.size + a_va.size == 100
    c_tr, _ = train_val_split(100, val_fraction=0.3, seed=7)
    assert not np.array_equal(a_tr, c_tr)  # different seed → different split


def test_train_val_split_validates_arguments():
    with pytest.raises(ValueError):
        train_val_split(1)
    with pytest.raises(ValueError):
        train_val_split(10, val_fraction=0.0)


def test_bootstrap_ci_brackets_the_point_estimate():
    rng = np.random.default_rng(0)
    y_true = rng.integers(0, 2, 400)
    y_pred = np.logical_or(y_true, rng.random(400) < 0.1)
    lo, hi = bootstrap_ci(y_true, y_pred, metric="f1", n_boot=200, seed=1)
    point = f1_score(y_true, y_pred)
    assert lo <= point <= hi
    assert 0.0 <= lo <= hi <= 1.0


def test_bootstrap_ci_rejects_unknown_metric():
    with pytest.raises(ValueError):
        bootstrap_ci([1, 0], [1, 0], metric="nope")
