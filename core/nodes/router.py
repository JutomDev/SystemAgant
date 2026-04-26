from core.state import AgentState

def router_node(state: AgentState) -> dict:
    """
    Węzeł Routera. Pełni rolę silnika reguł do zarządzania cyklem życia projektu.
    """
    wbs = state.get("wbs",[])
    current_phase = state.get("current_phase", "brainstorming")
    
    if not wbs:
        return {"current_phase": "brainstorming"}
        
    # Jeśli jesteśmy w fazie koncepcyjnej, a Architekt wygenerował WBS -> wymuszamy akceptację
    if current_phase == "brainstorming" and wbs:
        return {"current_phase": "hitl_approval"}
        
    if current_phase == "hitl_approval":
        return {"current_phase": "execution"}
        
    # Skanowanie WBS w poszukiwaniu nieukończonych zadań
    pending_tasks = False
    for epic in wbs:
        tasks = epic.get("tasks", []) if isinstance(epic, dict) else getattr(epic, "tasks",[])
        for task in tasks:
            status = task.get("status") if isinstance(task, dict) else getattr(task, "status", "pending")
            if status in ["pending", "in_progress", "failed"]:
                pending_tasks = True
                break
        if pending_tasks:
            break
            
    # Jeśli jesteśmy w fazie wykonawczej i nie ma zadań do zrobienia -> projekt ukończony
    if current_phase == "execution" and not pending_tasks:
        return {"current_phase": "completed"}
        
    return {}
