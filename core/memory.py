from typing import List
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage

def filter_architect_messages(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    Filters the message history for the Architect.
    Removes successful technical tool calls but PRESERVES error reports
    so the Architect can diagnose what the Coder is struggling with.
    """
    filtered_messages = []
    coder_tools = {"read_file", "edit_file", "execute_subprocess", "start_background_server", "kill_process_on_port", "finish_task"}
    
    # Error indicators that signal the Architect should see this message
    error_indicators = ["Exit code: 1", "Exit code: 2", "Error", "Traceback", 
                        "failed", "FAILED", "error", "Exception", "SyntaxError",
                        "ModuleNotFoundError", "ImportError", "TypeError"]
    
    for msg in messages:
        # Skip messages with empty content (fixes Vertex AI 'at least one parts field' error)
        content = getattr(msg, "content", "")
        if isinstance(content, str) and not content.strip():
            continue
            
        if isinstance(msg, (HumanMessage, SystemMessage)):
            filtered_messages.append(msg)
        elif isinstance(msg, AIMessage):
            has_coder_tools = any(tc.get("name") in coder_tools for tc in msg.tool_calls)
            if not has_coder_tools:
                filtered_messages.append(msg)
        elif isinstance(msg, ToolMessage):
            # CRITICAL: Let error-containing ToolMessages through!
            # The Architect MUST see stack traces and error logs to help.
            msg_content = str(content)
            is_error = any(indicator in msg_content for indicator in error_indicators)
            if is_error:
                # Truncate to avoid token bloat, but preserve the essential error info
                truncated = msg_content[:1500] if len(msg_content) > 1500 else msg_content
                filtered_messages.append(ToolMessage(
                    content=f"[ERROR REPORT from Coder tool]: {truncated}",
                    tool_call_id=getattr(msg, "tool_call_id", "unknown"),
                    name=getattr(msg, "name", "unknown_tool")
                ))
        # Successful ToolMessages are still excluded (no noise)
        
    return filtered_messages

