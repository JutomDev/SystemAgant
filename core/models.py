from typing import List, Optional
from pydantic import BaseModel, Field

# --- DATA MODELS (PYDANTIC) ---

class ArchitectOutput(BaseModel):
    response: str = Field(description="Text response from the Architect to the user.")
    wbs: Optional[List['Epic']] = Field(default=None, description="Generated WBS plan (if required in this turn).")

class FileMetadata(BaseModel):
    path: str
    hash: str
    last_modified: float
    lines_count: int

class ExecutionLog(BaseModel):
    task_id: str
    command: str
    stdout: str
    stderr: str
    exit_code: int
    timestamp: float

class AtomicTask(BaseModel):
    task_id: str
    epic_id: str
    description: str
    target_files: List[str]
    status: str = Field(default="pending", description="pending | in_progress | completed | failed")

class Epic(BaseModel):
    epic_id: str
    description: str
    tasks: List[AtomicTask]