"""AGENT 07 — Landslide & Slope Intelligence.

Baseline: strong, spatially coherent backscatter change on steep terrain
(slope from Copernicus DEM when reachable) with size/morphology screening.
It never predicts an imminent landslide: it reports *observed* slope disturbance.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import numpy as np
from scipy import ndimage

from app.agents._common import confidence_score, frame_region, mean_in, regions, severity_from
from app.agents.base import AgentCandidate, AgentContext, AgentResult, BaseAgent
from app.preprocessing.raster import pixel_area_km2


def slope_degrees(dem: np.ndarray, transform) -> np.ndarray:
    """Slope in degrees from a DEM on a lon/lat grid (pixel size corrected)."""
    import math
    lat_mid = transform.f - abs(transform.e) * dem.shape[0] / 2
    mx = abs(transform.a) * 111_320.0 * math.cos(math.radians(lat_mid))
    my = abs(transform.e) * 110_570.0
    gy, gx = np.gradient(np.where(np.isfinite(dem), dem, np.nan), my, mx)
    gy = np.nan_to_num(gy, nan=0.0)
    gx = np.nan_to_num(gx, nan=0.0)
    return np.degrees(np.arctan(np.hypot(gx, gy)))


class LandslideAgent(BaseAgent):
    id = "landslide"
    name = "Landslide & Slope Intelligence"
    ordinal = 7
    category = "LANDSLIDE_SLOPE"
    purpose = (
        "Identify potential landslide-related surface disturbance: scar candidates on steep "
        "slopes, slope disturbance, and displacement only where a valid measurement exists."
    )
    status = "experimental"
    status_reason = (
        "Runs with DEM slope context when Copernicus DEM is reachable; without a landslide "
        "inventory or rainfall context, candidates stay experimental and require verification."
    )
    baseline_method = "Change-patch detection filtered by DEM slope + size/morphology screening"
    capabilities = [
        "Slope-context change detection (Copernicus DEM)",
        "Scar-candidate mapping with size and shape screening",
        "Rainfall-context hook (not configured in this deployment)",
    ]
    supported_inputs = ["S1_RTC", "NISAR_GCOV", "S1_GRD_GEOCODED", "DEM_CONTEXT"]
    datasets = [
        {"id": "nasa_dem", "name": "NASADEM / Copernicus DEM", "status": "available",
         "note": "Copernicus DEM GLO-30 fetched anonymously from AWS open data when reachable."},
        {"id": "global_landslide_catalog", "name": "Global Landslide Catalog",
         "status": "interface_only", "note": "Catalogue lookup interface registered, not queried here."},
        {"id": "global_landslide_distrib", "name": "Global Landslide Distribution (CoStar)",
         "status": "not_configured", "note": "No landslide inventory bundled."},
        {"id": "rainfall_context", "name": "IMERG/GPM rainfall forcing", "status": "not_configured",
         "note": "Rainfall context API not configured; triggers are not evaluated."},
    ]
    evaluation = [
        {"metric": "precision", "value": None, "note": "Not measured — no landslide labels."},
        {"metric": "recall", "value": None, "note": "Not measured."},
        {"metric": "iou", "value": None, "note": "Not measured."},
    ]
    model_version = "slope-change-baseline-1.0"
    config = {"min_slope_deg": 18.0, "min_area_km2": 0.03, "max_area_km2": 25.0,
              "min_delta_db": 3.0, "confidence_cap": 0.6}
    output_schema = {
        "scar_mask": "boolean mask of steep-terrain change",
        "area_km2": "geodesic area of the candidate",
        "slope_deg": "median slope inside candidate",
        "mean_change_db": "backscatter difference inside candidate",
        "verification_status": "requires_verification unless inventory corroboration exists",
    }
    known_limitations = [
        "Slope threshold is a screening heuristic; not all landslides start on >18° slopes "
        "and many steep-slope changes are non-landslide processes.",
        "No rainfall or seismic triggering context is configured.",
        "Radar shadow/layover in steep terrain biases backscatter change there.",
        "This agent observes past surface change — it does not predict imminent landslides.",
    ]

    def _select_specific(self, ctx: AgentContext) -> tuple:
        if not ctx.has_pair:
            return False, "SINGLE_DATE_ONLY", "Requires two observations."
        if ctx.change is None:
            return False, "EARLIER_FAILURE", "Change-detection stage produced no layer."
        return True, "MULTI_DATE_OVERLAP", (
            "Two comparable observations plus a change layer are available; DEM slope context "
            + ("is loaded." if ctx.datasets.dem_array is not None
               else "will be fetched from AWS open DEM data when reachable.")
        )

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.time()
        logs: List[str] = []
        try:
            region = frame_region(ctx)
            before, after = ctx.before, ctx.after
            valid = ctx.valid if ctx.valid is not None else (before.valid & after.valid)
            thr = ctx.change.threshold_db
            strong = (np.abs(ctx.change.diff_db) > max(thr, self.config["min_delta_db"])) & valid
            logs.append(f"strong change px={int(strong.sum())}")

            slope: Optional[np.ndarray] = None
            if ctx.datasets.dem_array is not None and ctx.datasets.dem_transform is not None:
                slope = slope_degrees(ctx.datasets.dem_array, ctx.datasets.dem_transform)
                logs.append(f"DEM slope loaded: median {float(np.nanmedian(slope)):.1f}°")
            else:
                logs.append("DEM unavailable — slope filter skipped (not simulated).")

            if strong.sum() < 12:
                return self._result(status="no_candidates", reason_code="NO_STRONG_CHANGE",
                                    reason="No strong backscatter-change patches to screen.",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000))

            mask = strong.copy()
            if slope is not None:
                mask = strong & (slope >= self.config["min_slope_deg"])
                logs.append(f"steep-slope change px={int(mask.sum())} "
                            f"(≥{self.config['min_slope_deg']}°)")
            if mask.sum() < 12:
                return self._result(
                    status="no_candidates", reason_code="NO_STEEP_TERRAIN_CHANGE",
                    reason=("No strong change remained after the slope filter"
                            + (f" (≥{self.config['min_slope_deg']}°)." if slope is not None else ".")),
                    logs=logs, duration_ms=int((time.time() - t0) * 1000))

            mask = ndimage.binary_opening(mask, ndimage.generate_binary_structure(2, 2))
            comps = regions(mask, before.transform, region=region,
                            min_area_km2=self.config["min_area_km2"], max_components=5)
            comps = [c for c in comps if c["area_km2"] <= self.config["max_area_km2"]]
            if not comps:
                return self._result(status="no_candidates", reason_code="BELOW_MIN_AREA",
                                    reason="Screened patches outside the reportable size range.",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000))
            candidates: List[AgentCandidate] = []
            for comp in comps:
                m = self._mask(comp, mask, before.transform)
                delta = mean_in(ctx.change.diff_db, m) or 0.0
                med_slope = float(np.nanmedian(slope[m])) if slope is not None and m.any() else None
                conf = min(
                    confidence_score(magnitude_db=abs(delta), area_km2_=comp["area_km2"],
                                     quality=ctx.quality.get("quality_score", 0.0), persistent=False,
                                     corroborating=1 if (med_slope or 0) > 30 else 0),
                    self.config["confidence_cap"],
                )
                has_dem = slope is not None
                candidates.append(AgentCandidate(
                    title=f"Slope-disturbance candidate ({comp['area_km2']:.2f} km², "
                          f"{med_slope:.0f}°)" if med_slope else
                          f"Slope-disturbance candidate ({comp['area_km2']:.2f} km²)",
                    geometry=comp["geometry"], area_km2=comp["area_km2"], confidence=conf,
                    severity=severity_from(comp["area_km2"], abs(delta)),
                    measurements={
                        "mean_change_db": round(delta, 3),
                        "median_slope_deg": round(med_slope, 1) if med_slope is not None else None,
                        "slope_filter_applied": has_dem,
                        "slope_threshold_deg": self.config["min_slope_deg"],
                        "pixels": int(m.sum()),
                        "rainfall_context": "not_configured",
                    },
                    supporting=[
                        f"Backscatter changed by {delta:+.2f} dB between {before.datetime} and "
                        f"{after.datetime} inside a {comp['area_km2']:.2f} km² patch.",
                        (f"Median terrain slope {med_slope:.1f}° (Copernicus DEM) exceeds the "
                         f"{self.config['min_slope_deg']}° screening threshold."
                         if med_slope is not None else "No DEM slope context was available."),
                    ],
                    conflicting=[
                        "No landslide inventory or rainfall triggering context was available, so "
                        "the cause of the disturbance is untested.",
                    ] if not has_dem else [
                        "No landslide inventory or rainfall triggering context was available, so "
                        "the cause of the disturbance is untested.",
                    ],
                    uncertainty=(
                        "This is an observed surface-change candidate on steep terrain — not a "
                        "prediction of an imminent landslide. Score is a heuristic ranking value, "
                        "not a probability. Radar shadow/layover in steep terrain can exaggerate "
                        "change."
                    ),
                    explanation=(
                        f"A {comp['area_km2']:.2f} km² patch changed by {delta:+.2f} dB between "
                        f"{before.datetime} and {after.datetime}"
                        + (f" on {med_slope:.1f}° terrain" if med_slope is not None else "")
                        + ". Its size and position are consistent with slope disturbance, but "
                          "neither a landslide inventory nor rainfall/seismic triggering data was "
                          "available, so the process is unconfirmed and the finding requires "
                          "verification."
                    ),
                    first_observed=after.datetime, tags=["slope", "disturbance"],
                ))
            return self._result(
                status="succeeded", candidates=candidates, logs=logs,
                metrics={"candidates": len(candidates), "strong_px": int(strong.sum()),
                         "steep_px": int(mask.sum()), "dem_used": slope is not None},
                reason_code="SUFFICIENT_VALID_PIXELS", reason="Slope screening produced regions.",
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
