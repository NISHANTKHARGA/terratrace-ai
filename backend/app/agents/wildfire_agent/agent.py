"""AGENT 04 — Wildfire & Burned-Land Intelligence.

Critical rule encoded in this module: **a radar change alone cannot confirm
that a wildfire occurred.** Every candidate produced here carries a hard
`requires_verification` status and an explicit statement that an independent
fire observation (NASA FIRMS / MODIS / VIIRS burned area) was not available.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import numpy as np
from scipy import ndimage

from app.agents._common import (
    confidence_score, frame_region, mean_in, regions, severity_from,
)
from app.agents.base import AgentCandidate, AgentContext, AgentResult, BaseAgent
from app.preprocessing.raster import pixel_area_km2


class WildfireAgent(BaseAgent):
    id = "wildfire"
    name = "Wildfire & Burned-Land Intelligence"
    ordinal = 4
    category = "WILDFIRE_BURNED"
    purpose = (
        "Identify potential fire-related landscape changes: burned-area candidates and "
        "post-fire surface disturbance, always cross-checked against fire datasets when "
        "available."
    )
    status = "experimental"
    status_reason = (
        "Radar-change baseline runs, but NASA FIRMS/MODIS/VIIRS fire context requires an API "
        "key that is not configured here, so no candidate can be corroborated and every result "
        "stays at 'requires_verification'."
    )
    baseline_method = "Multi-temporal dB decrease + texture change, fire-context cross-check"
    capabilities = [
        "Burned-area candidate mapping",
        "Post-fire backscatter change statistics",
        "Optional FIRMS/MODIS/VIIRS corroboration (when API key configured)",
    ]
    supported_inputs = ["S1_RTC", "NISAR_GCOV", "S1_GRD_GEOCODED", "OPTICAL_CONTEXT"]
    datasets = [
        {"id": "nasa_firms", "name": "NASA FIRMS active fire", "status": "not_configured",
         "note": "FIRMS MAP_KEY required (https://firms.modaps.eosdis.nasa.gov/api/)."},
        {"id": "modis_burned_area", "name": "MCD64A1 MODIS burned area", "status": "interface_only",
         "note": "CMR discovery implemented; product download needs Earthdata credentials."},
        {"id": "viirs_burned_area", "name": "VIIRS/NPP burned area", "status": "interface_only",
         "note": "Interface registered, not downloaded in this deployment."},
    ]
    evaluation = [
        {"metric": "precision", "value": None, "note": "Not measured — no burned-area labels."},
        {"metric": "recall", "value": None, "note": "Not measured."},
        {"metric": "false_positive_rate", "value": None, "note": "Not measured."},
    ]
    model_version = "radar-burn-baseline-1.0"
    config = {"min_area_km2": 0.08, "min_delta_db": 3.0, "confidence_cap": 0.5}
    output_schema = {
        "burn_candidate_mask": "boolean mask of fire-like radar change",
        "area_km2": "geodesic area of the candidate",
        "mean_change_db": "backscatter difference inside candidate",
        "fire_context": "FIRMS/MODIS status (available or not_configured)",
        "verification_status": "always requires_verification without fire observations",
    }
    known_limitations = [
        "A radar change alone cannot confirm that a wildfire occurred.",
        "No fire-detection context is configured in this deployment.",
        "Harvest, flooding, soil-moisture change and grazing produce similar radar signatures.",
        "C-band SAR saturation over dense forest limits severity estimation.",
    ]

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.time()
        logs: List[str] = []
        try:
            if ctx.change is None or not ctx.has_pair:
                return self._result(status="skipped", reason_code="NO_CHANGE_LAYER",
                                    reason="No change layer available.", logs=logs,
                                    duration_ms=int((time.time() - t0) * 1000))
            region = frame_region(ctx)
            before, after = ctx.before, ctx.after
            valid = ctx.valid if ctx.valid is not None else (before.valid & after.valid)
            thr = ctx.change.threshold_db
            decr = ctx.change.decrease_mask & (np.abs(ctx.change.diff_db) > max(thr, self.config["min_delta_db"]))
            decr &= valid
            logs.append(f"post-fire-like decrease px={int(decr.sum())}")

            fire_context = ctx.datasets.describe()
            has_fire = any(d["id"] == "nasa_firms" and d["status"] == "available" for d in fire_context)
            if ctx.datasets.sentinel2 is not None:
                logs.append("Optical Sentinel-2 context available for corroboration.")

            if decr.sum() < 12:
                return self._result(
                    status="no_candidates", reason_code="NO_BURN_SIGNATURE",
                    reason="No backscatter-decrease patches strong enough to test for burn "
                           "scarring were found.",
                    logs=logs, duration_ms=int((time.time() - t0) * 1000))
            decr = ndimage.binary_opening(decr, ndimage.generate_binary_structure(2, 2))
            comps = regions(decr, before.transform, region=region,
                            min_area_km2=self.config["min_area_km2"], max_components=4)
            if not comps:
                return self._result(status="no_candidates", reason_code="BELOW_MIN_AREA",
                                    reason="Decrease patches below the minimum mapping area.",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000))
            candidates: List[AgentCandidate] = []
            for comp in comps:
                m = self._mask(comp, decr, before.transform)
                delta = mean_in(ctx.change.diff_db, m) or 0.0
                conf = min(
                    confidence_score(magnitude_db=abs(delta), area_km2_=comp["area_km2"],
                                     quality=ctx.quality.get("quality_score", 0.0),
                                     persistent=False, corroborating=1 if has_fire else 0),
                    self.config["confidence_cap"],
                )
                candidates.append(AgentCandidate(
                    title=f"Fire-related change candidate ({comp['area_km2']:.2f} km²)",
                    geometry=comp["geometry"], area_km2=comp["area_km2"], confidence=conf,
                    severity=severity_from(comp["area_km2"], abs(delta)),
                    measurements={
                        "mean_change_db": round(delta, 3),
                        "pixels": comp["pixels"],
                        "change_threshold_db": round(thr, 2),
                        "fire_context_status": "available" if has_fire else "not_configured",
                        "optical_context": ctx.datasets.sentinel2 is not None,
                    },
                    supporting=[
                        f"Backscatter decreased by {delta:+.2f} dB between {before.datetime} "
                        f"and {after.datetime}.",
                        f"Patch area {comp['area_km2']:.2f} km² with a coherent spatial extent.",
                    ],
                    conflicting=[
                        "NASA FIRMS/MODIS/VIIRS fire observations were NOT available for this "
                        "run, so the fire interpretation is untested.",
                        "Flooding, soil wetting and harvest produce the same decrease signature.",
                    ],
                    uncertainty=(
                        "Detection confidence is a heuristic score (0..1), not a probability of "
                        "fire. Without an active-fire or burned-area product this candidate "
                        "cannot be attributed to wildfire."
                    ),
                    explanation=(
                        f"Radar backscatter fell by {delta:+.2f} dB over {comp['area_km2']:.2f} km² "
                        f"between {before.datetime} and {after.datetime}. That is *consistent* "
                        "with post-fire surface change, but a radar change alone cannot confirm "
                        "that a wildfire occurred: no fire-detection dataset was available to "
                        "this run. Verify against NASA FIRMS/VIIRS or optical burn imagery "
                        "before treating this as a burned area."
                    ),
                    first_observed=after.datetime,
                    tags=["burn_candidate", "unverified_fire"],
                ))
            return self._result(
                status="succeeded", candidates=candidates, logs=logs,
                metrics={"candidates": len(candidates), "decrease_px": int(decr.sum()),
                         "fire_context": "available" if has_fire else "not_configured"},
                reason_code="MULTI_DATE_OVERLAP",
                reason="Backscatter decrease patches found; fire context unavailable.",
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
