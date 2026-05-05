import os
import sys

sys.path.append(os.getcwd())

from langgraph.checkpoint.sqlite import SqliteSaver
from core.graph import create_graph

db_path = r'workspaces\ai_house_web\state.db'
thread_id = "thread_ai_house_web"
config = {"configurable": {"thread_id": thread_id}}

print(f"[*] Opening database: {db_path}")

with SqliteSaver.from_conn_string(db_path) as saver:
    graph = create_graph(checkpointer=saver)
    state = graph.get_state(config)
    
    if not state or not state.values:
        print("[-] No state found.")
        sys.exit(1)
    
    messages = state.values.get("messages", [])
    print(f"[*] Current message count: {len(messages)}")
    
    if len(messages) > 10:
        graph.update_state(config, {"messages": messages[-10:]})
        print(f"[+] Truncated to 10 messages.")
    else:
        print("[!] Already short enough.")

print("[*] Done.")
