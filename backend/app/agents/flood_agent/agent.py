"""AGENT 01 — Flood & Inundation Intelligence.

Baseline: Otsu-constrained water segmentation on calibrated SAR backscatter,
differenced between two observations. Newly-inundated pixels are those classed
as water after the event but not before, corroborated by the magnitude of the
backscatter decrease (specular reflection away from the sensor).
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import numpy as np
from scipy import ndimage

from app.agents._common import (
    confidence_score, days_between, frame_region, mean_in, pct_in,
    persistence_note, regions, severity_from,
)
from app.agents.base import AgentCandidate, AgentContext, AgentResult, BaseAgent
from app.change_detection.segmentation import inundation_masks, segment_water


class FloodAgent(BaseAgent):
    id = "flood"
    name = "Flood & Inundation Intelligence"
    ordinal = 1
    category = "FLOOD_INUNDATION"
    purpose = (
        "Detect potential flooding and inundation: flood extent, before/after expansion of "
        "water, and inundated-surface candidates from multi-temporal SAR backscatter."
    )
    status = "operational"
    status_reason = (
        "Baseline pipeline runs end-to-end on geocoded SAR backscatter (Otsu water "
        "segmentation + temporal differencing). No labelled flood dataset is configured in "
        "this deployment, so precision/recall remain unmeasured rather than estimated."
    )
    baseline_method = "Otsu dB water segmentation + before/after inundation differencing"
    capabilities = [
        "Flood extent segmentation (open water)",
        "Before/after floodwater expansion",
        "Water-extent growth rate (km², %)",
        "Adjacency to persistent water (overflow indicator)",
        "Flooded-surface candidates with dB evidence",
    ]
    supported_inputs = ["S1_RTC", "NISAR_GCOV", "NISAR_GSLC", "S1_GRD_GEOCODED"]
    datasets = [
        {"id": "sen1floods11", "name": "Sen1Floods11", "status": "interface_only",
         "note": "Registration required; integration interface registered, not downloaded here."},
        {"id": "global_flood_database", "name": "Global Flood Database (MODIS)",
         "status": "interface_only", "note": "Optical flood composites; interface registered."},
        {"id": "opera_dswx_s1", "name": "OPERA DSWx-S1 dynamic surface water",
         "status": "registered", "note": "Discovered through CMR when a scene covers the region."},
        {"id": "jrc_global_surface_water", "name": "JRC Global Surface Water",
         "status": "interface_only", "note": "Requires Earthdata/GEE access to fetch; interface registered."},
    ]
    evaluation = [
        {"metric": "precision", "value": None, "note": "Not measured — no labelled test tiles configured."},
        {"metric": "recall", "value": None, "note": "Not measured — no labelled test tiles configured."},
        {"metric": "iou", "value": None, "note": "Not measured — no labelled test tiles configured."},
        {"metric": "false_positive_rate", "value": None, "note": "Not measured."},
    ]
    model_version = "otsu-water-baseline-1.0"
    config = {
        "hard_ceiling_db": -9.0, "hard_floor_db": -34.0, "min_component_px": 30,
        "min_candidate_area_km2": 0.05, "flood_delta_db": 1.5,
    }
    output_schema = {
        "flood_extent": "boolean raster mask of candidate inundation (analysis grid)",
        "changed_area_km2": "geodesic area of the newly-water regions",
        "observation_dates": "before/after acquisition timestamps (ISO8601)",
        "supporting_evidence": "per-region dB statistics and class thresholds",
        "uncertainty": "speckle, soil moisture, wind-roughened water, layover/shadow",
        "verification_status": "candidate_detected / requires_verification",
    }
    known_limitations = [
        "Open water only: flooded areas under dense canopy or within urban corridors can be "
        "radar-dark or bright and are missed or mislabelled.",
        "No river-gauge or rainfall context is attached in this deployment.",
        "Single-polarisation thresholds are scene-dependent; without a labelled set the "
        "false-alarm rate is unknown.",
        "Wind-roughened water can be as bright as land and is then missed.",
    ]

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.time()
        logs: List[str] = []
        try:
            region = frame_region(ctx)
            before, after = ctx.before, ctx.after
            if before is None or after is None:
                return self._result(status="skipped", reason_code="SINGLE_DATE_ONLY",
                                    reason="No before/after pair available.",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000))

            from app.core.geo import area_km2 as _area_km2
            from app.preprocessing.raster import pixel_area_km2 as _px_km2
            self._region_km2 = _area_km2(region)
            self._last_px_km2 = (_px_km2(before.transform, before.valid.shape)
                                 if before.valid is not None else 0.0)

            valid = ctx.valid if ctx.valid is not None else (before.valid & after.valid)
            b_db = before.db(before.primary_pol)
            a_db = after.db(after.primary_pol)
            logs.append(f"Grid {b_db.shape}, co-valid pixels {int(valid.sum())}")

            w_after = ctx.water_after or segment_water(a_db, valid, **{
                k: self.config[k] for k in ("hard_ceiling_db", "hard_floor_db", "min_component_px")
                if k in self.config})
            w_before = ctx.water_before or segment_water(b_db, valid, **{
                k: self.config[k] for k in ("hard_ceiling_db", "hard_floor_db", "min_component_px")
                if k in self.config})
            logs.extend([f"after: {n}" for n in w_after.notes])
            logs.extend([f"before: {n}" for n in w_before.notes])

            if not w_after.used and not w_before.used:
                return self._result(
                    status="no_candidates", reason_code="NO_DISTINCT_WATER",
                    reason="No distinct open-water population was found in either observation; "
                           "water segmentation cannot be asserted for this region.",
                    logs=logs, duration_ms=int((time.time() - t0) * 1000), metrics={})

            masks = inundation_masks(w_before, w_after)
            new_water = masks["new_water"] & valid
            persistent = masks["persistent_water"] & valid
            receded = masks["receded_water"] & valid
            logs.append(f"new={int(new_water.sum())} persistent={int(persistent.sum())} "
                        f"receded={int(receded.sum())} px")

            # adjacency to persistent water → overflow indicator
            if persistent.any():
                near = ndimage.binary_dilation(persistent, ndimage.generate_binary_structure(2, 2),
                                               iterations=6)
            else:
                near = np.zeros_like(persistent)

            if not new_water.any():
                stats = self._extent_stats(w_before, w_after, valid)
                return self._result(
                    status="no_candidates", reason_code="NO_NEW_WATER",
                    reason=("Water extent did not expand between these observations"
                            + (f" (it contracted by {stats['delta_km2']:.2f} km²)."
                               if stats.get("delta_km2", 0) < 0 else ".")),
                    logs=logs, duration_ms=int((time.time() - t0) * 1000), metrics=stats,
                )

            comps = regions(new_water, ctx.before.transform, region=region,
                            min_area_km2=self.config["min_candidate_area_km2"], max_components=6)
            if not comps:
                return self._result(status="no_candidates", reason_code="BELOW_MIN_AREA",
                                    reason="Newly-water regions are smaller than the minimum "
                                           f"mapping area ({self.config['min_candidate_area_km2']} km²).",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000))

            diff = ctx.change.diff_db if ctx.change is not None else (a_db - b_db)
            dates = [o.datetime for o in (after, before) if o.datetime]
            persist = persistence_note([after.datetime, before.datetime] if before.datetime else dates)
            extent = self._extent_stats(w_before, w_after, valid)

            candidates: List[AgentCandidate] = []
            for comp in comps:
                m = comp["pixels"] > 0
                geom = comp["geometry"]
                mask_for_geom = self._mask_for(comp, new_water, ctx.before.transform)
                delta = mean_in(diff, mask_for_geom) or 0.0
                p95 = pct_in(diff, mask_for_geom, 95) or 0.0
                overlaps_persistent = bool(np.logical_and(mask_for_geom, near).any())
                supporting = [
                    f"Backscatter inside the candidate changed by {delta:+.2f} dB "
                    f"(95th percentile {p95:+.2f} dB) between "
                    f"{before.datetime} and {after.datetime}.",
                    f"Pixel class moved to open water using a {w_after.threshold_db:.1f} dB "
                    "threshold fitted by Otsu on this scene."
                    if w_after.used else "Post-event water segmentation unavailable for this scene.",
                    f"Newly-water area {comp['area_km2']:.2f} km² "
                    f"({comp['pixels']} pixels at the analysis grid resolution).",
                ]
                if overlaps_persistent:
                    supporting.append(
                        "Region adjoins persistent surface water — consistent with a "
                        "river/lake overflow rather than isolated ponding."
                    )
                conflicting: List[str] = []
                if abs(ctx.quality.get("median_shift_db", 0.0)) > 1.5:
                    conflicting.append(
                        f"Scene-wide radiometric offset of {ctx.quality['median_shift_db']:+.2f} dB "
                        "was present and removed; small absolute changes are less reliable."
                    )
                if ctx.quality.get("orbit_direction") == "geometry_mismatch":
                    conflicting.append("Different acquisition geometry between dates.")
                severity = severity_from(comp["area_km2"], abs(delta))
                conf = confidence_score(
                    magnitude_db=abs(delta), area_km2_=comp["area_km2"],
                    quality=ctx.quality.get("quality_score", 0.0),
                    persistent=persist.get("persistent", False),
                    corroborating=1 if overlaps_persistent else 0,
                )
                candidates.append(AgentCandidate(
                    title=f"Potential surface inundation ({comp['area_km2']:.2f} km²)",
                    geometry=geom, area_km2=comp["area_km2"], confidence=conf, severity=severity,
                    measurements={
                        "new_water_area_km2": round(comp["area_km2"], 4),
                        "mean_backscatter_change_db": round(delta, 3),
                        "p95_backscatter_change_db": round(p95, 3),
                        "water_threshold_after_db": round(w_after.threshold_db, 2) if w_after.used else None,
                        "water_threshold_before_db": round(w_before.threshold_db, 2) if w_before.used else None,
                        "pixels": comp["pixels"],
                        "adjacent_to_persistent_water": overlaps_persistent,
                        "region_water_before_km2": extent.get("before_km2"),
                        "region_water_after_km2": extent.get("after_km2"),
                        "region_water_delta_km2": extent.get("delta_km2"),
                    },
                    supporting=supporting, conflicting=conflicting,
                    uncertainty=(
                        "Detection confidence reflects signal magnitude, mapped area, data "
                        "quality and date separation; it is a heuristic ranking score, not a "
                        "probability of flooding. Speckle, soil-moisture brightening, wind and "
                        "radar shadow can all imitate or mask inundation."
                    ),
                    explanation=(
                        f"Between {before.datetime} and {after.datetime} this region changed "
                        f"from a non-water to an open-water radar signature (mean "
                        f"{delta:+.2f} dB backscatter change at a "
                        f"{w_after.threshold_db:.1f} dB water threshold), mapping "
                        f"{comp['area_km2']:.2f} km² of candidate inundation. "
                        + ("It sits adjacent to persistent water, which supports an overflow "
                           "interpretation. " if overlaps_persistent else "")
                        + "Field verification or an independent water product is required "
                          "before this is treated as confirmed flooding."
                    ),
                    first_observed=after.datetime,
                    tags=["open_water", "inundation"] + (["overflow_adjacent"] if overlaps_persistent else []),
                ))

            metrics = {
                **extent,
                "new_water_fraction": round(float(new_water.mean()), 5),
                "candidates": len(candidates),
                "threshold_after_db": round(w_after.threshold_db, 2) if w_after.used else None,
            }
            logs.append(f"published {len(candidates)} candidate region(s)")
            return self._result(status="succeeded", candidates=candidates, logs=logs,
                                metrics=metrics, reason_code="MULTI_DATE_OVERLAP",
                                reason="Before/after water segmentation produced new-water regions.",
                                duration_ms=int((time.time() - t0) * 1000))
        except Exception as exc:
            return self._fail(exc, logs, t0)

    # -------------------------------------------------------------- helpers
    def _extent_stats(self, w_before, w_after, valid) -> Dict[str, Any]:
        b = float(w_before.mask[valid].mean()) if valid is not None and valid.any() else 0.0
        a = float(w_after.mask[valid].mean()) if valid is not None and valid.any() else 0.0
        return {
            "before_fraction": round(b, 5), "after_fraction": round(a, 5),
            "delta_fraction": round(a - b, 5),
            "before_km2": round(b * self._region_km2, 4) if self._region_km2 else None,
            "after_km2": round(a * self._region_km2, 4) if self._region_km2 else None,
            "delta_km2": round((a - b) * self._region_km2, 4) if self._region_km2 else None,
        }

    def _mask_for(self, comp: Dict[str, Any], mask: np.ndarray, transform) -> np.ndarray:
        """Pixel mask for one vectorised component (by label overlap)."""
        from rasterio import features as rfeatures
        from shapely.geometry import mapping
        try:
            geom_mask = rfeatures.geometry_mask(
                [mapping(comp["geometry"])], out_shape=mask.shape, transform=transform,
                invert=True, all_touched=True,
            )
            return geom_mask & mask
        except Exception:
            return mask

    # region area + pixel area are computed at the start of `run`
    _region_km2: float = 0.0
    _last_px_km2: float = 0.0
