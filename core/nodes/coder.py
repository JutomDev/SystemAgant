import platform
from pathlib import Path
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from core.state import AgentState
from core.tools.fs_tools import read_file, edit_file
from core.tools.sys_tools import execute_subprocess, finish_task, start_background_server, kill_process_on_port
from core.llm_factory import get_coder_llm
from core.repo_map import generate_repo_map

from typing import Any, Dict, List, Union


def sanitize_history(messages: List[Union[BaseMessage, Dict[str, Any]]]) -> List[BaseMessage]:
    """Sanitizes conversation history to prevent LLM API protocol violations.

    Google GenAI and Vertex AI require strict 1-to-1 parity between tool_calls
    and ToolMessages. This function repairs broken turns by injecting synthetic
    closures for any orphaned tool calls before invocation.
    """
    sanitized: List[BaseMessage] = []
    pending_tool_calls: Dict[str, Dict[str, Any]] = {}
    
    for msg in messages:
        msg_type = getattr(msg, "type", None) or (msg.get("type") if isinstance(msg, dict) else None)
        
        if msg_type == "ai":
            # Close old unanswered tool calls
            for tid in list(pending_tool_calls.keys()):
                tc_name = pending_tool_calls[tid].get("name", "unknown_tool")
                sanitized.append(ToolMessage(content="System: Tool interrupted by new AI message.", tool_call_id=tid, name=tc_name))
                del pending_tool_calls[tid]
                
            tool_calls = getattr(msg, "tool_calls", []) or (msg.get("tool_calls") if isinstance(msg, dict) else [])
            if tool_calls:
                pending_tool_calls = {tc["id"]: tc for tc in tool_calls}
            sanitized.append(msg)
            
        elif msg_type == "tool":
            tid = getattr(msg, "tool_call_id", None) or (msg.get("tool_call_id") if isinstance(msg, dict) else None)
            if tid in pending_tool_calls:
                del pending_tool_calls[tid]
            sanitized.append(msg)
            
        else:
            # HumanMessage / SystemMessage
            # Close old unanswered tool calls BEFORE adding this message
            for tid in list(pending_tool_calls.keys()):
                tc_name = pending_tool_calls[tid].get("name", "unknown_tool")
                sanitized.append(ToolMessage(content="System: Tool bypassed by intervention.", tool_call_id=tid, name=tc_name))
                del pending_tool_calls[tid]
            sanitized.append(msg)
            
    # Close anything remaining at the end (e.g., Tester was interrupted mid-turn)
    for tid in list(pending_tool_calls.keys()):
        tc_name = pending_tool_calls[tid].get("name", "unknown_tool")
        sanitized.append(ToolMessage(content="System: Tool execution pending/bypassed.", tool_call_id=tid, name=tc_name))
        
    return sanitized

