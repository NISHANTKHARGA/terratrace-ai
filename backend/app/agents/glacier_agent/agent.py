"""AGENT 06 — Glacier & Cryosphere Intelligence.

Baseline: bright/ textured ice-proxy mapping plus **feature tracking**
(phase correlation of radar texture) between two dates to measure image
offsets. Offsets are reported in pixels and ground metres with an explicit
statement that they are image offsets, not InSAR displacement.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import numpy as np
from scipy import ndimage

from app.agents._common import confidence_score, frame_region, mean_in, regions, severity_from
from app.agents.base import AgentCandidate, AgentContext, AgentResult, BaseAgent
from app.change_detection.tracking import offsets_to_ground, track_offsets
from app.preprocessing.raster import pixel_area_km2


def ice_proxy(db: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Bright, textured surfaces consistent with bare ice / firn in C-band."""
    if not valid.any():
        return np.zeros_like(db, dtype=bool)
    p90 = float(np.percentile(db[valid], 90))
    bright = valid & (db > max(p90, -4.0))
    mean = ndimage.uniform_filter(np.nan_to_num(db, nan=0.0), 7)
    sq = ndimage.uniform_filter(np.nan_to_num(db, nan=0.0) ** 2, 7)
    std = np.sqrt(np.maximum(sq - mean ** 2, 0.0))
    return bright & (std > 2.0)


