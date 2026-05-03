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
        "EXPLICIT OVER IMPLICIT: Always explain technical decisions in AI messages.",
        "FULL CI/CD AUTONOMY: You are fully authorized and REQUIRED to compile projects, build executables, and run build scripts (e.g., PyInstaller, build_exe.py) using the `execute_subprocess` tool. NEVER ask the user to run a script manually in the terminal if you can execute it yourself. You are responsible for delivering the final compiled artifact, not just the source code."
    ])
    project_directives: List[str] = Field(default_factory=list)

# --- STATE REDUCERS ---

def merge_file_system_state(left: Dict[str, FileMetadata], right: Dict[str, FileMetadata]) -> Dict[str, FileMetadata]:
    """Updates the file system state. New metadata overwrites the old for a given path key."""
    if not left:
        return right
    if not right:
        return left
    merged = left.copy()
    merged.update(right)
    return merged

def update_wbs(left: List[Epic], right: List[Epic]) -> List[Epic]:
    """
    Deep Merge for the Work Breakdown Structure.
    Updates existing Epics and Tasks based on their IDs instead of overwriting.
    Handles both Pydantic objects and plain dictionaries.
    """
    if not left: return right
    if not right: return left

    # Build a map of existing epics for fast lookup
    merged_epics = {
        (e.get("epic_id") if isinstance(e, dict) else getattr(e, "epic_id")): e
        for e in left
    }

    for new_epic in right:
        e_id = new_epic.get("epic_id") if isinstance(new_epic, dict) else getattr(new_epic, "epic_id")

        if e_id not in merged_epics:
            # New epic — simply add it
            merged_epics[e_id] = new_epic
        else:
            # Epic exists — merge tasks by task_id
            existing_epic = merged_epics[e_id]

            existing_tasks = existing_epic.get("tasks", []) if isinstance(existing_epic, dict) else getattr(existing_epic, "tasks", [])
            new_tasks = new_epic.get("tasks", []) if isinstance(new_epic, dict) else getattr(new_epic, "tasks", [])

            merged_tasks = {
                (t.get("task_id") if isinstance(t, dict) else getattr(t, "task_id")): t
                for t in existing_tasks
            }

            for new_task in new_tasks:
                t_id = new_task.get("task_id") if isinstance(new_task, dict) else getattr(new_task, "task_id")
                merged_tasks[t_id] = new_task

            # Write merged tasks back to the epic
            if isinstance(existing_epic, dict):
                existing_epic["tasks"] = list(merged_tasks.values())
            else:
                setattr(existing_epic, "tasks", list(merged_tasks.values()))

            merged_epics[e_id] = existing_epic

    return list(merged_epics.values())

def update_execution_logs(left: List[ExecutionLog], right: List[ExecutionLog]) -> List[ExecutionLog]:
    """
    Allows appending logs or resetting them (if an empty list is provided).
    """
    if right == []: # Explicit reset
        return []
    return (left or []) + (right or [])

# --- MAIN LANGGRAPH STATE (TYPEDDICT) ---

class AgentState(TypedDict):
    # 1. Conversation and tool call history (LangGraph standard)
    messages: Annotated[List[BaseMessage], add_messages]
    
    # 2. Project context (established during the Brainstorming phase)
    project_context: str
    
    # 3. Hierarchical Work Breakdown Structure (WBS)
    wbs: Annotated[List[Epic], update_wbs]
    
    # 4. Pointer to the currently executing atomic task ID
    current_task_id: Optional[str]
    
    # 5. File system state (mapping: path -> metadata)
    file_system_state: Annotated[Dict[str, FileMetadata], merge_file_system_state]
    
    # 6. Tester process logs (stderr/stdout) - appended to the list
    execution_logs: Annotated[List[ExecutionLog], update_execution_logs]
    
    # 7. Loop control (prevents infinite iterations between Coder <-> Tester)
    current_iteration: int
    max_iterations: int
    
    # 8. Lifecycle phase (e.g., "brainstorming", "planning", "execution", "hitl_approval")
    current_phase: str
    workspace_path: str
    
    # 9. Escalation loop control
    retry_count: int
    consultation_retries: int
    
    # 10. Guiding Principles
    guiding_principles: dict
