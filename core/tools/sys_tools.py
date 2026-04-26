import subprocess
import time
from langchain_core.tools import tool
from core.models import ExecutionLog

@tool
def execute_subprocess(command: str, task_id: str = "UNKNOWN") -> dict:
    """
    Wykonuje polecenie w izolowanym podprocesie. 
    Zwraca zrzut modelu ExecutionLog (dict).
    """
    start_time = time.time()
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30
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
