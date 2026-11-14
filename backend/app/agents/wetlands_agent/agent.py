"""AGENT 02 — Wetland & Water Intelligence.

Monitors expansion/contraction of surface-water and wetland areas from
multi-date SAR water segmentation (persistent, gained and lost water).
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from app.agents._common import (
    confidence_score, frame_region, mean_in, persistence_note, regions, severity_from,
)
from app.agents.base import AgentCandidate, AgentContext, AgentResult, BaseAgent
from app.change_detection.segmentation import inundation_masks, segment_water


class WetlandsAgent(BaseAgent):
    id = "wetlands"
    name = "Wetland & Water Intelligence"
    ordinal = 2
    category = "WETLAND_WATER"
    purpose = (
        "Monitor wetland expansion/contraction, lake and reservoir extent change, and "
        "persistent surface-water boundary movement across observations."
    )
    status = "operational"
    status_reason = (
        "Runs on geocoded SAR backscatter with two-date water segmentation. Wetland *type* "
        "detection (Ramsar mapping) needs external boundary datasets that are registered but "
        "not downloaded in this deployment."
    )
    baseline_method = "Multi-date Otsu water segmentation (gained / persistent / lost water)"
    capabilities = [
        "Wetland/surface-water expansion",
        "Wetland/surface-water contraction",
        "Lake & reservoir extent comparison",
        "Persistent water boundary change",
        "Water-area statistics (km², %)",
    ]
    supported_inputs = ["S1_RTC", "NISAR_GCOV", "OPERA_DSWX-S1", "S1_GRD_GEOCODED"]
    datasets = [
        {"id": "jrc_global_surface_water", "name": "JRC Global Surface Water (occurrence)",
         "status": "interface_only", "note": "Fetch requires Earthdata/GEE credentials."},
        {"id": "ramsar", "name": "Ramsar wetland boundaries", "status": "not_configured",
         "note": "No Ramsar site layer bundled; wetland typing therefore unavailable."},
        {"id": "opera_dswx_s1", "name": "OPERA DSWx-S1", "status": "registered",
         "note": "Discovered via CMR when a scene covers the region."},
        {"id": "esa_worldcover", "name": "ESA WorldCover", "status": "interface_only",
         "note": "Registration required for download; interface registered."},
        {"id": "uavsar_wetlands", "name": "UAVSAR ABoVE wetland polarimetric products (Peace-Athabasca)",
         "status": "interface_only",
         "note": "NASA/JPL airborne L-band polarimetry for wetland typing, discovered via CMR "
                 "(UAVSAR_Wetland_Peace-Athabasca_2442); full polarimetric decomposition requires "
                 "the open airborne archive download, registered here as an interface."},
    ]
    evaluation = [
        {"metric": "precision", "value": None, "note": "Not measured — no labelled water-change set."},
        {"metric": "iou", "value": None, "note": "Not measured — no labelled water-change set."},
        {"metric": "recall", "value": None, "note": "Not measured."},
    ]
    model_version = "otsu-water-baseline-1.0"
    config = {"hard_ceiling_db": -9.0, "hard_floor_db": -34.0, "min_component_px": 30,
              "min_candidate_area_km2": 0.05, "min_relative_change": 0.05}
    output_schema = {
        "water_change": "boolean mask of gained or lost surface water",
        "change_type": "expansion | contraction",
        "area_km2": "geodesic area of the changed water region",
        "persistence": "whether water is present on both dates elsewhere in region",
        "evidence": "thresholds, dB statistics, dates",
        "uncertainty": "seasonality, irrigation, tides, ice/snow cover",
    }
    known_limitations = [
        "Does not distinguish wetlands from lakes/reservoirs/ponds without a land-cover layer.",
        "Two dates cannot separate a seasonal cycle from a trend.",
        "Radar cannot see through dense emergent vegetation to the water surface beneath.",
        "Frozen/snow-covered water surfaces are not classified as open water.",
    ]

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.time()
        logs: List[str] = []
        try:
            region = frame_region(ctx)
            before, after = ctx.before, ctx.after
            if before is None or after is None:
                return self._result(status="skipped", reason_code="SINGLE_DATE_ONLY",
                                    reason="Requires two observations.", logs=logs,
                                    duration_ms=int((time.time() - t0) * 1000))
            valid = ctx.valid if ctx.valid is not None else (before.valid & after.valid)
            b_db, a_db = before.db(before.primary_pol), after.db(after.primary_pol)
            kw = {k: self.config[k] for k in ("hard_ceiling_db", "hard_floor_db", "min_component_px")
                  if k in self.config}
            w_b = ctx.water_before or segment_water(b_db, valid, **kw)
            w_a = ctx.water_after or segment_water(a_db, valid, **kw)
            logs.extend(w_b.notes)
            logs.extend(w_a.notes)
            if not (w_b.used and w_a.used):
                return self._result(
                    status="no_candidates", reason_code="WATER_SEGMENTATION_UNAVAILABLE",
                    reason="A distinct open-water class could not be fitted on both dates, so "
                           "water-body boundary change cannot be measured here.",
                    logs=logs, duration_ms=int((time.time() - t0) * 1000))

            masks = inundation_masks(w_b, w_a)
            gained = masks["new_water"] & valid
            lost = masks["receded_water"] & valid
            persistent = masks["persistent_water"] & valid
            px_km2 = 0.0
            from app.core.geo import area_km2 as _akm2
            from app.preprocessing.raster import pixel_area_km2
            region_km2 = _akm2(region)
            px_km2 = pixel_area_km2(before.transform, b_db.shape)

            water_before_km2 = float(w_b.mask[valid].sum()) * px_km2
            water_after_km2 = float(w_a.mask[valid].sum()) * px_km2
            rel_change = ((water_after_km2 - water_before_km2) / water_before_km2
                          if water_before_km2 > 0 else None)
            logs.append(f"water {water_before_km2:.2f} → {water_after_km2:.2f} km² "
                        f"(rel {rel_change if rel_change is None else round(rel_change, 3)})")

            if rel_change is not None and abs(rel_change) < self.config["min_relative_change"] \
                    and not (gained.any() and lost.any()):
                return self._result(
                    status="no_candidates", reason_code="NO_SIGNIFICANT_WATER_CHANGE",
                    reason=f"Total water extent changed by only {rel_change:+.1%} between "
                           "dates (below the 5% reporting threshold) and no localised "
                           "gain/loss regions cleared the minimum mapping area.",
                    logs=logs, duration_ms=int((time.time() - t0) * 1000),
                    metrics={"water_before_km2": round(water_before_km2, 3),
                             "water_after_km2": round(water_after_km2, 3),
                             "relative_change": round(rel_change, 4)},
                )

            diff = a_db - b_db
            candidates: List[AgentCandidate] = []
            for kind, mask, label in (("expansion", gained, "Surface-water expansion"),
                                      ("contraction", lost, "Surface-water contraction")):
                if not mask.any():
                    continue
                comps = regions(mask, before.transform, region=region,
                                min_area_km2=self.config["min_candidate_area_km2"], max_components=4)
                for comp in comps:
                    geom_mask = self._geom_mask(comp, mask, before.transform)
                    delta = mean_in(diff, geom_mask) or 0.0
                    persist = persistence_note([before.datetime, after.datetime])
                    adj = bool(persistent.any()) if kind == "expansion" else False
                    supporting = [
                        f"Water extent {kind} of {comp['area_km2']:.2f} km² between "
                        f"{before.datetime} and {after.datetime}.",
                        f"Thresholds: before {w_b.threshold_db:.1f} dB, after {w_a.threshold_db:.1f} dB "
                        f"(Otsu, scene-specific).",
                        f"Backscatter change inside region: {delta:+.2f} dB mean.",
                    ]
                    conflicting: List[str] = []
                    if rel_change is not None and abs(rel_change) < 0.05:
                        conflicting.append(
                            "Region-wide water extent is nearly unchanged — this is a localised "
                            "boundary shift rather than a basin-scale change."
                        )
                    if ctx.quality.get("median_shift_db", 0) and abs(ctx.quality["median_shift_db"]) > 1.5:
                        conflicting.append(
                            f"Global radiometric offset {ctx.quality['median_shift_db']:+.2f} dB removed first."
                        )
                    conf = confidence_score(
                        magnitude_db=abs(delta) if kind == "expansion" else abs(delta),
                        area_km2_=comp["area_km2"],
                        quality=ctx.quality.get("quality_score", 0.0),
                        persistent=persist.get("persistent", False),
                        corroborating=1 if adj else 0,
                    )
                    severity = severity_from(comp["area_km2"], abs(delta),
                                             "low" if kind == "contraction" else None)
                    candidates.append(AgentCandidate(
                        title=f"{label} ({comp['area_km2']:.2f} km²)",
                        geometry=comp["geometry"], area_km2=comp["area_km2"],
                        confidence=conf, severity=severity,
                        measurements={
                            "change_type": kind,
                            "area_km2": round(comp["area_km2"], 4),
                            "mean_backscatter_change_db": round(delta, 3),
                            "region_water_before_km2": round(water_before_km2, 4),
                            "region_water_after_km2": round(water_after_km2, 4),
                            "relative_change": round(rel_change, 4) if rel_change is not None else None,
                            "threshold_before_db": round(w_b.threshold_db, 2),
                            "threshold_after_db": round(w_a.threshold_db, 2),
                            "persistent_water_present": bool(persistent.any()),
                        },
                        supporting=supporting, conflicting=conflicting,
                        uncertainty=(
                            "Two observations cannot distinguish seasonal filling/draining from "
                            "a persistent trend; wind, ice cover and emergent vegetation change "
                            "the radar response of shallow water. Score is a heuristic, not a "
                            "probability."
                        ),
                        explanation=(
                            f"Water segmentation on {before.datetime} and {after.datetime} shows "
                            f"a {kind} of {comp['area_km2']:.2f} km² in this area; total mapped "
                            f"water moved from {water_before_km2:.2f} to {water_after_km2:.2f} km² "
                            f"({(rel_change or 0):+.1%}). Compare against a longer time series or "
                            "the JRC occurrence layer to decide whether this is seasonal."
                        ),
                        first_observed=after.datetime if kind == "expansion" else before.datetime,
                        tags=["surface_water", kind],
                    ))

            if not candidates:
                return self._result(status="no_candidates", reason_code="BELOW_MIN_AREA",
                                    reason="Water change regions were all smaller than the "
                                           f"{self.config['min_candidate_area_km2']} km² minimum mapping area.",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000))
            return self._result(
                status="succeeded", candidates=candidates, logs=logs,
                metrics={"water_before_km2": round(water_before_km2, 4),
                         "water_after_km2": round(water_after_km2, 4),
                         "relative_change": round(rel_change, 4) if rel_change is not None else None,
                         "candidates": len(candidates)},
                reason_code="MULTI_DATE_OVERLAP", reason="Two-date water segmentation succeeded.",
                duration_ms=int((time.time() - t0) * 1000))
        except Exception as exc:
            return self._fail(exc, logs, t0)

    @staticmethod
    def _geom_mask(comp, mask, transform):
        import numpy as np
        from rasterio import features as rfeatures
        from shapely.geometry import mapping
        try:
            g = rfeatures.geometry_mask([mapping(comp["geometry"])], out_shape=mask.shape,
                                        transform=transform, invert=True, all_touched=True)
            return g & mask
        except Exception:
            return mask
