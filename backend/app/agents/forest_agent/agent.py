"""AGENT 03 — Forest & Deforestation Intelligence.

Baseline: multi-temporal backscatter change with a texture-homogenisation test
(clearing makes radar texture more uniform). Forest *masking* needs a
land-cover layer (Global Forest Change / ESA WorldCover) which is registered as
an interface but not downloaded here, so results are explicitly experimental.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import numpy as np
from scipy import ndimage

from app.agents._common import (
    confidence_score, days_between, frame_region, mean_in, pct_in, persistence_note,
    regions, severity_from,
)
from app.agents.base import AgentCandidate, AgentContext, AgentResult, BaseAgent
from app.preprocessing.raster import pixel_area_km2


def _local_std(arr: np.ndarray, size: int = 5) -> np.ndarray:
    mean = ndimage.uniform_filter(np.nan_to_num(arr, nan=0.0), size=size)
    mean_sq = ndimage.uniform_filter(np.nan_to_num(arr, nan=0.0) ** 2, size=size)
    return np.sqrt(np.maximum(mean_sq - mean ** 2, 0.0))


class ForestAgent(BaseAgent):
    id = "forest"
    name = "Forest & Deforestation Intelligence"
    ordinal = 3
    category = "FOREST_LOSS"
    purpose = (
        "Identify potential forest disturbance and deforestation: clearing, logging and "
        "fragmentation candidates from multi-temporal SAR change plus texture analysis."
    )
    status = "experimental"
    status_reason = (
        "Change + texture baseline runs, but no forest land-cover mask is configured in this "
        "deployment, so candidates cannot be restricted to forested land and remain "
        "low-confidence 'requires verification' items."
    )
    baseline_method = "Multi-temporal dB change with local-texture homogenisation test"
    capabilities = [
        "Forest-clearing candidates (backscatter + texture)",
        "Post-disturbance texture homogenisation",
        "Change-patch statistics (magnitude, area, shape)",
    ]
    supported_inputs = ["S1_RTC", "NISAR_GCOV", "S1_GRD_GEOCODED"]
    datasets = [
        {"id": "global_forest_change", "name": "Global Forest Change (Hansen)",
         "status": "interface_only", "note": "Download requires Earthdata credentials; interface registered."},
        {"id": "esa_worldcover", "name": "ESA WorldCover 2021", "status": "interface_only",
         "note": "Registration required; interface registered."},
        {"id": "umd_global_forest", "name": "UMD global tree cover", "status": "not_configured",
         "note": "No tree-cover layer bundled with this deployment."},
    ]
    evaluation = [
        {"metric": "precision", "value": None, "note": "Not measured — no forest-loss labels configured."},
        {"metric": "recall", "value": None, "note": "Not measured."},
        {"metric": "f1", "value": None, "note": "Not measured."},
    ]
    model_version = "change-texture-baseline-1.0"
    config = {"min_area_km2": 0.05, "min_delta_db": 3.0, "texture_ratio": 0.9,
              "confidence_cap": 0.55}
    output_schema = {
        "disturbance_mask": "boolean mask of clearing-like change",
        "area_km2": "geodesic area",
        "mean_change_db": "mean backscatter difference inside candidate",
        "texture_ratio": "after/before local texture standard deviation",
        "verification_status": "always requires_verification without a forest mask",
    }
    known_limitations = [
        "No forest land-cover mask: candidates may be farmland, urban works or water change.",
        "Logging under canopy and selective logging are largely invisible to C-band SAR.",
        "Flooding, soil-moisture change and layover can imitate clearing signatures.",
        "Confidence is capped at 0.55 by design while no land-cover mask exists.",
    ]

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.time()
        logs: List[str] = []
        try:
            if ctx.change is None or not ctx.has_pair:
                return self._result(status="skipped", reason_code="NO_CHANGE_LAYER",
                                    reason="No change layer available for this run.", logs=logs,
                                    duration_ms=int((time.time() - t0) * 1000))
            region = frame_region(ctx)
            before, after = ctx.before, ctx.after
            valid = ctx.valid if ctx.valid is not None else (before.valid & after.valid)
            b_db, a_db = before.db(before.primary_pol), after.db(after.primary_pol)
            thr = ctx.change.threshold_db
            strong = np.abs(ctx.change.diff_db) > max(thr, self.config["min_delta_db"])
            strong &= valid

            std_b = _local_std(b_db)
            std_a = _local_std(a_db)
            with np.errstate(divide="ignore", invalid="ignore"):
                texture_ratio = np.where(std_b > 0.3, std_a / np.maximum(std_b, 1e-3), 1.0)
            homogenised = texture_ratio < self.config["texture_ratio"]
            clearing_like = strong & homogenised & valid
            logs.append(f"strong-change px={int(strong.sum())}, "
                        f"clearing-like px={int(clearing_like.sum())}")
            if clearing_like.sum() < 12:
                return self._result(
                    status="no_candidates", reason_code="NO_CLEARING_SIGNATURE",
                    reason="No region combined a strong backscatter change with the texture "
                           "homogenisation pattern expected after clearing.",
                    logs=logs, duration_ms=int((time.time() - t0) * 1000),
                    metrics={"strong_change_px": int(strong.sum())})
            clearing_like = ndimage.binary_opening(clearing_like, ndimage.generate_binary_structure(2, 2))
            comps = regions(clearing_like, before.transform, region=region,
                            min_area_km2=self.config["min_area_km2"], max_components=5)
            if not comps:
                return self._result(status="no_candidates", reason_code="BELOW_MIN_AREA",
                                    reason="Clearing-like patches below the minimum mapping area.",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000))
            px_km2 = pixel_area_km2(before.transform, b_db.shape)
            persist = persistence_note([before.datetime, after.datetime])
            candidates: List[AgentCandidate] = []
            for comp in comps:
                m = self._mask(comp, clearing_like, before.transform)
                delta = mean_in(ctx.change.diff_db, m) or 0.0
                ratio = float(np.median(texture_ratio[m])) if m.any() else 1.0
                conf = min(
                    confidence_score(magnitude_db=abs(delta), area_km2_=comp["area_km2"],
                                     quality=ctx.quality.get("quality_score", 0.0),
                                     persistent=persist.get("persistent", False)),
                    self.config["confidence_cap"],
                )
                candidates.append(AgentCandidate(
                    title=f"Forest-disturbance candidate ({comp['area_km2']:.2f} km²)",
                    geometry=comp["geometry"], area_km2=comp["area_km2"], confidence=conf,
                    severity=severity_from(comp["area_km2"], abs(delta)),
                    measurements={
                        "mean_change_db": round(delta, 3),
                        "texture_ratio": round(float(ratio), 3),
                        "pixels": comp["pixels"],
                        "change_threshold_db": round(thr, 2),
                        "area_hectares": round(comp["area_km2"] * 100, 2),
                    },
                    supporting=[
                        f"Backscatter changed by {delta:+.2f} dB between {before.datetime} and "
                        f"{after.datetime} (threshold ±{thr:.1f} dB).",
                        f"Local texture standard deviation fell to {ratio:.2f}× of the earlier "
                        "value inside the patch — consistent with canopy removal homogenising "
                        "the surface.",
                        f"Mapped area {comp['area_km2']:.2f} km².",
                    ],
                    conflicting=[
                        "No forest land-cover mask is configured, so this patch could equally "
                        "be cropland, bare soil works or water change.",
                    ],
                    uncertainty=(
                        "The candidate is a radar-texture anomaly only. Confidence is capped at "
                        "0.55 while no forest mask exists and is a ranking heuristic, not a "
                        "probability. Optical or field confirmation is required."
                    ),
                    explanation=(
                        f"Radar backscatter in this patch changed by {delta:+.2f} dB and its "
                        "texture homogenised between the two acquisitions, which is the "
                        "signature expected after canopy removal. Because this deployment has "
                        "no forest land-cover layer, the patch could not be restricted to "
                        "forested land and is reported as a disturbance candidate requiring "
                        "verification (e.g. Global Forest Change or optical imagery)."
                    ),
                    first_observed=after.datetime,
                    tags=["disturbance", "texture_homogenisation"],
                ))
            return self._result(
                status="succeeded", candidates=candidates, logs=logs,
                metrics={"candidates": len(candidates), "clearing_like_px": int(clearing_like.sum()),
                         "strong_change_px": int(strong.sum())},
                reason_code="MULTI_DATE_OVERLAP", reason="Change + texture test produced regions.",
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
