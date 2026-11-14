"""Classification metrics.

Every number here is computed from real `y_true` / `y_pred` pairs — there are no
placeholder or example values. A metric is only ever reported when it has been
measured on actual labelled samples.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

__all__ = [
    "confusion_counts",
    "precision",
    "recall",
    "f1_score",
    "iou",
    "accuracy",
    "specificity",
    "binary_metrics",
    "train_val_split",
    "bootstrap_ci",
]


def _as_bool_arrays(y_true: Sequence, y_pred: Sequence) -> Tuple[np.ndarray, np.ndarray]:
    a = np.asarray(list(y_true)).astype(bool).ravel()
    b = np.asarray(list(y_pred)).astype(bool).ravel()
    if a.shape != b.shape:
        raise ValueError(f"y_true ({a.size}) and y_pred ({b.size}) must have the same length")
    if a.size == 0:
        raise ValueError("cannot compute metrics on an empty sample set")
    return a, b


def confusion_counts(y_true: Sequence, y_pred: Sequence) -> Dict[str, int]:
    """True/false positives/negatives for the positive class."""
    t, p = _as_bool_arrays(y_true, y_pred)
    return {
        "tp": int(np.logical_and(t, p).sum()),
        "fp": int(np.logical_and(~t, p).sum()),
        "fn": int(np.logical_and(t, ~p).sum()),
        "tn": int(np.logical_and(~t, ~p).sum()),
    }


def precision(y_true: Sequence, y_pred: Sequence) -> float:
    c = confusion_counts(y_true, y_pred)
    denom = c["tp"] + c["fp"]
    return float(c["tp"] / denom) if denom else 0.0


def recall(y_true: Sequence, y_pred: Sequence) -> float:
    c = confusion_counts(y_true, y_pred)
    denom = c["tp"] + c["fn"]
    return float(c["tp"] / denom) if denom else 0.0


def f1_score(y_true: Sequence, y_pred: Sequence) -> float:
    p, r = precision(y_true, y_pred), recall(y_true, y_pred)
    return float(2 * p * r / (p + r)) if (p + r) else 0.0


def iou(y_true: Sequence, y_pred: Sequence) -> float:
    """Intersection over union (Jaccard) for the positive class."""
    c = confusion_counts(y_true, y_pred)
    denom = c["tp"] + c["fp"] + c["fn"]
    return float(c["tp"] / denom) if denom else 0.0


def accuracy(y_true: Sequence, y_pred: Sequence) -> float:
    t, p = _as_bool_arrays(y_true, y_pred)
    return float((t == p).mean())


def specificity(y_true: Sequence, y_pred: Sequence) -> float:
    c = confusion_counts(y_true, y_pred)
    denom = c["tn"] + c["fp"]
    return float(c["tn"] / denom) if denom else 0.0


def binary_metrics(y_true: Sequence, y_pred: Sequence) -> Dict[str, float]:
    """All standard binary metrics plus the raw confusion counts."""
    counts = confusion_counts(y_true, y_pred)
    return {
        "precision": round(precision(y_true, y_pred), 6),
        "recall": round(recall(y_true, y_pred), 6),
        "f1": round(f1_score(y_true, y_pred), 6),
        "iou": round(iou(y_true, y_pred), 6),
        "accuracy": round(accuracy(y_true, y_pred), 6),
        "specificity": round(specificity(y_true, y_pred), 6),
        **{k: float(v) for k, v in counts.items()},
    }


def train_val_split(
    n: int, val_fraction: float = 0.3, seed: int = 42
) -> Tuple[np.ndarray, np.ndarray]:
    """Deterministic shuffled split into train/validation index arrays."""
    if n < 2:
        raise ValueError("need at least 2 samples to split")
    if not 0.0 < val_fraction < 1.0:
        raise ValueError("val_fraction must be in (0, 1)")
    rng = np.random.default_rng(seed)
    idx = np.arange(n)
    rng.shuffle(idx)
    n_val = max(1, int(round(n * val_fraction)))
    n_val = min(n_val, n - 1)
    return idx[n_val:], idx[:n_val]


def bootstrap_ci(
    y_true: Sequence, y_pred: Sequence, metric: str = "f1",
    n_boot: int = 1000, seed: int = 0, alpha: float = 0.05,
) -> Tuple[float, float]:
    """Percentile bootstrap confidence interval for a metric (real resampling)."""
    fns = {
        "f1": f1_score, "precision": precision, "recall": recall,
        "iou": iou, "accuracy": accuracy, "specificity": specificity,
    }
    if metric not in fns:
        raise ValueError(f"unknown metric '{metric}'; expected one of {sorted(fns)}")
    t, p = _as_bool_arrays(y_true, y_pred)
    rng = np.random.default_rng(seed)
    values: List[float] = []
    for _ in range(n_boot):
        sample = rng.integers(0, t.size, t.size)
        values.append(fns[metric](t[sample], p[sample]))
    lo = float(np.percentile(values, 100 * (alpha / 2)))
    hi = float(np.percentile(values, 100 * (1 - alpha / 2)))
    return round(lo, 6), round(hi, 6)
