import os
import subprocess
import time
import socket
import psutil
from langchain_core.tools import tool
from core.models import ExecutionLog

def truncate_output(text: str, max_length: int = 5000) -> str:
    if not text or len(text) <= max_length:
        return text
    head_len = 1000
    tail_len = max_length - head_len - 50 # 50 chars for the warning message
    return text[:head_len] + f"\n\n...[TRUNCATED {len(text) - max_length} CHARACTERS] ...\n\n" + text[-tail_len:]

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
        
        stdout_str = truncate_output(result.stdout)
        stderr_str = truncate_output(result.stderr)
        
        return ExecutionLog(
            task_id=task_id,
            command=command,
            stdout=stdout_str,
            stderr=stderr_str,
            exit_code=result.returncode,
            timestamp=start_time
        ).model_dump()
        
    except subprocess.TimeoutExpired as e:
        stdout_str = truncate_output(e.stdout.decode('utf-8') if isinstance(e.stdout, bytes) else (e.stdout or ""))
        stderr_str = truncate_output(e.stderr.decode('utf-8') if isinstance(e.stderr, bytes) else (e.stderr or ""))
        
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

@tool
def finish_task(summary: str) -> str:
    """
    Call this tool ONLY when you have COMPLETELY finished the current atomic task.
    Provide a brief summary of what you have accomplished.
    This will mark the task as COMPLETED in the system.
    """
    return f"TASK_FINISHED: {summary}"

@tool
def kill_process_on_port(port: int) -> str:
    """
    CRITICAL TOOL FOR CLEANUP: Kills any process currently listening on the specified port.
    Use this immediately if you encounter an 'Address already in use' error or need to stop a test server.
    """
    killed_pids = []
    try:
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                # Szukamy połączeń sieciowych dla procesu
                conns = proc.connections(kind='inet')
                for conn in conns:
                    if conn.laddr.port == port:
                        proc.terminate()
                        proc.wait(timeout=3)
                        killed_pids.append(proc.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception as e:
        return f"Error while trying to kill processes on port {port}: {str(e)}"
        
    if killed_pids:
        return f"Successfully killed processes {killed_pids} listening on port {port}."
    return f"No processes found listening on port {port}."

@tool
def start_background_server(command: str, port: int, workspace_path: str = None) -> str:
    """
    Use this tool ONLY to start long-running servers (like FastAPI, Node.js, Next.js).
    It runs the server in the background and polls the specified port until it is open.
    DO NOT use execute_subprocess for servers.
    """
    import subprocess
    cwd = workspace_path if workspace_path and os.path.exists(workspace_path) else None
    
    try:
        # Uruchom w tle (nie czekamy na wynik)
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Port Polling: Czekamy aż serwer włączy nasłuch
        max_retries = 15
        for i in range(max_retries):
            time.sleep(1)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                result = sock.connect_ex(('127.0.0.1', port))
                if result == 0:
                    return f"Server started successfully in background (PID: {process.pid}) and is listening on port {port}."
                    
        # Jeśli port nadal zamknięty po 15 sekundach
        process.terminate()
        return f"Failed to start server: Process (PID: {process.pid}) timed out waiting to bind to port {port}."
        
    except Exception as e:
        return f"Exception while starting background server: {str(e)}"
