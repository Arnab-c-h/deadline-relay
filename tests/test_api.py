from fastapi.testclient import TestClient

from relay.main import create_app


def test_browser_journey_requires_alternative_and_explicit_approval(tmp_path):
    with TestClient(create_app(tmp_path, mode="simulated")) as client:
        assert client.get("/api/projects/demo/health").json()["mode"] == "simulated"
        snapshot = client.post("/api/projects/demo/snapshots", json={}).json()
        plan = client.post("/api/projects/demo/plans", json={"snapshot_id": snapshot["id"],
            "request": "Move delivery to September 18, 2026"}).json()
        assert plan["status"] == "infeasible"
        assert client.post(f"/api/plans/{plan['id']}/approve", json={"version": 1,
            "hash": plan["hash"], "idempotency_key": "invalid-plan"}).status_code == 409
        alternative = client.post("/api/projects/demo/plans", json={"snapshot_id": snapshot["id"],
            "request": plan["request"], "parent_plan_id": plan["id"], "alternative_date": plan["proposed_date"]}).json()
        assert alternative["status"] == "ready"
        approved = client.post(f"/api/plans/{alternative['id']}/approve", json={"version": alternative["version"],
            "hash": alternative["hash"], "idempotency_key": "approved-once"})
        assert approved.status_code == 202
        run = client.get(f"/api/runs/{approved.json()['run_id']}").json()
        assert run["status"] == "VERIFIED", run


def test_external_browser_origin_cannot_mutate_local_app(tmp_path):
    with TestClient(create_app(tmp_path, mode="simulated")) as client:
        response = client.post("/api/projects/demo/snapshots", json={}, headers={"Origin": "https://evil.example"})
        assert response.status_code == 403


def test_live_mode_health_exposes_missing_setup_without_simulator(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_CONFIG_PATH", str(tmp_path / "missing.json"))
    with TestClient(create_app(tmp_path, mode="live")) as client:
        health = client.get("/api/projects/demo/health").json()
        assert health["mode"] == "live"
        assert all(connection["status"] == "missing" for connection in health["connections"])
        assert client.post("/api/projects/demo/snapshots", json={}).status_code == 503


def test_unexpected_approval_fields_are_rejected(tmp_path):
    with TestClient(create_app(tmp_path, mode="simulated")) as client:
        response = client.post("/api/plans/no-plan/approve", json={"version": 1, "hash": "x",
            "idempotency_key": "forged", "operations": [{"delete": "everything"}]})
        assert response.status_code == 422
