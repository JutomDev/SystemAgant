import argparse
import logging
import logging.config
import os
import sys
import warnings
from pathlib import Path

from langchain_core._api.deprecation import LangChainDeprecationWarning
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from core.config import get_config
from core.graph import create_graph

# Suppress LangChain deprecation warnings in the console
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)

console = Console()


def generate_status_summary(wbs: list) -> str:
    """MODULE 2: Deterministic Summarizer (Cost: 0 tokens)"""
    last_completed = "None"
    next_step = "None"

    if not wbs:
        return "\n--- PROJECT STATUS ---\nNo active WBS plan.\n----------------------\n"

    for epic in wbs:
        tasks = epic.get("tasks", []) if isinstance(epic, dict) else getattr(epic, "tasks", [])
        for task in tasks:
            status = task.get("status") if isinstance(task, dict) else getattr(task, "status", "pending")
            title = task.get("description") if isinstance(task, dict) else getattr(task, "description", "Task")

            if status == "completed":
                last_completed = title
            elif status in ["pending", "in_progress", "failed"] and next_step == "None":
                next_step = title

    return (
        f"\n--- PROJECT STATUS ---\nLast Completed: {last_completed}\nNext Step: {next_step}\n----------------------\n"
    )


WORKSPACES_DIR = Path("./workspaces")


def setup_logging(log_path: Path):
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                    "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
                }
            },
            "handlers": {"file": {"class": "logging.FileHandler", "filename": str(log_path), "formatter": "json"}},
            "root": {"handlers": ["file"], "level": "INFO"},
        }
    )


