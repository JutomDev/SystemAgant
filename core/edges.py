from typing import Literal
from core.state import AgentState

def router_condition(state: AgentState) -> Literal["architect", "coder", "human_approval", "end"]:
    phase = state.get("current_phase", "brainstorming")
    if phase in ["brainstorming", "planning"]: return "architect"
    elif phase == "execution": return "coder"
    elif phase == "hitl_approval": return "human_approval"
    return "end"

def tester_condition(state: AgentState) -> Literal["coder", "human_approval", "architect", "router"]:
    logs = state.get("execution_logs", [])
    if not logs:
        # Jeśli nie ma logów, a jesteśmy tu, to znaczy że albo wszystko ok, albo bot nic nie zrobił.
        # Bezpieczniej iść do użytkownika.
        return "human_approval"
        
    current_task_id = state.get("current_task_id")
    
    # Filtrujemy logi tylko dla bieżącego zadania
    current_logs = [
        l for l in logs 
        if (isinstance(l, dict) and l.get("task_id") == current_task_id) or 
           (hasattr(l, "task_id") and l.task_id == current_task_id)
    ]
    
    if not current_logs: 
        # Jeśli brak logów, traktujemy to jako błąd wykonania/brak akcji
        retry_count = state.get("retry_count", 0)
        if retry_count < 3:
            return "coder"
        return "architect"
        
    last_log = current_logs[-1]
    # Bezpieczna ekstrakcja dla dict i obiektów Pydantic
    exit_code = last_log.get("exit_code", 1) if isinstance(last_log, dict) else getattr(last_log, "exit_code", 1)
    command = last_log.get("command") if isinstance(last_log, dict) else getattr(last_log, "command", "")

    if exit_code == 0: 
        # Jeśli operacja się udała, pozwól botowi lecieć dalej do Routera, 
        # który zdecyduje czy jest coś jeszcze do roboty.
        return "router"
    elif command == "none":
        # Koder odpowiedział samym tekstem (brak tool_calls).
        # ZAWSZE oddajemy kontrolę użytkownikowi - zapobiega nieskończonej pętli.
        # Koder mógł zadać pytanie, zgłosić problem, lub po prostu nie wiedzieć co robić.
        return "human_approval"
    else:
        retry_count = state.get("retry_count", 0)
        max_retries = 3
        consultation_retries = state.get("consultation_retries", 0)
        
        if retry_count < max_retries:
            return "coder"
        elif consultation_retries < 1:
            return "architect"
        else:
            return "human_approval"

def human_approval_condition(state: AgentState) -> Literal["router", "architect", "end"]:
    phase = state.get("current_phase")
    if phase == "completed": return "end"
    elif phase == "planning_rejected": return "architect"
    return "router"
