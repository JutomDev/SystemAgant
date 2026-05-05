import os
import sys
import logging
import logging.config
import warnings
import json
from langchain_core._api.deprecation import LangChainDeprecationWarning

# Suppress LangChain deprecation warnings in the console
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)
from pathlib import Path
from uuid import uuid4
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich.markdown import Markdown

console = Console()
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_vertexai import ChatVertexAI
from core.graph import create_graph

# Initialize PRO model for deep HITL summaries
pro_communicator = ChatVertexAI(
    model_name="gemini-3.1-pro-preview", 
    location="global", 
    project="nifty-saga-493918-c8", 
    temperature=0.1
)

def generate_status_summary(wbs: list) -> str:
    """MODULE 2: Deterministic Summarizer (Cost: 0 tokens)"""
    last_completed = "Brak"
    next_step = "Brak"
    
    if not wbs:
        return "\n--- STATUS PROJEKTU ---\nBrak aktywnego planu (WBS).\n-----------------------\n"

    for epic in wbs:
        tasks = epic.get("tasks", []) if isinstance(epic, dict) else getattr(epic, "tasks", [])
        for task in tasks:
            status = task.get("status") if isinstance(task, dict) else getattr(task, "status", "pending")
            title = task.get("description") if isinstance(task, dict) else getattr(task, "description", "Zadanie")
            
            if status == "completed":
                last_completed = title
            elif status in ["pending", "in_progress", "failed"] and next_step == "Brak":
                next_step = title
    
    return f"\n--- STATUS PROJEKTU ---\nOstatnio ukończono: {last_completed}\nNastępny krok: {next_step}\n-----------------------\n"
WORKSPACES_DIR = Path("./workspaces")

def setup_logging(log_path: Path):
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                "format": "%(asctime)s %(name)s %(levelname)s %(message)s"
            }
        },
        "handlers": {
            "file": {
                "class": "logging.FileHandler",
                "filename": str(log_path),
                "formatter": "json"
            }
        },
        "root": {"handlers": ["file"], "level": "INFO"}
    })

