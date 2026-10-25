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
    _session.reset(project_name="test_chat_flow_ws")
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
    reset_res = client.post("/api/reset", json={"project_name": "test_reset_sandbox"})
    assert reset_res.status_code == 200
    reset_data = reset_res.json()
    assert reset_data["current_phase"] == "BRAINSTORMING"


def test_preview_nested_and_static_assets():
    _session.config.mode = "simulation"
    _session.session_key = None
    _session.reset(project_name="test_routing_shop")

    # Manually create mock html and css in the workspace
    html_file = _session.workspace_path / "index.html"
    catalog_file = _session.workspace_path / "catalog.html"
    css_file = _session.workspace_path / "style.css"

    html_file.write_text(
        "<!DOCTYPE html><html><head><title>Test</title></head><body><h1>Home</h1><a href='catalog.html'>Catalog</a></body></html>",
        encoding="utf-8",
    )
    catalog_file.write_text(
        "<!DOCTYPE html><html><head><title>Catalog</title></head><body><h1>Catalog</h1></body></html>", encoding="utf-8"
    )
    css_file.write_text("body { background: #fff; }", encoding="utf-8")

    # 1. Preview index.html and verify <base> tag injection
    res_index = client.get("/api/workspace/preview/index.html")
    assert res_index.status_code == 200
    assert '<base href="/api/workspace/preview/">' in res_index.text

    # 2. Preview nested catalog.html
    res_catalog = client.get("/api/workspace/preview/catalog.html")
    assert res_catalog.status_code == 200
    assert "<h1>Catalog</h1>" in res_catalog.text

    # 3. Request CSS via preview nested path
    res_css_nested = client.get("/api/workspace/preview/style.css")
    assert res_css_nested.status_code == 200
    assert "text/css" in res_css_nested.headers.get("content-type", "")
    assert "background: #fff" in res_css_nested.text

    # 4. Request CSS via direct fallback router /api/workspace/style.css
    res_css_direct = client.get("/api/workspace/style.css")
    assert res_css_direct.status_code == 200
    assert "text/css" in res_css_direct.headers.get("content-type", "")

    # 5. Request catalog.html via direct fallback router /api/workspace/catalog.html
    res_cat_direct = client.get("/api/workspace/catalog.html")
    assert res_cat_direct.status_code == 200
    assert "<h1>Catalog</h1>" in res_cat_direct.text


def test_api_chat_async_execution():
    _session.config.mode = "simulation"
    _session.session_key = None
    _session.reset(project_name="test_async_exec")

    # Plan
    client.post("/api/chat", json={"message": "Build app"})
    # Approve with async_execution
    res = client.post("/api/chat", json={"message": "APPROVE", "async_execution": True})
    assert res.status_code == 200
    data = res.json()
    assert data["current_phase"] in ["EXECUTION", "COMPLETED"]
    assert "is_busy" in data


def test_non_destructive_editing_and_node_transitions():
    """Verifies that executing a follow-up task on an existing file preserves pre-existing code."""
    _session.config.mode = "simulation"
    _session.session_key = None
    _session.reset(project_name="test_preserve_existing")

    # Create an initial rich index.html
    html_file = _session.workspace_path / "index.html"
    initial_content = (
        "<!DOCTYPE html><html><head><title>Botanica</title></head>"
        "<body><header><h1>Botanica Studio</h1></header>"
        "<main><section class='hero'>Hero Content</section></main>"
        "<footer>Footer Links</footer></body></html>"
    )
    html_file.write_text(initial_content, encoding="utf-8")

    # Set up completed state with discovered files
    _session.load_state_from_disk()
    assert _session.current_phase == "completed"

    # User gives an incremental task modifying index.html
    plan_res = client.post("/api/chat", json={"message": "Add a newsletter form to index.html"})
    assert plan_res.status_code == 200
    assert plan_res.json()["awaiting_hitl"] is True

    # Execute approval
    approve_res = client.post("/api/chat", json={"message": "APPROVE"})
    assert approve_res.status_code == 200

    # Verify that index.html STILL has the original sections (NOT wiped out with a dummy stub)
    updated_content = html_file.read_text(encoding="utf-8")
    assert "Botanica Studio" in updated_content
    assert "Hero Content" in updated_content
    assert "Footer Links" in updated_content


def test_natural_language_approval_and_async_planning():
    """Verifies that natural language Polish approval sentences and async planning work seamlessly."""
    _session.config.mode = "simulation"
    _session.session_key = None
    _session.reset(project_name="test_nl_approval_ws")

    # 1. Async planning in brainstorming
    plan_res = client.post(
        "/api/chat",
        json={"message": "Build modern website for flower store", "async_execution": True},
    )
    assert plan_res.status_code == 200
    data = plan_res.json()
    assert "is_busy" in data
    assert data["active_node"] in ["ARCHITECT", "HUMAN_APPROVAL"]
    assert data["current_phase"] in ["BRAINSTORMING", "APPROVAL"]

    # Wait briefly or run synchronously for approval test
    _session.reset(project_name="test_nl_approval_sync")
    client.post("/api/chat", json={"message": "Build website"})
    assert _session.current_phase == "approval"

    # 2. Natural language approval with Polish typos and extra text
    nl_approval = "tak zatwiedzam wykonuj go krokami zrob zrobic liste zadan i testuj to"
    approve_res = client.post("/api/chat", json={"message": nl_approval, "async_execution": False})
    assert approve_res.status_code == 200
    approve_data = approve_res.json()
    assert approve_data["current_phase"] == "COMPLETED"
    assert len(approve_data["files"]) >= 1
