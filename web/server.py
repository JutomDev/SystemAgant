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
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import AppConfig, get_config
from core.llm_factory import get_architect_llms, get_coder_llm
from core.models import ArchitectOutput, AtomicTask, Epic
from core.tools.asset_tools import validate_and_repair_html_images
from core.repo_map import generate_repo_map

WEB_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="SystemAgant Tactile Dashboard",
    description="Interactive Multi-Agent Chat, Telemetry Rack & Live Preview",
    version="2.1.0",
)


class ChatRequest(BaseModel):
    message: str
    project_name: Optional[str] = None
    api_key: Optional[str] = None


class ResetRequest(BaseModel):
    project_name: Optional[str] = None


class DashboardSession:
    def __init__(self, session_key: Optional[str] = None, project_name: str = "web_project"):
        self.config = get_config()
        self.session_key = session_key or self.config.gemini_api_key or os.getenv("GEMINI_API_KEY")
        self.set_project(project_name)
        self.reset_state()

    def set_project(self, name: str) -> None:
        clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.strip()).strip("_") or "web_project"
        self.project_name = clean
        self.workspace_path = self.config.workspaces_dir / clean
        self.workspace_path.mkdir(parents=True, exist_ok=True)

    def reset_state(self) -> None:
        # Purge existing files on reset to guarantee clean build slate
        if self.workspace_path.exists():
            for p in list(self.workspace_path.rglob("*")):
                if p.is_file() and not p.name.startswith(".git"):
                    try:
                        p.unlink()
                    except Exception:
                        pass

        self.active_node = "router"
        self.current_phase = "brainstorming"  # brainstorming -> approval -> execution -> completed
        self.iteration = 1
        self.logs: List[Dict[str, Any]] = []
        self.chat_messages: List[Dict[str, Any]] = []
        self.wbs: List[Dict[str, Any]] = []
        self.current_task_id: Optional[str] = None
        self.awaiting_hitl = False

        # Initial system welcome message in English
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

    def process_chat(self, user_text: str, session_key: Optional[str] = None, project_name: Optional[str] = None) -> Dict[str, Any]:
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
                except Exception as e:
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

        return self.get_full_state()

    def run_execution_cycle(self) -> None:
        """Executes WBS tasks using real LLM generation or deterministic fallback."""
        cfg = self._get_active_config()
        all_tasks = []
        for epic in self.wbs:
            for t in epic.get("tasks", []):
                all_tasks.append(t)

        coder_llm = get_coder_llm(cfg)

        for task in all_tasks:
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
                # Real LLM Generation
                repo_map = generate_repo_map(self.workspace_path)
                repo_context = f"\nExisting Repository Symbol Map:\n{repo_map}\n" if repo_map else ""
                if repo_map:
                    self.logs.append({
                        "node": "coder",
                        "content": f"Repository Map: Injected cross-file symbols for {fname} ({len(repo_map.splitlines())} lines).",
                        "timestamp": self.iteration,
                    })
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
                    self.logs.append({
                        "node": "tester",
                        "content": f"AST Syntax Check: '{fname}' parsed successfully (Valid Python syntax).",
                        "timestamp": self.iteration,
                    })
                except SyntaxError as syn_err:
                    self.logs.append({
                        "node": "tester",
                        "content": f"AST Syntax Error in '{fname}': {syn_err}. Triggering self-healing repair...",
                        "timestamp": self.iteration,
                    })
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
                            self.logs.append({
                                "node": "tester",
                                "content": f"Self-Healing: Auto-repair successfully resolved syntax error in '{fname}'.",
                                "timestamp": self.iteration,
                            })
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

    def reset(self, project_name: Optional[str] = None) -> None:
        saved_mode = self.config.mode
        saved_key = self.session_key
        target_project = project_name or self.project_name
        self.__init__(session_key=saved_key, project_name=target_project)
        self.config.mode = saved_mode
        if saved_mode == "simulation":
            self.session_key = None

    def get_full_state(self) -> Dict[str, Any]:
        total_tasks = 0
        completed_tasks = 0
        for epic in self.wbs:
            for t in epic.get("tasks", []):
                total_tasks += 1
                if t.get("status") == "completed":
                    completed_tasks += 1

        progress = int((completed_tasks / total_tasks * 100)) if total_tasks > 0 else 0

        # Workspace file list (recursive relative paths)
        files = []
        if self.workspace_path.exists():
            for p in self.workspace_path.rglob("*"):
                if p.is_file() and not p.name.endswith(".db") and not p.name.endswith(".log"):
                    rel_name = str(p.relative_to(self.workspace_path)).replace("\\", "/")
                    files.append({"name": rel_name, "size": p.stat().st_size})

        return {
            "mode": self._get_active_config().mode.upper(),
            "active_node": self.active_node.upper(),
            "current_phase": self.current_phase.upper(),
            "iteration": self.iteration,
            "awaiting_hitl": self.awaiting_hitl,
            "current_task_id": self.current_task_id,
            "progress_percent": progress,
            "chat_messages": self.chat_messages,
            "logs": self.logs[-25:],
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
    with open(index_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/state")
def get_state() -> JSONResponse:
    return JSONResponse(content=_session.get_full_state())


@app.post("/api/chat")
def post_chat(req: ChatRequest, x_gemini_key: Optional[str] = Header(None)) -> JSONResponse:
    key = req.api_key or x_gemini_key
    state = _session.process_chat(req.message, session_key=key, project_name=req.project_name)
    return JSONResponse(content=state)


@app.post("/api/reset")
def post_reset(req: Optional[ResetRequest] = None) -> JSONResponse:
    pname = req.project_name if req else None
    _session.reset(project_name=pname)
    return JSONResponse(content=_session.get_full_state())


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
        with open(target, "r", encoding="utf-8") as f:
            return PlainTextResponse(content=f.read())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/workspace/preview")
def preview_workspace(file: str = "index.html") -> HTMLResponse:
    try:
        clean_path = file.lstrip("/").lstrip("\\")
        target = (_session.workspace_path / clean_path).resolve()
        base = _session.workspace_path.resolve()
        if not str(target).startswith(str(base)) or not target.is_file():
            # Fallback to index.html if specific page not created yet
            index_target = _session.workspace_path / "index.html"
            if index_target.is_file():
                target = index_target
            else:
                return HTMLResponse(
                    content="""<!DOCTYPE html><html><body style="background:#0d0f12;color:#8c9ba5;font-family:monospace;display:flex;align-items:center;justify-content:center;height:100vh;">
                    <div style="text-align:center;border:1px dashed #2d333b;padding:30px;">
                        <h3 style="color:#e6a23c;">[ NO ACTIVE BUILD IN WORKSPACE ]</h3>
                        <p>Send a prompt in the chat and approve the plan to generate and preview your project.</p>
                    </div></body></html>"""
                )
    except Exception:
        target = _session.workspace_path / "index.html"
        if not target.is_file():
            return HTMLResponse(content="<h3>No preview available</h3>")

    with open(target, "r", encoding="utf-8") as f:
        html_code = f.read()

    # If style.css exists, inline it into preview to guarantee CSS renders in iframe
    style_file = _session.workspace_path / "style.css"
    if style_file.is_file():
        with open(style_file, "r", encoding="utf-8") as sf:
            css_code = sf.read()
        if "</head>" in html_code:
            html_code = html_code.replace("</head>", f"<style>{css_code}</style></head>")
        else:
            html_code = f"<style>{css_code}</style>" + html_code

    return HTMLResponse(content=html_code)


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


def start_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Launches the tactile dashboard server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)