def main():
    print("=== AI Software House CLI (v2.0 - Production Ready) ===")
    project_name = input("Wpisz nazwę projektu (lub Enter dla 'default_bot'): ").strip()
    if not project_name: project_name = "default_bot"
        
    workspace_path = WORKSPACES_DIR / project_name
    workspace_path.mkdir(parents=True, exist_ok=True)
    
    db_path = workspace_path / "state.db"
    log_path = workspace_path / "system.log"
    
    setup_logging(log_path)
    logging.info(f"Initializing session for project '{project_name}'")
    print(f"[*] Workspace: {workspace_path}")
    
    # FIX: Open database using Context Manager
    with SqliteSaver.from_conn_string(str(db_path)) as memory:
        graph = create_graph(checkpointer=memory)
        
        thread_id = f"thread_{project_name}"
        config = {"configurable": {"thread_id": thread_id}}
        
        # Inject workspace path into the initial state
        graph.update_state(config, {"workspace_path": str(workspace_path)})
        
        print("Wpisz 'exit' lub 'quit' aby zakończyć.\n")
        
        while True:
            state = graph.get_state(config)
            
            if state.next and "human_approval" in state.next:
                state_values = graph.get_state(config).values
                retry_count = state_values.get("retry_count", 0)
                consultation_retries = state_values.get("consultation_retries", 0)
                
                console.print("\n[bold yellow]⏸️ SYSTEM ZATRZYMANY (HITL)[/bold yellow]")
                
                # Dynamiczna diagnoza powodu zatrzymania
                if consultation_retries >= 3:
                    console.print("[bold red]POWÓD:[/bold red] Architekt wyczerpał limit prób naprawy (Eskalacja L3). Wymagana interwencja człowieka.")
                elif retry_count >= 3:
                    console.print("[bold red]POWÓD:[/bold red] Koder wyczerpał limit prób naprawy (Eskalacja L2). Wymagana interwencja człowieka.")
                else:
                    console.print("[bold green]POWÓD:[/bold green] Oczekuję na zatwierdzenie strategii lub zadanie zostało ukończone.")

                try:
                    summary = generate_status_summary(state_values.get("wbs",[]))
                    console.print(summary)
                except Exception as e:
                    console.print(f"[bold red][BŁĄD RAPORTU]: {e}[/bold red]")
                
                user_input = input("Wpisz 'ZATWIERDZAM', podaj instrukcje, lub wpisz 'ARCHITEKT: [wiadomość]' aby podjąć dyskusję: ").strip()
                
                if user_input.lower() in['exit', 'quit']: sys.exit(0)
                
                # Przechwytywanie trybu Burzy Mózgów
                if user_input.upper().startswith("ARCHITEKT:"):
                    clean_input = user_input[10:].strip()
                    console.print("[dim]Przekierowuję do Architekta (Tryb Burzy Mózgów)...[/dim]")
                    # Aktualizujemy wiadomości ORAZ wymuszamy zmianę fazy na brainstorming
                    graph.update_state(config, {
                        "messages":[HumanMessage(content=clean_input)],
                        "current_phase": "brainstorming"
                    })
                else:
                    # Standardowa aktualizacja
                    graph.update_state(config, {"messages": [HumanMessage(content=user_input)]})
                    
                events = graph.stream(None, config, stream_mode="updates")
            else:
                user_input = input("\nUżytkownik: ").strip()
                if user_input.lower() in ['exit', 'quit']: sys.exit(0)
                if not user_input: continue
                    
                events = graph.stream(
                    {
                        "messages": [HumanMessage(content=user_input)],
                        "workspace_path": str(workspace_path)
                    }, 
                    config, 
                    stream_mode="updates"
                )
            
            for event in events:
                try:
                    for node_name, node_state in event.items():
                        # Skip if node_state is not a dictionary (e.g. metadata or router tuples)
                        if not isinstance(node_state, dict):
                            continue
                            
                        messages = node_state.get("messages", [])
                        if not messages: continue
                        last_msg = messages[-1]
                        
                        # Format KODER (AI + Tools)
                        if node_name == "coder" and isinstance(last_msg, AIMessage):
                            # Extract text safely
                            raw_content = last_msg.content
                            if isinstance(raw_content, list):
                                # Gemini sometimes returns a list of dicts for content
                                raw_content = "\n".join([item.get("text", "") for item in raw_content if isinstance(item, dict) and "text" in item])
                            
                            if last_msg.tool_calls:
                                for tc in last_msg.tool_calls:
                                    t_name = tc.get("name")
                                    t_args = tc.get("args", {})
                                    if t_name == "edit_file":
                                        target = t_args.get("path", "unknown")
                                        console.print(f"[bold cyan]🛠️  [Coder][/bold cyan] Edytuje: [yellow]{target}[/yellow]")
                                    elif t_name == "execute_subprocess":
                                        cmd = t_args.get("command", "")
                                        console.print(f"[bold magenta]⚡ [Coder][/bold magenta] Uruchamia: [yellow]{cmd}[/yellow]")
                                    elif t_name == "start_background_server":
                                        p = t_args.get("port", "...")
                                        console.print(f"[bold blue]📡 [Coder][/bold blue] Startuje serwer na porcie: [yellow]{p}[/yellow]")
                                    elif t_name == "finish_task":
                                        console.print(f"[bold green]🏁 [Coder][/bold green] KOŃCZY ZADANIE.")
                                    else:
                                        console.print(f"[bold cyan]⚙️  [Coder][/bold cyan] Narzędzie: [yellow]{t_name}[/yellow]")
                            elif raw_content:
                                console.print(Panel(raw_content, title="[bold cyan]Coder[/bold cyan]", border_style="cyan"))
                        
                        # Format TESTER (Tool Results)
                        elif node_name == "tester" and isinstance(last_msg, ToolMessage):
                            cnt = str(last_msg.content)
                            if "Successfully" in cnt or "Exit code: 0" in cnt:
                                console.print(f"[bold green]✅ [Tester][/bold green] Sukces.")
                            else:
                                # Show error snippet
                                err = cnt[:200] + "..." if len(cnt) > 200 else cnt
                                console.print(f"[bold red]❌ [Tester][/bold red] Błąd: {err}")
                        
                        # Format ARCHITEKTA
                        elif node_name == "architect" and isinstance(last_msg, AIMessage):
                            raw_content = last_msg.content
                            if isinstance(raw_content, list):
                                raw_content = "\n".join([item.get("text", "") for item in raw_content if isinstance(item, dict) and "text" in item])
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
