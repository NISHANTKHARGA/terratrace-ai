"""AGENT 11 — Coastal & Shoreline Intelligence.

Baseline: two-date water segmentation restricted to the water–land interface,
measuring shoreline displacement with a distance transform. Tide/water level is
NOT known here, so every shoreline shift carries an explicit tidal uncertainty.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List

import numpy as np
from scipy import ndimage

from app.agents._common import confidence_score, frame_region, regions, severity_from
from app.agents.base import AgentCandidate, AgentContext, AgentResult, BaseAgent
from app.change_detection.segmentation import inundation_masks, segment_water


class CoastalAgent(BaseAgent):
    id = "coastal"
    name = "Coastal & Shoreline Intelligence"
    ordinal = 11
    category = "COASTAL_SHORELINE"
    purpose = (
        "Monitor coastlines: shoreline movement, coastal erosion indicators, delta change, "
        "coastal inundation and coastal land change."
    )
    status = "operational"
    status_reason = (
        "Two-date water segmentation with interface extraction runs on real imagery. Tidal "
        "state and water level are not available in this deployment, so shoreline shifts are "
        "reported with an explicit tidal uncertainty and never as a final erosion rate."
    )
    baseline_method = "Water–land interface extraction + distance-transform shoreline shift"
    capabilities = [
        "Shoreline position extraction (both dates)",
        "Erosion vs accretion mapping at the interface",
        "Shoreline displacement statistics (metres, mean/median)",
        "Coastal inundation mapping where water advances inland",
    ]
    supported_inputs = ["S1_RTC", "NISAR_GCOV", "OPERA_DSWX-S1", "S1_GRD_GEOCODED"]
    datasets = [
        {"id": "jrc_global_surface_water", "name": "JRC Global Surface Water",
         "status": "interface_only", "note": "Fetch requires Earthdata/GEE credentials."},
        {"id": "global_shoreline", "name": "Global shoreline datasets (e.g. GSHHG/OpenStreetMap)",
         "status": "interface_only", "note": "No shoreline reference bundled; interface registered."},
        {"id": "tide_gauge", "name": "Tide/water-level context", "status": "not_configured",
         "note": "No tide model configured — shoreline displacement carries tidal uncertainty."},
    ]
    evaluation = [
        {"metric": "shoreline_position_error_m", "value": None,
         "note": "Not measured — no reference shoreline configured."},
        {"metric": "precision", "value": None, "note": "Not measured."},
        {"metric": "recall", "value": None, "note": "Not measured."},
    ]
    model_version = "interface-shift-baseline-1.0"
    config = {"min_interface_px": 300, "min_area_km2": 0.05,
              "interface_band_px": 8, "confidence_cap": 0.6}
    output_schema = {
        "erosion_mask": "pixels where land was replaced by water",
        "accretion_mask": "pixels where water was replaced by land",
        "shoreline_shift_m": "median distance-transform displacement at the interface",
        "displacement_sign": "negative = retreat, positive = advance",
        "tidal_uncertainty": "unknown tide state — always reported",
    }
    known_limitations = [
        "Tide and water level at each acquisition are unknown: apparent shoreline movement "
        "may be tidal, not geomorphic.",
        "Turbid/shallow water and wave run-up blur the radar shoreline.",
        "Two dates cannot establish an erosion *rate*.",
        "River-dominated coasts change with discharge as well as with sea level.",
    ]

    def _select_specific(self, ctx: AgentContext) -> tuple:
        if not ctx.has_pair:
            return False, "SINGLE_DATE_ONLY", "Requires two observations."
        before = ctx.before
        valid = ctx.valid if ctx.valid is not None else before.valid
        b_db = before.db(before.primary_pol)
        a_db = after_db = None
        if ctx.after is not None:
            a_db = ctx.after.db(ctx.after.primary_pol)
        kw = {k: self.config[k] for k in ("hard_ceiling_db", "hard_floor_db", "min_component_px")
              if k in self.config}
        w_b = ctx.water_before or segment_water(b_db, valid, **kw)
        w_a = ctx.water_after or (segment_water(a_db, valid, **kw) if a_db is not None else None)
        if not (w_b.used and w_a and w_a.used):
            return False, "NO_WATER_LAND_BOUNDARY", (
                "A water/land interface could not be fitted on both dates (no distinct water "
                "class), so shoreline change cannot be measured."
            )
        water_frac_b = float(w_b.mask[valid].mean())
        water_frac_a = float(w_a.mask[valid].mean())
        interface = int((ndimage.binary_dilation(w_b.mask, iterations=1) ^
                         ndimage.binary_dilation(w_a.mask, iterations=1)).sum())
        if max(water_frac_b, water_frac_a) > 0.92:
            return False, "NO_WATER_LAND_BOUNDARY", (
                f"The region is {max(water_frac_b, water_frac_a):.0%} water — there is no "
                "coastal interface to track."
            )
        if min(water_frac_b, water_frac_a) < 0.005:
            return False, "NO_WATER_LAND_BOUNDARY", (
                f"Only {min(water_frac_b, water_frac_a):.1%} water is present — no shoreline in "
                "this region."
            )
        return True, "SUFFICIENT_VALID_PIXELS", (
            f"Water covers {water_frac_b:.0%} (earlier) / {water_frac_a:.0%} (later) of the "
            "region with a measurable land–water interface."
        )

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.time()
        logs: List[str] = []
        try:
            ok, code, reason = self._select_specific(ctx)
            if not ok:
                return self._result(status="skipped", reason_code=code, reason=reason, logs=logs,
                                    duration_ms=int((time.time() - t0) * 1000))
            region = frame_region(ctx)
            before, after = ctx.before, ctx.after
            valid = ctx.valid if ctx.valid is not None else (before.valid & after.valid)
            b_db, a_db = before.db(before.primary_pol), after.db(after.primary_pol)
            kw = {k: self.config[k] for k in ("hard_ceiling_db", "hard_floor_db", "min_component_px")
                  if k in self.config}
            w_b = ctx.water_before or segment_water(b_db, valid, **kw)
            w_a = ctx.water_after or segment_water(a_db, valid, **kw)
            masks = inundation_masks(w_b, w_a)
            gained = masks["new_water"] & valid      # water advanced over land → erosion/retreat
            lost = masks["receded_water"] & valid    # land gained → accretion
            logs.append(f"interface: water advanced px={int(gained.sum())}, "
                        f"retreated px={int(lost.sum())}")

            # restrict to a band around the earlier shoreline (interface zone)
            shore_b = ndimage.binary_dilation(w_b.mask, iterations=3) & \
                      ndimage.binary_dilation(~w_b.mask, iterations=3)
            band = ndimage.binary_dilation(shore_b, iterations=self.config["interface_band_px"]) & valid
            gained_i, lost_i = gained & band, lost & band

            if gained_i.sum() + lost_i.sum() < 20:
                return self._result(
                    status="no_candidates", reason_code="NO_SHORELINE_MOVEMENT",
                    reason="No measurable water/land conversion occurred within the shoreline "
                           "interface band between these dates.",
                    logs=logs, duration_ms=int((time.time() - t0) * 1000),
                )

            # displacement statistics via distance transform
            px_m = _px_m(before.transform, (ctx.bbox[1] + ctx.bbox[3]) / 2)
            shift_m = None
            if lost_i.any():  # retreat: distance from lost pixels to previous water
                dist = ndimage.distance_transform_edt(~w_b.mask)
                shift_m = -float(np.median(dist[lost_i]) * px_m)
            elif gained_i.any():
                dist = ndimage.distance_transform_edt(~w_a.mask)
                shift_m = float(np.median(dist[gained_i]) * px_m)

            from app.agents._common import persistence_note
            persist = persistence_note([before.datetime, after.datetime])
            candidates: List[AgentCandidate] = []
            for kind, m in (("erosion", gained_i), ("accretion", lost_i)):
                if not m.any():
                    continue
                comps = regions(m, before.transform, region=region,
                                min_area_km2=self.config["min_area_km2"], max_components=3)
                for comp in comps:
                    sub = self._mask(comp, m, before.transform)
                    local_shift = None
                    if sub.any():
                        d = ndimage.distance_transform_edt(~(w_a.mask if kind == "erosion" else w_b.mask))
                        local_shift = float(np.median(d[sub]) * px_m) * (1 if kind == "accretion" else -1)
                    conf = min(
                        confidence_score(
                            magnitude_db=min(12, abs(local_shift or 0) / 5.0),
                            area_km2_=comp["area_km2"],
                            quality=ctx.quality.get("quality_score", 0.0),
                            persistent=persist.get("persistent", False),
                            penalty=0.15,  # unknown tide state
                        ),
                        self.config["confidence_cap"],
                    )
                    label = "Shoreline retreat (water advanced)" if kind == "erosion" else \
                            "Shoreline advance (water retreated)"
                    candidates.append(AgentCandidate(
                        title=f"{label} — {comp['area_km2']:.2f} km²",
                        geometry=comp["geometry"], area_km2=comp["area_km2"], confidence=conf,
                        severity=severity_from(comp["area_km2"], abs(local_shift or 0) / 3,
                                               "moderate" if kind == "erosion" else "low"),
                        measurements={
                            "change_type": kind,
                            "area_km2": round(comp["area_km2"], 4),
                            "median_shift_m": round(local_shift, 2) if local_shift is not None else None,
                            "region_median_shift_m": round(shift_m, 2) if shift_m is not None else None,
                            "pixel_size_m": round(px_m, 2),
                            "threshold_before_db": round(w_b.threshold_db, 2),
                            "threshold_after_db": round(w_a.threshold_db, 2),
                            "tide_state": "unknown",
                        },
                        supporting=[
                            f"Water/land conversion of {comp['area_km2']:.2f} km² at the shoreline "
                            f"between {before.datetime} and {after.datetime}.",
                            f"Median interface displacement {local_shift:.1f} m "
                            f"(pixel size {px_m:.1f} m)." if local_shift is not None else "",
                        ],
                        conflicting=[
                            "Tide and water level at both acquisitions are unknown, so part or "
                            "all of this displacement may be tidal rather than geomorphic.",
                        ],
                        uncertainty=(
                            "Two-date segmentation cannot separate tidal stage, wave state and "
                            "wind-driven setup from true shoreline change; no tide model is "
                            "configured. Confidence is a heuristic score, not a probability, and "
                            "no erosion rate should be inferred from a single pair."
                        ),
                        explanation=(
                            f"The shoreline moved {local_shift:+.1f} m "
                            + ("seaward" if (local_shift or 0) < 0 else "landward")
                            + f" at this location between {before.datetime} and {after.datetime}, "
                            f"affecting {comp['area_km2']:.2f} km². Because the tide state during "
                            "each acquisition is unknown, this is reported as a shoreline "
                            "position difference, not as a confirmed erosion/accretion rate."
                        ),
                        first_observed=after.datetime if kind == "erosion" else before.datetime,
                        tags=["shoreline", kind],
                    ))
            if not candidates:
                return self._result(status="no_candidates", reason_code="BELOW_MIN_AREA",
                                    reason="Interface changes below minimum mapping area.",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000))
            return self._result(status="succeeded", candidates=candidates, logs=logs,
                                metrics={"candidates": len(candidates),
                                         "water_advanced_px": int(gained_i.sum()),
                                         "water_retreated_px": int(lost_i.sum()),
                                         "median_shift_m": round(shift_m, 2) if shift_m else None},
                                reason_code="SUFFICIENT_VALID_PIXELS",
                                reason="Shoreline interface change measured.",
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


def _px_m(transform, lat_mid: float) -> float:
    return abs(transform.a) * 111_320.0 * math.cos(math.radians(lat_mid))
