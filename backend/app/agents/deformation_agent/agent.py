"""AGENT 05 — Ground Deformation Intelligence.

Hard scientific rule enforced here: **displacement in metres must never be
derived from ordinary SAR image differences.** This agent only produces
measurements when a genuine interferometric / displacement product (NISAR
GUNW/RUNW, OPERA DISP-S1) is available and readable; otherwise it is skipped
with reason code `NEEDS_INSAR`.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import numpy as np

from app.agents._common import confidence_score, frame_region, mean_in, pct_in, regions, severity_from
from app.agents.base import AgentCandidate, AgentContext, AgentResult, BaseAgent
from app.preprocessing.raster import pixel_area_km2

INSAR_PRODUCTS = {"GUNW", "RUNW", "RIFG", "DISP-S1", "CSLC", "ROFF", "GOFF"}


class DeformationAgent(BaseAgent):
    id = "deformation"
    name = "Ground Deformation Intelligence"
    ordinal = 5
    category = "GROUND_DEFORMATION"
    purpose = (
        "Investigate ground displacement: earthquake-associated displacement, subsidence, "
        "uplift and volcanic deformation — using interferometric or validated displacement "
        "products only."
    )
    status = "not_configured"
    status_reason = (
        "InSAR processing (SLC pairing, interferogram formation, unwrapping) and authenticated "
        "access to NISAR GUNW / OPERA DISP displacement rasters are not configured in this "
        "deployment (EARTHDATA_TOKEN absent). The interface exists and activates automatically "
        "when a readable displacement product covers the region."
    )
    baseline_method = "Validated displacement-product statistics (no phase from intensity data)"
    capabilities = [
        "Reads NISAR GUNW / OPERA DISP-S1 displacement products when accessible",
        "LOS displacement statistics and exceedance-region mapping",
        "Coherence/data-availability gating",
        "Explicit refusal to estimate metres from intensity differences",
    ]
    supported_inputs = ["NISAR_GUNW", "NISAR_RUNW", "OPERA_DISP-S1", "OPERA_CSLC-S1", "UAVSAR_RPI"]
    datasets = [
        {"id": "opera_disp_s1", "name": "OPERA DISP-S1 validated displacement",
         "status": "interface_only", "note": "CMR discovery works; raster download needs Earthdata Login."},
        {"id": "nisar_gunw", "name": "NISAR GUNW unwrapped interferogram", "status": "interface_only",
         "note": "Discovered via CMR; HDF5 download needs Earthdata Login (h5py optional)."},
        {"id": "uavsar_rpi", "name": "UAVSAR repeat-pass interferometric products", "status": "interface_only",
         "note": "Open NASA/JPL airborne archive discovered via CMR; .unw/.int rasters need "
                 "custom .ann-header conversion before geospatial analysis in this build."},
        {"id": "usgs_earthquake", "name": "USGS earthquake event records", "status": "not_configured",
         "note": "No USGS event lookup configured in this deployment."},
        {"id": "published_insar", "name": "Published InSAR displacement products", "status": "not_configured",
         "note": "No third-party displacement archive configured."},
    ]
    evaluation = [
        {"metric": "displacement_error_m", "value": None,
         "note": "Not measured — no validated displacement ground truth configured."},
        {"metric": "coherence_threshold", "value": None, "note": "No interferograms processed here."},
    ]
    model_version = "displacement-product-reader-1.0"
    config = {"max_abs_displacement_m": 0.10, "min_area_km2": 0.2}
    output_schema = {
        "displacement_m": "line-of-sight displacement from a validated product (metres)",
        "exceedance_mask": "region exceeding the configured displacement threshold",
        "product_id": "identifier of the interferometric/displacement product",
        "quality": "coherence/validity statistics where present",
        "caveat": "never derived from intensity differences",
    }
    known_limitations = [
        "No interferometric processing chain (phase formation/unwrapping) runs in this build.",
        "Requires authenticated NASA product access (EARTHDATA_TOKEN).",
        "Atmospheric phase, ionospheric artefacts and unwrapping errors are not modelled here.",
        "Ordinary SAR backscatter differences carry no absolute displacement information.",
    ]

    # ------------------------------------------------------------- selection
    def _select_specific(self, ctx: AgentContext) -> tuple:
        insar_obs = [o for o in ctx.observations
                     if (o.product_type or "").upper() in INSAR_PRODUCTS]
        readable = [o for o in insar_obs if not o.requires_credentials and o.url]
        if readable:
            return True, "SUFFICIENT_VALID_PIXELS", (
                f"{len(readable)} readable interferometric/displacement product(s) cover this "
                "region; displacement statistics can be computed."
            )
        if insar_obs:
            return False, "NEEDS_INSAR", (
                f"{len(insar_obs)} InSAR/displacement product(s) found, but all require "
                "Earthdata Login credentials that are not configured on this server. "
                "Displacement in metres is never estimated from intensity differences."
            )
        return False, "NEEDS_INSAR", (
            "No interferometric or validated displacement product covers this region and "
            "period, so ground deformation cannot be measured. Ordinary image differences "
            "are deliberately not used for displacement claims."
        )

    # ------------------------------------------------------------------ run
    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.time()
        logs: List[str] = []
        try:
            ok, code, reason = self._select_specific(ctx)
            if not ok:
                return self._result(status="skipped", reason_code=code, reason=reason, logs=logs,
                                    duration_ms=int((time.time() - t0) * 1000))
            region = frame_region(ctx)
            readable = [o for o in ctx.observations
                        if (o.product_type or "").upper() in INSAR_PRODUCTS
                        and not o.requires_credentials and o.url]
            from app.preprocessing.io import read_scene

            scene = None
            last_err = None
            for obs in readable[:2]:
                try:
                    scene = read_scene(
                        obs.url, ctx.bbox, source=obs.source, mission=obs.mission,
                        polarizations=obs.polarizations or ["LOS"], observation_id=obs.id,
                        product_type=obs.product_type, datetime_=obs.datetime,
                        fallback_url=obs.context.get("s3_url"),
                    )
                    logs.append(f"Read displacement product {obs.provider_id}")
                    break
                except Exception as exc:
                    last_err = exc
                    logs.append(f"Product {obs.provider_id} unreadable: {exc}")
            if scene is None:
                return self._result(status="failed", reason_code="PRODUCT_UNREADABLE",
                                    reason=str(last_err or "unreadable displacement product"),
                                    error=str(last_err), logs=logs,
                                    duration_ms=int((time.time() - t0) * 1000))

            band = next(iter(scene.arrays.values()))
            valid = np.isfinite(band)
            thr = self.config["max_abs_displacement_m"]
            exceed = valid & (np.abs(band) > thr)
            logs.append(f"displacement pixels: {int(exceed.sum())} exceed ±{thr} m")
            if not exceed.any():
                return self._result(status="no_candidates", reason_code="BELOW_THRESHOLD",
                                    reason=f"No pixels exceed ±{thr} m LOS displacement.",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000),
                                    metrics={"max_abs_m": float(np.nanmax(np.abs(band[valid]))) if valid.any() else None})
            comps = regions(exceed, scene.transform, region=region,
                            min_area_km2=self.config["min_area_km2"], max_components=4)
            candidates: List[AgentCandidate] = []
            for comp in comps:
                m = self._mask(comp, exceed, scene.transform)
                vals = band[m & valid]
                if vals.size == 0:
                    continue
                max_m = float(np.max(np.abs(vals)))
                mean_m = float(np.mean(vals))
                conf = confidence_score(magnitude_db=min(12, max_m * 40), area_km2_=comp["area_km2"],
                                        quality=ctx.quality.get("quality_score", 0.0), persistent=True)
                candidates.append(AgentCandidate(
                    title=f"Ground displacement region (|LOS| up to {max_m:.3f} m)",
                    geometry=comp["geometry"], area_km2=comp["area_km2"], confidence=conf,
                    severity=severity_from(comp["area_km2"], max_m * 20),
                    measurements={
                        "max_abs_los_displacement_m": round(max_m, 4),
                        "mean_los_displacement_m": round(mean_m, 4),
                        "threshold_m": thr,
                        "pixels": int(m.sum()),
                        "product_type": scene.product_type,
                    },
                    supporting=[
                        f"Displacement from product {scene.product_type} ({scene.mission}) "
                        f"acquired {scene.datetime}.",
                        f"Peak line-of-sight displacement {max_m:.3f} m over {comp['area_km2']:.2f} km².",
                    ],
                    conflicting=["Atmospheric/ionospheric phase and unwrapping errors are not "
                                 "separated in this quick-look product read."],
                    uncertainty="Values come from a validated displacement product, not from "
                                "image differencing; no phase unwrapping is performed here.",
                    explanation=(
                        f"A displacement product covering this region reports up to {max_m:.3f} m "
                        "line-of-sight movement over the acquisition interval. This is a direct "
                        "product reading; TerraTrace does not derive displacement from ordinary "
                        "SAR image differences."
                    ),
                    first_observed=scene.datetime, tags=["displacement", "insar_product"],
                ))
            return self._result(status="succeeded" if candidates else "no_candidates",
                                candidates=candidates, logs=logs,
                                metrics={"candidates": len(candidates)},
                                reason_code="SUFFICIENT_VALID_PIXELS",
                                reason="Displacement product read successfully.",
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
