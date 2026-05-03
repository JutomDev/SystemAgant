from typing import List
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

def filter_architect_messages(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    Filters the message history for the Architect.
    Removes technical Coder tool calls and their results to reduce noise.
    """
    filtered_messages = []
    coder_tools = {"read_file", "edit_file", "execute_subprocess"}
    
    for msg in messages:
        if isinstance(msg, (HumanMessage, SystemMessage)):
            filtered_messages.append(msg)
        elif isinstance(msg, AIMessage):
            has_coder_tools = any(tc.get("name") in coder_tools for tc in msg.tool_calls)
            if not has_coder_tools:
                filtered_messages.append(msg)
        # ToolMessages are intentionally excluded
        
    return filtered_messages
