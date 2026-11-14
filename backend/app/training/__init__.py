"""Training pipeline: registry, metrics and honest run records."""
from app.training.metrics import binary_metrics, confusion_counts, train_val_split
from app.training.pipeline import run_training
from app.training.registry import DATASETS, dataset_catalog, dataset_infos

__all__ = [
    "DATASETS", "dataset_catalog", "dataset_infos",
    "binary_metrics", "confusion_counts", "train_val_split", "run_training",
]
