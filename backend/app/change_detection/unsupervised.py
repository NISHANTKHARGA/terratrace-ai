"""Unsupervised change screening: anomaly detection and novel-change clustering.

Used by Agent 12 (Unknown Change Discovery) and as a generic screen. Nothing
here assigns a semantic category — outputs are deliberately *unclassified*.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import ndimage
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest

from app.preprocessing.raster import robust_mad

FEATURE_NAMES = [
    "mean_before_db", "std_before_db", "p10_before_db", "p90_before_db",
    "mean_after_db", "std_after_db", "p10_after_db", "p90_after_db",
    "mean_diff_db", "std_diff_db", "abs_diff_p90_db", "frac_changed",
]


@dataclass
class PatchGrid:
    features: np.ndarray            # (n_patches, n_features)
    valid: np.ndarray               # (n_patches,) usable patches
    shape: Tuple[int, int]          # (rows, cols) of patches
    row0: np.ndarray
    col0: np.ndarray
    size: int


def build_patch_grid(
    before_db: np.ndarray,
    after_db: np.ndarray,
    valid: np.ndarray,
    changed: Optional[np.ndarray] = None,
    patch: int = 16,
) -> PatchGrid:
    h, w = before_db.shape
    rows = h // patch
    cols = w // patch
    feats = np.zeros((rows * cols, len(FEATURE_NAMES)), dtype="float32")
    ok = np.zeros(rows * cols, dtype=bool)
    row0 = np.repeat(np.arange(rows) * patch, cols)
    col0 = np.tile(np.arange(cols) * patch, rows)

    i = 0
    for r in range(rows):
        for c in range(cols):
            sl = (slice(r * patch, (r + 1) * patch), slice(c * patch, (c + 1) * patch))
            v = valid[sl]
            b = before_db[sl][v & np.isfinite(before_db[sl])]
            a = after_db[sl][v & np.isfinite(after_db[sl])]
            if b.size < patch * patch * 0.4:
                i += 1
                continue
            d = a - b if a.size == b.size else np.array([])
            if d.size == 0:
                i += 1
                continue
            frac = float(changed[sl].mean()) if changed is not None else 0.0
            feats[i] = [
                np.mean(b), np.std(b), np.percentile(b, 10), np.percentile(b, 90),
                np.mean(a), np.std(a), np.percentile(a, 10), np.percentile(a, 90),
                np.mean(d), np.std(d), np.percentile(np.abs(d), 90), frac,
            ]
            ok[i] = True
            i += 1
    return PatchGrid(feats, ok, (rows, cols), row0, col0, patch)


def patch_mask(grid: PatchGrid, selected: np.ndarray, shape: Tuple[int, int]) -> np.ndarray:
    """Expand selected patches to a pixel mask."""
    out = np.zeros(shape, dtype=bool)
    idx = np.where(selected)[0]
    for i in idx:
        r0, c0 = int(grid.row0[i]), int(grid.col0[i])
        out[r0:r0 + grid.size, c0:c0 + grid.size] = True
    return out


def detect_patch_anomalies(
    before_db: np.ndarray,
    after_db: np.ndarray,
    valid: np.ndarray,
    changed: Optional[np.ndarray] = None,
    *,
    contamination: float = 0.04,
    patch: int = 16,
) -> Dict[str, Any]:
    """IsolationForest over temporal patch statistics → unexplained-change pixels."""
    grid = build_patch_grid(before_db, after_db, valid, changed, patch=patch)
    if grid.valid.sum() < 30:
        return {
            "anomaly_mask": np.zeros(before_db.shape, dtype=bool),
            "scores": None,
            "n_anomalous_patches": 0,
            "usable_patches": int(grid.valid.sum()),
            "method": "isolation_forest",
            "notes": ["Not enough valid patches for anomaly screening."],
        }
    X = grid.features[grid.valid]
    # constant columns break nothing for IsolationForest but normalise anyway
    med = np.median(X, axis=0)
    mad = robust_mad(X.ravel() - np.median(X)) if X.size else 1.0
    Xs = (X - med) / (np.median(np.abs(X - med), axis=0) + 1e-6)

    model = IsolationForest(
        n_estimators=200, contamination=contamination, random_state=0, n_jobs=1
    )
    labels = model.fit_predict(Xs)  # -1 = anomaly
    scores = model.decision_function(Xs)

    valid_idx = np.where(grid.valid)[0]
    anomalous_global = np.zeros(grid.features.shape[0], dtype=bool)
    anomalous_global[valid_idx] = labels == -1
    mask = patch_mask(grid, anomalous_global, before_db.shape)
    mask &= valid

    score_map = np.full(grid.features.shape[0], np.nan, dtype="float32")
    score_map[valid_idx] = scores.astype("float32")
    notes = [
        f"IsolationForest screened {int(grid.valid.sum())} valid {patch}px patches; "
        f"{int((labels == -1).sum())} flagged as statistically unusual "
        f"(contamination={contamination})."
    ]
    return {
        "anomaly_mask": mask,
        "scores": score_map.reshape(grid.shape),
        "n_anomalous_patches": int((labels == -1).sum()),
        "usable_patches": int(grid.valid.sum()),
        "method": "isolation_forest",
        "model_params": {"n_estimators": 200, "contamination": contamination, "patch": patch},
        "notes": notes,
        "grid": grid,
    }


def cluster_change(
    before_db: np.ndarray,
    after_db: np.ndarray,
    valid: np.ndarray,
    changed: np.ndarray,
    *,
    k: int = 3,
    patch: int = 16,
) -> Dict[str, Any]:
    """Group changed patches into k novel change styles (no semantic labels)."""
    grid = build_patch_grid(before_db, after_db, valid, changed, patch=patch)
    changed_patch = grid.features[:, FEATURE_NAMES.index("frac_changed")] > 0.02
    usable = grid.valid & changed_patch
    if usable.sum() < k + 5:
        return {"labels": None, "k": 0, "usable": int(usable.sum()),
                "notes": ["Too few changed patches to cluster."]}
    X = grid.features[usable][:, [8, 9, 10, 11]]
    X = (X - X.mean(0)) / (X.std(0) + 1e-6)
    km = KMeans(n_clusters=k, n_init=10, random_state=0)
    lab = km.fit_predict(X)
    full = np.full(grid.features.shape[0], -1, dtype=int)
    full[np.where(usable)[0]] = lab
    mask = np.zeros(before_db.shape, dtype=bool)
    for i, l in enumerate(full):
        if l >= 0:
            r0, c0 = int(grid.row0[i]), int(grid.col0[i])
            mask[r0:r0 + grid.size, c0:c0 + grid.size] = True
    stats = []
    for c in range(k):
        m = lab == c
        if not m.any():
            continue
        sub = grid.features[usable][m]
        stats.append({
            "cluster": int(c),
            "patches": int(m.sum()),
            "mean_diff_db": round(float(sub[:, 8].mean()), 3),
            "std_diff_db": round(float(sub[:, 9].mean()), 3),
            "frac_changed": round(float(sub[:, 11].mean()), 4),
        })
    return {"labels": lab, "k": k, "mask": mask, "cluster_stats": stats,
            "usable": int(usable.sum()),
            "notes": ["Clusters describe different *styles* of change; they are not "
                      "assigned to any known category."]}
