from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_google_vertexai import ChatVertexAI
from core.state import AgentState
from core.tools.fs_tools import read_file, edit_file

def coder_node(state: AgentState) -> dict:
    # Wyciągnięcie zasad systemowych z bieżącego stanu
    principles = state.get("guiding_principles", {"core_constitution": [], "project_directives": []})
    
    # Rygorystyczna instrukcja systemowa ze znacznikami XML
    sys_instruct = f"""<role>Jesteś Senior Software Engineer.</role>
<core_constitution>\n{principles.get('core_constitution')}\n</core_constitution>
<project_directives>\n{principles.get('project_directives')}\n</project_directives>
<instructions>
KRYTYCZNE: Jesteś maszyną wykonawczą, a nie chatbotem! 
NIGDY nie generuj kodu w blokach markdown jako zwykły tekst. 
ABY WYKONAĆ ZADANIE, MUSISZ BEZWZGLĘDNIE WYWOŁAĆ NARZĘDZIE `edit_file`, aby fizycznie zapisać plik na dysku. 
Nawet nie próbuj odpowiadać konwersacyjnie. Użyj narzędzia!
Jeśli to kolejna iteracja, napraw błędy z `ToolMessage`.
</instructions>"""

    # UWAGA: Nie używamy system_instruction= w konstruktorze ChatVertexAI,
    # ponieważ ta wersja langchain_google_vertexai go nie obsługuje natywnie
    # i generuje ostrzeżenie. Zamiast tego przekazujemy SystemMessage do listy wiadomości.
    llm = ChatVertexAI(
        model_name="gemini-3-flash-preview",
        location="global",
        project="nifty-saga-493918-c8",
        temperature=0.2,
        top_p=0.95,
        max_output_tokens=4096,
    )
    tools = [read_file, edit_file]
    llm_with_tools = llm.bind_tools(tools, tool_choice="any")
    
    messages = state.get("messages", []).copy()
    logs = state.get("execution_logs", [])
    current_iteration = state.get("current_iteration", 0)
    
    if logs and current_iteration > 0:
        last_log = logs[-1]
        exit_code = last_log.get("exit_code", 1) if isinstance(last_log, dict) else getattr(last_log, "exit_code", 1)
        
        if exit_code != 0:
            stderr = last_log.get("stderr", "") if isinstance(last_log, dict) else getattr(last_log, "stderr", "")
            
            # INŻYNIERIA BŁĘDÓW: Szukanie ostatniego wywołania narzędzia
            last_ai_message = next((m for m in reversed(messages) if isinstance(m, AIMessage) and m.tool_calls), None)
            
            if last_ai_message and last_ai_message.tool_calls:
                # Bierzemy ID pierwszego narzędzia, które zawiodło
                tool_call_id = last_ai_message.tool_calls[0]["id"]
                error_msg = ToolMessage(
                    content=f"Execution failed (Exit Code {exit_code}). Stderr:\n{stderr}\nFix this issue.",
                    tool_call_id=tool_call_id
                )
                messages.append(error_msg)
            else:
                # Fallback, jeśli z jakiegoś powodu nie było tool_call
                messages.append(HumanMessage(content=f"Fix the following error:\n{stderr}"))

    # Instrukcja systemowa jako pierwszy element listy wiadomości (gwarantowany kanał)
    coder_system_msg = SystemMessage(content=sys_instruct)
    response = llm_with_tools.invoke([coder_system_msg] + messages)
    
    return {
        "messages": [response],
        "current_iteration": current_iteration + 1,
        "retry_count": state.get("retry_count", 0) + 1  # Zwiększamy licznik przy każdej próbie
    }
