"""Dataset registry.

Each entry describes a real dataset that is either *actually reachable* from this
deployment (status ``available``), merely *registered* as a known source
(``registered``), exposed through an integration interface that has not been
downloaded (``interface_only``), or requires credentials/keys that are not
configured (``not_configured``). Nothing here is ever reported as available
unless this deployment can really read it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents import build_agents
from app.config import settings
from app.schemas.api import DatasetInfoOut

# status values: available | registered | interface_only | not_configured
DATASETS: List[Dict[str, Any]] = [
    {
        "id": "sentinel1_rtc_planetary_computer",
        "name": "Sentinel-1 RTC (Microsoft Planetary Computer)",
        "status": "available",
        "access": "STAC search + anonymous SAS signing of COG hrefs",
        "url": "https://planetarycomputer.microsoft.com/api/stac/v1",
        "note": "Calibrated 10 m sigma0 VV/VH rasters, read anonymously for every analysis.",
    },
    {
        "id": "sentinel1_grd_earth_search",
        "name": "Sentinel-1 GRD (AWS / Element84 Earth Search)",
        "status": "registered",
        "access": "STAC search for metadata and browse images",
        "url": "https://earth-search.aws.element84.com/v1",
        "note": "GRD COGs in this catalogue carry no embedded CRS (radar geometry), so they "
                "are used for discovery/browse only, never as analysis rasters.",
    },
    {
        "id": "copernicus_dem_glo30",
        "name": "Copernicus DEM GLO-30",
        "status": "available",
        "access": "Earth Search STAC item assets (anonymous HTTPS)",
        "url": "https://copernicus-dem-30m.s3.amazonaws.com",
        "note": "Loaded for slope/terrain context used by landslide, glacier and deformation agents.",
    },
    {
        "id": "sentinel2_l2a",
        "name": "Sentinel-2 L2A (AWS / Element84)",
        "status": "available",
        "access": "Earth Search STAC search for the nearest cloud-scored scene",
        "url": "https://earth-search.aws.element84.com/v1",
        "note": "Optical corroboration only; never substituted for SAR evidence.",
    },
    {
        "id": "opera_dswx_s1",
        "name": "OPERA DSWx-S1 dynamic surface water",
        "status": "registered",
        "access": "NASA CMR metadata discovery; raster download needs Earthdata Login",
        "url": "https://cmr.earthdata.nasa.gov",
        "note": "Discovery is anonymous; pixel access requires EARTHDATA_TOKEN in .env.",
    },
    {
        "id": "nisar_l1_rslc",
        "name": "NISAR L1 RSLC / L2 GSLC",
        "status": "registered",
        "access": "NASA CMR metadata discovery; science rasters need Earthdata Login",
        "url": "https://cmr.earthdata.nasa.gov",
        "note": "Granules are discovered and listed; downloading them needs server-side credentials.",
    },
    {
        "id": "sen1floods11",
        "name": "Sen1Floods11",
        "status": "interface_only",
        "access": "Registration required by the provider",
        "url": "https://github.com/cloudtostreet/Sen1Floods11",
        "note": "Integration interface registered; dataset not downloaded by this deployment.",
    },
    {
        "id": "global_flood_database",
        "name": "Global Flood Database (MODIS)",
        "status": "interface_only",
        "access": "Provider download portal",
        "url": "https://www.globalflooddb.org",
        "note": "Optical flood composites; interface registered, not fetched here.",
    },
    {
        "id": "jrc_global_surface_water",
        "name": "JRC Global Surface Water",
        "status": "interface_only",
        "access": "Google Earth Engine / provider download",
        "url": "https://global-surface-water.appspot.com",
        "note": "Requires external access; interface registered only.",
    },
    {
        "id": "global_forest_change",
        "name": "Global Forest Change (Hansen et al.)",
        "status": "interface_only",
        "access": "University of Maryland download portal",
        "url": "https://www.globalforestwatch.org",
        "note": "Optical tree-cover loss layers; interface registered, not downloaded.",
    },
    {
        "id": "esa_worldcover",
        "name": "ESA WorldCover 10 m land cover",
        "status": "interface_only",
        "access": "ESA Copernicus portal",
        "url": "https://esa-worldcover.org",
        "note": "Used as an optional class-context reference; not fetched by default.",
    },
    {
        "id": "uavsar_rpi_polsar",
        "name": "UAVSAR (NASA/JPL airborne L-band SAR)",
        "status": "available",
        "access": "NASA CMR discovery (anonymous); browse images and products verified publicly accessible",
        "url": "https://uavsar.jpl.nasa.gov",
        "note": "Repeat-pass interferometric (RPI) and polarimetric (POLSAR) L090 products discovered "
                "with footprints and open quicklook images; the airborne archive is openly licensed.",
    },
    {
        "id": "rcm_csa",
        "name": "Radarsat Constellation Mission (CSA)",
        "status": "interface_only",
        "access": "CMR collection CWIC_REG_RCM registered; distributed by CSA / NRCan",
        "url": "https://cmr.earthdata.nasa.gov/search/concepts/CWIC_REG_RCM",
        "note": "Space Agency Partner resource: maritime surveillance, disaster management and ecosystem "
                "monitoring; public CMR granule access is not available in this deployment.",
    },
    {
        "id": "radarsat1_open_archive",
        "name": "RADARSAT-1 (CSA, open licence)",
        "status": "interface_only",
        "access": "CMR collection RSAT-1_L1 registered; full archive released under an open licence",
        "url": "https://cmr.earthdata.nasa.gov/search/concepts/RSAT-1_L1",
        "note": "Canadian operational radar archive (1995+); day/night all-weather SAR. Integration "
                "interface registered, products not fetched by this deployment.",
    },
    {
        "id": "saocom_conae",
        "name": "SAOCOM (CONAE L-band SAR)",
        "status": "interface_only",
        "access": "CMR collection SAOCOM.data.products registered; downloads require ONE CLICK registration",
        "url": "https://catalogos.conae.gov.ar",
        "note": "Space Agency Partner resource; catalogue registration is required by the provider, "
                "so this deployment lists metadata only.",
    },
    {
        "id": "nasa_firms",
        "name": "NASA FIRMS active fire detections",
        "status": "not_configured",
        "access": "Requires FIRMS API key in .env",
        "url": "https://firms.modaps.eosdis.nasa.gov",
        "note": "No FIRMS_MAP_KEY configured — wildfire agent reports this honestly instead of guessing.",
    },
    {
        "id": "copernicus_glass_albedo",
        "name": "Copernicus GLASS albedo/snow products",
        "status": "not_configured",
        "access": "Requires Copernicus Data Space OAuth credentials",
        "url": "https://dataspace.copernicus.eu",
        "note": "Optional cryosphere context; credentials not configured.",
    },
    {
        "id": "nasa_modis_ndvi",
        "name": "NASA MODIS NDVI (MOD13Q1)",
        "status": "interface_only",
        "access": "NASA LP DAAC / Earthdata — requires EARTHDATA_TOKEN for download",
        "url": "https://lpdaac.usgs.gov/products/mod13q1v061/",
        "note": "250 m vegetation index; forest/agriculture agents use as context.",
    },
    {
        "id": "nasa_modis_burned_area",
        "name": "NASA MODIS Burned Area (MCD64A1)",
        "status": "interface_only",
        "access": "NASA LP DAAC / Earthdata — requires EARTHDATA_TOKEN for download",
        "url": "https://lpdaac.usgs.gov/products/mcd64a1v061/",
        "note": "500 m burned-area product; wildfire agent reference.",
    },
    {
        "id": "nasa_viirs_nightlights",
        "name": "NASA VIIRS Nighttime Lights (VNP46A2)",
        "status": "interface_only",
        "access": "NASA LAADS DAAC — requires EARTHDATA_TOKEN",
        "url": "https://ladsweb.modaps.eosdis.nasa.gov/",
        "note": "Urban growth proxy; urban agent reference.",
    },
    {
        "id": "nasa_landsat_c2",
        "name": "NASA/USGS Landsat Collection 2",
        "status": "interface_only",
        "access": "USGS EarthExplorer / NASA Earthdata — requires account",
        "url": "https://www.usgs.gov/landsat-missions/landsat-collection-2",
        "note": "30 m optical; forest/urban/agriculture agents reference.",
    },
    {
        "id": "nasa_nsids_ice",
        "name": "NASA NSIDC Sea Ice / Glacier (MOD10A1)",
        "status": "interface_only",
        "access": "NASA NSIDC DAAC — requires EARTHDATA_TOKEN",
        "url": "https://nsidc.org/data/mod10a1",
        "note": "Glacier/cryosphere agent reference.",
    },
    {
        "id": "nasa_gibs_modis",
        "name": "NASA GIBS MODIS True Color (live)",
        "status": "available",
        "access": "Anonymous WMTS tiles (no credentials)",
        "url": "https://gibs.earthdata.nasa.gov",
        "note": "Live daily MODIS Terra imagery used as the map basemap.",
    },
]


def dataset_catalog() -> Dict[str, Dict[str, Any]]:
    """Catalog keyed by dataset id, with owning agent ids filled in."""
    catalog: Dict[str, Dict[str, Any]] = {d["id"]: {**d, "agent_ids": []} for d in DATASETS}
    for agent in build_agents():
        for ds in agent.datasets:
            entry = catalog.get(ds.get("id", ""))
            if entry is None:
                entry = {
                    "id": ds.get("id", "unknown"),
                    "name": ds.get("name", ds.get("id", "unknown")),
                    "status": ds.get("status", "registered"),
                    "access": "declared by the agent module",
                    "url": None,
                    "note": ds.get("note", ""),
                    "agent_ids": [],
                }
                catalog[entry["id"]] = entry
            if agent.id not in entry["agent_ids"]:
                entry["agent_ids"].append(agent.id)
    return catalog


def dataset_infos() -> List[DatasetInfoOut]:
    return [
        DatasetInfoOut(
            id=e["id"], name=e["name"], agent_ids=list(e["agent_ids"]),
            status=e["status"], access=e.get("access", ""), url=e.get("url"),
            note=e.get("note", ""),
        )
        for e in sorted(dataset_catalog().values(), key=lambda x: x["id"])
    ]


def get_dataset(dataset_id: str) -> Optional[Dict[str, Any]]:
    return dataset_catalog().get(dataset_id)


def local_dataset_path(dataset_id: str):
    """Path where a labelled dataset would live if it had been downloaded."""
    return settings.data_dir / "datasets" / dataset_id
