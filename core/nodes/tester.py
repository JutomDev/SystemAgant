import time
from langchain_core.messages import AIMessage, ToolMessage
from core.state import AgentState
from core.tools.fs_tools import read_file, edit_file
from core.tools.sys_tools import execute_subprocess

def tester_node(state: AgentState) -> dict:
    messages = state.get("messages",[])
    if not messages:
        return {}
        
    last_message = messages[-1]
    new_messages = []
    new_logs =[]
    workspace_path = state.get("workspace_path")
    
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        available_tools = {
            "read_file": read_file,
            "edit_file": edit_file,
            "execute_subprocess": execute_subprocess
        }
        
        executed_subprocess = False
        
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"].copy()
            
            # KRYTYCZNE: Wstrzyknięcie ścieżki dla narzędzi plikowych
            if tool_name in ["read_file", "edit_file"]:
                tool_args["workspace_path"] = workspace_path
            
            if tool_name in available_tools:
                if tool_name == "execute_subprocess":
                    executed_subprocess = True
                    
                try:
                    result = available_tools[tool_name].invoke(tool_args)
                    
                    if tool_name == "execute_subprocess":
                        new_logs.append(result)
                        result_str = f"Exit code: {result['exit_code']}\nStdout: {result['stdout']}\nStderr: {result['stderr']}"
                    else:
                        result_str = str(result)
                        
                    new_messages.append(ToolMessage(content=result_str, tool_call_id=tool_call["id"]))
                except Exception as e:
                    new_messages.append(ToolMessage(content=f"System Error: {str(e)}", tool_call_id=tool_call["id"]))
        
        # Zabezpieczenie przed nieskończoną pętlą: wstrzyknięcie syntetycznego logu
        if not executed_subprocess:
            new_logs.append({
                "task_id": "SYSTEM",
                "command": "internal_fs_operation",
                "stdout": "File operations completed. No subprocess tests requested.",
                "stderr": "",
                "exit_code": 0,
                "timestamp": time.time()
            })
                    
    return {
        "messages": new_messages,
        "execution_logs": new_logs
    }
