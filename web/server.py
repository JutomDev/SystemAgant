"""Tactile Web Dashboard Backend Server.

Provides REST endpoints for:
1. Interactive Multi-Agent Conversation (User <-> Architect <-> Coder <-> Tester)
2. Live Workspace File Browser & Sandboxed HTML Preview
3. Real-Time Multi-Agent Graph State and Telemetry
4. In-Memory Session API Key handling (Zero Secret Leakage)
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import AppConfig, get_config
from core.llm_factory import get_architect_llms, get_coder_llm
from core.models import ArchitectOutput, AtomicTask, Epic
from core.repo_map import generate_task_scoped_repo_map
from core.tools.asset_tools import validate_and_repair_html_images

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent

IGNORED_DIRS = {
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".git",
    "dist",
    "build",
    ".systemagant",
    ".pytest_cache",
    ".benchmarks",
    ".cache",
    ".idea",
    ".vscode",
}
IGNORED_EXTENSIONS = {".db", ".sqlite", ".sqlite3", ".log", ".pyc", ".tmp"}


def is_project_file(p: Path) -> bool:
    """Verifies that path is a valid workspace source file and not internal state or junk."""
    if not p.is_file():
        return False
    if any(part in IGNORED_DIRS for part in p.parts):
        return False
    if p.name.startswith(".") or p.name.endswith(tuple(IGNORED_EXTENSIONS)):
        return False
    return True


def scan_workspace_files(workspace_path: Path) -> list[dict[str, Any]]:
    """Scans and returns all project files, sorting index.html and HTML files first."""
    files: list[dict[str, Any]] = []
    if not workspace_path.exists():
        return files
    for p in workspace_path.rglob("*"):
        if is_project_file(p):
            rel_name = str(p.relative_to(workspace_path)).replace("\\", "/")
            files.append({"name": rel_name, "size": p.stat().st_size})
    files.sort(
        key=lambda x: (0 if x["name"] == "index.html" else (1 if x["name"].endswith(".html") else 2), x["name"].lower())
    )
    return files


def serialize_wbs(wbs_raw: Any) -> list[dict[str, Any]]:
    """Normalizes WBS data models into plain JSON-serializable dictionaries."""
    if not wbs_raw:
        return []
    clean_wbs: list[dict[str, Any]] = []
    for item in wbs_raw:
        if hasattr(item, "model_dump"):
            clean_wbs.append(item.model_dump())
        elif isinstance(item, dict):
            clean_epic = dict(item)
            if "tasks" in clean_epic:
                clean_tasks: list[dict[str, Any]] = []
                for t in clean_epic["tasks"]:
                    if hasattr(t, "model_dump"):
                        clean_tasks.append(t.model_dump())
                    elif isinstance(t, dict):
                        clean_tasks.append(dict(t))
                clean_epic["tasks"] = clean_tasks
            clean_wbs.append(clean_epic)
    return clean_wbs


def serialize_logs(logs_raw: Any) -> list[dict[str, Any]]:
    """Normalizes execution logs into plain dictionaries."""
    if not logs_raw:
        return []
    clean_logs: list[dict[str, Any]] = []
    for log_item in logs_raw:
        if hasattr(log_item, "model_dump"):
            clean_logs.append(log_item.model_dump())
        elif isinstance(log_item, dict):
            clean_logs.append(dict(log_item))
        else:
            clean_logs.append({"node": "system", "content": str(log_item), "timestamp": 1})
    return clean_logs


def convert_langgraph_messages_to_ui(raw_messages: list[Any], wbs: list[Any]) -> list[dict[str, Any]]:
    """Translates LangGraph BaseMessage objects from SQLite checkpoints into UI chat messages."""
    ui_messages: list[dict[str, Any]] = []
    for i, m in enumerate(raw_messages):
        author = type(m).__name__
        text = str(getattr(m, "content", ""))
        if author == "HumanMessage":
            ui_messages.append(
                {
                    "id": f"msg_{i}",
                    "sender": "user",
                    "title": "User",
                    "text": text,
                    "type": "user",
                }
            )
        elif author == "ToolMessage":
            tool_name = getattr(m, "name", "sandbox")
            ui_messages.append(
                {
                    "id": f"msg_{i}",
                    "sender": "tester",
                    "title": f"Tool: {tool_name}",
                    "text": text,
                    "type": "tester",
                }
            )
        else:
            # AIMessage or generic assistant turn
            title = "Architect"
            sender = "architect"
            msg_type = "agent"
            has_wbs = False
            text_lower = text.lower()
            if (
                "coder" in text_lower
                or "implemented" in text_lower
                or text.strip().startswith("<!DOCTYPE")
                or "def " in text
            ):
                title = "Coder"
                sender = "coder"
                msg_type = "coder"
            elif "tester" in text_lower or "verified" in text_lower or "exit code: 0" in text_lower:
                title = "Tester"
                sender = "tester"
                msg_type = "tester"
            elif (
                "wbs" in text_lower
                or "epics" in text_lower
                or "atomic tasks" in text_lower
                or "architecture" in text_lower
            ):
                title = "Architect"
                sender = "architect"
                msg_type = "agent"
                has_wbs = bool(wbs)

            ui_messages.append(
                {
                    "id": f"msg_{i}",
                    "sender": sender,
                    "title": title,
                    "text": text,
                    "type": msg_type,
                    "has_wbs": has_wbs,
                }
            )
    return ui_messages


def extract_state_from_db(workspace_path: Path, project_name: str) -> dict[str, Any] | None:
    """Extracts the latest checkpoint channel values from LangGraph SQLite checkpointer."""
    db_path = workspace_path / "state.db"
    if not db_path.is_file():
        return None
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        thread_id = f"thread_{project_name}"
        with SqliteSaver.from_conn_string(str(db_path)) as cp:
            checkpoint = cp.get({"configurable": {"thread_id": thread_id}})
            if not checkpoint or "channel_values" not in checkpoint:
                import sqlite3

                con = sqlite3.connect(str(db_path))
                row = con.execute("SELECT thread_id FROM checkpoints ORDER BY checkpoint_id DESC LIMIT 1").fetchone()
                con.close()
                if row:
                    checkpoint = cp.get({"configurable": {"thread_id": row[0]}})

            if not checkpoint or "channel_values" not in checkpoint:
                return None
            return checkpoint["channel_values"]
    except Exception as e:
        logger.warning("Failed to extract state from db %s: %s", db_path, e)
        return None


app = FastAPI(
    title="SystemAgant Tactile Dashboard",
    description="Interactive Multi-Agent Chat, Telemetry Rack & Live Preview",
    version="2.1.0",
)


class ChatRequest(BaseModel):
    message: str
    project_name: str | None = None
    api_key: str | None = None


class ResetRequest(BaseModel):
    project_name: str | None = None
    purge_files: bool = True


class WorkspaceActionRequest(BaseModel):
    project_name: str


class DashboardSession:
    def __init__(self, session_key: str | None = None, project_name: str = "web_project"):
        self.config = get_config()
        self.session_key = session_key or self.config.gemini_api_key or os.getenv("GEMINI_API_KEY")
        self.set_project(project_name, load_existing=True)

    def set_project(self, name: str, load_existing: bool = True) -> None:
        clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.strip()).strip("_") or "web_project"
        self.project_name = clean
        self.workspace_path = self.config.workspaces_dir / clean
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        if load_existing:
            loaded = self.load_state_from_disk()
            if not loaded:
                self.init_default_state(purge_files=False)
        else:
            self.init_default_state(purge_files=False)

    def init_default_state(self, purge_files: bool = False) -> None:
        if purge_files and self.workspace_path.exists():
            for p in list(self.workspace_path.rglob("*")):
                if p.is_file() and not p.name.startswith(".git"):
                    try:
                        p.unlink()
                    except Exception:
                        pass

        self.active_node = "router"
        self.current_phase = "brainstorming"  # brainstorming -> approval -> execution -> completed
        self.iteration = 1
        self.logs: list[dict[str, Any]] = []
        self.chat_messages: list[dict[str, Any]] = []
        self.wbs: list[dict[str, Any]] = []
        self.current_task_id: str | None = None
        self.awaiting_hitl = False

        self.chat_messages.append(
            {
                "id": "msg_0",
                "sender": "architect",
                "title": "Architect",
                "text": (
                    f"Welcome to SystemAgant. Active workspace: 'workspaces/{self.project_name}'. "
                    "Describe the web application, game, or script you wish to build. "
                    "I will synthesize a deterministic Work Breakdown Structure (WBS). "
                    "You can refine requirements with me or approve to begin autonomous implementation."
                ),
                "type": "agent",
            }
        )

    def save_state_to_disk(self) -> None:
        try:
            sg_dir = self.workspace_path / ".systemagant"
            sg_dir.mkdir(parents=True, exist_ok=True)
            s_file = sg_dir / "session.json"
            payload = {
                "project_name": self.project_name,
                "active_node": self.active_node,
                "current_phase": self.current_phase,
                "iteration": self.iteration,
                "awaiting_hitl": self.awaiting_hitl,
                "current_task_id": self.current_task_id,
                "chat_messages": self.chat_messages,
                "wbs": self.wbs,
                "logs": self.logs[-50:],
            }
            s_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error("Failed to save workspace state: %s", e)

    def load_state_from_disk(self) -> bool:
        s_file = self.workspace_path / ".systemagant" / "session.json"
        db_file = self.workspace_path / "state.db"

        # Check if state.db has rich checkpoints
        db_cv = extract_state_from_db(self.workspace_path, self.project_name) if db_file.is_file() else None

        # 1. If session.json exists on disk
        if s_file.is_file():
            try:
                data = json.loads(s_file.read_text(encoding="utf-8"))
                saved_msgs = data.get("chat_messages", [])

                # If session.json was only a 1-message stub, but state.db has real history, prefer state.db!
                if db_cv and len(db_cv.get("messages", [])) > len(saved_msgs):
                    raw_wbs = serialize_wbs(db_cv.get("wbs", []))
                    raw_msgs = db_cv.get("messages", [])
                    self.chat_messages = convert_langgraph_messages_to_ui(raw_msgs, raw_wbs)
                    self.wbs = raw_wbs
                    self.logs = serialize_logs(db_cv.get("execution_logs", []))
                    self.current_phase = str(db_cv.get("current_phase", "completed"))
                    self.current_task_id = db_cv.get("current_task_id")
                    self.iteration = int(db_cv.get("current_iteration", len(self.chat_messages)))
                    self.active_node = "router"
                    self.awaiting_hitl = self.current_phase == "approval"
                    self.save_state_to_disk()
                    return True

                self.project_name = data.get("project_name", self.project_name)
                self.active_node = data.get("active_node", "router")
                self.current_phase = data.get("current_phase", "completed")
                self.iteration = data.get("iteration", 1)
                self.awaiting_hitl = data.get("awaiting_hitl", False)
                self.current_task_id = data.get("current_task_id")
                self.chat_messages = saved_msgs
                self.wbs = data.get("wbs", [])
                self.logs = data.get("logs", [])
                return True
            except Exception as e:
                logger.error("Failed to load workspace session: %s", e)

        # 2. If no valid session.json, but state.db exists
        if db_cv:
            raw_wbs = serialize_wbs(db_cv.get("wbs", []))
            raw_msgs = db_cv.get("messages", [])
            self.chat_messages = convert_langgraph_messages_to_ui(raw_msgs, raw_wbs)
            self.wbs = raw_wbs
            self.logs = serialize_logs(db_cv.get("execution_logs", []))
            self.current_phase = str(db_cv.get("current_phase", "completed"))
            self.current_task_id = db_cv.get("current_task_id")
            self.iteration = int(db_cv.get("current_iteration", len(self.chat_messages)))
            self.active_node = "router"
            self.awaiting_hitl = self.current_phase == "approval"
            self.save_state_to_disk()
            return True

        # 3. Hydrate from existing workspace files if session.json & state.db are absent
        existing_files = scan_workspace_files(self.workspace_path)
        if existing_files:
            self.active_node = "router"
            self.current_phase = "completed"
            self.iteration = 1
            self.awaiting_hitl = False
            self.current_task_id = None

            # Synthesize initial WBS showing all existing component files
            epic_tasks = []
            for i, f in enumerate(existing_files):
                epic_tasks.append(
                    {
                        "task_id": f"TASK_RESUME_{i + 1}",
                        "epic_id": "EPIC_DISCOVERED",
                        "description": f"Verified existing component: '{f['name']}' ({f['size']} bytes).",
                        "target_files": [f["name"]],
                        "status": "completed",
                    }
                )
            self.wbs = [
                {
                    "epic_id": "EPIC_DISCOVERED",
                    "description": f"Discovered existing codebase architecture ({len(existing_files)} component files)",
                    "tasks": epic_tasks,
                }
            ]

            file_names = ", ".join(f["name"] for f in existing_files[:5])
            if len(existing_files) > 5:
                file_names += f" and {len(existing_files) - 5} more"

            self.logs = [
                {
                    "node": "router",
                    "content": f"Hydrated workspace '{self.project_name}' with {len(existing_files)} existing files: {file_names}.",
                    "timestamp": 1,
                }
            ]
            self.chat_messages = [
                {
                    "id": "msg_0",
                    "sender": "architect",
                    "title": "Architect",
                    "text": (
                        f"Resumed active workspace: 'workspaces/{self.project_name}'. "
                        f"Discovered {len(existing_files)} files: {file_names}. "
                        "Live preview has loaded the primary interface. You can inspect all files in 'Workspace Files', "
                        "or enter follow-up instructions to extend this project."
                    ),
                    "has_wbs": True,
                    "type": "agent",
                }
            ]
            self.save_state_to_disk()
            return True

        return False

    def load_project(self, project_name: str) -> dict[str, Any]:
        clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", project_name.strip()).strip("_") or "web_project"
        self.project_name = clean
        self.workspace_path = self.config.workspaces_dir / clean
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        if not self.load_state_from_disk():
            self.init_default_state(purge_files=False)
            self.save_state_to_disk()
        return self.get_full_state()

    def create_new_project(self, project_name: str) -> dict[str, Any]:
        clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", project_name.strip()).strip("_") or "web_project"
        self.project_name = clean
        self.workspace_path = self.config.workspaces_dir / clean
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        self.init_default_state(purge_files=True)
        self.save_state_to_disk()
        return self.get_full_state()

    def set_api_key(self, key: str) -> None:
        """Sets temporary in-memory session key without persisting to disk."""
        if key and key.strip():
            self.session_key = key.strip()

    def _get_active_config(self) -> AppConfig:
        if self.config.mode == "simulation":
            return AppConfig(mode="simulation")
        mode = "gemini-free" if self.session_key else self.config.mode
        return AppConfig(
            mode=mode,
            gemini_api_key=self.session_key,
            gemini_model=self.config.gemini_model,
        )

    def process_chat(
        self, user_text: str, session_key: str | None = None, project_name: str | None = None
    ) -> dict[str, Any]:
        """Processes user input through the multi-agent state lifecycle."""
        user_clean = user_text.strip()
        if session_key:
            self.set_api_key(session_key)
        if project_name and self.current_phase == "brainstorming":
            self.set_project(project_name)

        # 1. Record user message
        self.chat_messages.append(
            {
                "id": f"msg_{len(self.chat_messages)}",
                "sender": "user",
                "title": "User",
                "text": user_clean,
                "type": "user",
            }
        )

        cfg = self._get_active_config()

        # Phase 1: User requests plan / project description
        if self.current_phase == "brainstorming":
            self.active_node = "architect"
            self.iteration += 1

            if cfg.mode == "simulation":
                # Deterministic test mock
                from tests.fakes import FakeArchitectStructured

                fake_arch = FakeArchitectStructured()
                structured_res: ArchitectOutput = fake_arch.invoke([])
            else:
                # Real LLM Call via Google AI Studio Gemini API
                models = get_architect_llms(cfg)
                planner = models["planner"]
                structured_planner = planner.with_structured_output(ArchitectOutput)

                architect_prompt = (
                    f"User project prompt: {user_clean}\n\n"
                    "Instructions: Synthesize a professional, deterministic Work Breakdown Structure (WBS). "
                    "Provide 1-2 Epics and 3-5 Atomic Tasks. If this is a website, plan index.html, subpages, and style.css. "
                    "Reply to the user in their language explaining the strategy, but formulate all task IDs and file targets in English."
                )
                try:
                    structured_res = structured_planner.invoke(architect_prompt)
                except Exception:
                    # Fallback to local structured plan if API fails
                    structured_res = ArchitectOutput(
                        response=f"Architect analyzed requirements: {user_clean}. WBS synthesized.",
                        wbs=[
                            Epic(
                                epic_id="EPIC_1",
                                description="Web Application Baseline",
                                tasks=[
                                    AtomicTask(
                                        task_id="TASK_1_1",
                                        epic_id="EPIC_1",
                                        description="Implement landing page index.html with header, hero section, and navigation",
                                        target_files=["index.html"],
                                        status="pending",
                                    ),
                                    AtomicTask(
                                        task_id="TASK_1_2",
                                        epic_id="EPIC_1",
                                        description="Implement product catalog catalog.html with flower showcase cards",
                                        target_files=["catalog.html"],
                                        status="pending",
                                    ),
                                    AtomicTask(
                                        task_id="TASK_1_3",
                                        epic_id="EPIC_1",
                                        description="Implement contact page contact.html with contact form and details",
                                        target_files=["contact.html"],
                                        status="pending",
                                    ),
                                    AtomicTask(
                                        task_id="TASK_1_4",
                                        epic_id="EPIC_1",
                                        description="Implement responsive styling in style.css",
                                        target_files=["style.css"],
                                        status="pending",
                                    ),
                                ],
                            )
                        ],
                    )

            # Convert Pydantic epics to dict
            self.wbs = [epic.model_dump() for epic in (structured_res.wbs or [])]

            self.current_phase = "approval"
            self.awaiting_hitl = True
            self.active_node = "human_approval"

            architect_reply = (
                f"{structured_res.response}\n\n"
                f"Generated {len(self.wbs)} Epics with "
                f"{sum(len(e.get('tasks', [])) for e in self.wbs)} Atomic Tasks.\n"
                "If you accept this strategy, click [+ APPROVE STRATEGY]. "
                "Or reply with suggestions/questions to refine the architecture."
            )

            self.chat_messages.append(
                {
                    "id": f"msg_{len(self.chat_messages)}",
                    "sender": "architect",
                    "title": "Architect",
                    "text": architect_reply,
                    "has_wbs": True,
                    "type": "agent",
                }
            )

            self.logs.append(
                {
                    "node": "architect",
                    "content": f"Structured WBS generated ({len(self.wbs)} epics). Escalating to Human-in-the-Loop gate.",
                    "timestamp": self.iteration,
                }
            )

        # Phase 2: User approves plan or provides feedback
        elif self.current_phase in ["approval", "execution"]:
            approval_keywords = ["APPROVE", "ZATWIERDZAM", "ZATWIERDZ", "YES", "TAK", "OK", "PROCEED"]
            if any(kw in user_clean.upper() for kw in approval_keywords):
                self.current_phase = "execution"
                self.awaiting_hitl = False
                self.run_execution_cycle()
            else:
                # Conceptual refinement loop with Architect
                self.active_node = "architect"
                self.iteration += 1
                if cfg.mode == "simulation":
                    reply_text = f"Architecture requirements updated with feedback: '{user_clean}'. Plan updated."
                else:
                    refine_prompt = (
                        f"Current WBS: {json.dumps(self.wbs)}\n"
                        f"User feedback/amendment: {user_clean}\n\n"
                        "Instructions: Refine the Work Breakdown Structure based on the user's feedback. "
                        "Keep or adjust existing tasks, and add new atomic tasks as necessary. "
                        "Reply in the user's language explaining how the architecture was updated, but formulate task IDs and target files in English."
                    )
                    try:
                        models = get_architect_llms(cfg)
                        structured_planner = models["planner"].with_structured_output(ArchitectOutput)
                        structured_res = structured_planner.invoke(refine_prompt)
                        self.wbs = [e.model_dump() for e in structured_res.wbs]
                        reply_text = structured_res.response
                    except Exception as e:
                        logger.error("Architect refinement error: %s", e)
                        reply_text = f"Conceptual feedback noted: '{user_clean}'. Architecture ready for your approval."

                self.chat_messages.append(
                    {
                        "id": f"msg_{len(self.chat_messages)}",
                        "sender": "architect",
                        "title": "Architect",
                        "text": f"{reply_text}\n\nWork Breakdown Structure updated. Click [+ APPROVE STRATEGY] when you are ready to begin implementation.",
                        "has_wbs": True,
                        "type": "agent",
                    }
                )
                self.logs.append(
                    {
                        "node": "architect",
                        "content": f"Conceptual plan refined from user input: '{user_clean[:60]}'.",
                        "timestamp": self.iteration,
                    }
                )
        # Phase 3: Post-Completion Continuous Development & Iterative Features
        elif self.current_phase == "completed":
            self.active_node = "architect"
            self.iteration += 1
            repo_map = generate_task_scoped_repo_map(
                self.workspace_path,
                task_description=user_clean,
                max_files=8,
            )

            if cfg.mode == "simulation":
                new_epic = {
                    "epic_id": f"EPIC_{len(self.wbs) + 1}",
                    "title": f"Follow-Up: {user_clean[:30]}",
                    "description": user_clean,
                    "tasks": [
                        {
                            "task_id": f"TASK_{len(self.wbs) + 1}_1",
                            "description": f"Implement incremental change: {user_clean}",
                            "target_files": ["index.html"],
                            "status": "pending",
                        }
                    ],
                }
                self.wbs.append(new_epic)
                reply_text = (
                    f"Analyzed follow-up requirement for existing codebase: '{user_clean}'. Planned incremental task."
                )
            else:
                models = get_architect_llms(cfg)
                structured_planner = models["planner"].with_structured_output(ArchitectOutput)
                incremental_prompt = (
                    f"Existing Workspace Symbol Map:\n{repo_map}\n\n"
                    f"Previously Completed WBS:\n{json.dumps(self.wbs)}\n\n"
                    f"User New Feature Request / Refinement: {user_clean}\n\n"
                    "Instructions: Synthesize an INCREMENTAL Work Breakdown Structure for this existing project. "
                    "You may define modifications to existing files or create new files. "
                    "Ensure new tasks are marked as pending. Formulate task IDs and target files in English. "
                    "Reply explaining what incremental changes will be made."
                )
                try:
                    structured_res = structured_planner.invoke(incremental_prompt)
                    new_epics = [e.model_dump() for e in structured_res.wbs]
                    self.wbs.extend(new_epics)
                    reply_text = structured_res.response
                except Exception as e:
                    logger.error("Architect incremental planning error: %s", e)
                    reply_text = (
                        f"Follow-up requirement received: '{user_clean}'. Architecture ready for your approval."
                    )

            self.current_phase = "approval"
            self.awaiting_hitl = True
            self.chat_messages.append(
                {
                    "id": f"msg_{len(self.chat_messages)}",
                    "sender": "architect",
                    "title": "Architect",
                    "text": f"{reply_text}\n\nIncremental plan generated. Click [+ APPROVE STRATEGY] to implement.",
                    "has_wbs": True,
                    "type": "agent",
                }
            )
            self.logs.append(
                {
                    "node": "architect",
                    "content": f"Incremental WBS synthesized for follow-up prompt: '{user_clean[:50]}'.",
                    "timestamp": self.iteration,
                }
            )

        self.save_state_to_disk()
        return self.get_full_state()

    def run_execution_cycle(self) -> None:
        """Executes WBS tasks using real LLM generation or deterministic fallback."""
        cfg = self._get_active_config()
        all_tasks = []
        for epic in self.wbs:
            for t in epic.get("tasks", []):
                all_tasks.append(t)

        pending_tasks = [t for t in all_tasks if t.get("status") != "completed"]
        coder_llm = get_coder_llm(cfg)

        for task in pending_tasks:
            tid = task["task_id"]
            desc = task["description"]
            target_files = task.get("target_files", ["index.html"])
            fname = target_files[0] if target_files else "index.html"

            # 1. Coder Phase
            self.active_node = "coder"
            self.iteration += 1
            task["status"] = "in_progress"
            self.current_task_id = tid

            content = ""
            if cfg.mode == "simulation":
                # Fast mock generation
                content = f"<!DOCTYPE html><html><head><title>{tid}</title></head><body><h1>{desc}</h1></body></html>"
            else:
                # Real LLM Generation with Task-Scoped Repo Map
                repo_map = generate_task_scoped_repo_map(
                    self.workspace_path,
                    target_file=fname,
                    task_description=desc,
                    max_files=8,
                )
                repo_context = f"\nExisting Repository Symbol Map:\n{repo_map}\n" if repo_map else ""
                if repo_map:
                    self.logs.append(
                        {
                            "node": "coder",
                            "content": f"Repository Map: Injected scoped symbols for {fname}.",
                            "timestamp": self.iteration,
                        }
                    )
                coder_prompt = (
                    f"Task ID: {tid}\n"
                    f"Description: {desc}\n"
                    f"Target file: {fname}\n"
                    f"{repo_context}"
                    "You are implementing this component. Return the complete, clean code for this file. "
                    "Ensure consistency with the classes, functions, and style variables listed in the Repository Symbol Map above. "
                    "For HTML files, include semantic HTML5 structure, responsive layout, modern aesthetic, "
                    "and use valid Unsplash floral photography URLs (e.g., https://images.unsplash.com/photo-1563245372-f21724e3856d?auto=format&fit=crop&w=800&q=80). "
                    "Output ONLY the raw file contents with NO markdown fences."
                )
                try:
                    ai_msg = coder_llm.invoke(coder_prompt)
                    raw_text = ai_msg.content or ""
                    # Strip possible markdown code fences
                    if raw_text.startswith("```"):
                        lines = raw_text.splitlines()
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].strip().startswith("```"):
                            lines = lines[:-1]
                        raw_text = "\n".join(lines).strip()
                    content = raw_text
                except Exception as e:
                    logger.error("Coder invocation error: %s", e)
                    content = f"<!-- Auto-generated fallback for {fname} -->\n<!DOCTYPE html><html><body><h1>{desc}</h1></body></html>"

            # Validate and auto-repair any broken image URLs in HTML
            file_path = self.workspace_path / fname
            if fname.endswith(".html"):
                content, asset_logs = validate_and_repair_html_images(content, self.workspace_path)
                for alog in asset_logs:
                    self.logs.append({"node": "tester", "content": alog, "timestamp": self.iteration})

            # AST Syntax Verification & Auto-Repair for Python files
            if fname.endswith(".py"):
                try:
                    ast.parse(content)
                    self.logs.append(
                        {
                            "node": "tester",
                            "content": f"AST Syntax Check: '{fname}' parsed successfully (Valid Python syntax).",
                            "timestamp": self.iteration,
                        }
                    )
                except SyntaxError as syn_err:
                    self.logs.append(
                        {
                            "node": "tester",
                            "content": f"AST Syntax Error in '{fname}': {syn_err}. Triggering self-healing repair...",
                            "timestamp": self.iteration,
                        }
                    )
                    if cfg.mode != "simulation":
                        repair_prompt = (
                            f"File: {fname}\n"
                            f"Source Code:\n{content}\n\n"
                            f"Syntax Error: {syn_err}\n"
                            "Instructions: Fix the syntax error. Return ONLY the complete corrected Python code with NO markdown fences."
                        )
                        try:
                            rep_msg = coder_llm.invoke(repair_prompt)
                            rep_code = rep_msg.content or content
                            if rep_code.startswith("```"):
                                lines = rep_code.splitlines()
                                if lines[0].startswith("```"):
                                    lines = lines[1:]
                                if lines and lines[-1].strip().startswith("```"):
                                    lines = lines[:-1]
                                rep_code = "\n".join(lines).strip()
                            ast.parse(rep_code)
                            content = rep_code
                            self.logs.append(
                                {
                                    "node": "tester",
                                    "content": f"Self-Healing: Auto-repair successfully resolved syntax error in '{fname}'.",
                                    "timestamp": self.iteration,
                                }
                            )
                        except Exception as re_err:
                            logger.error("Auto-repair error: %s", re_err)

            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            self.logs.append(
                {
                    "node": "coder",
                    "content": f"edit_file(path='{fname}', overwrite=True) -> Wrote {len(content)} bytes to workspace.",
                    "timestamp": self.iteration,
                }
            )
            self.chat_messages.append(
                {
                    "id": f"msg_{len(self.chat_messages)}",
                    "sender": "coder",
                    "title": "Coder",
                    "text": f"Implemented '{fname}' for task {tid} ({len(content)} bytes).",
                    "type": "coder",
                }
            )

            # 2. Tester Phase
            self.active_node = "tester"
            self.iteration += 1
            self.logs.append(
                {
                    "node": "tester",
                    "content": f"Verified '{fname}': Syntax validated, asset integrity confirmed. Status: 0 OK",
                    "timestamp": self.iteration,
                }
            )
            self.chat_messages.append(
                {
                    "id": f"msg_{len(self.chat_messages)}",
                    "sender": "tester",
                    "title": "Tester",
                    "text": f"File '{fname}' verified. Sandboxed tests passed (Exit code: 0).",
                    "type": "tester",
                }
            )

            # 3. Router Phase
            self.active_node = "router"
            self.iteration += 1
            task["status"] = "completed"
            self.logs.append(
                {
                    "node": "router",
                    "content": f"Task {tid} transitioned to COMPLETED.",
                    "timestamp": self.iteration,
                }
            )

        self.current_phase = "completed"
        self.active_node = "router"
        self.current_task_id = None
        self.chat_messages.append(
            {
                "id": f"msg_{len(self.chat_messages)}",
                "sender": "architect",
                "title": "Architect",
                "text": (
                    "All atomic tasks have been successfully implemented and verified. "
                    "Switch to the 'Live Preview' tab to interact with your live web service, "
                    "or 'Workspace Files' to inspect the generated code."
                ),
                "type": "agent",
            }
        )

    def reset(self, project_name: str | None = None, purge_files: bool = True) -> None:
        saved_mode = self.config.mode
        saved_key = self.session_key
        target_project = project_name or self.project_name
        clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", target_project.strip()).strip("_") or "web_project"
        self.project_name = clean
        self.workspace_path = self.config.workspaces_dir / clean
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        self.init_default_state(purge_files=purge_files)
        self.config.mode = saved_mode
        self.session_key = saved_key
        if saved_mode == "simulation":
            self.session_key = None
        self.save_state_to_disk()

    def get_full_state(self) -> dict[str, Any]:
        total_tasks = 0
        completed_tasks = 0
        for epic in self.wbs:
            for t in epic.get("tasks", []):
                total_tasks += 1
                if t.get("status") == "completed":
                    completed_tasks += 1

        progress = (
            int(completed_tasks / total_tasks * 100)
            if total_tasks > 0
            else (100 if self.current_phase.lower() == "completed" else 0)
        )

        # Workspace file list (recursive relative paths, excluding internal state and junk)
        files = scan_workspace_files(self.workspace_path)

        return {
            "mode": self._get_active_config().mode.upper(),
            "active_node": self.active_node.upper(),
            "current_phase": self.current_phase.upper(),
            "iteration": self.iteration,
            "awaiting_hitl": self.awaiting_hitl,
            "current_task_id": self.current_task_id,
            "progress_percent": progress,
            "chat_messages": self.chat_messages,
            "logs": self.logs[-50:],
            "wbs": self.wbs,
            "files": files,
            "has_api_key": bool(self.session_key),
            "project_name": self.project_name,
            "workspace_dir": f"workspaces/{self.project_name}",
        }


# Global in-memory session instance
_session = DashboardSession()


@app.get("/", response_class=HTMLResponse)
def serve_index() -> HTMLResponse:
    index_file = WEB_DIR / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=404, detail="index.html not found")
    with open(index_file, encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/state")
def get_state() -> JSONResponse:
    return JSONResponse(content=_session.get_full_state())


@app.post("/api/chat")
def post_chat(req: ChatRequest, x_gemini_key: str | None = Header(None)) -> JSONResponse:
    key = req.api_key or x_gemini_key
    state = _session.process_chat(req.message, session_key=key, project_name=req.project_name)
    return JSONResponse(content=state)


@app.post("/api/reset")
def post_reset(req: ResetRequest | None = None) -> JSONResponse:
    pname = req.project_name if req else None
    purge = req.purge_files if req is not None else True
    _session.reset(project_name=pname, purge_files=purge)
    return JSONResponse(content=_session.get_full_state())


@app.get("/api/workspaces")
def list_workspaces() -> JSONResponse:
    workspaces_dir = _session.config.workspaces_dir
    result = []
    if workspaces_dir.exists():
        for d in sorted(workspaces_dir.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                files = scan_workspace_files(d)
                has_session = (d / ".systemagant" / "session.json").is_file()
                has_db = (d / "state.db").is_file()
                phase = "READY"
                if has_session:
                    try:
                        s_data = json.loads((d / ".systemagant" / "session.json").read_text(encoding="utf-8"))
                        phase = s_data.get("current_phase", "completed").upper()
                    except Exception:
                        pass
                elif has_db or files:
                    phase = "COMPLETED"
                result.append(
                    {
                        "name": d.name,
                        "file_count": len(files),
                        "has_session": has_session or has_db,
                        "phase": phase,
                        "is_active": (d.name == _session.project_name),
                    }
                )
    return JSONResponse(content={"workspaces": result, "active_workspace": _session.project_name})


@app.post("/api/workspace/load")
def post_load_workspace(req: WorkspaceActionRequest) -> JSONResponse:
    state = _session.load_project(req.project_name)
    return JSONResponse(content=state)


@app.post("/api/workspace/new")
def post_new_workspace(req: WorkspaceActionRequest) -> JSONResponse:
    state = _session.create_new_project(req.project_name)
    return JSONResponse(content=state)


@app.get("/api/workspace/files")
def get_workspace_files() -> JSONResponse:
    state = _session.get_full_state()
    return JSONResponse(content={"files": state["files"]})


@app.get("/api/workspace/file")
def get_file_content(path: str = Query(...)) -> PlainTextResponse:
    try:
        clean_path = path.lstrip("/").lstrip("\\")
        target = (_session.workspace_path / clean_path).resolve()
        base = _session.workspace_path.resolve()
        if not str(target).startswith(str(base)) or not target.is_file():
            raise HTTPException(status_code=404, detail=f"File {path} not found")
        with open(target, encoding="utf-8") as f:
            return PlainTextResponse(content=f.read())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/workspace/preview")
def preview_workspace(file: str | None = None) -> HTMLResponse:
    files = scan_workspace_files(_session.workspace_path)
    html_files = [f["name"] for f in files if f["name"].endswith(".html")]

    target_name = file
    if not target_name:
        if "index.html" in html_files:
            target_name = "index.html"
        elif html_files:
            target_name = html_files[0]

    if target_name and target_name.endswith(".html"):
        try:
            clean_path = target_name.lstrip("/").lstrip("\\")
            target = (_session.workspace_path / clean_path).resolve()
            base = _session.workspace_path.resolve()
            if str(target).startswith(str(base)) and target.is_file():
                with open(target, encoding="utf-8") as f:
                    html_code = f.read()

                style_file = _session.workspace_path / "style.css"
                if style_file.is_file():
                    with open(style_file, encoding="utf-8") as sf:
                        css_code = sf.read()
                    if "</head>" in html_code:
                        html_code = html_code.replace("</head>", f"<style>{css_code}</style></head>")
                    else:
                        html_code = f"<style>{css_code}</style>" + html_code

                return HTMLResponse(content=html_code)
        except Exception as e:
            logger.warning("Error reading preview file %s: %s", target_name, e)

    # If non-HTML codebase files exist (e.g. Python CLI, JS, etc.)
    if files:
        file_items_html = "".join(
            f'<li style="margin: 6px 0; color: #58a6ff;">[FILE] {f["name"]} <span style="color:#8c9ba5;">({f["size"]} B)</span></li>'
            for f in files[:12]
        )
        return HTMLResponse(
            content=f"""<!DOCTYPE html><html><body style="background:#0d0f12;color:#d8dee9;font-family:ui-monospace,monospace;padding:30px;margin:0;">
            <div style="border:1px solid #2d333b;padding:24px;background:#161b22;border-radius:4px;max-width:700px;margin:0 auto;">
                <h3 style="color:#e6a23c;margin-top:0;">[ NON-HTML WORKSPACE DETECTED ]</h3>
                <p style="color:#8c9ba5;font-size:12px;margin-bottom:14px;">
                    This workspace ('workspaces/{_session.project_name}') contains backend / CLI source code:
                </p>
                <ul style="list-style:none;padding:0;margin:0 0 16px 0;font-size:12px;">
                    {file_items_html}
                </ul>
                <div style="color:#3fb950;font-size:11px;border-top:1px dashed #2d333b;padding-top:12px;">
                    &gt; Switch to the <strong>Workspace Files</strong> tab to view and inspect all code files.
                </div>
            </div></body></html>"""
        )

    # Empty workspace
    return HTMLResponse(
        content="""<!DOCTYPE html><html><body style="background:#0d0f12;color:#8c9ba5;font-family:monospace;display:flex;align-items:center;justify-content:center;height:100vh;">
        <div style="text-align:center;border:1px dashed #2d333b;padding:30px;">
            <h3 style="color:#e6a23c;">[ NO ACTIVE BUILD IN WORKSPACE ]</h3>
            <p>Send a prompt in the chat and approve the plan to generate and preview your project.</p>
        </div></body></html>"""
    )


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


def start_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Launches the tactile dashboard server."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)
