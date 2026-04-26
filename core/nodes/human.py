from core.state import AgentState

def human_approval_node(state: AgentState) -> dict:
    """
    Punkt kontrolny HITL. Resetuje stan wykonawczy przed kolejnym zadaniem.
    """
    return {
        "current_iteration": 0,
        "execution_logs": [] # Czyszczenie logów dzięki nowemu reducerowi w state.py
    }
