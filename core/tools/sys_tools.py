import os
import socket
import subprocess
import time
from pathlib import Path

import psutil
from langchain_core.tools import tool

from core.models import ExecutionLog


def truncate_output(text: str, max_length: int = 5000) -> str:
    if not text or len(text) <= max_length:
        return text
    head_len = 1000
    tail_len = max_length - head_len - 50  # 50 chars for the warning message
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
        "sudo ",
        "rm -rf /",
        "rm -rf *",
        "mkfs",
        "reboot",
        "shutdown",
        "~/.ssh",
        "/etc/passwd",
        "/etc/shadow",
        "C:\\Windows",
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
                timestamp=start_time,
            ).model_dump()

    try:
        # Set workspace as working directory if valid
        cwd_path = Path(workspace_path).resolve() if workspace_path and Path(workspace_path).is_dir() else None
        cwd = str(cwd_path) if cwd_path else None

        # Resolve .venv paths: virtualenv lives in repository root, not inside isolated workspaces
        if cwd_path and ".venv" in command:
            for parent in [cwd_path] + list(cwd_path.parents):
                venv_candidate = parent / ".venv"
                if venv_candidate.is_dir():
                    abs_venv = str(venv_candidate.resolve())
                    command = command.replace(r".\.venv", abs_venv)
                    command = command.replace("./.venv", abs_venv)
                    command = command.replace(".venv", abs_venv)
                    break

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=cwd,
            encoding="utf-8",
            errors="replace",
        )

        stdout_str = truncate_output(result.stdout)
        stderr_str = truncate_output(result.stderr)

        return ExecutionLog(
            task_id=task_id,
            command=command,
            stdout=stdout_str,
            stderr=stderr_str,
            exit_code=result.returncode,
            timestamp=start_time,
        ).model_dump()

    except subprocess.TimeoutExpired as e:
        stdout_str = truncate_output(e.stdout.decode("utf-8") if isinstance(e.stdout, bytes) else (e.stdout or ""))
        stderr_str = truncate_output(e.stderr.decode("utf-8") if isinstance(e.stderr, bytes) else (e.stderr or ""))

        return ExecutionLog(
            task_id=task_id,
            command=command,
            stdout=stdout_str,
            stderr=f"TimeoutExpired (120s limit reached).\n{stderr_str}",
            exit_code=124,
            timestamp=start_time,
        ).model_dump()

    except Exception as e:
        return ExecutionLog(
            task_id=task_id,
            command=command,
            stdout="",
            stderr=f"Execution failed: {str(e)}",
            exit_code=1,
            timestamp=start_time,
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
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                # Szukamy połączeń sieciowych dla procesu
                conns = proc.connections(kind="inet")
                for conn in conns:
                    if conn.laddr.port == port:
                        proc.terminate()
                        proc.wait(timeout=3)
                        killed_pids.append(proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception as e:
        return f"Error while trying to kill processes on port {port}: {str(e)}"

    if killed_pids:
        return f"Successfully killed processes {killed_pids} listening on port {port}."
    return f"No processes found listening on port {port}."


@tool
def start_background_server(command: str, port: int, workspace_path: str = None, task_id: str = "UNKNOWN") -> dict:
    """
    Use this tool ONLY to start long-running servers (like FastAPI, Node.js, Next.js).
    It runs the server in the background and polls the specified port until it is open.
    Returns an ExecutionLog-like dict.
    """
    port = int(port)  # Gemini may send 3000.0 (float)
    cwd = workspace_path if workspace_path and os.path.exists(workspace_path) else None
    start_time = time.time()

    # DEBUG: Log resolved CWD for troubleshooting
    print(
        f"[DEBUG start_background_server] workspace_path={workspace_path!r}, resolved cwd={cwd!r}, port={port}",
        flush=True,
    )

    # Log file in workspace dir — overwritten on each start (no disk bloat)
    log_file_path = os.path.join(cwd if cwd else ".", f"server_{port}.log")
    log_file = None

    try:
        log_file = open(log_file_path, "w", encoding="utf-8", errors="replace")
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )

        # Port Polling: Wait for server to bind
        max_retries = 20
        for _i in range(max_retries):
            time.sleep(1)
            # Check if process crashed
            if process.poll() is not None:
                log_file.close()
                log_file = None
                with open(log_file_path, encoding="utf-8", errors="replace") as f:
                    error_tail = "".join(f.readlines()[-30:])
                return ExecutionLog(
                    task_id=task_id,
                    command=command,
                    stdout="",
                    stderr=f"Server process crashed with exit code {process.returncode}.\nLogs:\n{error_tail}",
                    exit_code=process.returncode or 1,
                    timestamp=start_time,
                ).model_dump()

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                result = sock.connect_ex(("127.0.0.1", port))
                if result == 0:
                    log_file.close()
                    log_file = None
                    return ExecutionLog(
                        task_id=task_id,
                        command=command,
                        stdout=f"Server started successfully (PID: {process.pid}) on port {port}.",
                        stderr="",
                        exit_code=0,
                        timestamp=start_time,
                    ).model_dump()

        # Timeout — server never bound to port
        process.terminate()
        log_file.close()
        log_file = None
        with open(log_file_path, encoding="utf-8", errors="replace") as f:
            error_tail = "".join(f.readlines()[-30:])

        return ExecutionLog(
            task_id=task_id,
            command=command,
            stdout="",
            stderr=f"Timeout waiting for server to bind to port {port}. Last logs:\n{error_tail}",
            exit_code=124,
            timestamp=start_time,
        ).model_dump()

    except Exception as e:
        return ExecutionLog(
            task_id=task_id,
            command=command,
            stdout="",
            stderr=f"Exception while starting background server: {str(e)}",
            exit_code=1,
            timestamp=start_time,
        ).model_dump()
    finally:
        # Safety net: always close the log file handle
        if log_file and not log_file.closed:
            log_file.close()
