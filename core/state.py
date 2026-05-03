import operator
from typing import TypedDict, Annotated, List, Dict, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from core.models import FileMetadata, ExecutionLog, Epic
from pydantic import BaseModel, Field

class GuidingPrinciples(BaseModel):
    core_constitution: List[str] = Field(default_factory=lambda: [
        "STRICLY SEPARATION OF CONCERNS: Architect plans, Coder implements intent, Tester executes tools.",
        "ZERO TOLERANCE FOR SYNTAX ERRORS: Always validate code before proposing.",
        "SECURITY FIRST: Use safe subprocess calls and validated paths.",
        "MODULARITY: Prefer small, single-purpose functions and files.",
        "EXPLICIT OVER IMPLICIT: Always explain technical decisions in AI messages."
    ])
    project_directives: List[str] = Field(default_factory=list)

# --- FUNKCJE REDUKUJĄCE (REDUCERS) ---

def merge_file_system_state(left: Dict[str, FileMetadata], right: Dict[str, FileMetadata]) -> Dict[str, FileMetadata]:
    """Aktualizuje stan systemu plików. Nowe metadane nadpisują stare dla danego klucza (ścieżki)."""
    if not left:
        return right
    if not right:
        return left
    merged = left.copy()
    merged.update(right)
    return merged

def update_wbs(left: List[Epic], right: List[Epic]) -> List[Epic]:
    """
    Aktualizuje Work Breakdown Structure. 
    Wymaga logiki nadpisującej konkretne Epiki/Zadania na podstawie ich ID.
    """
    if not left:
        return right
    return right

def update_execution_logs(left: List[ExecutionLog], right: List[ExecutionLog]) -> List[ExecutionLog]:
    """
    Umożliwia dodawanie logów lub ich resetowanie (jeśli przekazano pustą listę).
    """
    if right == []: # Jawny reset
        return []
    return (left or []) + (right or [])

# --- GŁÓWNY STAN LANGGRAPH (TYPEDDICT) ---

class AgentState(TypedDict):
    # 1. Historia konwersacji i wywołań narzędzi (standard LangGraph)
    messages: Annotated[List[BaseMessage], add_messages]
    
    # 2. Kontekst projektu (ustalany w fazie Brainstormingu)
    project_context: str
    
    # 3. Hierarchiczny plan pracy (WBS)
    wbs: Annotated[List[Epic], update_wbs]
    
    # 4. Wskaźnik na aktualnie wykonywane zadanie atomowe
    current_task_id: Optional[str]
    
    # 5. Stan systemu plików (mapowanie: ścieżka -> metadane)
    file_system_state: Annotated[Dict[str, FileMetadata], merge_file_system_state]
    
    # 6. Logi z procesu Testera (stderr/stdout) - dodawane do listy
    execution_logs: Annotated[List[ExecutionLog], update_execution_logs]
    
    # 7. Kontrola pętli (zapobieganie nieskończonym iteracjom Koder <-> Tester)
    current_iteration: int
    max_iterations: int
    
    # 8. Faza cyklu życia (np. "brainstorming", "planning", "execution", "hitl_approval")
    current_phase: str
    workspace_path: str
    
    # 9. Kontrola pętli eskalacji
    retry_count: int
    consultation_retries: int
    
    # 10. Zasady projektowe (Guiding Principles)
    guiding_principles: dict
