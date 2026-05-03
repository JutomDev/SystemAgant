from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_google_vertexai import ChatVertexAI
from core.state import AgentState
from core.tools.fs_tools import read_file, edit_file

def sanitize_history(messages):
    """
    CRITICAL: Vertex AI throws a 400 error if each tool call (ToolCall)
    does not have exactly one corresponding response (ToolMessage) per turn.
    This function repairs corrupted history (e.g., loaded from the database state)
    by injecting missing responses BEFORE sending to the LLM.
    """
    sanitized = []
    pending_tool_calls = {}
    
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
    
    sys_instruct = f"""<role>Jesteś Senior Software Engineer.</role>
<core_constitution>\n{principles.get('core_constitution')}\n</core_constitution>
<project_directives>\n{principles.get('project_directives')}\n</project_directives>
<instructions>
KRYTYCZNE: Jesteś maszyną wykonawczą. ABY WYKONAĆ ZADANIE, MUSISZ WYWOŁAĆ NARZĘDZIE `edit_file`. 
NIGDY nie używaj pustego bloku SEARCH, jeśli plik posiada już treść.
PREFERUJ EDYCJĘ CHIRURGICZNĄ: Nie nadpisuj całego pliku bez potrzeby. Znajdź konkretny fragment i podmień tylko jego część.

Przykład poprawnej edycji:
<<<< SEARCH
def old_function():
    print("old")
====
def new_function():
    print("new")
>>>> REPLACE

Jeśli zakończyłeś zadanie lub chcesz zadać pytanie, wyślij SAM TEKST. System wtedy zatrzyma się i poczeka na decyzję użytkownika.
Nie generuj kodu jako zwykły tekst. Użyj narzędzia!
</instructions>"""

    llm = ChatVertexAI(
        model_name="gemini-3-flash-preview",
        location="global",
        project="nifty-saga-493918-c8",
        temperature=0.1,
        top_p=0.90,
        frequency_penalty=0.2,
        max_output_tokens=16384,
        model_kwargs={"thinking_level": "high"}
    )
    tools = [read_file, edit_file]
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
        # Gemini requires every message to have content or a tool call
        m_content = getattr(m, "content", "")
        m_tools = getattr(m, "tool_calls", [])
        if m_content or m_tools:
            final_messages.append(m)
        elif isinstance(m, ToolMessage): # ToolMessage musi być, nawet jeśli wynik to pusty string
            # SAFETY NET: Gemini requires a 'name' field in every function_response
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
        "current_iteration": current_iteration + 1,
        "retry_count": state.get("retry_count", 0) + 1
    }