def main():
    cfg = get_config()
    parser = argparse.ArgumentParser(description="SystemAgant — Autonomous Software House Telemetry & Engine")
    parser.add_argument(
        "--mode",
        choices=["simulation", "gemini-free", "vertex"],
        default=None,
        help="Execution mode (default: simulation)",
    )
    parser.add_argument("--web", action="store_true", help="Launch the tactile web dashboard")
    parser.add_argument("--project", default=None, help="Project workspace name")
    parser.add_argument("--port", type=int, default=8000, help="Web dashboard port")
    args = parser.parse_args()

    if args.mode:
        os.environ["EXECUTION_MODE"] = args.mode
        cfg.mode = args.mode

    if args.web:
        from web.server import start_server

        start_server(host=cfg.web_host, port=args.port or cfg.web_port)
        return

    print("=== AI Software House CLI (v2.0 - Production Ready) ===")
    print(f"[*] Execution Mode: {cfg.mode.upper()}")

    project_name = args.project
    if not project_name:
        project_name = input("Enter project name (or press Enter for 'default_bot'): ").strip()
    if not project_name:
        project_name = "default_bot"

    workspace_path = WORKSPACES_DIR / project_name
    workspace_path.mkdir(parents=True, exist_ok=True)

    db_path = workspace_path / "state.db"
    log_path = workspace_path / "system.log"

    setup_logging(log_path)
    logging.info(f"Initializing session for project '{project_name}' in mode '{cfg.mode}'")
    print(f"[*] Workspace: {workspace_path}")

    # FIX: Open database using Context Manager
    with SqliteSaver.from_conn_string(str(db_path)) as memory:
        graph = create_graph(checkpointer=memory)

        thread_id = f"thread_{project_name}"
        config = {"configurable": {"thread_id": thread_id}}

        # Inject workspace path into the initial state
        graph.update_state(config, {"workspace_path": str(workspace_path)})

        print("Type 'exit' or 'quit' to terminate session.\n")

        while True:
            state = graph.get_state(config)

            if state.next and "human_approval" in state.next:
                state_values = graph.get_state(config).values
                retry_count = state_values.get("retry_count", 0)
                consultation_retries = state_values.get("consultation_retries", 0)

                console.print("\n[bold yellow][!] SYSTEM PAUSED (HITL GATE)[/bold yellow]")

                # Dynamic diagnostics of pause reason
                if consultation_retries >= 3:
                    console.print(
                        "[bold red]REASON:[/bold red] Architect exceeded retry limit (L3 Escalation). Human intervention required."
                    )
                elif retry_count >= 3:
                    console.print(
                        "[bold red]REASON:[/bold red] Coder exceeded retry limit (L2 Escalation). Human intervention required."
                    )
                else:
                    console.print(
                        "[bold green]REASON:[/bold green] Awaiting architecture strategy approval or task milestone completed."
                    )

                try:
                    summary = generate_status_summary(state_values.get("wbs", []))
                    console.print(summary)
                except Exception as e:
                    console.print(f"[bold red][REPORT ERROR]: {e}[/bold red]")

                user_input = input(
                    "Type 'APPROVE' (or 'ZATWIERDZAM'), enter instructions, or 'ARCHITECT: [message]' to consult: "
                ).strip()

                if user_input.lower() in ["exit", "quit"]:
                    sys.exit(0)

                # Intercept Brainstorming mode
                if user_input.upper().startswith("ARCHITECT:") or user_input.upper().startswith("ARCHITEKT:"):
                    prefix_len = 10 if user_input.upper().startswith("ARCHITECT:") else 10
                    clean_input = user_input[prefix_len:].strip()
                    console.print("[dim]Routing to Architect (Brainstorming Consultation)...[/dim]")
                    graph.update_state(
                        config, {"messages": [HumanMessage(content=clean_input)], "current_phase": "brainstorming"}
                    )
                else:
                    graph.update_state(config, {"messages": [HumanMessage(content=user_input)]})

                events = graph.stream(None, config, stream_mode="updates")
            else:
                user_input = input("\nUser: ").strip()
                if user_input.lower() in ["exit", "quit"]:
                    sys.exit(0)
                if not user_input:
                    continue

                events = graph.stream(
                    {"messages": [HumanMessage(content=user_input)], "workspace_path": str(workspace_path)},
                    config,
                    stream_mode="updates",
                )

            for event in events:
                try:
                    for node_name, node_state in event.items():
                        # Skip if node_state is not a dictionary (e.g. metadata or router tuples)
                        if not isinstance(node_state, dict):
                            continue

                        messages = node_state.get("messages", [])
                        if not messages:
                            continue
                        last_msg = messages[-1]

                        # Format KODER (AI + Tools)
                        if node_name == "coder" and isinstance(last_msg, AIMessage):
                            # Extract text safely
                            raw_content = last_msg.content
                            if isinstance(raw_content, list):
                                # Gemini sometimes returns a list of dicts for content
                                raw_content = "\n".join(
                                    [
                                        item.get("text", "")
                                        for item in raw_content
                                        if isinstance(item, dict) and "text" in item
                                    ]
                                )

                            if last_msg.tool_calls:
                                for tc in last_msg.tool_calls:
                                    t_name = tc.get("name")
                                    t_args = tc.get("args", {})
                                    if t_name == "edit_file":
                                        target = t_args.get("path", "unknown")
                                        console.print(
                                            f"[bold cyan][+] [Coder][/bold cyan] Editing: [yellow]{target}[/yellow]"
                                        )
                                    elif t_name == "execute_subprocess":
                                        cmd = t_args.get("command", "")
                                        console.print(
                                            f"[bold magenta][>] [Coder][/bold magenta] Executing: [yellow]{cmd}[/yellow]"
                                        )
                                    elif t_name == "start_background_server":
                                        p = t_args.get("port", "...")
                                        console.print(
                                            f"[bold blue][*] [Coder][/bold blue] Starting daemon on port: [yellow]{p}[/yellow]"
                                        )
                                    elif t_name == "finish_task":
                                        console.print("[bold green][+] [Coder][/bold green] Completed atomic task.")
                                    else:
                                        console.print(
                                            f"[bold cyan][*] [Coder][/bold cyan] Tool call: [yellow]{t_name}[/yellow]"
                                        )
                            elif raw_content:
                                console.print(
                                    Panel(raw_content, title="[bold cyan]Coder[/bold cyan]", border_style="cyan")
                                )

                        # Format TESTER (Tool Results)
                        elif node_name == "tester" and isinstance(last_msg, ToolMessage):
                            cnt = str(last_msg.content)
                            if "Successfully" in cnt or "Exit code: 0" in cnt or "Status: 0 OK" in cnt:
                                console.print("[bold green][+] [Tester][/bold green] Tool execution passed.")
                            else:
                                err = cnt[:200] + "..." if len(cnt) > 200 else cnt
                                console.print(f"[bold red][!] [Tester][/bold red] Execution failure: {err}")

                        # Format ARCHITEKTA
                        elif node_name == "architect" and isinstance(last_msg, AIMessage):
                            raw_content = last_msg.content
                            if isinstance(raw_content, list):
                                raw_content = "\n".join(
                                    [
                                        item.get("text", "")
                                        for item in raw_content
                                        if isinstance(item, dict) and "text" in item
                                    ]
                                )
                            if raw_content:
                                md = Markdown(raw_content)
                                console.print(Panel(md, title="[bold blue]Architect[/bold blue]", border_style="blue"))

                        # Format ROUTERA (optional, simple log)
                        elif node_name == "router":
                            pass

                        # Fallback for other nodes
                        else:
                            if hasattr(last_msg, "content") and last_msg.content:
                                console.print(f"[dim] -> [Wykonano: {node_name}][/dim]")
                except Exception as e:
                    console.print(f"[bold red]INTERNAL CLI ERROR:[/bold red] {str(e)}")
                    continue


if __name__ == "__main__":
    main()
