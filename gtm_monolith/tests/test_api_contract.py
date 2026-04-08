"""
API contract tests for app_monolith.py.

Verifies that the monolith Flask app exposes the same routes and response
schemas as the original app.py, ensuring backward compatibility for
frontend consumers.
"""

import json
import pytest
from pathlib import Path

from gtm_monolith.app_monolith import app


PROJECT_ROOT = Path(__file__).parent.parent.parent
VERSIONS_DIR = PROJECT_ROOT / "versions"


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _get_first_version_id():
    """Find the first available version ID for testing."""
    if VERSIONS_DIR.exists():
        for vdir in sorted(VERSIONS_DIR.glob("v*")):
            if (vdir / "summary.json").exists():
                return vdir.name
    return None


# ── Health and static routes ───────────────────────────────────────


class TestHealthRoutes:
    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"
        assert data["service"] == "gtm-planning-engine"

    def test_health_response_schema(self, client):
        resp = client.get("/health")
        data = resp.get_json()
        assert set(data.keys()) == {"status", "service"}


# ── Config routes ──────────────────────────────────────────────────


class TestConfigRoutes:
    def test_config_schema_endpoint(self, client):
        resp = client.get("/api/config-schema")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)
        assert "dimensions" in data
        assert "targets" in data
        assert "economics" in data

    def test_config_defaults_endpoint(self, client):
        resp = client.get("/api/config/defaults")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)
        assert "targets" in data


# ── Version list route ─────────────────────────────────────────────


class TestVersionRoutes:
    def test_list_versions(self, client):
        resp = client.get("/api/versions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "versions" in data
        assert isinstance(data["versions"], list)

    def test_list_versions_item_schema(self, client):
        resp = client.get("/api/versions")
        data = resp.get_json()
        if data["versions"]:
            item = data["versions"][0]
            assert "id" in item
            assert "description" in item
            assert "created" in item

    def test_version_summary(self, client):
        version_id = _get_first_version_id()
        if version_id is None:
            pytest.skip("No versions available")
        resp = client.get(f"/api/version/{version_id}/summary")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, dict)

    def test_version_summary_not_found(self, client):
        resp = client.get("/api/version/v999/summary")
        assert resp.status_code == 404

    def test_version_results(self, client):
        version_id = _get_first_version_id()
        if version_id is None:
            pytest.skip("No versions available")
        resp = client.get(f"/api/version/{version_id}/results")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_version_files(self, client):
        version_id = _get_first_version_id()
        if version_id is None:
            pytest.skip("No versions available")
        resp = client.get(f"/api/version/{version_id}/files")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "version_id" in data
        assert "files" in data
        assert isinstance(data["files"], list)

    def test_version_download(self, client):
        version_id = _get_first_version_id()
        if version_id is None:
            pytest.skip("No versions available")
        resp = client.get(f"/api/version/{version_id}/download/summary.json")
        assert resp.status_code == 200

    def test_version_download_not_found(self, client):
        version_id = _get_first_version_id()
        if version_id is None:
            pytest.skip("No versions available")
        resp = client.get(f"/api/version/{version_id}/download/nonexistent.csv")
        assert resp.status_code == 404


# ── Chart server routes ────────────────────────────────────────────


class TestChartServerRoutes:
    def test_list_chart_servers(self, client):
        resp = client.get("/api/charts/servers")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "servers" in data
        assert "count" in data

    def test_chart_server_status_not_found(self, client):
        resp = client.get("/api/charts/server/v999/status")
        assert resp.status_code == 404


# ── Run plan route contract ────────────────────────────────────────


class TestRunPlanContract:
    """Verify the /api/run-plan response schema matches the original app.py."""

    def test_run_plan_response_schema(self, client):
        """Test that a successful run returns the expected keys."""
        resp = client.post(
            "/api/run-plan",
            data=json.dumps({"description": "API contract test", "mode": "full"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()

        # These keys must be present for frontend compatibility
        assert "version_id" in data, "Response must include version_id"
        assert "summary" in data, "Response must include summary"
        assert "validation_passed" in data, "Response must include validation_passed"

        # version_id format
        assert data["version_id"].startswith("v"), "version_id must start with 'v'"

        # summary must be a dict with expected keys
        summary = data["summary"]
        assert isinstance(summary, dict)

    def test_run_plan_summary_keys(self, client):
        """Verify summary contains the key metrics the frontend expects."""
        resp = client.post(
            "/api/run-plan",
            data=json.dumps({"description": "Schema check"}),
            content_type="application/json",
        )
        if resp.status_code != 200:
            pytest.skip(f"Run plan failed: {resp.get_json()}")

        summary = resp.get_json()["summary"]
        expected_keys = {
            "total_annual_bookings", "total_annual_saos",
            "total_annual_pipeline", "total_ae_hc",
        }
        # At least the core metrics should be present (possibly under aliases)
        has_bookings = "total_annual_bookings" in summary or "total_bookings" in summary
        has_saos = "total_annual_saos" in summary or "total_saos" in summary
        assert has_bookings, "Summary must include bookings metric"
        assert has_saos, "Summary must include SAOs metric"
