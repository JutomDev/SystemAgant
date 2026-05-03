from langgraph.checkpoint.sqlite import SqliteSaver
import sqlite3

db_path = r"c:\Users\Julek\Documents\SystemAgant\workspaces\test_kal\state.db"

with sqlite3.connect(db_path) as conn:
    saver = SqliteSaver(conn)
    # Pobierz najnowszy stan dla domyślnego projektu
    config = {"configurable": {"thread_id": "thread_test_kal"}}
    state = saver.get(config)
    
    if state:
        values = state.get("values", {})
        wbs = values.get("wbs", [])
        print(f"PHASE: {values.get('current_phase')}")
        print(f"CURRENT TASK: {values.get('current_task_id')}")
        print("WBS STATUS:")
        for epic in wbs:
            e_title = epic.get('title', 'No Title')
            print(f" Epic: {e_title}")
            tasks = epic.get('tasks', [])
            for t in tasks:
                t_id = t.get('task_id', 'No ID')
                t_status = t.get('status', 'No Status')
                print(f"   - {t_id}: {t_status}")
    else:
        print("No state found for thread 'default_bot'.")
