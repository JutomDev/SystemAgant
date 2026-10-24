"""Integration tests for Tactile Dashboard API endpoints."""

from fastapi.testclient import TestClient

from web.server import _session, app

client = TestClient(app)


def test_serve_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "SYSTEM_AGANT" in response.text
    assert "AUTONOMOUS SOFTWARE HOUSE" in response.text


def test_api_state():
    response = client.get("/api/state")
    assert response.status_code == 200
    data = response.json()
    assert "mode" in data
    assert "active_node" in data
    assert "chat_messages" in data
    assert "progress_percent" in data


def test_api_chat_flow():
    # Force simulation mode for deterministic test execution
    _session.config.mode = "simulation"
    _session.session_key = None
    _session.reset()
    _session.config.mode = "simulation"
    _session.session_key = None

    # 1. User prompts for website
    res = client.post("/api/chat", json={"message": "Build botanical store for Kwiaciarnia-Mex Toruń"})
    assert res.status_code == 200
    data = res.json()
    assert data["awaiting_hitl"] is True
    assert len(data["wbs"]) > 0

    # 2. User approves (APPROVE / ZATWIERDZAM)
    approve_res = client.post("/api/chat", json={"message": "APPROVE"})
    assert approve_res.status_code == 200
    approve_data = approve_res.json()
    assert approve_data["current_phase"] == "COMPLETED"
    assert len(approve_data["files"]) >= 2

    # 3. Preview returns generated index.html
    prev_res = client.get("/api/workspace/preview")
    assert prev_res.status_code == 200
    assert len(prev_res.text) > 0


def test_api_reset():
    reset_res = client.post("/api/reset")
    assert reset_res.status_code == 200
    reset_data = reset_res.json()
    assert reset_data["current_phase"] == "BRAINSTORMING"