def coder_node(state: AgentState) -> dict:
    principles = state.get("guiding_principles", {"core_constitution": [], "project_directives":[]})
    os_info = platform.system()
    sys_instruct = rf"""<role>You are a Senior Software Engineer with FULL CI/CD AUTONOMY.</role>
<environment>OPERATING SYSTEM: {os_info}</environment>
<core_constitution>\n{principles.get('core_constitution')}\n</core_constitution>
<project_directives>\n{principles.get('project_directives')}\n</project_directives>

<operating_modes>
MODE 1: EXECUTION & DEBUGGING (Default)
- SILENT EXECUTION: You are a machine. DO NOT output conversational text, explanations, or apologies. Your ONLY output should be Tool Calls.
- BATCH EDITS: When using `edit_file`, DO NOT make single small edits. You MUST group multiple changes into a single tool call by providing multiple `<<<< SEARCH ==== >>>> REPLACE` blocks in the `diff_instructions`.
- TEST-DRIVEN DEVELOPMENT: After editing a file, you MUST run tests or compile the code using `execute_subprocess` BEFORE editing another file. Do not fly blind.
- CRITICAL: Use `start_background_server` for long-running processes (FastAPI, Next.js, etc.).
- If a port is blocked, use `kill_process_on_port` immediately.

MODE 2: TASK COMPLETION
- When tests pass and requirements are met, you MUST call `finish_task`.
- Provide a brief summary of what was done. This is the ONLY way to mark a task as COMPLETED.

MODE 3: HUMAN CONVERSATION
- If the User asks a direct question or gives a "STOP" command, reply in PLAIN TEXT.
- Be concise. Do not use tools in this mode.
</operating_modes>

<critical_rules>
- NEVER hallucinate tools.
- OVERWRITE MODE: If you need to REPLACE THE ENTIRE CONTENT of an existing file, call `edit_file` with `overwrite=True`. The `diff_instructions` will become the new file content directly. Use this instead of trying to match SEARCH blocks for full rewrites.
- PREFER SURGICAL EDITS: For small changes to existing files, use SEARCH/REPLACE blocks in `edit_file` (overwrite=False, the default).
- ANTI-LOOP RULE (MANDATORY): If you have called `dir` or `read_file` more than 2 times in a row without calling `edit_file` or `execute_subprocess`, you are STUCK IN A LOOP. You MUST immediately use `edit_file` with `overwrite=True` to write the file, or call `finish_task` to end the task. NEVER call read_file more than twice consecutively.
- IMAGE ASSETS: When generating HTML pages requiring photos, use valid Unsplash image URLs (e.g. https://images.unsplash.com/photo-1563245372-f21724e3856d?auto=format&fit=crop&w=800&q=80) with semantic alt attributes.
</critical_rules>"""

    current_task_id = state.get("current_task_id")
    if current_task_id:
        sys_instruct += f"\n<active_task>ACTIVE TASK TO IMPLEMENT: {current_task_id}</active_task>"

    w_path = state.get("workspace_path")
    if w_path:
        rmap = generate_repo_map(Path(w_path))
        if rmap:
            sys_instruct += f"\n<repository_map>\n{rmap}\n</repository_map>"

    llm = get_coder_llm()
    tools = [read_file, edit_file, execute_subprocess, start_background_server, kill_process_on_port, finish_task]
    llm_with_tools = llm.bind_tools(tools, tool_choice="auto", parallel_tool_calls=False)
    
    messages = state.get("messages",[]).copy()
    logs = state.get("execution_logs",[])
    current_iteration = state.get("current_iteration", 0)
    
    if logs and current_iteration > 0:
        last_log = logs[-1]
        exit_code = last_log.get("exit_code", 1) if isinstance(last_log, dict) else getattr(last_log, "exit_code", 1)
        
        if exit_code != 0:
            stderr = last_log.get("stderr", "") if isinstance(last_log, dict) else getattr(last_log, "stderr", "")
            
            # Force a code fix instead of an artificial ToolMessage
            messages.append(HumanMessage(
                content=f"CRITICAL FIX REQUIRED: The previous tool operation (Exit Code {exit_code}) failed.\nDetails: {stderr}\nAnalyze the tool response in history and IMMEDIATELY fix this error by generating a correct tool call."
            ))

    # 1. Sanitize the history and remove empty messages (prevents 400 error)
    safe_messages = sanitize_history(messages)
    coder_system_msg = SystemMessage(content=sys_instruct)
    final_messages = [coder_system_msg]
    for m in safe_messages:
        # Model protocol requires either text content or a tool_calls payload
        m_content = getattr(m, "content", "")
        m_tools = getattr(m, "tool_calls", [])
        if m_content or m_tools:
            final_messages.append(m)
        elif isinstance(m, ToolMessage):
            # ToolMessage must be retained to maintain request-response symmetry in API protocol
            if not getattr(m, "name", None):
                m = ToolMessage(content=m.content or "[empty]", tool_call_id=m.tool_call_id, name="unknown_tool")
            final_messages.append(m)

    # 2. Invoke the model
    response = llm_with_tools.invoke(final_messages)
    
    wbs_list = state.get("wbs",[])
    updated_wbs = wbs_list.copy() if isinstance(wbs_list, list) else[]
    current_task_id = state.get("current_task_id")
    
    if current_task_id:
        for epic in updated_wbs:
            tasks = epic.tasks if hasattr(epic, 'tasks') else epic.get('tasks',[])
            for task in tasks:
                tid = task.task_id if hasattr(task, 'task_id') else task.get('task_id')
                if tid == current_task_id:
                    if hasattr(task, 'status'): task.status = 'in_progress'
                    else: task['status'] = 'in_progress'
                    break

    return {
        "messages": [response],
        "wbs": updated_wbs,
        "current_iteration": current_iteration + 1
    }
