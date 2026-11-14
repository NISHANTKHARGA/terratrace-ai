"""AGENT 09 — Urban Growth & Infrastructure Intelligence.

Baseline: double-bounce-sensitive backscatter *increase* over an already-bright
(built-up proxy) surface between two dates, with compact-patch screening.
Built-up typing requires GHSL/OSM/building footprints, which are registered but
not bundled.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import numpy as np
from scipy import ndimage

from app.agents._common import confidence_score, frame_region, mean_in, regions, severity_from
from app.agents.base import AgentCandidate, AgentContext, AgentResult, BaseAgent
from app.preprocessing.raster import pixel_area_km2


class UrbanAgent(BaseAgent):
    id = "urban"
    name = "Urban Growth & Infrastructure Intelligence"
    ordinal = 9
    category = "URBAN_INFRASTRUCTURE"
    purpose = (
        "Monitor human-built environments: urban expansion, new construction, road and "
        "infrastructure change, and built-up land conversion."
    )
    status = "experimental"
    status_reason = (
        "Runs on backscatter increase over a built-up proxy; no GHSL/OSM/building-footprint "
        "layer is bundled to confirm that a change is construction rather than another process."
    )
    baseline_method = "Backscatter-increase detection over a bright built-up proxy"
    capabilities = [
        "Built-up expansion candidates (double-bounce increase)",
        "Compact-patch screening for construction-like change",
        "Infrastructure-change candidates with area statistics",
    ]
    supported_inputs = ["S1_RTC", "NISAR_GCOV", "S1_GRD_GEOCODED"]
    datasets = [
        {"id": "ghsl", "name": "GHSL built-up grid", "status": "interface_only",
         "note": "No GHSL layer bundled in this deployment."},
        {"id": "osm", "name": "OpenStreetMap buildings/roads", "status": "not_configured",
         "note": "OSM overlay not configured (public API could be added)."},
        {"id": "esa_worldcover", "name": "ESA WorldCover built-up class", "status": "interface_only",
         "note": "Registration required; interface registered."},
        {"id": "google_buildings", "name": "Google/OpenStreetMap building footprints",
         "status": "not_configured", "note": "No building footprint dataset bundled."},
    ]
    evaluation = [
        {"metric": "precision", "value": None, "note": "Not measured — no built-up labels."},
        {"metric": "recall", "value": None, "note": "Not measured."},
        {"metric": "iou", "value": None, "note": "Not measured."},
    ]
    model_version = "double-bounce-baseline-1.0"
    config = {"min_area_km2": 0.05, "builtup_proxy_db": -9.0, "min_delta_db": 2.5,
              "confidence_cap": 0.5}
    output_schema = {
        "expansion_mask": "boolean mask of construction-like increase",
        "area_km2": "geodesic area",
        "mean_change_db": "backscatter increase inside candidate",
        "builtup_proxy": "brightness criterion used to identify existing built-up land",
        "verification_status": "requires_verification without a built-up dataset",
    }
    known_limitations = [
        "Bright natural surfaces (rock, dry riverbeds) also show strong double-bounce-like "
        "returns and can be misclassified as construction.",
        "No building/road dataset is bundled, so 'construction' is an interpretation only.",
        "Speckle and moisture changes can produce moderate increases.",
        "Seasonal scaffolding/vegetation change is not modelled.",
    ]

    def _select_specific(self, ctx: AgentContext) -> tuple:
        if not ctx.has_pair:
            return False, "SINGLE_DATE_ONLY", "Requires two observations."
        if ctx.change is None:
            return False, "EARLIER_FAILURE", "Change-detection stage produced no layer."
        before = ctx.before
        valid = ctx.valid if ctx.valid is not None else before.valid
        db = before.db(before.primary_pol)
        bright = float((db[valid] > self.config["builtup_proxy_db"]).mean()) if valid.any() else 0.0
        if bright < 0.01:
            return False, "NO_BUILTUP_CONTEXT", (
                f"Only {bright:.2%} of the region is bright enough to act as a built-up proxy — "
                "no existing urban fabric to expand from."
            )
        return True, "SUFFICIENT_VALID_PIXELS", (
            f"Built-up proxy covers {bright:.2%} of the region and a change layer exists."
        )

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.time()
        logs: List[str] = []
        try:
            region = frame_region(ctx)
            before, after = ctx.before, ctx.after
            valid = ctx.valid if ctx.valid is not None else (before.valid & after.valid)
            b_db = before.db(before.primary_pol)
            thr = ctx.change.threshold_db
            proxy = valid & (b_db > self.config["builtup_proxy_db"])
            increase = ctx.change.increase_mask & (ctx.change.diff_db > max(thr, self.config["min_delta_db"]))
            mask = increase & (ndimage.binary_dilation(proxy, iterations=3) | proxy)
            logs.append(f"built-up proxy px={int(proxy.sum())}; candidate increase px={int(mask.sum())}")
            if mask.sum() < 20:
                return self._result(status="no_candidates", reason_code="NO_BUILTUP_CHANGE",
                                    reason="No backscatter-increase patches overlapped the built-up "
                                           "proxy area.",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000))
            mask = ndimage.binary_closing(mask, ndimage.generate_binary_structure(2, 2))
            comps = regions(mask, before.transform, region=region,
                            min_area_km2=self.config["min_area_km2"], max_components=4)
            if not comps:
                return self._result(status="no_candidates", reason_code="BELOW_MIN_AREA",
                                    reason="Increase patches below minimum mapping area.",
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
                    title=f"Built-up/infrastructure change candidate ({comp['area_km2']:.2f} km²)",
                    geometry=comp["geometry"], area_km2=comp["area_km2"], confidence=conf,
                    severity=severity_from(comp["area_km2"], abs(delta)),
                    measurements={
                        "mean_change_db": round(delta, 3),
                        "pixels": int(m.sum()),
                        "builtup_proxy_db": self.config["builtup_proxy_db"],
                        "overlap_with_proxy_fraction": round(
                            float((m & proxy).sum() / max(1, m.sum())), 3),
                    },
                    supporting=[
                        f"Backscatter increased by {delta:+.2f} dB between {before.datetime} and "
                        f"{after.datetime} over {comp['area_km2']:.2f} km².",
                        "The patch overlaps an existing bright (built-up) surface, where a "
                        "double-bounce increase is the usual response to new vertical structures.",
                    ],
                    conflicting=[
                        "No GHSL/OSM/building dataset was available to confirm construction; "
                        "dry riverbeds and bare rock can produce the same signature.",
                    ],
                    uncertainty=(
                        "Interpretation is a radar-response inference only. The confidence value "
                        "is a heuristic ranking score capped at "
                        f"{self.config['confidence_cap']}, not a probability of construction."
                    ),
                    explanation=(
                        f"Radar backscatter rose {delta:+.2f} dB inside {comp['area_km2']:.2f} km² "
                        "adjacent to existing built-up surface between the two acquisitions — a "
                        "response consistent with new construction or infrastructure. Without a "
                        "building/land-use dataset this cannot be confirmed, so verification "
                        "(optical imagery, OSM, GHSL) is required."
                    ),
                    first_observed=after.datetime, tags=["built_up", "infrastructure"],
                ))
            return self._result(status="succeeded", candidates=candidates, logs=logs,
                                metrics={"candidates": len(candidates),
                                         "proxy_px": int(proxy.sum()),
                                         "increase_px": int(mask.sum())},
                                reason_code="SUFFICIENT_VALID_PIXELS",
                                reason="Built-up proxy + increase patches found.",
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
