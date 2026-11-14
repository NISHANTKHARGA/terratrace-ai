"""Training pipeline.

Two honest outcomes:

* **registered_only** — the dataset is known/registered but not present in this
  deployment, so nothing is trained and no metrics are invented.
* **completed** — a labelled feature table really exists on disk; a model is
  fitted, evaluated on a held-out split with real metrics, and a checkpoint is
  written and registered.

``failed`` is used for genuine errors (unknown agent, unreadable data, empty
label set).
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from app.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.database.models import ModelVersion, TrainingRun, now_iso, new_id
from app.database.session import session_scope
from app.agents import get_agent
from app.training.registry import get_dataset, local_dataset_path

log = get_logger("training.pipeline")

MAX_SAMPLES = 200_000


# --------------------------------------------------------------------- helpers
def _feature_file(config: Dict[str, Any], dataset_id: str) -> Optional[Path]:
    explicit = config.get("features_path")
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    base = local_dataset_path(dataset_id)
    for name in ("features.npz", "features.csv", "labels.npz"):
        cand = base / name
        if cand.is_file():
            return cand
    return None


def _load_features(path: Path) -> Dict[str, Any]:
    """Load a real labelled feature table (npz or csv)."""
    if path.suffix == ".npz":
        data = np.load(path, allow_pickle=True)
        X = np.asarray(data["X"], dtype="float64")
        y = np.asarray(data["y"]).ravel()
        names = [str(n) for n in data["feature_names"]] if "feature_names" in data.files else [
            f"f{i}" for i in range(X.shape[1])
        ]
    else:
        import csv

        with path.open("r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            raise ValueError("feature table is empty")
        label_key = next((k for k in rows[0] if k.lower() in ("label", "y", "target")), None)
        if label_key is None:
            raise ValueError("feature table must contain a 'label' column")
        names = [k for k in rows[0] if k != label_key]
        X = np.array([[float(r[k]) for k in names] for r in rows], dtype="float64")
        raw = [r[label_key] for r in rows]
        try:
            y = np.array([float(v) for v in raw])
        except ValueError:
            y = np.array(raw)
    if X.ndim != 2 or X.shape[0] != y.shape[0]:
        raise ValueError(f"X {X.shape} and y {y.shape} are inconsistent")
    if X.shape[0] > MAX_SAMPLES:
        X, y = X[:MAX_SAMPLES], y[:MAX_SAMPLES]
    return {"X": X, "y": y, "feature_names": names}


def _register_model(
    agent_id: str, model_id: str, *, version: str, metrics: List[Dict[str, Any]],
    checkpoint: Path, dataset_ids: List[str], sample_count: int, config: Dict[str, Any],
    limitations: List[str],
) -> None:
    with session_scope() as db:
        rec = db.get(ModelVersion, model_id)
        if rec is None:
            rec = ModelVersion(id=model_id, agent_id=agent_id, name=model_id.split(":", 1)[-1],
                               kind="trained_model")
            db.add(rec)
        rec.kind = "trained_model"
        rec.version = version
        rec.status = "candidate"
        rec.dataset_ids = dataset_ids
        rec.metrics = metrics
        rec.checkpoint_path = str(checkpoint)
        rec.trained_at = now_iso()
        rec.sample_count = sample_count
        rec.limitations = limitations
        rec.config = config


def _record_run(**fields: Any) -> Dict[str, Any]:
    run = {
        "id": fields.get("id") or new_id("trn"),
        "agent_id": fields["agent_id"],
        "model_id": fields["model_id"],
        "status": fields["status"],
        "started_at": fields.get("started_at") or now_iso(),
        "ended_at": fields.get("ended_at"),
        "dataset_ids": fields.get("dataset_ids") or [],
        "config": fields.get("config") or {},
        "metrics": fields.get("metrics") or {},
        "notes": fields.get("notes", ""),
    }
    with session_scope() as db:
        db.add(TrainingRun(**run))
    return run


# --------------------------------------------------------------------- pipeline
def run_training(
    agent_id: str,
    dataset_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run (or honestly decline) a training job for one agent."""
    cfg = dict(config or {})
    started = now_iso()
    agent = get_agent(agent_id)
    if agent is None:
        raise AppError("unknown_agent", f"Agent '{agent_id}' does not exist", 404)

    dataset_id = dataset_id or next(
        (d["id"] for d in agent.datasets if d.get("status") == "available"),
        (agent.datasets[0]["id"] if agent.datasets else None),
    )
    if dataset_id is None:
        return _record_run(
            agent_id=agent_id, model_id=f"{agent_id}:baseline", status="failed",
            started_at=started, ended_at=now_iso(), config=cfg,
            notes="This agent declares no dataset, so there is nothing to train on.",
        )

    dataset = get_dataset(dataset_id)
    if dataset is None:
        return _record_run(
            agent_id=agent_id, model_id=f"{agent_id}:baseline", status="failed",
            started_at=started, ended_at=now_iso(), dataset_ids=[dataset_id], config=cfg,
            notes=f"Dataset '{dataset_id}' is not in the registry.",
        )

    model_id = f"{agent_id}:{cfg.get('model_name', dataset_id)}"
    feature_file = _feature_file(cfg, dataset_id)

    # ---------------------------------------------------- nothing to train on
    if dataset["status"] != "available" or feature_file is None:
        why = (
            f"Dataset '{dataset_id}' is registered with status "
            f"'{dataset['status']}' but is not present in this deployment."
            if feature_file is None else
            f"Dataset '{dataset_id}' cannot be read in this deployment."
        )
        return _record_run(
            agent_id=agent_id, model_id=model_id, status="registered_only",
            started_at=started, ended_at=now_iso(), dataset_ids=[dataset_id], config=cfg,
            metrics={},
            notes=why + " No model was fitted and no metrics were produced — TerraTrace "
                       "does not invent evaluation numbers. Place a labelled feature table "
                       f"at {local_dataset_path(dataset_id)}/features.npz (arrays 'X', 'y') "
                       "to enable real training.",
        )

    # ------------------------------------------------------------ real training
    try:
        payload = _load_features(feature_file)
    except Exception as exc:
        return _record_run(
            agent_id=agent_id, model_id=model_id, status="failed",
            started_at=started, ended_at=now_iso(), dataset_ids=[dataset_id], config=cfg,
            notes=f"Could not read labelled features from {feature_file}: {exc}",
        )

    X, y = payload["X"], payload["y"]
    if X.shape[0] < 4:
        return _record_run(
            agent_id=agent_id, model_id=model_id, status="failed",
            started_at=started, ended_at=now_iso(), dataset_ids=[dataset_id], config=cfg,
            notes=f"Only {X.shape[0]} labelled sample(s) available; at least 4 are required "
                  "to produce a hold-out evaluation.",
        )

    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import accuracy_score

        from app.training.metrics import binary_metrics, train_val_split

        seed = int(cfg.get("seed", 42))
        train_idx, val_idx = train_val_split(X.shape[0], val_fraction=0.3, seed=seed)
        clf = RandomForestClassifier(
            n_estimators=int(cfg.get("n_estimators", 300)),
            max_depth=cfg.get("max_depth"),
            min_samples_leaf=int(cfg.get("min_samples_leaf", 3)),
            class_weight="balanced_subsample",
            random_state=seed,
            n_jobs=-1,
        )
        clf.fit(X[train_idx], y[train_idx])
        pred_tr = clf.predict(X[train_idx])
        pred_va = clf.predict(X[val_idx])
        y_tr, y_va = y[train_idx], y[val_idx]

        metrics: Dict[str, Any] = {
            "train_accuracy": round(float(accuracy_score(y_tr, pred_tr)), 6),
            "val_accuracy": round(float(accuracy_score(y_va, pred_va)), 6),
            "n_train": int(train_idx.size),
            "n_val": int(val_idx.size),
        }
        metric_records: List[Dict[str, Any]] = [
            {"name": "train_accuracy", "value": metrics["train_accuracy"], "split": "train"},
            {"name": "val_accuracy", "value": metrics["val_accuracy"], "split": "validation"},
        ]
        if set(np.unique(y)) <= {0, 1}:
            bm = binary_metrics(y_va, pred_va)
            for k in ("precision", "recall", "f1", "iou", "specificity"):
                metrics[f"val_{k}"] = bm[k]
                metric_records.append({"name": f"val_{k}", "value": bm[k], "split": "validation"})
            metrics["val_tp"], metrics["val_fp"] = int(bm["tp"]), int(bm["fp"])
            metrics["val_fn"], metrics["val_tn"] = int(bm["fn"]), int(bm["tn"])

        out_dir = settings.data_dir / "models"
        out_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = out_dir / f"{model_id.replace(':', '_')}.joblib"
        import joblib

        joblib.dump({"estimator": clf, "feature_names": payload["feature_names"],
                     "agent_id": agent_id, "dataset_id": dataset_id,
                     "trained_at": now_iso()}, checkpoint)

        limitations = [
            "Model trained on a locally supplied labelled feature table; it is a candidate "
            "artefact, not a validated operational model.",
            "Metrics are hold-out measurements on the supplied split only and do not "
            "generalise automatically to other regions or sensors.",
        ]
        _register_model(
            agent_id, model_id, version=f"rf-{now_iso()[:10]}", metrics=metric_records,
            checkpoint=checkpoint, dataset_ids=[dataset_id],
            sample_count=int(X.shape[0]), config={**cfg, "feature_names": payload["feature_names"]},
            limitations=limitations,
        )
        notes = (
            f"Trained RandomForest on {X.shape[0]} labelled samples from '{dataset_id}' "
            f"(hold-out {int(val_idx.size)} samples). Checkpoint: {checkpoint.name}."
        )
        log.info("training completed", extra={"extra_fields": {"model_id": model_id}})
        return _record_run(
            agent_id=agent_id, model_id=model_id, status="completed",
            started_at=started, ended_at=now_iso(), dataset_ids=[dataset_id],
            config={**cfg, "n_features": int(X.shape[1])}, metrics=metrics, notes=notes,
        )
    except Exception as exc:
        return _record_run(
            agent_id=agent_id, model_id=model_id, status="failed",
            started_at=started, ended_at=now_iso(), dataset_ids=[dataset_id], config=cfg,
            notes=f"Training failed: {type(exc).__name__}: {exc}",
        )
