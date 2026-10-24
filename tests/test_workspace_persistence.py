"""Integration tests for Workspace Persistence, Resumption, and Post-Completion Iteration."""

from pathlib import Path
from fastapi.testclient import TestClient
from web.server import app, _session

client = TestClient(app)


def test_workspace_listing_and_new():
    # 1. Create a clean new workspace
    res = client.post("/api/workspace/new", json={"project_name": "test_store"})
    assert res.status_code == 200
    data = res.json()
    assert data["project_name"] == "test_store"
    assert data["current_phase"] == "BRAINSTORMING"

    # 2. List workspaces
    ws_res = client.get("/api/workspaces")
    assert ws_res.status_code == 200
    ws_data = ws_res.json()
    names = [w["name"] for w in ws_data["workspaces"]]
    assert "test_store" in names
    assert ws_data["active_workspace"] == "test_store"


def test_workspace_persistence_and_resume():
    # 1. Force simulation mode
    _session.config.mode = "simulation"
    _session.session_key = None

    # 2. Start project and complete it
    client.post("/api/workspace/new", json={"project_name": "resume_demo"})
    chat_res = client.post("/api/chat", json={"message": "Build arcade game", "project_name": "resume_demo"})
    assert chat_res.status_code == 200
    assert chat_res.json()["awaiting_hitl"] is True

    approve_res = client.post("/api/chat", json={"message": "APPROVE"})
    assert approve_res.status_code == 200
    assert approve_res.json()["current_phase"] == "COMPLETED"

    # Verify session file was persisted to disk
    session_file = _session.workspace_path / ".systemagant" / "session.json"
    assert session_file.is_file()

    # 3. Switch to another workspace
    client.post("/api/workspace/new", json={"project_name": "other_demo"})
    assert _session.project_name == "other_demo"

    # 4. Resume the previous workspace without losing files or state
    load_res = client.post("/api/workspace/load", json={"project_name": "resume_demo"})
    assert load_res.status_code == 200
    load_data = load_res.json()
    assert load_data["project_name"] == "resume_demo"
    assert load_data["current_phase"] == "COMPLETED"
    assert len(load_data["files"]) >= 2

    # 5. Continuous Development (Phase 3 - Iteration on completed project)
    extend_res = client.post("/api/chat", json={"message": "Add a high score leaderboard section"})
    assert extend_res.status_code == 200
    extend_data = extend_res.json()
    assert extend_data["current_phase"] == "APPROVAL"
    assert extend_data["awaiting_hitl"] is True
    # Verify WBS now has an additional epic
    assert len(extend_data["wbs"]) >= 2
