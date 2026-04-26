import os
import sys
import logging
import logging.config
from pathlib import Path
from uuid import uuid4
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_vertexai import ChatVertexAI
from core.graph import create_graph

# Inicjalizacja modelu PRO dla głębokich podsumowań HITL
pro_communicator = ChatVertexAI(model_name="gemini-3.1-pro-preview", location="global", project="nifty-saga-493918-c8", temperature=0.2)

def generate_pro_hitl_summary(state_values: dict) -> str:
    # Zbuduj kontekst z WBS, ostatnich logów i fazy
    context = f"Faza: {state_values.get('current_phase')}, WBS: {state_values.get('wbs')}, Consultations: {state_values.get('consultation_retries')}"
    prompt = SystemMessage(content="Jesteś Architektem Projektu. Podsumuj merytorycznie obecny stan prac, wskaż z czym jest problem (jeśli eskalowano błąd) i jasno określ, jakiej decyzji oczekujesz od użytkownika. Bądź zwięzły, profesjonalny i techniczny.")
    
    response = pro_communicator.invoke([prompt, HumanMessage(content=context)])
    return f"\n=== RAPORT ARCHITEKTA ===\n{response.content}\n=========================\n"
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
    
    # NAPRAWA: Otwarcie bazy przez Context Manager
    with SqliteSaver.from_conn_string(str(db_path)) as memory:
        graph = create_graph(checkpointer=memory)
        
        thread_id = f"thread_{project_name}"
        config = {"configurable": {"thread_id": thread_id}}
        
        # Wstrzyknięcie folderu roboczego do stanu na starcie!
        graph.update_state(config, {"workspace_path": str(workspace_path)})
        
        print("Wpisz 'exit' lub 'quit' aby zakończyć.\n")
        
        while True:
            state = graph.get_state(config)
            
            if state.next and "human_approval" in state.next:
                print("\n[HITL] SYSTEM OCZEKUJE NA DECYZJĘ STRATEGICZNĄ.")
                print("Architekt przygotowuje raport stanu...")
                try:
                    summary = generate_pro_hitl_summary(graph.get_state(config).values)
                    print(summary)
                except Exception as e:
                    print(f"\n[BŁĄD RAPORTU]: {e}")
                
                user_input = input("Wpisz 'ZATWIERDZAM' lub podaj instrukcje/nowe dyrektywy: ").strip()
                
                if user_input.lower() in ['exit', 'quit']: sys.exit(0)
                    
                if user_input.upper() == "ZATWIERDZAM":
                    events = graph.stream(None, config, stream_mode="updates")
                else:
                    graph.update_state(config, {"messages": [HumanMessage(content=user_input)]})
                    events = graph.stream(None, config, stream_mode="updates")
            else:
                user_input = input("\nUżytkownik: ").strip()
                if user_input.lower() in ['exit', 'quit']: sys.exit(0)
                if not user_input: continue
                    
                events = graph.stream({"messages": [HumanMessage(content=user_input)]}, config, stream_mode="updates")
            
            for event in events:
                for node_name, node_state in event.items():
                    print(f" -> [Wykonano: {node_name}]")
                    
                    # NOWE: Drukowanie wiadomości od AI
                    if node_state and "messages" in node_state and node_state["messages"]:
                        last_msg = node_state["messages"][-1]
                        # Sprawdzamy czy to AI i czy wiadomość ma tekst
                        if last_msg.type == "ai" and last_msg.content:
                            print(f"\n[AI {node_name.upper()}]: {last_msg.content}\n")

if __name__ == "__main__":
    main()
