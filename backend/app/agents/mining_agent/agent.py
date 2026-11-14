"""AGENT 10 — Mining & Land Disturbance Intelligence.

Baseline: unsupervised anomaly screening over patch statistics combined with
large-magnitude surface change — mining/quarry excavation is a high-magnitude,
spatially coherent disturbance with a distinct brightness/texture trajectory.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import numpy as np
from scipy import ndimage

from app.agents._common import confidence_score, frame_region, mean_in, regions, severity_from
from app.agents.base import AgentCandidate, AgentContext, AgentResult, BaseAgent
from app.change_detection.unsupervised import detect_patch_anomalies


class MiningAgent(BaseAgent):
    id = "mining"
    name = "Mining & Land Disturbance Intelligence"
    ordinal = 10
    category = "MINING_DISTURBANCE"
    purpose = (
        "Identify mining-related and excavation-related landscape change: mining expansion, "
        "quarry growth, excavation and land disturbance around mining infrastructure."
    )
    status = "experimental"
    status_reason = (
        "Anomaly-based disturbance screening runs, but no global mining-site inventory is "
        "configured to confirm that an anomaly is mining rather than another excavation process."
    )
    baseline_method = "IsolationForest patch anomalies ∩ high-magnitude surface change"
    capabilities = [
        "Unsupervised anomaly detection over temporal patch statistics",
        "Excavation-like change candidate mapping",
        "Land-cover context hooks (not configured)",
    ]
    supported_inputs = ["S1_RTC", "NISAR_GCOV", "S1_GRD_GEOCODED"]
    datasets = [
        {"id": "global_mining_footprints", "name": "Global mining site inventories",
         "status": "not_configured", "note": "No mining inventory bundled with this deployment."},
        {"id": "esa_worldcover", "name": "ESA WorldCover land-cover context",
         "status": "interface_only", "note": "Registration required; interface registered."},
        {"id": "gmw_mangrove", "name": "Natural-cover reference layers", "status": "not_configured",
         "note": "Not used."},
    ]
    evaluation = [
        {"metric": "precision", "value": None, "note": "Not measured — no mining labels."},
        {"metric": "recall", "value": None, "note": "Not measured."},
        {"metric": "f1", "value": None, "note": "Not measured."},
    ]
    model_version = "isolation-forest-baseline-1.0"
    config = {"min_area_km2": 0.08, "min_delta_db": 3.5, "contamination": 0.03,
              "confidence_cap": 0.5}
    output_schema = {
        "disturbance_mask": "boolean mask of anomalous high-magnitude change",
        "area_km2": "geodesic area",
        "anomaly_score": "IsolationForest decision score of the patch (relative)",
        "mean_change_db": "backscatter change inside candidate",
        "mining_confirmed": "false — no inventory configured",
    }
    known_limitations = [
        "An anomaly is not evidence of mining: construction, landslides, logging and floods "
        "are also statistically unusual.",
        "No mining inventory or land-cover context is bundled.",
        "Small quarries below the minimum mapping area are missed.",
        "Anomaly scores are dataset-relative and are not calibrated probabilities.",
    ]

    def _select_specific(self, ctx: AgentContext) -> tuple:
        if not ctx.has_pair:
            return False, "SINGLE_DATE_ONLY", "Requires two observations."
        if ctx.change is None:
            return False, "EARLIER_FAILURE", "Change-detection stage produced no layer."
        return True, "MULTI_DATE_OVERLAP", (
            "Two observations with a change layer are available for anomaly screening."
        )

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.time()
        logs: List[str] = []
        try:
            region = frame_region(ctx)
            before, after = ctx.before, ctx.after
            valid = ctx.valid if ctx.valid is not None else (before.valid & after.valid)
            b_db, a_db = before.db(before.primary_pol), after.db(after.primary_pol)
            thr = ctx.change.threshold_db
            strong = (np.abs(ctx.change.diff_db) > max(thr, self.config["min_delta_db"])) & valid

            anom = detect_patch_anomalies(
                b_db, a_db, valid, ctx.change.mask,
                contamination=self.config["contamination"],
            )
            logs.extend(anom.get("notes", []))
            mask = strong & anom["anomaly_mask"]
            logs.append(f"anomalous px={int(anom['anomaly_mask'].sum())}, "
                        f"anomalous∧strong px={int(mask.sum())}")
            if mask.sum() < 20:
                return self._result(
                    status="no_candidates", reason_code="NO_ANOMALOUS_DISTURBANCE",
                    reason="No patch was both statistically unusual and strongly changed — "
                           "nothing met the disturbance screen for this region.",
                    logs=logs, duration_ms=int((time.time() - t0) * 1000),
                    metrics={"anomalous_px": int(anom["anomaly_mask"].sum()),
                             "usable_patches": anom.get("usable_patches", 0)},
                )
            mask = ndimage.binary_opening(mask, ndimage.generate_binary_structure(2, 2))
            comps = regions(mask, before.transform, region=region,
                            min_area_km2=self.config["min_area_km2"], max_components=4)
            if not comps:
                return self._result(status="no_candidates", reason_code="BELOW_MIN_AREA",
                                    reason="Anomalous disturbance patches below minimum mapping area.",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000))
            candidates: List[AgentCandidate] = []
            for comp in comps:
                m = self._mask(comp, mask, before.transform)
                delta = mean_in(ctx.change.diff_db, m) or 0.0
                conf = min(
                    confidence_score(magnitude_db=abs(delta), area_km2_=comp["area_km2"],
                                     quality=ctx.quality.get("quality_score", 0.0), persistent=False),
                    self.config["confidence_cap"],
                )
                candidates.append(AgentCandidate(
                    title=f"Land-disturbance anomaly ({comp['area_km2']:.2f} km²)",
                    geometry=comp["geometry"], area_km2=comp["area_km2"], confidence=conf,
                    severity=severity_from(comp["area_km2"], abs(delta)),
                    measurements={
                        "mean_change_db": round(delta, 3),
                        "pixels": int(m.sum()),
                        "anomalous_patches": anom.get("n_anomalous_patches", 0),
                        "usable_patches": anom.get("usable_patches", 0),
                        "mining_confirmed": False,
                        "anomaly_method": anom.get("method"),
                    },
                    supporting=[
                        f"Patch is statistically unusual relative to {anom.get('usable_patches')} "
                        "other patches in this region (IsolationForest).",
                        f"Backscatter changed by {delta:+.2f} dB between {before.datetime} and "
                        f"{after.datetime} over {comp['area_km2']:.2f} km².",
                    ],
                    conflicting=[
                        "No mining inventory or land-cover dataset was available; excavation "
                        "type is unconfirmed.",
                    ],
                    uncertainty=(
                        "Unsupervised anomaly detection describes rarity, not cause. Scores are "
                        "relative to this scene and are not calibrated probabilities."
                    ),
                    explanation=(
                        f"This {comp['area_km2']:.2f} km² patch changed by {delta:+.2f} dB and is "
                        "an outlier compared with the rest of the analysed region — the pattern "
                        "expected from a major surface excavation such as a quarry or mine "
                        "expansion. Because no mining inventory is configured, the cause is "
                        "unconfirmed and the candidate requires verification."
                    ),
                    first_observed=after.datetime, tags=["anomaly", "excavation_possible"],
                ))
            return self._result(status="succeeded", candidates=candidates, logs=logs,
                                metrics={"candidates": len(candidates),
                                         "anomalous_px": int(anom["anomaly_mask"].sum()),
                                         "strong_px": int(strong.sum())},
                                reason_code="SUFFICIENT_VALID_PIXELS",
                                reason="Anomaly ∩ strong-change screening produced regions.",
                                duration_ms=int((time.time() - t0) * 1000))
        except Exception as exc:
            return self._fail(exc, logs, t0)

    @staticmethod
    def _mask(comp, mask, transform):
        from rasterio import features as rfeatures
        from shapely.geometry import mapping
        try:
            g = rfeatures.geometry_mask([mapping(comp["geometry"])], out_shape=mask.shape,
                                        transform=transform, invert=True, all_touched=True)
            return g & mask
        except Exception:
            return mask
