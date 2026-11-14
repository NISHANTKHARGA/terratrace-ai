"""API contract tests: shapes, honest statuses and machine-readable errors."""
from __future__ import annotations


def assert_error_body(payload, code):
    assert "error" in payload
    assert payload["error"]["code"] == code
    assert payload["error"]["message"]


def test_health_has_the_documented_shape(client):
    r = client.get("/api/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert body["database"] == "ok"
    assert body["version"]
    assert body["counts"]["agents"] == 12
    assert {s["id"] for s in body["sources"]} >= {"nasa_cmr", "earthdata_login"}
    earthdata = next(s for s in body["sources"] if s["id"] == "earthdata_login")
    assert earthdata["status"] == "requires_credentials"


def test_agents_list_and_detail(client):
    r = client.get("/api/agents")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 12
    assert [a["id"] for a in items] == [
        "flood", "wetlands", "forest", "wildfire", "deformation", "glacier",
        "landslide", "agriculture", "urban", "mining", "coastal", "unknown_change",
    ]
    flood = items[0]
    assert flood["ordinal"] == 1
    assert flood["status"] == "operational"
    assert flood["status_reason"]
    assert flood["baseline_method"]

    detail = client.get("/api/agents/flood")
    assert detail.status_code == 200
    d = detail.json()
    assert d["config"]["hard_ceiling_db"] == -9.0
    assert d["output_schema"]
    assert d["known_limitations"]

    missing = client.get("/api/agents/nope")
    assert missing.status_code == 404
    assert_error_body(missing.json(), "not_found")


def test_sources_list_reports_credentials_honestly(client):
    r = client.get("/api/sources")
    assert r.status_code == 200, r.text
    statuses = {s["id"]: s for s in r.json()["items"]}
    assert statuses["earthdata_login"]["status"] == "requires_credentials"
    assert statuses["earthdata_login"]["auth_required"] is True


def test_observations_list_uses_real_connector_target(client, offline_discovery):
    r = client.get(
        "/api/observations",
        params={
            "bbox": "85.2,27.55,85.5,27.75",
            "start": "2024-01-01",
            "end": "2024-12-31",
            "page_size": 5,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 5
    assert {o["mission"] for o in body["items"]} == {"SENTINEL-1", "NISAR"}
    nisar = next(o for o in body["items"] if o["mission"] == "NISAR")
    assert nisar["requires_credentials"] is True

    detail = client.get("/api/observations/obs_test_1")
    assert detail.status_code == 200, detail.text
    assert detail.json()["source"] == "planetary_computer"

    missing = client.get("/api/observations/unknown_id")
    assert missing.status_code == 404
    assert_error_body(missing.json(), "not_found")

    bad_bbox = client.get("/api/observations", params={"bbox": "bad"})
    assert bad_bbox.status_code == 422
    assert_error_body(bad_bbox.json(), "invalid_bbox")


def test_datasets_and_models_catalogues_are_honest(client):
    r = client.get("/api/datasets")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) >= 12
    by_id = {d["id"]: d for d in items}
    assert by_id["nasa_firms"]["status"] == "not_configured"
    # every baseline model states its limitations and never fabricates metrics
    assert by_id["sentinel1_rtc_planetary_computer"]["status"] == "available"

    models = client.get("/api/models")
    assert models.status_code == 200, models.text
    model_items = models.json()["items"]
    assert len(model_items) == 12
    flood = next(m for m in model_items if m["id"] == "flood:baseline")
    assert flood["kind"] == "baseline_algorithm"
    assert flood["status"] == "active"
    assert flood["limitations"]
    assert all(m["value"] is None for m in flood["metrics"]), (
        "unmeasured metrics must stay null, not be filled with estimates"
    )

    one = client.get("/api/models/flood:baseline")
    assert one.status_code == 200
    assert one.json()["agent_id"] == "flood"


def test_findings_map_and_history_shapes(client):
    findings = client.get("/api/findings")
    assert findings.status_code == 200, findings.text
    fbody = findings.json()
    assert {"items", "page", "page_size", "total"} <= set(fbody)
    assert fbody["page"] == 1

    layers = client.get("/api/map-layers")
    assert layers.status_code == 200, layers.text
    body = layers.json()
    assert {l["id"] for l in body["layers"]} == {
        "findings", "observation_footprints", "change_polygons", "analysis_regions"
    }
    assert body["findings_geojson"]["type"] == "FeatureCollection"
    assert body["observations_geojson"]["type"] == "FeatureCollection"
    assert body["change_polygons_geojson"]["type"] == "FeatureCollection"
    assert body["analysis_regions_geojson"]["type"] == "FeatureCollection"

    for endpoint in (
        "/api/map-layers/change.geojson",
        "/api/map-layers/analysis.geojson",
    ):
        geo = client.get(endpoint)
        assert geo.status_code == 200
        assert geo.headers["content-type"].startswith("application/geo+json")
    assert "©" in body["basemap_attribution"]

    geo = client.get("/api/map-layers/findings.geojson")
    assert geo.status_code == 200
    assert geo.headers["content-type"].startswith("application/geo+json")

    history = client.get("/api/history")
    assert history.status_code == 200
    assert {"items", "page", "page_size", "total"} <= set(history.json())


def test_finding_detail_and_assets_are_not_fabricated(client):
    missing = client.get("/api/findings/nope")
    assert missing.status_code == 404
    assert_error_body(missing.json(), "not_found")

    missing_evidence = client.get("/api/findings/nope/evidence")
    assert missing_evidence.status_code == 404

    missing_asset = client.get("/api/jobs/nope/assets/before.png")
    assert missing_asset.status_code == 404

    bad_asset = client.get("/api/jobs/nope/assets/../../terratrace.db")
    # path traversal is rejected; the route normalises to a 404/422 rather than a file
    assert bad_asset.status_code in (404, 422)


def test_analysis_validation_errors_are_machine_readable(client):
    no_region = client.post(
        "/api/analysis", json={"start": "2024-01-01", "end": "2024-12-31"}
    )
    assert no_region.status_code == 422, no_region.text
    assert_error_body(no_region.json(), "missing_region")

    wrong_period = client.post(
        "/api/analysis",
        json={
            "bbox": [85.2, 27.55, 85.5, 27.75],
            "start": "2024-12-31",
            "end": "2024-01-01",
        },
    )
    assert wrong_period.status_code == 422
    assert_error_body(wrong_period.json(), "invalid_period")

    missing = client.get("/api/analysis/nope")
    assert missing.status_code == 404

    cancel = client.post("/api/analysis/nope/cancel")
    assert cancel.status_code == 404


def test_unknown_api_routes_use_the_documented_error_shape(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert_error_body(r.json(), "not_found")


def test_training_endpoints_work_offline(client):
    runs = client.get("/api/training/runs")
    assert runs.status_code == 200, runs.text
    assert "items" in runs.json()

    missing_agent = client.post("/api/training/runs", json={"agent_id": "nope"})
    assert missing_agent.status_code == 404
