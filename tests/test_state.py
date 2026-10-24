from core.models import ExecutionLog, FileMetadata
from core.state import merge_file_system_state, update_execution_logs


def test_update_execution_logs_append():
    """Testuje dopisywanie logów."""
    left = [ExecutionLog(task_id="T1", command="ls", stdout="ok", stderr="", exit_code=0, timestamp=1.0)]
    right = [ExecutionLog(task_id="T2", command="pwd", stdout="/", stderr="", exit_code=0, timestamp=2.0)]

    result = update_execution_logs(left, right)

    assert len(result) == 2
    assert result[0].task_id == "T1"
    assert result[1].task_id == "T2"


def test_update_execution_logs_reset():
    """Testuje resetowanie logów (Epik 4)."""
    left = [ExecutionLog(task_id="T1", command="ls", stdout="ok", stderr="", exit_code=0, timestamp=1.0)]
    right = []  # Pusta lista oznacza reset zgodnie z naszą implementacją

    result = update_execution_logs(left, right)

    assert result == []


def test_merge_file_system_state():
    """Testuje łączenie metadanych plików."""
    f1 = FileMetadata(path="a.py", hash="h1", last_modified=1.0, lines_count=10)
    f2 = FileMetadata(path="a.py", hash="h2", last_modified=2.0, lines_count=12)
    f3 = FileMetadata(path="b.py", hash="h3", last_modified=3.0, lines_count=5)

    state = {"a.py": f1}
    updates = {"a.py": f2, "b.py": f3}

    result = merge_file_system_state(state, updates)

    assert result["a.py"].hash == "h2"
    assert result["b.py"].hash == "h3"
    assert len(result) == 2
