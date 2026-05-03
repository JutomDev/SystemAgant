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
from langchain_core.messages import HumanMessage, SystemMessage
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
                print("\n[HITL] SYSTEM OCZEKUJE NA DECYZJĘ STRATEGICZNĄ.")
                print("Architekt przygotowuje raport stanu...")
                try:
                    summary = generate_status_summary(graph.get_state(config).values.get("wbs", []))
                    print(summary)
                except Exception as e:
                    print(f"\n[BŁĄD RAPORTU]: {e}")
                
                user_input = input("Wpisz 'ZATWIERDZAM' lub podaj instrukcje/nowe dyrektywy: ").strip()
                
                if user_input.lower() in ['exit', 'quit']: sys.exit(0)
                    
                # Every user message (including APPROVALS) must be added to the state
                # so the human_approval_node can interpret it and transition the project phase.
                graph.update_state(config, {"messages": [HumanMessage(content=user_input)]})
                events = graph.stream(None, config, stream_mode="updates")
            else:
                user_input = input("\nUżytkownik: ").strip()
                if user_input.lower() in ['exit', 'quit']: sys.exit(0)
                if not user_input: continue
                    
                events = graph.stream(
                    {
                        "messages": [HumanMessage(content=user_input)],
                        "workspace_path": workspace_path
                    }, 
                    config, 
                    stream_mode="updates"
                )
            
            for event in events:
                for node_name, node_state in event.items():
                    print(f" -> [Wykonano: {node_name}]")
                    
                    # Print messages from AI and Tools
                    if node_state and "messages" in node_state and node_state["messages"]:
                        last_msg = node_state["messages"][-1]
                        
                        # Check if the message is from AI (Text or Tool Calls)
                        msg_type = getattr(last_msg, "type", None) or (last_msg.get("type") if isinstance(last_msg, dict) else None)
                        
                        if msg_type == "ai":
                            content = getattr(last_msg, "content", "") or (last_msg.get("content") if isinstance(last_msg, dict) else "")
                            if content:
                                print(f"\n[AI {node_name.upper()}]: {content}\n")
                            
                            tool_calls = getattr(last_msg, "tool_calls", []) or (last_msg.get("tool_calls") if isinstance(last_msg, dict) else [])
                            if tool_calls:
                                for tc in tool_calls:
                                    tc_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                                    tc_args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                                    
                                    # Sanitize logs - avoid printing the entire code block if it is too long
                                    args_str = json.dumps(tc_args, indent=2)
                                    if len(args_str) > 500:
                                        # Extract only key information (e.g., file path)
                                        path = tc_args.get("path") or tc_args.get("command") or "..."
                                        args_str = f'{{ "path": "{path}", "content": "... (truncated for readability)" }}'
                                        
                                    print(f" -> [INTENCJA]: {tc_name}({args_str})")
                        
                        # Check if the message is a Tool Result
                        elif msg_type == "tool":
                            content = getattr(last_msg, "content", "") or (last_msg.get("content") if isinstance(last_msg, dict) else "")
                            print(f" -> [WYNIK]: {content}\n")

if __name__ == "__main__":
    main()
