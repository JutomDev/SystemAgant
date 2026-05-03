import os
import ast
from langchain_core.tools import tool

def _secure_path(workspace_path: str, user_path: str) -> str:
    """Validates the path. Allows relative paths typed by the agent."""
    base_path = os.path.abspath(workspace_path)
    clean_user_path = user_path.lstrip('/').lstrip('\\')
    requested_path = os.path.abspath(os.path.join(base_path, clean_user_path))
    
    if not requested_path.startswith(base_path):
        raise PermissionError(f"Access denied: Path {user_path} is outside of the workspace.")
    return requested_path

@tool
def read_file(path: str, workspace_path: str = "") -> str:
    """Reads the contents of a file from the isolated project directory."""
    try:
        if not workspace_path: raise ValueError("Missing workspace_path")
        safe_path = _secure_path(workspace_path, path)
        with open(safe_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

@tool
def edit_file(path: str, diff_instructions: str, workspace_path: str = "") -> str:
    """
    Edits a file using SEARCH/REPLACE blocks. Does not overwrite the entire file.
    Required diff_instructions format:
    <<<< SEARCH
    exact code to remove
    ====
    new code to insert
    >>>> REPLACE
    """
    try:
        if not workspace_path: raise ValueError("Missing workspace_path")
        safe_path = _secure_path(workspace_path, path)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        
        # DEBUG LOG
        debug_path = os.path.join(workspace_path, "fs_debug.log")
        with open(debug_path, "a", encoding="utf-8") as df:
            df.write(f"\n[{path}] DIFF LEN: {len(diff_instructions)}\n")
            df.write(f"SAMPLE: {diff_instructions[:200]}\n")
        
        if not os.path.exists(safe_path):
            with open(safe_path, 'w', encoding='utf-8') as f:
                f.write("")
        
        with open(safe_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Parse SEARCH/REPLACE blocks
        blocks = diff_instructions.split("<<<< SEARCH")
        
        if len(blocks) <= 1:
            if content.strip() == "":
                content = diff_instructions
            else:
                return "Error: File is not empty. You MUST use <<<< SEARCH ... ==== ... >>>> REPLACE blocks to edit it."
        else:
            for block in blocks[1:]:
                # Strip leading newline immediately after <<<< SEARCH
                block = block.lstrip('\n')
                
                if "====\n" not in block or ">>>> REPLACE" not in block:
                    return "Error: Invalid diff_instructions format. Missing ==== or >>>> REPLACE."
                
                search_part, rest = block.split("====\n", 1)
                replace_part = rest.split(">>>> REPLACE")[0]
                
                # Strip trailing whitespace but preserve internal structure
                search_part = search_part.rstrip('\n')
                replace_part = replace_part.rstrip('\n')

                if search_part == "":
                    if content == "":
                        # First write to an empty file
                        content = replace_part
                    else:
                        # Non-empty file with empty SEARCH block is likely a model error.
                        # For stability: return an error to force precision.
                        return f"Error: SEARCH block is empty but file '{path}' already has content. Please specify what to replace."
                else:
                    if search_part not in content:
                        return f"Error: SEARCH block not found in file '{path}'. Ensure exact match."
                    content = content.replace(search_part, replace_part, 1)

        if path.endswith('.py'):
            try:
                ast.parse(content)
            except SyntaxError as e:
                return f"SyntaxError at line {e.lineno}, offset {e.offset}: {e.msg}. Write aborted. Fix the syntax and try again."

        with open(safe_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        return f"Successfully edited {safe_path}."
    except Exception as e:
        return f"Error editing file: {str(e)}"
