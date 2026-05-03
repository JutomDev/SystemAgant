import sqlite3
import json
import os

db_path = r"c:\Users\Julek\Documents\SystemAgant\workspaces\test_kal\state.db"

if not os.path.exists(db_path):
    print("Database not found")
    exit()

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get the latest checkpoint
cursor.execute("SELECT checkpoint FROM checkpoints ORDER BY thread_id DESC, checkpoint_id DESC LIMIT 1")
row = cursor.fetchone()

if row:
    checkpoint = json.loads(row[0])
    # The messages are usually in channel_values
    messages = checkpoint.get("channel_values", {}).get("messages", [])
    for msg in messages[-5:]:
        print(f"--- {msg.get('type')} ---")
        print(f"Content: {msg.get('content')[:200]}")
        if msg.get('tool_calls'):
            print(f"Tool Calls: {msg.get('tool_calls')}")
else:
    print("No checkpoints found")

conn.close()
