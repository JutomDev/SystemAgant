from langgraph.graph import StateGraph, START, END
from core.state import AgentState
from core.nodes.router import router_node
from core.nodes.architect import architect_node
from core.nodes.coder import coder_node
from core.nodes.tester import tester_node
from core.nodes.human import human_approval_node
from core.edges import router_condition, tester_condition, human_approval_condition

def architect_condition(state: AgentState):
    # Jeśli jesteśmy w fazie burzy mózgów, wracamy do użytkownika (END), by mógł odpowiedzieć
    if state.get("current_phase", "brainstorming") == "brainstorming":
        return "end"
        
    # Powrót z konsultacji do Kodera
    if state.get("current_phase") == "execution" and state.get("consultation_retries", 0) > 0:
        return "coder"
        
    # Jeśli Architekt wygenerował WBS, idziemy po akceptację
    return "human_approval"

def create_graph(checkpointer=None):
    workflow = StateGraph(AgentState)
    
    workflow.add_node("router", router_node)
    workflow.add_node("architect", architect_node)
    workflow.add_node("coder", coder_node)
    workflow.add_node("tester", tester_node)
    workflow.add_node("human_approval", human_approval_node)
    
    workflow.add_edge(START, "router")
    
    workflow.add_conditional_edges(
        "router",
        router_condition,
        {
            "architect": "architect",
            "coder": "coder",
            "human_approval": "human_approval",
            "end": END
        }
    )
    
    workflow.add_conditional_edges(
        "architect", 
        architect_condition,
        {
            "human_approval": "human_approval",
            "coder": "coder",
            "end": END
        }
    )
    workflow.add_edge("coder", "tester")
    
    workflow.add_conditional_edges(
        "tester",
        tester_condition,
        {
            "coder": "coder",
            "architect": "architect",
            "human_approval": "human_approval",
            "router": "router"
        }
    )
    
    workflow.add_conditional_edges(
        "human_approval",
        human_approval_condition,
        {
            "router": "router",
            "architect": "architect",
            "end": END
        }
    )
    
    # Kompilacja grafu z wbudowanym mechanizmem przerwań (HITL)
    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_approval"]
    )
