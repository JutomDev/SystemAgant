from core.state import AgentState

def router_node(state: AgentState) -> dict:
    """
    Router node. Acts as a rule engine for managing the project lifecycle.
    """
    wbs = state.get("wbs", [])
    current_phase = state.get("current_phase", "brainstorming")
    
    # 1. Scan WBS for incomplete tasks and select the active task
    pending_tasks = False
    next_task_id = None
    
    for epic in wbs:
        tasks = epic.get("tasks", []) if isinstance(epic, dict) else getattr(epic, "tasks", [])
        for task in tasks:
            status = task.get("status") if isinstance(task, dict) else getattr(task, "status", "pending")
            tid = task.get("task_id") if isinstance(task, dict) else getattr(task, "task_id", None)
            
            if status in ["pending", "in_progress", "failed"]:
                pending_tasks = True
                if not next_task_id:
                    next_task_id = tid
                break
        if next_task_id:
            break

    # 2. Phase transition logic (MODULE 3: Milestone-Based HITL)
    if not wbs:
        return {"current_phase": "brainstorming", "current_task_id": None}
        
    # Check if the current Epic (first incomplete) just finished
    # Logic: Look for an Epic with all tasks 'completed',
    # while the system is still in 'execution' phase.
    all_epics_completed = True
    
    for epic in wbs:
        tasks = epic.get("tasks", []) if isinstance(epic, dict) else getattr(epic, "tasks", [])
        epic_done = all((t.get("status") == "completed" if isinstance(t, dict) else t.status == "completed") for t in tasks)
        
        if not epic_done:
            all_epics_completed = False
            break
        # If an epic is done but phase hasn't been marked 'completed' yet,
        # it means we likely just finished it.
    
    # 3. Phase management
    messages = state.get("messages", [])
    if current_phase == "completed" and messages:
        last_msg = messages[-1]
        msg_type = getattr(last_msg, "type", None) or (last_msg.get("type") if isinstance(last_msg, dict) else None)
        if msg_type == "human":
            return {"current_phase": "brainstorming", "current_task_id": None}

    if current_phase == "brainstorming" and wbs:
        return {"current_phase": "hitl_approval", "current_task_id": next_task_id}
        
    if current_phase == "hitl_approval":
        return {"current_phase": "execution", "current_task_id": next_task_id}

    if current_phase == "execution":
        if all_epics_completed:
            return {"current_phase": "completed", "current_task_id": None}
        
        # If a task finished and no more tasks remain in THIS Epic (next_task_id moved to a new Epic)
        # request milestone approval.
        # Requires comparing with the previous task_id. Simplified logic:
        # If previous and current task belong to different Epics -> HITL.
        prev_task_id = state.get("current_task_id")
        if prev_task_id and next_task_id and prev_task_id != next_task_id:
            # Check if prev_task_id and next_task_id belong to different Epics
            def get_epic_index(tid):
                for i, e in enumerate(wbs):
                    ts = e.get("tasks", []) if isinstance(e, dict) else getattr(e, "tasks", [])
                    if any((t.get("task_id") if isinstance(t, dict) else t.task_id) == tid for t in ts):
                        return i
                return -1
            
            if get_epic_index(prev_task_id) != get_epic_index(next_task_id):
                return {"current_phase": "hitl_approval", "current_task_id": next_task_id}

    return {
        "current_task_id": next_task_id,
        "retry_count": 0,
        "consultation_retries": 0
    }