class GlacierAgent(BaseAgent):
    id = "glacier"
    name = "Glacier & Cryosphere Intelligence"
    ordinal = 6
    category = "GLACIER_CRYOSPHERE"
    purpose = (
        "Monitor glacier movement, terminus/extent change and ice-surface change using "
        "feature tracking and temporal comparison of SAR observations."
    )
    status = "experimental"
    status_reason = (
        "Feature tracking runs on real imagery, but no glacier inventory mask "
        "(RGI/GLIMS) is bundled, so ice regions are identified by a bright/textured radar "
        "proxy rather than by an inventory boundary."
    )
    baseline_method = "Ice-proxy mapping + phase-correlation feature tracking between dates"
    capabilities = [
        "Ice-surface image-offset tracking (pixels / metres)",
        "Ice-proxy extent change between dates",
        "Tracking confidence and window statistics",
    ]
    supported_inputs = ["S1_RTC", "NISAR_GCOV", "S1_GRD_GEOCODED"]
    datasets = [
        {"id": "randolph_glacier_inventory", "name": "Randolph Glacier Inventory",
         "status": "interface_only", "note": "No RGI outlines bundled; interface registered."},
        {"id": "its_live", "name": "ITS_LIVE glacier velocity", "status": "interface_only",
         "note": "Reference velocity product for validation; not downloaded here."},
        {"id": "glims", "name": "GLIMS glacier database", "status": "not_configured",
         "note": "No GLIMS access configured."},
    ]
    evaluation = [
        {"metric": "displacement_error_px", "value": None,
         "note": "Not measured — no reference velocity field configured."},
        {"metric": "tracking_confidence", "value": None,
         "note": "Runtime confidence is reported per run; no offline evaluation performed."},
    ]
    model_version = "feature-tracking-1.0"
    config = {"window": 128, "step": 128, "max_shift": 20, "min_ice_fraction": 0.004,
              "min_offset_px": 0.75, "min_area_km2": 0.5}
    output_schema = {
        "offset_dx_px/dy_px": "median image offset between dates (pixels)",
        "offset_dx_m/dy_m": "approximate ground offset (metres) using local pixel size",
        "ice_proxy_mask": "bright/textured region used as the ice proxy",
        "confidence": "mean tracking confidence of retained windows",
        "caveat": "feature tracking, not interferometric phase",
    }
    known_limitations = [
        "No glacier inventory mask: ice is proxied by brightness/texture, which also matches "
        "bare rock, snowfields and urban areas.",
        "Feature tracking measures image offset, not ice thickness or true flow velocity; "
        "along-/across-track components are not resolved to a ground velocity vector.",
        "Speckle decorrelation over long intervals degrades tracking confidence.",
        "Terminus change requires inventory outlines or higher-resolution data.",
    ]

    def _select_specific(self, ctx: AgentContext) -> tuple:
        if not ctx.has_pair:
            return False, "SINGLE_DATE_ONLY", "Requires two observations."
        before = ctx.before
        valid = ctx.valid if ctx.valid is not None else before.valid
        db = before.db(before.primary_pol)
        frac = float(ice_proxy(db, valid).mean()) if valid is not None else 0.0
        if frac < self.config["min_ice_fraction"]:
            return False, "NO_CRYOSPHERE_CONTEXT", (
                f"Ice-proxy coverage is {frac:.2%} (threshold "
                f"{self.config['min_ice_fraction']:.2%}) — no glacier-like bright, textured "
                "surface in this region, so tracking would not measure ice motion."
            )
        return True, "SUFFICIENT_VALID_PIXELS", (
            f"Ice-proxy covers {frac:.2%} of the region; two observations allow feature tracking."
        )

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.time()
        logs: List[str] = []
        try:
            region = frame_region(ctx)
            before, after = ctx.before, ctx.after
            valid = ctx.valid if ctx.valid is not None else (before.valid & after.valid)
            b_db, a_db = before.db(before.primary_pol), after.db(after.primary_pol)
            proxy = ice_proxy(b_db, valid) | ice_proxy(a_db, valid)
            proxy = ndimage.binary_opening(proxy, ndimage.generate_binary_structure(2, 2))
            proxy = ndimage.binary_closing(proxy, ndimage.generate_binary_structure(2, 2))
            logs.append(f"ice proxy px={int(proxy.sum())} ({float(proxy.mean()):.2%})")
            if proxy.sum() < 100:
                return self._result(status="no_candidates", reason_code="NO_CRYOSPHERE_CONTEXT",
                                    reason="Ice proxy too small to track.", logs=logs,
                                    duration_ms=int((time.time() - t0) * 1000))

            track = track_offsets(
                b_db, a_db, valid & ndimage.binary_dilation(proxy, iterations=64),
                window=self.config["window"], step=self.config["step"],
                max_shift=self.config["max_shift"],
            )
            logs.extend(track.get("notes", []))
            if track.get("windows", 0) == 0:
                # still report extent change, but no motion claim
                track = {**track, "median_dx_px": None, "median_dy_px": None}
            track = offsets_to_ground(track, before.transform,
                                      lat_mid=(ctx.bbox[1] + ctx.bbox[3]) / 2)

            dx, dy = track.get("median_dx_px"), track.get("median_dy_px")
            conf = float(track.get("confidence") or 0.0)
            moving = dx is not None and dy is not None and (abs(dx) + abs(dy)) >= self.config["min_offset_px"]

            comps = regions(proxy, before.transform, region=region,
                            min_area_km2=self.config["min_area_km2"], max_components=4)
            if not comps:
                return self._result(status="no_candidates", reason_code="BELOW_MIN_AREA",
                                    reason="Ice-proxy regions below the minimum mapping area.",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000))
            candidates: List[AgentCandidate] = []
            for comp in comps:
                if not moving and len(comps) > 2:
                    continue
                mag = float(np.hypot(dx or 0.0, dy or 0.0))
                conf_c = confidence_score(
                    magnitude_db=min(12.0, mag * 4 + (conf * 4)),
                    area_km2_=comp["area_km2"], quality=ctx.quality.get("quality_score", 0.0),
                    persistent=True, corroborating=1 if conf > 0.6 else 0,
                    penalty=0.0 if moving else 0.2,
                )
                candidates.append(AgentCandidate(
                    title=(f"Ice-surface feature motion ({mag:.1f} px, {track.get('median_dx_m')} m E)"
                           if moving else
                           f"Ice-like surface change without resolvable motion ({comp['area_km2']:.1f} km²)"),
                    geometry=comp["geometry"], area_km2=comp["area_km2"], confidence=conf_c,
                    severity=severity_from(comp["area_km2"], mag * 3,
                                           "low" if not moving else "moderate"),
                    measurements={
                        "offset_dx_px": dx, "offset_dy_px": dy,
                        "offset_dx_m": track.get("median_dx_m"), "offset_dy_m": track.get("median_dy_m"),
                        "pixel_size_m": track.get("pixel_size_m"),
                        "tracking_windows": track.get("windows", 0),
                        "tracking_confidence": conf,
                        "tracking_spread_px": track.get("spread_px"),
                        "product": after.product_type,
                    },
                    supporting=track.get("notes", []) + [
                        f"Tracking used {track.get('windows', 0)} textured windows between "
                        f"{before.datetime} and {after.datetime}.",
                        f"Ice-proxy region {comp['area_km2']:.2f} km².",
                    ],
                    conflicting=(
                        ["No glacier inventory outline was available, so the region is a radar "
                         "proxy for ice and could include bare rock or snow." ]
                        if not moving else []
                    ),
                    uncertainty=(
                        "Offsets come from texture correlation between two dates (feature "
                        "tracking), not from interferometric phase; they are approximate image "
                        "offsets with a spread of "
                        f"{track.get('spread_px')} px and no orbit/terrain orthorectification "
                        "residual is modelled. Score is heuristic, not a probability."
                    ),
                    explanation=(
                        (f"Cross-correlating radar texture between {before.datetime} and "
                         f"{after.datetime} gives a median offset of ({dx}, {dy}) px "
                         f"(≈ {track.get('median_dx_m')} m east, {track.get('median_dy_m')} m "
                         f"north) over the ice-proxy area with confidence {conf:.2f}. "
                         if moving else
                         f"An ice-like bright/textured region of {comp['area_km2']:.2f} km² was "
                         "found, but texture tracking did not resolve a consistent offset. ")
                        + "This is image feature tracking, not InSAR, and no glacier inventory "
                          "boundary was available to confirm the ice extent."
                    ),
                    first_observed=after.datetime, tags=["cryosphere", "feature_tracking"],
                ))
            return self._result(
                status="succeeded" if candidates else "no_candidates", candidates=candidates,
                logs=logs, metrics={"candidates": len(candidates), "windows": track.get("windows", 0),
                                    "confidence": conf, "ice_fraction": float(proxy.mean())},
                reason_code="SUFFICIENT_VALID_PIXELS" if candidates else "NO_TRACKABLE_TEXTURE",
                reason="Feature tracking completed." if candidates else
                       "Tracking produced no reportable region.",
                duration_ms=int((time.time() - t0) * 1000))
        except Exception as exc:
            return self._fail(exc, logs, t0)
