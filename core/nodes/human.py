from core.state import AgentState
from langchain_core.messages import HumanMessage

def human_approval_node(state: AgentState) -> dict:
    """
    HITL checkpoint. Analyzes user input and transitions project phases.
    """
    messages = state.get("messages", [])
    last_human_msg = next((m.content for m in reversed(messages) if isinstance(m, HumanMessage)), "").upper()
    
    updates = {
        "current_iteration": 0,
        "execution_logs": [],
        "retry_count": 0,
        "consultation_retries": 0
    }
    
    # Plan/state approval logic
    if any(word in last_human_msg for word in ["ZATWIERDZAM", "START", "OK", "GO", "DAWAJ"]):
        updates["current_phase"] = "execution"
    elif any(word in last_human_msg for word in ["ODRZUĆ", "STOP", "POPRAW", "ZMIANA"]):
        updates["current_phase"] = "brainstorming"
        
    return updates
