import time
from langchain_core.messages import AIMessage, ToolMessage, RemoveMessage
from core.state import AgentState
from core.tools.fs_tools import read_file, edit_file
from core.tools.sys_tools import execute_subprocess

def tester_node(state: AgentState) -> dict:
    messages = state.get("messages",[])
    if not messages: return {}
        
    # 1. Znajdź ostatnią wiadomość AI, która posiada tool_calls
    last_ai_message = None
    for m in reversed(messages):
        m_type = getattr(m, "type", None) or (m.get("type") if isinstance(m, dict) else None)
        tool_calls = getattr(m, "tool_calls", None) or (m.get("tool_calls") if isinstance(m, dict) else None)
        if m_type == "ai" and tool_calls:
            last_ai_message = m
            break
            
    if not last_ai_message:
        return {}

    # 2. Pobierz ID narzędzi, które już mają odpowiedzi w tej konkretnej turze
    # Szukamy tylko wiadomości ToolMessage, które wystąpiły PO last_ai_message
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
        "execute_subprocess": execute_subprocess
    }
    
    executed_subprocess = False
    processed_any_tool = False
    fs_success = True
    
    
    # 3. Iteruj po WSZYSTKICH wywołaniach narzędzi z ostatniej wiadomości AI
    tool_calls = getattr(last_ai_message, "tool_calls", []) or (last_ai_message.get("tool_calls") if isinstance(last_ai_message, dict) else [])
    
    for tool_call in tool_calls:
        tool_id = tool_call["id"]
        tool_name = tool_call["name"]
        
        # Jeśli już odpowiedzieliśmy na to wywołanie, pomiń
        if tool_id in already_responded_ids:
            continue
            
        processed_any_tool = True
        tool_args = tool_call["args"].copy()
        
        # Przygotowanie argumentów
        if tool_name in ["read_file", "edit_file", "execute_subprocess"]:
            tool_args["workspace_path"] = workspace_path
        if tool_name == "execute_subprocess":
            tool_args["task_id"] = current_task_id
            executed_subprocess = True
        
        # Wykonanie narzędzia
        if tool_name in available_tools:
            try:
                result = available_tools[tool_name].invoke(tool_args)
                if tool_name == "execute_subprocess":
                    new_logs.append(result)
                    stdout_trunc = result['stdout'][-2000:] if len(result['stdout']) > 2000 else result['stdout']
                    stderr_trunc = result['stderr'][-2000:] if len(result['stderr']) > 2000 else result['stderr']
                    result_str = f"Exit code: {result['exit_code']}\nStdout: {stdout_trunc}\nStderr: {stderr_trunc}"
                else:
                    result_str = str(result)
                    if "Error" in result_str or "failed" in result_str.lower():
                        fs_success = False
                new_messages.append(ToolMessage(content=result_str, tool_call_id=tool_id, name=tool_name))
            except Exception as e:
                fs_success = False
                new_messages.append(ToolMessage(content=f"System Error: {str(e)}", tool_call_id=tool_id, name=tool_name))
        else:
            # Zawsze zwracaj ToolMessage dla nieznanych narzędzi (wymóg Vertex AI)
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
        # KRYTYCZNE: Jeśli Koder nic nie zrobił (brak tool_calls), musimy to odnotować jako błąd,
        # aby uniknąć pętli nieskończonej.
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
    new_status = "pending"  # Domyślny; nadpisany poniżej jeśli są logi
    
    if new_logs:
        last_log = new_logs[-1]
        exit_code = last_log.get("exit_code", 1) if isinstance(last_log, dict) else getattr(last_log, "exit_code", 1)
        command = last_log.get("command", "") if isinstance(last_log, dict) else getattr(last_log, "command", "")
        
        if command == "internal_fs_operation":
            new_status = "in_progress" if exit_code == 0 else "failed"
        elif command == "none":
            new_status = "in_progress"
        else:
            # Subprocess execution (tests, scripts)
            new_status = "completed" if exit_code == 0 else "failed"
        
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

    # Jeśli zadanie zakończono sukcesem, czyścimy historię z szumu (MODUŁ 4)
    if new_status == "completed":
        # Usuwamy techniczne wiadomości ToolMessage i AIMessage z wywołaniami
        # Pozostawiamy HumanMessage i SystemMessage dla zachowania intencji
        for msg in messages:
            is_tool = isinstance(msg, ToolMessage)
            is_ai_with_tools = isinstance(msg, AIMessage) and msg.tool_calls
            
            if (is_tool or is_ai_with_tools) and hasattr(msg, "id") and msg.id:
                messages_to_remove.append(RemoveMessage(id=msg.id))
        
        # Resetowanie logów przenosimy do momentu faktycznego przejścia do nowego zadania w Routerze
        pass

    # Finalne pakowanie stanu
    if new_messages or messages_to_remove:
        result_state["messages"] = new_messages + messages_to_remove
    
    if new_logs: 
        result_state["execution_logs"] = new_logs
        # Jeśli ostatnia operacja się nie udała, zwiększamy licznik prób
        if new_status == "failed":
            result_state["retry_count"] = state.get("retry_count", 0) + 1
        else:
            result_state["retry_count"] = 0 # Reset po sukcesie
            
    if updated_wbs: 
        result_state["wbs"] = updated_wbs
    
    return result_state
