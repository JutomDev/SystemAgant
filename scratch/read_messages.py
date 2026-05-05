from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3
import sys

def read_messages(db_path, thread_id):
    with sqlite3.connect(db_path) as conn:
        saver = SqliteSaver(conn)
        config = {"configurable": {"thread_id": thread_id}}
        checkpoint_tuple = saver.get(config)
        
        if not checkpoint_tuple:
            print(f"No state for {thread_id}")
            return
            
        # checkpoint_tuple is (checkpoint, metadata, parent_config)
        checkpoint = checkpoint_tuple['checkpoint']
        messages = checkpoint.get('channel_values', {}).get('messages', [])
        
        print(f"=== MESSAGES FOR {thread_id} ({len(messages)}) ===")
        for m in messages[-5:]:
            print(f"[{m.type.upper()}]: {m.content[:200]}...")

if __name__ == "__main__":
    read_messages(sys.argv[1], sys.argv[2])
