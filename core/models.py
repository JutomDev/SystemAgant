"""Domain Models and Structured Schemas for SystemAgant.

Defines Pydantic v2 models for:
1. Structured outputs from planning nodes (ArchitectOutput, Epic, AtomicTask).
2. File system metadata tracking (FileMetadata).
3. Sandboxed subprocess telemetry logs (ExecutionLog).
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class ArchitectOutput(BaseModel):
    """Structured response schema returned by the Architect planning node."""

    response: str = Field(
        description="Conversational or technical response from the Architect to the user."
    )
    wbs: Optional[List["Epic"]] = Field(
        default=None,
        description="Synthesized hierarchical Work Breakdown Structure containing Epics and Atomic Tasks.",
    )


class FileMetadata(BaseModel):
    """Cryptographic and temporal metadata tracking file system state."""

    path: str = Field(description="Relative path of the tracked file within workspace.")
    hash: str = Field(description="SHA-256 digest of file contents for change detection.")
    last_modified: float = Field(description="POSIX epoch timestamp of last file modification.")
    lines_count: int = Field(description="Total line count of the source file.")


class ExecutionLog(BaseModel):
    """Standardized record of a sandboxed subprocess execution."""

    task_id: str = Field(description="Identifier of the task executing this subprocess.")
    command: str = Field(description="Exact shell command executed.")
    stdout: str = Field(description="Standard output stream captured during execution.")
    stderr: str = Field(description="Standard error stream captured during execution.")
    exit_code: int = Field(description="Process return code (0 indicates success).")
    timestamp: float = Field(description="POSIX epoch timestamp when execution started.")


class AtomicTask(BaseModel):
    """Discrete, single-purpose unit of implementation executed by the Coder."""

    task_id: str = Field(description="Deterministic task identifier, e.g., 'TASK_1_1'.")
    epic_id: str = Field(description="Parent Epic identifier to which this task belongs.")
    description: str = Field(description="Actionable technical description of changes required.")
    target_files: List[str] = Field(description="List of file paths modified or created by this task.")
    status: str = Field(
        default="pending",
        description="Lifecycle state: 'pending', 'in_progress', 'completed', or 'failed'.",
    )


class Epic(BaseModel):
    """High-level architectural milestone grouping related atomic tasks."""

    epic_id: str = Field(description="Deterministic epic identifier, e.g., 'EPIC_1'.")
    description: str = Field(description="Milestone summary describing the subsystem being delivered.")
    tasks: List[AtomicTask] = Field(description="Ordered sequence of atomic implementation tasks.")