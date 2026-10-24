import os
import pytest
from core.tools.fs_tools import read_file, edit_file

def test_read_file_not_found():
    """Testuje odczyt nieistniejącego pliku."""
    result = read_file.invoke({"path": "non_existent_file.txt"})
    assert "Error" in result

def test_edit_file_format():
    """Testuje walidację formatu SEARCH/REPLACE."""
    # Tworzymy tymczasowy plik do testu
    test_path = "test_file.txt"
    with open(test_path, "w") as f:
        f.write("A\nB\nC")
        
    try:
        # Błędny format (brak separatora ====)
        instructions = "<<<< SEARCH\nA\n>>>> REPLACE\nX"
        result = edit_file.invoke({"path": test_path, "diff_instructions": instructions, "workspace_path": "."})
        assert "Error: Invalid diff_instructions format" in result
    finally:
        if os.path.exists(test_path):
            os.makedirs("tests/trash", exist_ok=True) # porządek
            os.remove(test_path)

def test_edit_file_success():
    """Testuje poprawną edycję pliku."""
    test_path = "test_file_ok.txt"
    with open(test_path, "w") as f:
        f.write("Line 1\nLine 2\nLine 3")
        
    try:
        instructions = "<<<< SEARCH\nLine 2\n====\nLine 2 Modified\n>>>> REPLACE"
        result = edit_file.invoke({"path": test_path, "diff_instructions": instructions, "workspace_path": "."})
        assert "Successfully edited" in result
        
        with open(test_path, "r") as f:
            content = f.read()
            assert "Line 2 Modified" in content
    finally:
        if os.path.exists(test_path):
            os.remove(test_path)
