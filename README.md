# TerraTrace AI

TerraTrace AI is a NASA Space Apps prototype for global multi-agent Earth
observation. It discovers real NISAR, Sentinel-1, and OPERA observations, runs
SAR change detection on calibrated backscatter, routes candidate changes to
twelve specialist agents, validates the evidence, and publishes findings that
link back to the source observations and processing artifacts.

The product is designed to be explicit about uncertainty: confidence scores are
heuristic ranking scores between 0 and 1, not calibrated probabilities. The
five evidence concepts are kept separate throughout the UI and reports:

- detection confidence;
- evidence completeness;
- data quality;
- severity;
- verification status.

## What is implemented

- FastAPI backend with SQLAlchemy/SQLite, background job processing, and a
  documented REST API.
- React + TypeScript + Vite frontend with Leaflet maps, Recharts charts, and
  the Lucide icon set.
- Real catalogue discovery through NASA CMR, Microsoft Planetary Computer,
  AWS Earth Search, and Copernicus Data Space.
- NASA & partner mission coverage from the Space Apps resource list:
  **NISAR**, **OPERA**, **Sentinel-1**, and **UAVSAR** (NASA/JPL airborne
  L-band, verified open access — browse images and products are fetched
  anonymously), plus registered interfaces for **RCM (CSA)**,
  **RADARSAT-1 (CSA, open licence)**, and **SAOCOM (CONAE)** via their CMR
  collections. ASF Vertex and NASA Earthdata Search are reached through CMR,
  the catalogue behind both.
- Real SAR pair loading, dB conversion, log-ratio change detection, Otsu water
  segmentation, raster vectorisation, and PNG/GeoJSON artifact generation.
- A central orchestrator with seven pipeline stages:
  1. global data scout;
  2. SAR processing;
  3. change detection;
  4. data-aware agent routing;
  5. parallel specialist agent execution;
  6. evidence validation;
  7. finding publishing.
- Twelve specialist agents covering flood, wetlands, forest, wildfire,
  deformation, glacier, landslide, agriculture, urban growth, mining, coastal
  change, and unclassified change discovery.
- Published findings with evidence, source observations, before/after/change
  imagery, standalone GeoJSON export, and printable HTML reports.
- API-driven map layers for observations, findings, change polygons, and
  analysis regions.
- Backend tests for API contracts, agent routing, change detection, rendering,
  training metrics, de-duplication, and publisher behavior.

## Map API

The map is served by the backend instead of shipping local GeoJSON:

```text
GET /api/map-layers
GET /api/map-layers/findings.geojson
GET /api/map-layers/change.geojson
GET /api/map-layers/analysis.geojson
```

`GET /api/map-layers` returns one response containing:

- `observations_geojson`;
- `findings_geojson`;
- `change_polygons_geojson` (vectorised change-mask artifacts);
- `analysis_regions_geojson` (analysis and discovery footprints);
- layer definitions and basemap attribution.

The three standalone endpoints return the corresponding collections as
`application/geo+json`.

## Run it

### Backend

From `backend/`:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000/docs` for the generated API documentation.

### Frontend

From `frontend/`:

```powershell
npm install
npm run dev
```

The browser app is available at `http://localhost:5173`. The production build can
be produced with:

```powershell
npm run build
```

## Configuration

Copy `backend/.env.example` to `backend/.env` and add credentials only if you
have them. Anonymous discovery and the Planetary Computer raster path work
without credentials. Earthdata Login credentials are needed to download NISAR
and OPERA science rasters.

Important supported variables include:

```env
DATABASE_URL=sqlite:///D:/nasa finalist/backend/terratrace.db
EARTHDATA_USERNAME=
EARTHDATA_PASSWORD=
EARTHDATA_TOKEN=
COPERNICUS_CLIENT_ID=
COPERNICUS_CLIENT_SECRET=
```

## Example request

```powershell
$body = @{
  bbox = @(85.2, 27.55, 85.5, 27.75)
  start = "2024-01-01"
  end = "2024-12-31"
  label = "Kathmandu live check"
  source_preference = @("planetary_computer")
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/analysis" `
  -Body $body -ContentType "application/json"
```

Poll:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/analysis/<job_id>"
```

## Useful endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Service, database, source, and inventory status |
| `GET /api/observations` | Catalogue search across configured connectors |
| `POST /api/analysis` | Start a multi-agent analysis |
| `GET /api/analysis/{job_id}` | Poll job progress and logs |
| `GET /api/agents` | Twelve-agent catalogue |
| `GET /api/findings` | Published findings |
| `GET /api/findings/{id}` | Finding plus evidence and source observations |
| `GET /api/findings/{id}/export.geojson` | Finding GeoJSON export |
| `GET /api/findings/{id}/report` | Standalone HTML evidence report |
| `GET /api/map-layers` | Complete API-driven map response |
| `GET /api/datasets` | Dataset registry and access status |
| `GET /api/models` | Model registry |
| `POST /api/discovery/run` | Metadata-only discovery sweep |
| `GET /api/jobs/{job_id}/assets/{name}` | Derived PNG/GeoJSON artifacts |

## Tests

Backend tests do not depend on the live internet. They use a temporary SQLite
database and controlled numeric fixtures.

```powershell
cd backend
python -m pytest -q
```

The frontend production build is checked with:

```powershell
cd frontend
npm run build
```

## Data and honesty rules

- The system does not substitute synthetic data when a real product is
  unavailable.
- Metadata-only products are labelled as such.
- Products that require credentials are labelled `requires_credentials`.
- GRD products without embedded georeferencing are used for discovery, not for
  direct geospatial raster analysis.
- Agent confidence is always described as a heuristic score, not a probability.
- Every activation and skip decision carries a machine-readable reason code.

## Project structure

```text
backend/
  app/
    agents/              Twelve specialist agents
    api/                 REST routers and serialisation
    change_detection/    Log-ratio, segmentation, unsupervised change
    config.py            Application settings
    core/                Logging, errors, geo utilities, caching
    database/            SQLAlchemy models and seeding
    data_sources/        CMR, Planetary Computer, Earth Search, Copernicus
    inference/           Checkpoint loading
    orchestrator/        Central seven-stage pipeline
    preprocessing/       Raster IO, quality checks, rendering
    reports/             Finding reports and GeoJSON export
    training/            Dataset registry, metrics, training pipeline
    validation/          Evidence validation
    workers/             Background job runner
  tests/
frontend/
  src/
    components/          Map, chart, layout, and shared UI
    pages/               Overview, map, analysis, agents, findings, data
    services/            API client and data hooks
    types/               TypeScript mirror of the API contract
docs/
  API_CONTRACT.md        Authoritative API contract
```
