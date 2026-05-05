from typing import Literal
from core.state import AgentState
from langchain_core.messages import AIMessage

def router_condition(state: AgentState) -> Literal["architect", "coder", "human_approval", "end"]:
    phase = state.get("current_phase", "brainstorming")
    if phase in ["brainstorming", "planning"]: return "architect"
    elif phase == "execution": return "coder"
    elif phase == "hitl_approval": return "human_approval"
    return "end"

def tester_condition(state: AgentState) -> Literal["coder", "human_approval", "architect", "router"]:
    messages = state.get("messages", [])
    
    # HARD SAFETY LIMIT: If the agent has been looping for more than 20 iterations
    # on a single task, force escalation to human regardless of state.
    current_iteration = state.get("current_iteration", 0)
    if current_iteration > 20:
        return "human_approval"
    
    if not messages:
        return "coder"

    # Find the last message from AI (Coder)
    last_ai_message = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    
    # Check if the Coder called any tools
    has_tool_calls = bool(last_ai_message and getattr(last_ai_message, "tool_calls", []))

    retry_count = state.get("retry_count", 0)
    max_retries = 3
    consultation_retries = state.get("consultation_retries", 0)
    max_consultations = 3 # L3: Limit of consultations with the Architect

    if not has_tool_calls:
        # Coder returned only text (stuck or asking for help)
        if consultation_retries < max_consultations:
            return "architect" # L2: Escalation to Architect
        else:
            return "human_approval" # L3: Escalation to human

    # Coder used tools. Checking logs.
    logs = state.get("execution_logs", [])
    current_task_id = state.get("current_task_id")
    
    current_logs = [
        l for l in logs 
        if (isinstance(l, dict) and l.get("task_id") == current_task_id) or 
           (hasattr(l, "task_id") and getattr(l, "task_id") == current_task_id)
    ]
    
    if not current_logs: 
        # Tools called, but no logs (e.g., only read_file). Return to Coder.
        if retry_count < max_retries:
            return "coder"
        return "architect"
        
    last_log = current_logs[-1]
    exit_code = last_log.get("exit_code", 1) if isinstance(last_log, dict) else getattr(last_log, "exit_code", 1)

    if exit_code == 0: 
        # Success!
        return "router"
    
    # Tool returned an error.
    if retry_count < max_retries:
        return "coder" # L1: Coder tries to fix the error themselves
    elif consultation_retries < max_consultations:
        return "architect" # L2: Coder couldn't handle it, escalation to Architect
    else:
        return "human_approval" # L3: Architect didn't help either, escalation to human

def human_approval_condition(state: AgentState) -> Literal["router", "architect", "end"]:
    phase = state.get("current_phase")
    if phase == "completed": return "end"
    elif phase == "planning_rejected": return "architect"
    return "router"
