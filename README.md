# SystemAgant

> **Deterministic Multi-Agent State Machine for Autonomous Software Engineering**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests: 30 Passed](https://img.shields.io/badge/Tests-30%20Passed-emerald.svg)](tests/)
[![Architecture: LangGraph](https://img.shields.io/badge/Orchestrator-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![Status: On Hold](https://img.shields.io/badge/Status-On%20Hold%20%28Maintenance%29-amber.svg)]()
[![Release: v2.2.1 Stable](https://img.shields.io/badge/Release-v2.2.1%20Stable-brightgreen.svg)]()

| Specification | Details |
|---|---|
| **Project Status** | **On Hold** (Feature-complete v2.2.1 baseline; maintained in stable state) |
| **Orchestration** | Cyclic State Machine via LangGraph & SQLite Checkpoints |
| **Runtime Target** | Python 3.11+ (Pydantic v2, FastAPI, AsyncIO) |
| **Telemetry & UI** | Tactile Web Visualizer (250ms streaming) & Rich Terminal CLI |
| **Test Verification** | 30/30 Unit & Integration Tests Passing (PyTest) |

---

## 1. Overview

**SystemAgant** is a deterministic multi-agent software engineering system orchestrated by **LangGraph**. The platform coordinates specialized autonomous nodes—**Architect**, **Coder**, **Tester**, and **Router**—with milestone-based Human-In-The-Loop (HITL) escalation to plan, implement, and self-verify software projects inside isolated filesystem sandboxes.

The repository includes:
- **Offline Deterministic Simulation Engine:** Instant replay of multi-agent runs consuming 0 tokens and requiring no external credentials.
- **Autonomous Free Gemini Engine:** Live multi-agent execution powered by Google AI Studio Gemini API free-tier with in-memory session keys.
- **Tactile Web Visualizer:** Low-latency telemetry dashboard (250ms polling) with active LED indicators, real-time node state transitions, and a sandboxed live preview.
- **Empirical Retrospective & Architecture Analysis:** Candid engineering documentation on token economy, SQLite checkpoint inflation, and AST repository mapping.

---

## 2. Interactive Tactile Dashboard

The repository includes a self-contained web dashboard (`main.py --web`) featuring a multi-agent chat feed, HITL approval buttons, a live iframe renderer of generated websites, and a real-time file tree with a code inspector:

![Tactile Dashboard - Multi-Agent Chat & Live Website Preview](docs/dashboard_chat_preview.png)
*Figure 1: Tactile UI with multi-agent conversation log and HITL gate (left), and live iframe preview of generated 'Kwiaciarnia-Mex' website (right).*

![Tactile Dashboard - Workspace File Explorer & Code Viewer](docs/dashboard_code_viewer.png)
*Figure 2: Real-time workspace file tree and code inspector rendering generated HTML/CSS files without external dependencies.*

---

## 3. Multi-Agent Architecture

The lifecycle operates as a directed cyclic graph with state checkpoints stored in SQLite:

```mermaid
graph TD
    START([Start]) --> Router["Router Node\n(Lifecycle & Task Transition Engine)"]
    
    Router -->|"Phase: Brainstorming"| Architect["Architect Node\n(Pydantic v2 Structured WBS)"]
    Router -->|"Phase: Execution (Task Pending)"| Coder["Coder Node\n(Self-Directed Code Modification)"]
    Router -->|"All Tasks Complete / Escalation"| Human["Human Approval Node\n(Milestone HITL Gate)"]
    
    Architect -->|"Plan Generated"| Human
    Human -->|"User Approves (ZATWIERDZAM)"| Router
    Human -->|"User Feedback / Intervention"| Architect
    
    Coder -->|"Tool Call Generated"| Tester["Tester Node\n(Sandboxed Tool Execution)"]
    Tester -->|"Exit Code 0 / Next Iteration"| Coder
    Tester -->|"Tool Error / Fix Required"| Coder
    Tester -->|"Task Finished (finish_task)"| Router
    
    Router -->|"All Epics Completed"| END([Project Complete])
```

### Agent Roles & Separation of Concerns

* **Architect:** Operates in two modes: conversational brainstorming and deterministic Work Breakdown Structure (WBS) synthesis. Outputs structured Pydantic models containing Epics and Atomic Tasks.
* **Coder:** Operates in an isolated workspace with file access restricted to strict path confinement. Generates batch `SEARCH/REPLACE` diffs and shell commands.
* **Tester:** Intercepts tool calls (`read_file`, `edit_file`, `execute_subprocess`, `finish_task`), executes them inside the workspace sandbox, records execution logs, and returns structured tool results.
* **Router:** Rule engine evaluating WBS progress, task completion signals, and escalation boundaries.

---

## 4. What Succeeded (The Wins)

1. **Deterministic WBS Synthesis (0 Parsing Hallucinations):**
   * Using Pydantic v2 Structured Outputs (`with_structured_output(ArchitectOutput)`) eliminated Markdown extraction failures and prompt-formatting drift. Plans cleanly serialize into validated JSON Epics.
2. **Strict Filesystem Sandboxing:**
   * Guardrail functions (`_secure_path`) prevent directory traversal attacks (`../`), confining all modifications to isolated project directories in `workspaces/<project_name>/`.
3. **Automated Tool History Sanitization (`sanitize_history`):**
   * Solved multi-turn tool calling errors (e.g., Vertex AI / Gemini 400 Bad Request caused by orphaned tool calls) by automatically repairing interrupted conversation turns prior to model invocation.
4. **Offline Simulation Replay Engine:**
   * Allows anyone cloning the repository to run, inspect, and evaluate the entire multi-agent loop with **0 API cost and 0 configuration**.
5. **Zero-Dependency AST Repository Mapping (`core/repo_map.py`):**
   * Inspired by Tree-sitter and Aider repo map pipelines, the system extracts structural AST symbols (classes, methods, exports, functions, HTML IDs, and CSS variables) across multi-script workspaces. Injected into the Coder's prompt, this guarantees cross-file coherence in multi-page and multi-script projects at a fraction of the token cost of reading raw files.

---

## 5. Architectural Ceilings & Engineering Retrospective

During non-trivial full-stack web application development (e.g., building a complete React + FastAPI application), the autonomous loop hit practical limits:

```
[+] Pydantic WBS Planning ............................................ [OK - High Reliability]
[+] Sandbox File & Process Operations ................................. [OK - Deterministic]
[-] Multi-Turn State Bloat (SQLite Memory) ........................... [FAILED - Context Inflation]
[-] Long-Loop Error Recovery (Local Minima) .......................... [FAILED - Economic Ceiling]
[-] Multi-File Semantic Refactoring ................................... [FAILED - Missing AST Index]
```

### 1. State Bloat & Context Rot in SQLite Checkpoints
* **Issue:** Serializing all turn messages into LangGraph's SQLite checkpointer caused exponential token inflation. By turn 15, prompt contexts reached 30,000+ tokens, driving up latency and degrading recall (*context rot*).
* **Lesson Learned:** Checkpointers must maintain dual memory channels: a lightweight rolling summary window for conversation, and a vectorized, externalized state for file modifications and test outputs.

### 2. The Economic & Autonomy Ceiling in Long Loops
* **Issue:** When a syntax or runtime error occurred in generated code, the Coder often entered cyclical repair attempts (fixing file A broke file B). While the loop-detection rule prevented infinite loops, token costs escalated rapidly without making forward progress.
* **Lesson Learned:** Pure LLM autoregression without static language server protocol (LSP) feedback creates expensive trial-and-error loops. Compilers and typecheckers must guide edits before querying the LLM.

### 3. Lack of Semantic Abstract Syntax Tree (AST) Indexing
* **Issue:** Relying on `SEARCH/REPLACE` text blocks without an AST code-graph made multi-file refactoring fragile. Renaming a component in one file often left dangling imports in three others.
* **Lesson Learned:** An agent software house requires a semantic repository map (AST tree, call graphs, symbol tables) rather than treating codebases purely as flat filesystem text.

### 4. Scope & Capabilities: What SystemAgant is Built For vs. Out of Scope

| Dimension | In Scope (Deterministic Sweet Spot) | Out of Scope (Architectural Ceilings) |
|---|---|---|
| **Web Applications** | Multi-page responsive websites, interactive HTML5/CSS/JS, portfolio sites, Canvas 2D games | Heavy distributed Next.js/React full-stacks with SSR database migrations and Docker swarms |
| **Backend & CLI** | Modular Python CLI developer tools, data parsers, statistical summary generators, unit tests | Enterprise microservice clusters requiring active PostgreSQL instances and message queues |
| **Planning & Conceptual Phase** | Multi-turn requirement brainstorming with Architect, deterministic Pydantic v2 WBS | Autoregressive free-form code editing without human milestone approval |
| **Error Recovery & Self-Healing** | AST syntax self-repair, broken image URL HEAD checks with inline SVG fallback | Recursive multi-file debugging traps where fixing file A breaks files B, C, and D |
| **Storage & Sandboxing** | Isolated local filesystem sandbox (`workspaces/<project_name>/`) with path boundary guards | Remote production server deployments, cloud infrastructure provisioning |

---

## 6. Quickstart Guide

### Installation

```bash
# Clone the repository
git clone https://github.com/JutomDev/SystemAgant.git
cd SystemAgant

# Create virtual environment and install dependencies
python -m venv .venv
.\.venv\Scripts\activate      # Windows
# source .venv/bin/activate   # Linux/macOS

pip install -r requirements.txt
```

### Running the Tactile Web Dashboard (Recommended)

Launch the industrial telemetry visualizer:

```bash
python main.py --web
```
Open **`http://127.0.0.1:8000`** in your browser.
* **Offline Simulation Mode:** Default mode with 0 token consumption and instant deterministic replays.
* **Live Autonomous Execution:** Configure your free Google AI Studio key either via `.env` (`GEMINI_API_KEY=...`) or via the in-browser **`[ KEY: CONFIGURE ]`** session modal. Select quick prompt presets (`[BOTANICAL]`, `[ARCADE]`, `[CLI]`) or enter any custom prompt, inspect the synthesized WBS, click **`[ APPROVE STRATEGY ]`**, and watch the live generated site render in the real-time iframe preview!

### Running via CLI

```bash
# 1. Run offline simulation mode (Default, 0 tokens)
python main.py --mode simulation

# 2. Run with free Google AI Studio API key (Live autonomous agent)
# Copy template and add your free GEMINI_API_KEY from https://aistudio.google.com/
cp .env.example .env
python main.py --mode gemini-free
```

### Where Generated Projects are Stored

All autonomous agent outputs are safely sandboxed in isolated directories on your local filesystem:

```text
SystemAgant/
└── workspaces/
    ├── web_project/             # Default workspace
    │   ├── index.html           # Generated web interface
    │   ├── style.css            # Stylesheet & CSS variables
    │   └── app.js               # Client logic / Canvas / scripts
    └── <custom_project>/        # Custom workspace named via UI or CLI
```

* **Direct Browser Access:** Open any generated page directly in Chrome, Firefox, or Edge:
  ```text
  file:///path/to/SystemAgant/workspaces/web_project/index.html
  ```
* **Direct Editor Access:** Open the generated project in VS Code or your preferred IDE:
  ```bash
  code workspaces/web_project
  ```
* **Custom Workspace Naming:** In the web UI telemetry bar, edit the `WORKSPACE:` input (e.g., `WORKSPACE: [ flower_shop ]`). All subsequent code generations will be scoped strictly inside `workspaces/flower_shop/`.
* **Multi-Page Navigation:** In the Tactile UI, use the **`// PAGE:`** dropdown to switch the live iframe preview between `index.html`, `catalog.html`, `contact.html`, or any other generated page.
* **Git Hygiene:** The entire `workspaces/` directory is strictly excluded in `.gitignore` to prevent generated artifacts from polluting the core repository.

### Empirical E2E Verification Suite

The repository includes an empirical E2E test suite running live multi-agent synthesis across 3 diverse prompt archetypes:
```bash
python scripts/e2e_live.py
```
See the verified test logs and metrics in **[`docs/e2e_runs.md`](docs/e2e_runs.md)** (3/3 Passed, avg 49.6s per project).

---

## 7. Test Suite & Verification

The project includes unit tests for reducers, sandbox filesystem tools, configuration, and the web telemetry server:

```bash
pytest -v
```

Verification output:
```
tests/test_botanical_shop_integrity.py::test_botanical_shop_files_exist PASSED [  3%]
tests/test_botanical_shop_integrity.py::test_botanical_shop_hamburger_menu_integrity PASSED [  6%]
tests/test_botanical_shop_integrity.py::test_botanical_shop_all_links_and_anchors_valid PASSED [ 10%]
tests/test_botanical_shop_integrity.py::test_botanical_shop_preview_http_endpoints PASSED [ 13%]
tests/test_factory_and_config.py::test_app_config_defaults PASSED        [ 16%]
tests/test_factory_and_config.py::test_simulation_architect_wbs_generation PASSED [ 20%]
tests/test_factory_and_config.py::test_simulation_coder_tool_calls PASSED [ 23%]
tests/test_repo_map.py::test_parse_python_symbols PASSED                 [ 26%]
tests/test_repo_map.py::test_parse_js_symbols PASSED                     [ 30%]
tests/test_repo_map.py::test_parse_html_symbols PASSED                   [ 33%]
tests/test_repo_map.py::test_generate_repo_map PASSED                    [ 36%]
tests/test_repo_map.py::test_generate_task_scoped_repo_map PASSED        [ 40%]
tests/test_state.py::test_update_execution_logs_append PASSED            [ 43%]
tests/test_state.py::test_update_execution_logs_reset PASSED             [ 46%]
tests/test_state.py::test_merge_file_system_state PASSED                 [ 50%]
tests/test_tools.py::test_read_file_not_found PASSED                     [ 53%]
tests/test_tools.py::test_edit_file_format PASSED                        [ 56%]
tests/test_tools.py::test_edit_file_success PASSED                       [ 60%]
tests/test_web_server.py::test_serve_index PASSED                        [ 63%]
tests/test_web_server.py::test_api_state PASSED                          [ 66%]
tests/test_web_server.py::test_api_chat_flow PASSED                      [ 70%]
tests/test_web_server.py::test_api_reset PASSED                          [ 73%]
tests/test_web_server.py::test_preview_nested_and_static_assets PASSED   [ 76%]
tests/test_web_server.py::test_api_chat_async_execution PASSED           [ 80%]
tests/test_web_server.py::test_non_destructive_editing_and_node_transitions PASSED [ 83%]
tests/test_web_server.py::test_natural_language_approval_and_async_planning PASSED [ 86%]
tests/test_workspace_persistence.py::test_workspace_listing_and_new PASSED [ 90%]
tests/test_workspace_persistence.py::test_workspace_persistence_and_resume PASSED [ 93%]
tests/test_workspace_persistence.py::test_load_existing_files_workspace_and_preview PASSED [ 96%]
tests/test_workspace_persistence.py::test_load_statedb_checkpoint_workspace PASSED [100%]
============================= 30 passed in 14.20s =============================
```

---

## 8. License

MIT License. See [LICENSE](LICENSE) for full legal text. Open-source research and engineering showcase for the autonomous agent and multi-agent systems community.
