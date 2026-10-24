import time

from langchain_core.messages import AIMessage, RemoveMessage, ToolMessage

from core.state import AgentState
from core.tools.fs_tools import edit_file, read_file
from core.tools.sys_tools import execute_subprocess, finish_task, kill_process_on_port, start_background_server


def tester_node(state: AgentState) -> dict:
    messages = state.get("messages", [])
    if not messages:
        return {}

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
    for m in messages[last_ai_idx + 1 :]:
        m_type = getattr(m, "type", None) or (m.get("type") if isinstance(m, dict) else None)
        if m_type == "tool":
            tid = getattr(m, "tool_call_id", None) or (m.get("tool_call_id") if isinstance(m, dict) else None)
            if tid:
                already_responded_ids.add(tid)

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
        "kill_process_on_port": kill_process_on_port,
    }

    executed_subprocess = False
    executed_bg_server = False
    processed_any_tool = False
    fs_success = True

    # 3. Iterate over ALL tool calls from the last AI message
    tool_calls = getattr(last_ai_message, "tool_calls", []) or (
        last_ai_message.get("tool_calls") if isinstance(last_ai_message, dict) else []
    )

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
                    stdout_trunc = result["stdout"][-2000:] if len(result["stdout"]) > 2000 else result["stdout"]
                    stderr_trunc = result["stderr"][-2000:] if len(result["stderr"]) > 2000 else result["stderr"]
                    result_str = f"Exit code: {result['exit_code']}\nStdout: {stdout_trunc}\nStderr: {stderr_trunc}"
                elif tool_name == "start_background_server":
                    # start_background_server now returns an ExecutionLog dict
                    # with the REAL exit_code — respect it!
                    executed_bg_server = True
                    if isinstance(result, dict):
                        new_logs.append(result)
                        stdout_trunc = (result.get("stdout", "") or "")[-2000:]
                        stderr_trunc = (result.get("stderr", "") or "")[-2000:]
                        result_str = (
                            f"Exit code: {result.get('exit_code', 1)}\nStdout: {stdout_trunc}\nStderr: {stderr_trunc}"
                        )
                    else:
                        # Fallback for legacy string return
                        new_logs.append(
                            {
                                "task_id": current_task_id,
                                "command": tool_name,
                                "stdout": str(result),
                                "stderr": "",
                                "exit_code": 0,
                                "timestamp": time.time(),
                            }
                        )
                        result_str = str(result)
                elif tool_name in ["finish_task", "kill_process_on_port"]:
                    new_logs.append(
                        {
                            "task_id": current_task_id,
                            "command": tool_name,
                            "stdout": str(result),
                            "stderr": "",
                            "exit_code": 0,
                            "timestamp": time.time(),
                        }
                    )
                    result_str = str(result)
                else:
                    result_str = str(result)
                    if "Error" in result_str or "failed" in result_str.lower():
                        fs_success = False
                new_messages.append(ToolMessage(content=result_str, tool_call_id=tool_id, name=tool_name))
            except Exception as e:
                fs_success = False
                new_messages.append(
                    ToolMessage(content=f"System Error: {str(e)}", tool_call_id=tool_id, name=tool_name)
                )
        else:
            # Always return a ToolMessage for unrecognized tools (Vertex AI requirement)
            new_messages.append(
                ToolMessage(
                    content=f"Error: Tool '{tool_name}' is not recognized.", tool_call_id=tool_id, name=tool_name
                )
            )
            fs_success = False

    if processed_any_tool and not executed_subprocess and not executed_bg_server:
        new_logs.append(
            {
                "task_id": current_task_id,
                "command": "internal_fs_operation",
                "stdout": "File operations completed successfully." if fs_success else "File operations failed.",
                "stderr": "" if fs_success else "Errors detected during file operations.",
                "exit_code": 0 if fs_success else 1,
                "timestamp": time.time(),
            }
        )
    elif not processed_any_tool:
        # CRITICAL: If the Coder did nothing (no tool_calls), log it as a failure
        # to prevent infinite loops.
        new_logs.append(
            {
                "task_id": current_task_id,
                "command": "none",
                "stdout": "Agent provided a text response or question.",
                "stderr": "Awaiting user clarification or approval.",
                "exit_code": 1,
                "timestamp": time.time(),
            }
        )

    wbs = state.get("wbs", [])
    updated_wbs = wbs.copy() if isinstance(wbs, list) else []
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
            tasks = epic.tasks if hasattr(epic, "tasks") else epic.get("tasks", [])
            for task in tasks:
                tid = task.task_id if hasattr(task, "task_id") else task.get("task_id")
                status = task.status if hasattr(task, "status") else task.get("status")

                if (current_task_id != "UNKNOWN" and tid == current_task_id) or (
                    current_task_id == "UNKNOWN" and status == "in_progress"
                ):
                    if hasattr(task, "status"):
                        task.status = new_status
                    else:
                        task["status"] = new_status
                    break

    messages_to_remove = []
    # When a task completes successfully (exit code 0), prune intermediate tool execution
    # messages from history to conserve the LLM token budget while preserving the prompt preamble.
    if new_logs and new_logs[-1].get("exit_code", 1) == 0:
        safe_window_start = 5  # Preserve constitutional system instructions and initial requirements
        if len(messages) > safe_window_start + 2:
            # Iterate through intermediate turns and prune ephemeral tool calls
            for msg in messages[safe_window_start:-2]:
                if isinstance(msg, ToolMessage) or (isinstance(msg, AIMessage) and getattr(msg, "tool_calls", [])):
                    if hasattr(msg, "id") and msg.id:
                        messages_to_remove.append(RemoveMessage(id=msg.id))

    result_state = {}
    if new_messages or messages_to_remove:
        result_state["messages"] = new_messages + messages_to_remove

    if new_logs:
        result_state["execution_logs"] = new_logs
        # RETRY COUNTER LOGIC:
        # - "failed" -> INCREMENT (bot made an error)
        # - "completed" (finish_task) -> RESET to 0 (task done, fresh start)
        # - "in_progress" -> DO NOT TOUCH (dir/read_file must NOT reset the counter)
        if new_status == "failed":
            result_state["retry_count"] = state.get("retry_count", 0) + 1
        elif new_status == "completed":
            result_state["retry_count"] = 0  # Only reset on explicit task completion
        # else: in_progress — leave retry_count unchanged (no key = no update)

    if updated_wbs:
        result_state["wbs"] = updated_wbs

    return result_state
