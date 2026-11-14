"""Evaluation metrics used by agents, training and tests."""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np


def confusion(pred: np.ndarray, truth: np.ndarray) -> Dict[str, int]:
    p = pred.astype(bool).ravel()
    t = truth.astype(bool).ravel()
    n = min(p.size, t.size)
    p, t = p[:n], t[:n]
    tp = int(np.logical_and(p, t).sum())
    fp = int(np.logical_and(p, ~t).sum())
    fn = int(np.logical_and(~p, t).sum())
    tn = int(np.logical_and(~p, ~t).sum())
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def precision_recall_f1(pred: np.ndarray, truth: np.ndarray) -> Dict[str, Optional[float]]:
    c = confusion(pred, truth)
    tp, fp, fn = c["tp"], c["fp"], c["fn"]
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    if precision is None or recall is None or (precision + recall) == 0:
        f1 = None
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        **{k: v for k, v in c.items()},
    }


def iou(pred: np.ndarray, truth: np.ndarray) -> Optional[float]:
    p = pred.astype(bool).ravel()
    t = truth.astype(bool).ravel()
    n = min(p.size, t.size)
    p, t = p[:n], t[:n]
    inter = np.logical_and(p, t).sum()
    union = np.logical_or(p, t).sum()
    return round(float(inter / union), 4) if union else None


def accuracy(pred: np.ndarray, truth: np.ndarray) -> Optional[float]:
    p = pred.astype(bool).ravel()
    t = truth.astype(bool).ravel()
    n = min(p.size, t.size)
    if n == 0:
        return None
    return round(float((p[:n] == t[:n]).mean()), 4)


def false_positive_rate(pred: np.ndarray, truth: np.ndarray) -> Optional[float]:
    c = confusion(pred, truth)
    fp, tn = c["fp"], c["tn"]
    return round(fp / (fp + tn), 4) if (fp + tn) else None


def displacement_error(pred_offsets: np.ndarray, ref_offsets: np.ndarray) -> Dict[str, Optional[float]]:
    """Mean absolute offset error (pixels) for feature-tracking evaluation."""
    p = np.asarray(pred_offsets, dtype="float64")
    r = np.asarray(ref_offsets, dtype="float64")
    if p.size == 0 or p.size != r.size:
        return {"mean_abs_error_px": None, "rmse_px": None, "n": int(p.size)}
    err = p - r
    return {
        "mean_abs_error_px": round(float(np.mean(np.abs(err))), 4),
        "rmse_px": round(float(np.sqrt(np.mean(err ** 2))), 4),
        "n": int(p.size),
    }


def metric_pack(pred: np.ndarray, truth: np.ndarray) -> Dict[str, Optional[float]]:
    prf = precision_recall_f1(pred, truth)
    return {
        "precision": prf["precision"],
        "recall": prf["recall"],
        "f1": prf["f1"],
        "iou": iou(pred, truth),
        "accuracy": accuracy(pred, truth),
        "false_positive_rate": false_positive_rate(pred, truth),
        "tp": prf["tp"], "fp": prf["fp"], "fn": prf["fn"], "tn": prf["tn"],
    }
