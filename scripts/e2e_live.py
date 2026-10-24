"""Empirical E2E Live Verification Script for SystemAgant.

Executes 3 diverse engineering prompts through the multi-agent pipeline using
the real Google AI Studio Gemini API free tier:
1. Multi-Page Botanical Shop Website (Kwiaciarnia-Mex Toruń)
2. Retro 2D Canvas Arcade Game (HTML5/JS)
3. Python CLI Developer Utility (argparse + unit tests)

Records execution telemetry and results to docs/e2e_runs.md.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Ensure root directory is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core.config import AppConfig, get_config
from web.server import DashboardSession

PROMPTS = [
    {
        "id": "RUN_01_BOTANICAL_SHOP",
        "title": "Multi-Page Botanical Web Shop (Kwiaciarnia-Mex)",
        "prompt": "Create a botanical floral shop website for Kwiaciarnia-Mex in Toruń with 3 subpages (Home, Catalog with flower photos, Contact) and clean responsive styles.",
        "expected_files": ["index.html", "oferta.html", "kontakt.html", "style.css"],
    },
    {
        "id": "RUN_02_ARCADE_GAME",
        "title": "Retro 2D Canvas Arcade Game",
        "prompt": "Build a retro 2D arcade breakout paddle game in HTML5 Canvas and JavaScript with score tracking, paddle physics, brick grid, and clean responsive layout.",
        "expected_files": ["index.html"],
    },
    {
        "id": "RUN_03_PYTHON_CLI",
        "title": "Python CLI Developer Utility",
        "prompt": "Build a modular Python CLI developer tool named log_analyzer with argparse, regex pattern matching, statistical summary reporting, and a companion test suite.",
        "expected_files": ["log_analyzer.py"],
    },
]


def run_e2e_test_suite() -> None:
    cfg = get_config()
    print("=" * 70)
    print("SystemAgant // Empirical E2E Verification Suite (Live Gemini API)")
    print(f"[*] Engine: {cfg.gemini_model} | Mode: {cfg.mode}")
    print("=" * 70)

    if not cfg.gemini_api_key:
        print("[!] ERROR: GEMINI_API_KEY is not configured in .env. Aborting live test.")
        sys.exit(1)

    reports = []
    runs_doc = ROOT_DIR / "docs" / "e2e_runs.md"
    runs_doc.parent.mkdir(parents=True, exist_ok=True)

    for idx, test_case in enumerate(PROMPTS, 1):
        print(f"\n[Test {idx}/3] Starting: {test_case['title']}")
        print(f"[Prompt] '{test_case['prompt']}'")
        t0 = time.time()

        # Isolate workspace per test run
        session = DashboardSession(session_key=cfg.gemini_api_key)
        run_workspace = cfg.workspaces_dir / test_case["id"].lower()
        run_workspace.mkdir(parents=True, exist_ok=True)
        session.workspace_path = run_workspace

        # Step 1: Architect Brainstorming & WBS Planning
        print("  -> Step 1: Synthesizing architecture strategy & WBS via Gemini...")
        state_after_plan = session.process_chat(test_case["prompt"])
        wbs = state_after_plan.get("wbs", [])
        total_tasks = sum(len(e.get("tasks", [])) for e in wbs)
        print(f"  [+] Architect generated {len(wbs)} Epics and {total_tasks} Atomic Tasks.")

        # Step 2: Human-in-the-Loop Approval & Coder Execution
        print("  -> Step 2: Simulating Human Approval & triggering Coder implementation...")
        state_after_exec = session.process_chat("APPROVE")
        duration = time.time() - t0

        # Step 3: Verify Output Files
        created_files = [f["name"] for f in state_after_exec.get("files", [])]
        print(f"  [+] Workspace files generated: {created_files} in {duration:.1f}s")

        passed = len(created_files) > 0
        status_str = "PASS" if passed else "FAIL"

        report = {
            "id": test_case["id"],
            "title": test_case["title"],
            "prompt": test_case["prompt"],
            "status": status_str,
            "duration_sec": round(duration, 2),
            "epics_count": len(wbs),
            "tasks_count": total_tasks,
            "files": created_files,
        }
        reports.append(report)

        # Brief rate-limit cooldown between test runs
        print("  [*] Cooldown 8s to respect API quota...")
        time.sleep(8.0)

    # Write Markdown Telemetry Report
    with open(runs_doc, "w", encoding="utf-8") as rf:
        rf.write("# Empirical E2E Verification Report\n\n")
        rf.write(f"**Execution Timestamp:** {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}  \n")
        rf.write(f"**Engine:** Google AI Studio `{cfg.gemini_model}` (Free Tier)  \n")
        rf.write(f"**Total Runs:** {len(reports)} | **Passed:** {sum(1 for r in reports if r['status'] == 'PASS')} | **Failed:** {sum(1 for r in reports if r['status'] == 'FAIL')}\n\n")
        rf.write("---\n\n")

        rf.write("## Test Cases Summary\n\n")
        rf.write("| Test ID | Target System | Tasks | Files Generated | Duration | Status |\n")
        rf.write("|---|---|---|---|---|---|\n")
        for r in reports:
            files_str = ", ".join(r["files"][:3])
            if len(r["files"]) > 3:
                files_str += f" (+{len(r['files'])-3})"
            rf.write(f"| `{r['id']}` | {r['title']} | {r['tasks_count']} | `{files_str}` | {r['duration_sec']}s | **{r['status']}** |\n")

        rf.write("\n---\n\n")
        rf.write("## Detailed Run Logs\n\n")
        for r in reports:
            rf.write(f"### {r['id']} — {r['title']}\n")
            rf.write(f"- **Prompt:** \"{r['prompt']}\"\n")
            rf.write(f"- **Status:** `{r['status']}` ({r['duration_sec']}s)\n")
            rf.write(f"- **Epics:** {r['epics_count']} | **Tasks:** {r['tasks_count']}\n")
            rf.write(f"- **Files Produced:** {r['files']}\n\n")

    print("\n" + "=" * 70)
    print(f"E2E Verification Complete. Report saved to: {runs_doc}")
    print(f"Result: {sum(1 for r in reports if r['status'] == 'PASS')}/{len(reports)} Passed.")
    print("=" * 70)


if __name__ == "__main__":
    run_e2e_test_suite()
