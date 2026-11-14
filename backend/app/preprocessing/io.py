"""Raster I/O: windowed reads of real SAR products onto a common analysis grid."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import rasterio
from affine import Affine
from pyproj import CRS as PyCRS
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.warp import reproject
from rasterio.windows import Window, from_bounds

from app.config import settings
from app.core.errors import UnsupportedAnalysisError
from app.core.logging import get_logger
from app.data_sources.earth_search import s3_to_https
from app.data_sources.planetary_computer import sign_href

log = get_logger("preprocessing.io")

ANALYSIS_CRS = "EPSG:4326"


@dataclass
class RasterScene:
    """A real raster read from a satellite product, on the common analysis grid."""

    observation_id: str
    source: str
    mission: str
    product_type: str
    datetime: str
    polarizations: List[str]
    url: Optional[str]
    platform: str = ""
    orbit_direction: Optional[str] = None
    arrays: Dict[str, np.ndarray] = field(default_factory=dict)  # pol -> float32 linear
    valid: Optional[np.ndarray] = None  # bool, any-pol valid
    transform: Optional[Affine] = None  # in ANALYSIS_CRS
    crs: str = ANALYSIS_CRS
    notes: List[str] = field(default_factory=list)
    native_crs: Optional[str] = None
    read_ms: int = 0

    def db(self, pol: str) -> np.ndarray:
        arr = self.arrays[pol]
        out = np.full(arr.shape, np.nan, dtype="float32")
        ok = np.isfinite(arr) & (arr > 0)
        out[ok] = (10.0 * np.log10(arr[ok])).astype("float32")
        return out

    @property
    def primary_pol(self) -> str:
        for p in ("VV", "HH"):
            if p in self.arrays:
                return p
        return next(iter(self.arrays), "VV")

    def orbit_mismatch_hint(self, other: "RasterScene") -> bool:
        """True when the two scenes were acquired from different geometries."""
        if self.orbit_direction and other.orbit_direction:
            return self.orbit_direction != other.orbit_direction
        if self.platform and other.platform and self.platform != other.platform:
            return True
        return False


def resolve_url(url: str, source: str) -> str:
    """Apply provider-specific URL resolution (SAS signing, s3→https)."""
    if not url:
        return url
    if url.startswith("s3://"):
        url = s3_to_https(url)
    if source == "planetary_computer":
        url = sign_href(url)
    return url


def _common_grid(
    bbox: Sequence[float], size: int
) -> Tuple[Affine, int, int]:
    w, s, e, n = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    # keep aspect roughly square in ground distance
    width_deg = max(e - w, 1e-6)
    height_deg = max(n - s, 1e-6)
    mid_lat = (s + n) / 2.0
    # convert to km to balance pixels
    km_w = width_deg * 111.32 * np.cos(np.radians(mid_lat))
    km_h = height_deg * 110.57
    if km_w >= km_h:
        px = size
        py = max(16, int(round(size * km_h / km_w)))
    else:
        py = size
        px = max(16, int(round(size * km_w / km_h)))
    transform = Affine(width_deg / px, 0.0, w, 0.0, -height_deg / py, n)
    return transform, px, py


def read_scene(
    obs_url: str,
    bbox: Sequence[float],
    *,
    size: int = None,  # type: ignore[assignment]
    source: str = "",
    mission: str = "",
    polarizations: Sequence[str] = ("VV", "VH"),
    observation_id: str = "",
    product_type: str = "",
    datetime_: str = "",
    fallback_url: Optional[str] = None,
    platform: str = "",
    orbit_direction: Optional[str] = None,
) -> RasterScene:
    """Read the requested region from a real product onto the common lon/lat grid.

    Raises `UnsupportedAnalysisError` with a human-readable explanation when the
    product cannot support geospatial analysis (e.g. no embedded georeferencing,
    or authenticated access without configured credentials).
    """
    size = size or settings.raster_size
    target_transform, px, py = _common_grid(bbox, size)
    dst = np.full((py, px), np.nan, dtype="float32")
    started = time.time()
    notes: List[str] = []

    url = resolve_url(obs_url or "", source)
    attempts = [u for u in (url, fallback_url and resolve_url(fallback_url, source)) if u]

    last_error: Optional[Exception] = None
    for candidate in attempts:
        try:
            with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                               CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff,.vrt"):
                with rasterio.open(candidate) as src:
                    if src.crs is None:
                        raise UnsupportedAnalysisError(
                            "This product's raster has no embedded georeferencing (radar "
                            "geometry), so TerraTrace cannot geolocate a change result from it. "
                            "Use a geocoded product (e.g. Sentinel-1 RTC / OPERA / NISAR GSLC)."
                        )
                    native_crs = src.crs
                    tr = Transformer.from_crs(ANALYSIS_CRS, native_crs, always_xy=True)
                    x0, y0 = tr.transform(bbox[0], bbox[1])
                    x1, y1 = tr.transform(bbox[2], bbox[3])
                    minx, maxx = min(x0, x1), max(x0, x1)
                    miny, maxy = min(y0, y1), max(y0, y1)
                    # pad 4% to avoid edge artefacts
                    pad_x = (maxx - minx) * 0.04
                    pad_y = (maxy - miny) * 0.04
                    win = from_bounds(minx - pad_x, miny - pad_y, maxx + pad_x, maxy + pad_y,
                                      src.transform)
                    # clamp to raster
                    win = win.intersection(Window(0, 0, src.width, src.height))
                    if win.width <= 0 or win.height <= 0:
                        raise UnsupportedAnalysisError(
                            "The requested area does not intersect this observation's footprint."
                        )
                    out = np.full((py, px), np.nan, dtype="float32")
                    reproject(
                        source=rasterio.band(src, 1),
                        destination=out,
                        src_transform=src.transform,
                        src_crs=src.crs,
                        src_nodata=src.nodata,
                        dst_transform=target_transform,
                        dst_crs=ANALYSIS_CRS,
                        dst_nodata=np.nan,
                        resampling=Resampling.bilinear,
                        num_threads=2,
                    )
                    dst = out
                    notes.append(f"Read {src.width}x{src.height} product window from {source or 'url'} "
                                 f"({native_crs.to_string()}).")
                    scene_native = native_crs.to_string()
                    break
        except UnsupportedAnalysisError:
            raise
        except Exception as exc:  # try fallback / report
            last_error = exc
            continue
    else:
        raise UnsupportedAnalysisError(
            f"Could not read raster from {attempts[:1]}: {last_error}. "
            "The product may require Earthdata Login credentials or may not be readable "
            "from this environment."
        )

    valid = np.isfinite(dst) & (dst > 0)
    coverage = float(valid.mean()) if valid.size else 0.0
    notes.append(f"Valid data fraction inside region: {coverage:.1%}.")
    if coverage < 0.05:
        raise UnsupportedAnalysisError(
            f"Only {coverage:.1%} of the requested region contains valid pixels for this "
            "observation — insufficient data for a change statement."
        )

    scene = RasterScene(
        observation_id=observation_id,
        source=source,
        mission=mission,
        product_type=product_type,
        datetime=datetime_,
        polarizations=list(polarizations),
        url=url,
        platform=platform,
        orbit_direction=orbit_direction,
        arrays={"PRIMARY": dst.astype("float32")},
        valid=valid,
        transform=target_transform,
        crs=ANALYSIS_CRS,
        notes=notes,
        native_crs=scene_native,
        read_ms=int((time.time() - started) * 1000),
    )
    # rasterio single-band products carry one polarization: label honestly
    scene.arrays[_primary_label(polarizations)] = scene.arrays.pop("PRIMARY")
    return scene


def _primary_label(polarizations: Sequence[str]) -> str:
    for p in polarizations or ("VV",):
        if p in ("VV", "HH"):
            return p
    return polarizations[0] if polarizations else "VV"


def read_raster_array(url: str, bbox: Sequence[float], size: int = 256, source: str = "") -> Tuple[np.ndarray, Affine, str]:
    """Utility: single-band read of any georeferenced raster (e.g. Copernicus DEM)."""
    target_transform, px, py = _common_grid(bbox, size)
    out = np.full((py, px), np.nan, dtype="float32")
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(resolve_url(url, source)) as src:
            if src.crs is None:
                raise UnsupportedAnalysisError("Raster has no georeferencing.")
            reproject(
                source=rasterio.band(src, 1), destination=out,
                src_transform=src.transform, src_crs=src.crs, src_nodata=src.nodata,
                dst_transform=target_transform, dst_crs=ANALYSIS_CRS, dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
    return out, target_transform, src.crs.to_string()
