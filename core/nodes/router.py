from core.state import AgentState

def router_node(state: AgentState) -> dict:
    """
    Węzeł Routera. Pełni rolę silnika reguł do zarządzania cyklem życia projektu.
    """
    wbs = state.get("wbs", [])
    current_phase = state.get("current_phase", "brainstorming")
    
    # 1. Skanowanie WBS w poszukiwaniu nieukończonych zadań i wybór aktywnego zadania
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

    # 2. Logika przejść faz (MODUŁ 3: Milestone-Based HITL)
    if not wbs:
        return {"current_phase": "brainstorming", "current_task_id": None}
        
    # Sprawdzamy, czy aktualny Epik (pierwszy nieukończony) właśnie się skończył
    # Logika: Szukamy Epiku, który ma wszystkie zadania 'completed', 
    # ale system wciąż jest w fazie 'execution'.
    all_epics_completed = True
    epic_just_finished = False
    
    for epic in wbs:
        tasks = epic.get("tasks", []) if isinstance(epic, dict) else getattr(epic, "tasks", [])
        epic_done = all((t.get("status") == "completed" if isinstance(t, dict) else t.status == "completed") for t in tasks)
        
        if not epic_done:
            all_epics_completed = False
            break
        # Jeśli epik jest skończony, ale nie ma jeszcze 'completed' fazy, 
        # to znaczy, że prawdopodobnie właśnie go skończyliśmy.
    
    # 3. Zarządzanie fazami
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
        
        # Jeśli skończyliśmy zadanie i nie ma więcej zadań w TYM Epiku (next_task_id przesunął się do nowego Epiku)
        # to prosimy o akceptację kamienia milowego.
        # Wymaga to porównania z poprzednim task_id, ale możemy uprościć:
        # Jeśli poprzednie zadanie było w innym epiku niż obecne -> HITL.
        prev_task_id = state.get("current_task_id")
        if prev_task_id and next_task_id and prev_task_id != next_task_id:
            # Sprawdzamy czy prev_task_id i next_task_id należą do różnych epików
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
        "retry_count": 0
    }
