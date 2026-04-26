from typing import Literal
from core.state import AgentState

def router_condition(state: AgentState) -> Literal["architect", "coder", "human_approval", "end"]:
    phase = state.get("current_phase", "brainstorming")
    if phase in ["brainstorming", "planning"]: return "architect"
    elif phase == "execution": return "coder"
    elif phase == "hitl_approval": return "human_approval"
    return "end"

def tester_condition(state: AgentState) -> Literal["coder", "human_approval", "architect"]:
    logs = state.get("execution_logs", [])
    if not logs: return "human_approval"
    last_log = logs[-1]
    # Bezpieczna ekstrakcja dla dict i obiektów Pydantic
    exit_code = last_log.get("exit_code", 1) if isinstance(last_log, dict) else getattr(last_log, "exit_code", 1)
    if exit_code == 0: return "human_approval"
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
