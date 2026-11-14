"""AGENT 08 — Agriculture & Farming Intelligence.

Baseline: patch-scale temporal statistics screening for field-like change
patterns (moderate magnitude, high within-field variability, spatially
organised patches). Crop typing requires WorldCereal/field boundaries, which
are registered but not bundled — so outputs are field-pattern *candidates*.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import numpy as np
from scipy import ndimage

from app.agents._common import confidence_score, frame_region, mean_in, regions, severity_from
from app.agents.base import AgentCandidate, AgentContext, AgentResult, BaseAgent
from app.change_detection.unsupervised import build_patch_grid, cluster_change
from app.preprocessing.raster import pixel_area_km2


def _local_std(arr, size=5):
    m = ndimage.uniform_filter(np.nan_to_num(arr, nan=0.0), size=size)
    mq = ndimage.uniform_filter(np.nan_to_num(arr, nan=0.0) ** 2, size=size)
    return np.sqrt(np.maximum(mq - m ** 2, 0.0))


class AgricultureAgent(BaseAgent):
    id = "agriculture"
    name = "Agriculture & Farming Intelligence"
    ordinal = 8
    category = "AGRICULTURE"
    purpose = (
        "Monitor agricultural landscapes: field-scale change, crop-pattern changes, "
        "agricultural land conversion, flooded farmland and seasonal pattern shifts."
    )
    status = "experimental"
    status_reason = (
        "Patch-statistics baseline runs on real imagery, but no crop mask/field-boundary layer "
        "(WorldCereal, ESA WorldCover) is bundled, so agricultural *typing* is not claimed."
    )
    baseline_method = "Patch-scale temporal statistics + spatial clustering of change"
    capabilities = [
        "Field-scale change patch detection",
        "Spatial clustering of change styles",
        "Flooded-farmland screening via the water agent's overlap",
        "Seasonal-pattern hooks (needs multi-year stack — not configured)",
    ]
    supported_inputs = ["S1_RTC", "NISAR_GCOV", "S1_GRD_GEOCODED"]
    datasets = [
        {"id": "worldcereal", "name": "WorldCereal cropland/annual crops",
         "status": "interface_only", "note": "Registration required; interface registered."},
        {"id": "esa_worldcover", "name": "ESA WorldCover (cropland class)",
         "status": "interface_only", "note": "Not downloaded in this deployment."},
        {"id": "crop_field_boundaries", "name": "Global field boundary datasets",
         "status": "not_configured", "note": "No field-boundary layer bundled."},
    ]
    evaluation = [
        {"metric": "precision", "value": None, "note": "Not measured — no crop labels."},
        {"metric": "recall", "value": None, "note": "Not measured."},
        {"metric": "f1", "value": None, "note": "Not measured."},
    ]
    model_version = "patch-stats-baseline-1.0"
    config = {"min_area_km2": 0.1, "min_local_std_db": 1.6, "max_delta_db": 6.0,
              "confidence_cap": 0.5}
    output_schema = {
        "field_change_mask": "boolean mask of field-scale change",
        "area_km2": "geodesic area",
        "mean_change_db": "mean backscatter change",
        "field_texture_db": "within-patch texture standard deviation",
        "crop_type": "not asserted (no crop mask configured)",
    }
    known_limitations = [
        "No crop mask: change may be bare soil, water, or urban works rather than farmland.",
        "Two dates cannot resolve within-season phenology; a full time series is needed for "
        "seasonal classification.",
        "Tillage, planting and harvest all produce similar backscatter changes.",
        "Confidence capped at 0.5 while no land-cover context exists.",
    ]

    def _select_specific(self, ctx: AgentContext) -> tuple:
        if not ctx.has_pair:
            return False, "SINGLE_DATE_ONLY", "Requires two observations."
        if ctx.change is None:
            return False, "EARLIER_FAILURE", "Change-detection stage produced no layer."
        before = ctx.before
        valid = ctx.valid if ctx.valid is not None else before.valid
        db = before.db(before.primary_pol)
        std = float(np.nanmedian(_local_std(db)[valid])) if valid is not None else 0.0
        if std < self.config["min_local_std_db"]:
            return False, "NO_AGRICULTURAL_TEXTURE", (
                f"Median local texture is {std:.2f} dB (threshold "
                f"{self.config['min_local_std_db']} dB) — surface is too uniform for "
                "field-scale pattern analysis."
            )
        return True, "SUFFICIENT_VALID_PIXELS", (
            f"Field-like texture present (median {std:.2f} dB) and a change layer exists."
        )

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.time()
        logs: List[str] = []
        try:
            region = frame_region(ctx)
            before, after = ctx.before, ctx.after
            valid = ctx.valid if ctx.valid is not None else (before.valid & after.valid)
            b_db, a_db = before.db(before.primary_pol), after.db(after.primary_pol)
            diff = ctx.change.diff_db
            thr = ctx.change.threshold_db

            # field-like change: moderate magnitude, high local variability
            moderate = (np.abs(diff) > max(1.5, thr * 0.7)) & (np.abs(diff) < self.config["max_delta_db"])
            std_b, std_a = _local_std(b_db), _local_std(a_db)
            field_like = ((std_b > self.config["min_local_std_db"]) |
                          (std_a > self.config["min_local_std_db"]))
            mask = moderate & field_like & valid
            logs.append(f"field-like change px={int(mask.sum())} (thr {thr:.2f} dB)")
            if mask.sum() < 40:
                return self._result(status="no_candidates", reason_code="NO_FIELD_PATTERN",
                                    reason="No moderate, texture-rich change patches found — the "
                                           "region does not show field-scale patterns.",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000))

            cl = cluster_change(b_db, a_db, valid, mask, k=3)
            logs.extend(cl.get("notes", []))
            mask = ndimage.binary_opening(mask, ndimage.generate_binary_structure(2, 2))
            comps = regions(mask, before.transform, region=region,
                            min_area_km2=self.config["min_area_km2"], max_components=4)
            if not comps:
                return self._result(status="no_candidates", reason_code="BELOW_MIN_AREA",
                                    reason="Field-scale change patches below minimum mapping area.",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000))
            candidates: List[AgentCandidate] = []
            px_km2 = pixel_area_km2(before.transform, b_db.shape)
            for comp in comps:
                m = self._mask(comp, mask, before.transform)
                delta = mean_in(diff, m) or 0.0
                tex = float(np.nanmedian(std_b[m])) if m.any() else 0.0
                conf = min(
                    confidence_score(magnitude_db=abs(delta), area_km2_=comp["area_km2"],
                                     quality=ctx.quality.get("quality_score", 0.0), persistent=False),
                    self.config["confidence_cap"],
                )
                candidates.append(AgentCandidate(
                    title=f"Agricultural pattern change candidate ({comp['area_km2']:.2f} km²)",
                    geometry=comp["geometry"], area_km2=comp["area_km2"], confidence=conf,
                    severity=severity_from(comp["area_km2"], abs(delta), "low"),
                    measurements={
                        "mean_change_db": round(delta, 3),
                        "field_texture_db": round(tex, 3),
                        "pixels": int(m.sum()),
                        "clusters_found": cl.get("k", 0),
                        "crop_type": None,
                    },
                    supporting=[
                        f"Moderate backscatter change ({delta:+.2f} dB) with field-scale texture "
                        f"({tex:.2f} dB local variability) between {before.datetime} and "
                        f"{after.datetime}.",
                        f"Patch area {comp['area_km2']:.2f} km² is consistent with field blocks.",
                    ],
                    conflicting=[
                        "No crop or field-boundary layer was available, so agricultural use is "
                        "inferred from texture alone.",
                    ],
                    uncertainty=(
                        "Planting, tillage, harvest, bare soil and water change all produce the "
                        "same signature. Confidence is a heuristic cap of "
                        f"{self.config['confidence_cap']} without land-cover context."
                    ),
                    explanation=(
                        f"Between {before.datetime} and {after.datetime} a "
                        f"{comp['area_km2']:.2f} km² block changed by {delta:+.2f} dB while "
                        "keeping strong field-scale texture. That pattern is typical of "
                        "agricultural activity, but no crop/field dataset was configured to "
                        "confirm land use, so the finding is reported as an agricultural-pattern "
                        "candidate requiring verification."
                    ),
                    first_observed=after.datetime, tags=["field_pattern", "agriculture"],
                ))
            return self._result(
                status="succeeded", candidates=candidates, logs=logs,
                metrics={"candidates": len(candidates), "field_like_px": int(mask.sum()),
                         "clusters": cl.get("k", 0)},
                reason_code="SUFFICIENT_VALID_PIXELS", reason="Field-pattern screening succeeded.",
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
