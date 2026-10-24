"""Fakes and test doubles for SystemAgant unit tests.

These deterministic mock runnables allow offline testing with 0 tokens and no API dependencies.
"""

from typing import Any, List, Optional
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from core.models import ArchitectOutput, AtomicTask, Epic


class FakeArchitectStructured(Runnable):
    """Test fake returning a deterministic WBS."""

    def __init__(self, target_schema: Any = None):
        super().__init__()
        self.target_schema = target_schema

    def with_structured_output(self, schema: Any) -> "FakeArchitectStructured":
        return FakeArchitectStructured(target_schema=schema)

    def invoke(self, input: Any, config: Optional[Any] = None) -> Any:
        return ArchitectOutput(
            response="Architecture strategy verified. WBS synthesized.",
            wbs=[
                Epic(
                    epic_id="EPIC_1",
                    description="Initialize project baseline and state management.",
                    tasks=[
                        AtomicTask(
                            task_id="TASK_1_1",
                            epic_id="EPIC_1",
                            description="Implement index file",
                            target_files=["index.html"],
                            status="pending",
                        ),
                        AtomicTask(
                            task_id="TASK_1_2",
                            epic_id="EPIC_1",
                            description="Implement styles",
                            target_files=["style.css"],
                            status="pending",
                        ),
                    ],
                )
            ],
        )


class FakeCoderLLM(Runnable):
    """Test fake generating deterministic tool calls."""

    def __init__(self) -> None:
        super().__init__()
        self.tools: List[Any] = []

    def bind_tools(self, tools: List[Any], **kwargs: Any) -> "FakeCoderLLM":
        clone = FakeCoderLLM()
        clone.tools = tools
        return clone

    def invoke(self, input: Any, config: Optional[Any] = None) -> AIMessage:
        return AIMessage(
            content="Creating index.html file",
            tool_calls=[
                {
                    "name": "edit_file",
                    "args": {
                        "path": "index.html",
                        "diff_instructions": "<!DOCTYPE html><html><body><h1>Test</h1></body></html>",
                        "overwrite": True,
                    },
                    "id": "call_fake_001",
                }
            ],
        )
