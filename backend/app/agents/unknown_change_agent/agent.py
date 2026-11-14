"""AGENT 12 — Unknown Change Discovery Intelligence.

Finds significant surface changes that do **not** confidently fit any known
category. It runs last, excludes regions already claimed by the other eleven
agents, and never forces its output into a known class — results are published
as *Unclassified Surface Change* with suggested investigations.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import numpy as np
from scipy import ndimage

from app.agents._common import confidence_score, frame_region, mean_in, regions, severity_from
from app.agents.base import AgentCandidate, AgentContext, AgentResult, BaseAgent, unclaimed
from app.change_detection.unsupervised import cluster_change, detect_patch_anomalies
from app.change_detection.tracking import offsets_to_ground, track_offsets

INVESTIGATION_HINTS = {
    0: "Compare with optical imagery (Sentinel-2/Landsat) and check for human activity in OSM.",
    1: "Check against independent event catalogues (flood, fire, seismic, landslide) for this date.",
    2: "Inspect the area in higher-resolution SAR/optical data and consult local records.",
}


class UnknownChangeAgent(BaseAgent):
    id = "unknown_change"
    name = "Unknown Change Discovery Intelligence"
    ordinal = 12
    category = "UNCASSIFIED_CHANGE"
    purpose = (
        "Discover significant surface changes that do not confidently fit known categories, "
        "using unsupervised anomaly detection, clustering and temporal outlier screening."
    )
    status = "operational"
    status_reason = (
        "IsolationForest + k-means screening runs on every analysed region after the specialist "
        "agents, excluding areas they already claimed; outputs are never assigned a known "
        "category."
    )
    baseline_method = "IsolationForest anomaly screening + k-means change clustering (unlabelled)"
    capabilities = [
        "Unsupervised anomaly detection over temporal patch statistics",
        "Novel-change clustering (k-means, unlabelled styles)",
        "Temporal outlier identification",
        "Overlap exclusion against specialist-agent findings",
    ]
    supported_inputs = ["S1_RTC", "NISAR_GCOV", "S1_GRD_GEOCODED"]
    datasets = [
        {"id": "self_supervised_embeddings", "name": "Self-supervised SAR embeddings",
         "status": "not_configured", "note": "No pretrained encoder bundled; sklearn baselines only."},
        {"id": "unlabelled_change_corpus", "name": "Unlabelled change corpus",
         "status": "not_configured", "note": "Would be built from multi-date analysis history."},
    ]
    evaluation = [
        {"metric": "precision_at_k", "value": None,
         "note": "Not measured — no reviewed set of novel-change examples exists yet."},
        {"metric": "cluster_silhouette", "value": None,
         "note": "Computed per run when clusters are formed; no offline evaluation set."},
    ]
    model_version = "isolation-forest-kmeans-1.0"
    config = {"contamination": 0.04, "min_area_km2": 0.15, "patch": 16, "k": 3,
              "confidence_cap": 0.55}
    output_schema = {
        "unclassified_mask": "boolean mask of unexplained change outside known findings",
        "area_km2": "geodesic area of the unclassified change",
        "cluster_id": "index of the change style (semantic meaning intentionally absent)",
        "anomaly_score": "relative IsolationForest decision score",
        "suggested_investigation": "recommended next verification step",
    }
    known_limitations = [
        "Anomaly ≠ cause: unusual-looking change may still be a known process with unusual "
        "radiometry.",
        "Cluster indices are arbitrary and carry no semantic label by design.",
        "Results depend on which specialist agents already claimed overlapping areas.",
        "Scores are relative to the analysed scene and are not calibrated probabilities.",
    ]

    def _select_specific(self, ctx: AgentContext) -> tuple:
        if not ctx.has_pair:
            return False, "SINGLE_DATE_ONLY", (
                "Unsupervised temporal screening needs at least two observations."
            )
        if ctx.change is None:
            return False, "EARLIER_FAILURE", "No change layer available for screening."
        return True, "ALWAYS_ELIGIBLE_UNKNOWN_SCREEN", (
            "Final discovery screen: always eligible after the specialist agents so that "
            "significant changes without an explained cause are not lost."
        )

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.time()
        logs: List[str] = []
        try:
            region = frame_region(ctx)
            before, after = ctx.before, ctx.after
            valid = ctx.valid if ctx.valid is not None else (before.valid & after.valid)
            b_db, a_db = before.db(before.primary_pol), after.db(after.primary_pol)
            change = ctx.change.mask & valid

            # exclude regions already claimed by specialist agents
            claimed = ctx.claimed_geometries or []
            if claimed:
                from rasterio import features as rfeatures
                from shapely.geometry import mapping
                claim_mask = np.zeros(change.shape, dtype=bool)
                for g in claimed:
                    try:
                        claim_mask |= rfeatures.geometry_mask(
                            [mapping(g)], out_shape=change.shape, transform=before.transform,
                            invert=True, all_touched=True)
                    except Exception:
                        continue
                leftover = change & ~claim_mask
                logs.append(f"claimed regions cover {int(claim_mask.sum())} px; "
                            f"leftover change {int(leftover.sum())} px "
                            f"({len(claimed)} claim(s))")
            else:
                leftover = change
                logs.append(f"no specialist claims; screening all {int(change.sum())} changed px")

            if leftover.sum() < 20:
                return self._result(
                    status="no_candidates", reason_code="ALL_CHANGE_EXPLAINED",
                    reason=("Every detected change region overlapped a specialist-agent "
                            "candidate" if claimed else "No significant change pixels to screen")
                    + ".",
                    logs=logs, duration_ms=int((time.time() - t0) * 1000),
                    metrics={"leftover_px": int(leftover.sum())})

            anom = detect_patch_anomalies(b_db, a_db, valid, leftover,
                                          contamination=self.config["contamination"],
                                          patch=self.config["patch"])
            logs.extend(anom.get("notes", []))
            cl = cluster_change(b_db, a_db, valid, leftover, k=self.config["k"],
                                patch=self.config["patch"])
            logs.extend(cl.get("notes", []))

            mask = leftover & (anom["anomaly_mask"] | (cl.get("mask") & leftover)
                               if cl.get("mask") is not None else anom["anomaly_mask"])
            mask = ndimage.binary_opening(mask, ndimage.generate_binary_structure(2, 2))
            logs.append(f"unclassified px={int(mask.sum())}")
            if mask.sum() < 20:
                return self._result(status="no_candidates", reason_code="NO_UNEXPLAINED_CHANGE",
                                    reason="Residual change was not statistically unusual — no "
                                           "unclassified change to report.",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000),
                                    metrics={"leftover_px": int(leftover.sum())})

            comps = regions(mask, before.transform, region=region,
                            min_area_km2=self.config["min_area_km2"], max_components=4)
            if not comps:
                return self._result(status="no_candidates", reason_code="BELOW_MIN_AREA",
                                    reason="Unexplained change patches below minimum mapping area.",
                                    logs=logs, duration_ms=int((time.time() - t0) * 1000))

            # optional: is it just a shift of texture? (helps suggest investigation)
            track = track_offsets(b_db, a_db, valid & ndimage.binary_dilation(mask, iterations=24),
                                  window=96, step=96, max_shift=12)
            if track.get("windows", 0) > 0:
                track = offsets_to_ground(track, before.transform,
                                          lat_mid=(ctx.bbox[1] + ctx.bbox[3]) / 2)

            candidates: List[AgentCandidate] = []
            for i, comp in enumerate(comps):
                m = self._mask(comp, mask, before.transform)
                delta = mean_in(ctx.change.diff_db, m) or 0.0
                conf = min(
                    confidence_score(magnitude_db=abs(delta), area_km2_=comp["area_km2"],
                                     quality=ctx.quality.get("quality_score", 0.0),
                                     persistent=False, corroborating=0),
                    self.config["confidence_cap"],
                )
                cluster_id = int(i % max(1, cl.get("k", 1))) if cl.get("labels") is not None else None
                hint = INVESTIGATION_HINTS.get(cluster_id or 0, INVESTIGATION_HINTS[0])
                supporting = [
                    f"Backscatter changed {delta:+.2f} dB between {before.datetime} and "
                    f"{after.datetime} over {comp['area_km2']:.2f} km².",
                    f"Patch is an outlier against {anom.get('usable_patches')} other patches "
                    f"(IsolationForest, method {anom.get('method')}).",
                ]
                if cl.get("cluster_stats"):
                    st = next((s for s in cl["cluster_stats"] if s["cluster"] == cluster_id), None)
                    if st:
                        supporting.append(
                            f"Belongs to change style #{cluster_id}: mean {st['mean_diff_db']:+.2f} dB "
                            f"with {st['frac_changed']:.0%} of its pixels changed "
                            f"({st['patches']} similar patches in scene)."
                        )
                if track.get("windows", 0):
                    supporting.append(
                        f"Local texture registration gives ({track['median_dx_px']}, "
                        f"{track['median_dy_px']}) px offset across "
                        f"{track['windows']} windows (confidence {track['confidence']})."
                    )
                candidates.append(AgentCandidate(
                    title=f"Unclassified surface change ({comp['area_km2']:.2f} km²)",
                    geometry=comp["geometry"], area_km2=comp["area_km2"], confidence=conf,
                    severity=severity_from(comp["area_km2"], abs(delta), "unknown"),
                    measurements={
                        "mean_change_db": round(delta, 3),
                        "pixels": int(m.sum()),
                        "cluster_id": cluster_id,
                        "anomalous_patches": anom.get("n_anomalous_patches", 0),
                        "usable_patches": anom.get("usable_patches", 0),
                        "tracking_windows": track.get("windows", 0),
                        "tracking_dx_px": track.get("median_dx_px"),
                        "tracking_dy_px": track.get("median_dy_px"),
                    },
                    supporting=supporting,
                    conflicting=[
                        "No specialist agent explained this region with its own domain test "
                        "(water, clearing, slope, built-up, shoreline, etc.)."
                    ],
                    uncertainty=(
                        "This finding is intentionally unclassified. The score is a heuristic "
                        "anomaly ranking relative to this scene, not a probability, and no cause "
                        "is asserted."
                    ),
                    explanation=(
                        f"Between {before.datetime} and {after.datetime} this "
                        f"{comp['area_km2']:.2f} km² region changed by {delta:+.2f} dB and is a "
                        "statistical outlier relative to the rest of the analysed area. None of "
                        "the specialist agents' domain tests explained it, so it is reported as "
                        "unclassified surface change rather than being forced into a known "
                        f"category. Suggested investigation: {hint}"
                    ),
                    first_observed=after.datetime,
                    tags=["unclassified", "novel_change"] + (
                        [f"style_{cluster_id}"] if cluster_id is not None else []),
                ))
            return self._result(
                status="succeeded", candidates=candidates, logs=logs,
                metrics={"candidates": len(candidates), "unclassified_px": int(mask.sum()),
                         "leftover_px": int(leftover.sum()),
                         "anomalous_patches": anom.get("n_anomalous_patches", 0),
                         "clusters": cl.get("k", 0)},
                reason_code="ALWAYS_ELIGIBLE_UNKNOWN_SCREEN",
                reason="Residual change screened with unsupervised methods.",
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
