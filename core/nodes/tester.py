import time
from langchain_core.messages import AIMessage, ToolMessage, RemoveMessage
from core.state import AgentState
from core.tools.fs_tools import read_file, edit_file
from core.tools.sys_tools import execute_subprocess, finish_task, start_background_server, kill_process_on_port

def tester_node(state: AgentState) -> dict:
    messages = state.get("messages",[])
    if not messages: return {}
        
    # 1. Find the last AI message that contains tool_calls
    last_ai_message = None
    for m in reversed(messages):
        m_type = getattr(m, "type", None) or (m.get("type") if isinstance(m, dict) else None)
        tool_calls = getattr(m, "tool_calls", None) or (m.get("tool_calls") if isinstance(m, dict) else None)
        if m_type == "ai" and tool_calls:
            last_ai_message = m
            break
            
    if not last_ai_message:
        return {}

    # 2. Get IDs of tools that already have responses in this specific turn
    # Only look for ToolMessages that appeared AFTER last_ai_message
    last_ai_idx = messages.index(last_ai_message)
    already_responded_ids = set()
    for m in messages[last_ai_idx+1:]:
        m_type = getattr(m, "type", None) or (m.get("type") if isinstance(m, dict) else None)
        if m_type == "tool":
            tid = getattr(m, "tool_call_id", None) or (m.get("tool_call_id") if isinstance(m, dict) else None)
            if tid: already_responded_ids.add(tid)
    
    new_messages = []
    new_logs = []
    workspace_path = str(state.get("workspace_path", ""))
    current_task_id = state.get("current_task_id", "UNKNOWN")
    
    available_tools = {
        "read_file": read_file,
        "edit_file": edit_file,
        "execute_subprocess": execute_subprocess,
        "finish_task": finish_task,
        "start_background_server": start_background_server,
        "kill_process_on_port": kill_process_on_port
    }
    
    executed_subprocess = False
    processed_any_tool = False
    fs_success = True
    
    
    # 3. Iterate over ALL tool calls from the last AI message
    tool_calls = getattr(last_ai_message, "tool_calls", []) or (last_ai_message.get("tool_calls") if isinstance(last_ai_message, dict) else [])
    
    for tool_call in tool_calls:
        tool_id = tool_call["id"]
        tool_name = tool_call["name"]
        
        # Already responded to this call — skip
        if tool_id in already_responded_ids:
            continue
            
        processed_any_tool = True
        tool_args = tool_call["args"].copy()
        
        # Prepare arguments
        if tool_name in ["read_file", "edit_file", "execute_subprocess"]:
            tool_args["workspace_path"] = workspace_path
        if tool_name == "execute_subprocess":
            tool_args["task_id"] = current_task_id
            executed_subprocess = True
        
        # Execute the tool
        if tool_name in available_tools:
            try:
                result = available_tools[tool_name].invoke(tool_args)
                if tool_name == "execute_subprocess":
                    new_logs.append(result)
                    stdout_trunc = result['stdout'][-2000:] if len(result['stdout']) > 2000 else result['stdout']
                    stderr_trunc = result['stderr'][-2000:] if len(result['stderr']) > 2000 else result['stderr']
                    result_str = f"Exit code: {result['exit_code']}\nStdout: {stdout_trunc}\nStderr: {stderr_trunc}"
                elif tool_name in ["finish_task", "start_background_server", "kill_process_on_port"]:
                    new_logs.append({
                        "task_id": current_task_id,
                        "command": tool_name,
                        "stdout": str(result),
                        "stderr": "",
                        "exit_code": 0,
                        "timestamp": time.time()
                    })
                    result_str = str(result)
                else:
                    result_str = str(result)
                    if "Error" in result_str or "failed" in result_str.lower():
                        fs_success = False
                new_messages.append(ToolMessage(content=result_str, tool_call_id=tool_id, name=tool_name))
            except Exception as e:
                fs_success = False
                new_messages.append(ToolMessage(content=f"System Error: {str(e)}", tool_call_id=tool_id, name=tool_name))
        else:
            # Always return a ToolMessage for unrecognized tools (Vertex AI requirement)
            new_messages.append(ToolMessage(
                content=f"Error: Tool '{tool_name}' is not recognized.", 
                tool_call_id=tool_id,
                name=tool_name
            ))
            fs_success = False
    
    if processed_any_tool and not executed_subprocess:
        new_logs.append({
            "task_id": current_task_id,
            "command": "internal_fs_operation",
            "stdout": "File operations completed successfully." if fs_success else "File operations failed.",
            "stderr": "" if fs_success else "Errors detected during file operations.",
            "exit_code": 0 if fs_success else 1,
            "timestamp": time.time()
        })
    elif not processed_any_tool:
        # CRITICAL: If the Coder did nothing (no tool_calls), log it as a failure
        # to prevent infinite loops.
        new_logs.append({
            "task_id": current_task_id,
            "command": "none",
            "stdout": "Agent provided a text response or question.",
            "stderr": "Awaiting user clarification or approval.",
            "exit_code": 1,
            "timestamp": time.time()
        })

    wbs = state.get("wbs",[])
    updated_wbs = wbs.copy() if isinstance(wbs, list) else[]
    new_status = "pending"  # Default; overridden below if logs exist
    
    if new_logs:
        last_log = new_logs[-1]
        exit_code = last_log.get("exit_code", 1) if isinstance(last_log, dict) else getattr(last_log, "exit_code", 1)
        command = last_log.get("command", "") if isinstance(last_log, dict) else getattr(last_log, "command", "")
        
        if command == "finish_task":
            new_status = "completed"
        elif command == "internal_fs_operation":
            new_status = "in_progress" if exit_code == 0 else "failed"
        elif command == "none":
            new_status = "in_progress"
        else:
            # Subprocess execution (tests, scripts)
            # A successful command DOES NOT automatically complete the task.
            # The Coder must explicitly call 'finish_task'.
            new_status = "in_progress" if exit_code == 0 else "failed"
        
        for epic in updated_wbs:
            tasks = epic.tasks if hasattr(epic, 'tasks') else epic.get('tasks',[])
            for task in tasks:
                tid = task.task_id if hasattr(task, 'task_id') else task.get('task_id')
                status = task.status if hasattr(task, 'status') else task.get('status')
                
                if (current_task_id != "UNKNOWN" and tid == current_task_id) or \
                   (current_task_id == "UNKNOWN" and status == "in_progress"):
                    if hasattr(task, 'status'): task.status = new_status
                    else: task['status'] = new_status
                    break

    result_state = {}
    messages_to_remove = []
    if new_status == "completed":
        # Task succeeded! Let's prune the intermediate thrashing (errors, tool calls)
        # Keep the first few messages (system prompt, initial WBS) and the very last success messages.
        safe_window_start = 5
        
        if len(messages) > safe_window_start:
            # We don't remove the last message (which triggered this success)
            for msg in messages[safe_window_start:-1]:
                if isinstance(msg, ToolMessage) or (isinstance(msg, AIMessage) and getattr(msg, "tool_calls", [])):
                    if hasattr(msg, "id") and msg.id:
                        messages_to_remove.append(RemoveMessage(id=msg.id))

    # Final state packaging
    if new_messages or messages_to_remove:
        result_state["messages"] = new_messages + messages_to_remove
    
    if new_logs: 
        result_state["execution_logs"] = new_logs
        # If the last operation failed, increment the retry counter
        if new_status == "failed":
            result_state["retry_count"] = state.get("retry_count", 0) + 1
        else:
            result_state["retry_count"] = 0 # Reset on success
            
    if updated_wbs: 
        result_state["wbs"] = updated_wbs
    
    return result_state
