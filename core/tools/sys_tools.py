import os
import subprocess
import time
from langchain_core.tools import tool
from core.models import ExecutionLog

@tool
def execute_subprocess(command: str, task_id: str = "UNKNOWN", workspace_path: str = "") -> dict:
    """
    Executes a command in an isolated subprocess.
    Returns an ExecutionLog model dump (dict).
    """
    start_time = time.time()
    
    # --- SECURITY GUARDRAILS ---
    forbidden_substrings = [
        "sudo ", "rm -rf /", "rm -rf *", "mkfs", "reboot", "shutdown",
        "~/.ssh", "/etc/passwd", "/etc/shadow", "C:\\Windows"
    ]
    
    command_check = command.lower()
    for forbidden in forbidden_substrings:
        if forbidden.lower() in command_check:
            return ExecutionLog(
                task_id=task_id,
                command=command,
                stdout="",
                stderr="SECURITY BREACH PREVENTED: Command contains forbidden operations or paths. Do not attempt to access system files or use destructive commands.",
                exit_code=126,
                timestamp=start_time
            ).model_dump()

    try:
        # Use workspace_path as the working directory if provided
        cwd = workspace_path if workspace_path and os.path.exists(workspace_path) else None
        
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd
        )
        return ExecutionLog(
            task_id=task_id,
            command=command,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
            timestamp=start_time
        ).model_dump()
        
    except subprocess.TimeoutExpired as e:
        stdout_str = e.stdout.decode('utf-8') if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr_str = e.stderr.decode('utf-8') if isinstance(e.stderr, bytes) else (e.stderr or "")
        
        return ExecutionLog(
            task_id=task_id,
            command=command,
            stdout=stdout_str,
            stderr=f"TimeoutExpired (30s limit reached).\n{stderr_str}",
            exit_code=124,
            timestamp=start_time
        ).model_dump()
        
    except Exception as e:
        return ExecutionLog(
            task_id=task_id,
            command=command,
            stdout="",
            stderr=f"Execution failed: {str(e)}",
            exit_code=1,
            timestamp=start_time
        ).model_dump()
