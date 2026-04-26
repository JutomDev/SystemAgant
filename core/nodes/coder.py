from langchain_core.messages import HumanMessage
from langchain_google_vertexai import ChatVertexAI
from core.state import AgentState
from core.tools.fs_tools import read_file, edit_file

def coder_node(state: AgentState) -> dict:
    llm = ChatVertexAI(
        model_name="gemini-3-flash-preview", # POPRAWIONE API ID DLA VERTEX AI
        temperature=0.5,
        location="global", # WYMAGANE DLA NOWYCH MODELI PREVIEW
        project="nifty-saga-493918-c8"
    )
    tools = [read_file, edit_file]
    llm_with_tools = llm.bind_tools(tools)
    
    principles = state.get("guiding_principles", {"core_constitution": [], "project_directives": []})
    principles_text = f"ZASADY SYSTEMU: {principles.get('core_constitution')}\nDYREKTYWY PROJEKTU: {principles.get('project_directives')}"

    coder_prompt = SystemMessage(content=f"""Jesteś Senior Software Engineer.
Twoje nadrzędne zasady to: {principles_text}.
Masz do dyspozycji narzędzia do edycji plików. Pisz czysty, wydajny kod. Jeśli to Twoje kolejne podejście do zadania, uwzględnij uwagi z błędów lub od Architekta.""")
    
    messages = state.get("messages", []).copy()
    logs = state.get("execution_logs",[])
    current_iteration = state.get("current_iteration", 0)
    
    if logs and current_iteration > 0:
        last_log = logs[-1]
        exit_code = last_log.get("exit_code", 1) if isinstance(last_log, dict) else getattr(last_log, "exit_code", 1)
        
        if exit_code != 0:
            command = last_log.get("command", "") if isinstance(last_log, dict) else getattr(last_log, "command", "")
            stderr = last_log.get("stderr", "") if isinstance(last_log, dict) else getattr(last_log, "stderr", "")
            
            error_context = (
                f"Task failed in iteration {current_iteration}.\n"
                f"Command: {command}\n"
                f"Exit Code: {exit_code}\n"
                f"Stderr:\n{stderr}\n"
                "Fix the code based on the error above."
            )
            messages.append(HumanMessage(content=error_context))
            
    response = llm_with_tools.invoke([coder_prompt] + messages)
    
    return {
        "messages": [response],
        "current_iteration": current_iteration + 1,
        "retry_count": state.get("retry_count", 0) + 1 # Zwiększamy licznik przy każdej próbie
    }
