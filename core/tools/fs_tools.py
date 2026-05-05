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
def edit_file(path: str, diff_instructions: str, workspace_path: str = "", overwrite: bool = False) -> str:
    """
    Edits a file using SEARCH/REPLACE blocks OR overwrites the entire file.
    
    MODE 1 (Default, overwrite=False): Use SEARCH/REPLACE blocks.
    CRITICAL: You can and SHOULD include MULTIPLE blocks in a single call to batch your edits.
    Required format:
    <<<< SEARCH
    exact code to remove 1
    ====
    new code to insert 1
    >>>> REPLACE
    
    MODE 2 (overwrite=True): The entire file content is replaced with diff_instructions.
    Use this when you want to completely rewrite a file that already has content.
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

        # MODE 2: Full overwrite — skip SEARCH/REPLACE parsing entirely
        if overwrite:
            content = diff_instructions
        else:
            # MODE 1: Parse SEARCH/REPLACE blocks
            blocks = diff_instructions.split("<<<< SEARCH")
            
            if len(blocks) <= 1:
                if content.strip() == "":
                    content = diff_instructions
                else:
                    # SAFETY: Instead of blocking, allow overwrite with a warning in debug log
                    debug_path = os.path.join(workspace_path, "fs_debug.log")
                    with open(debug_path, "a", encoding="utf-8") as df:
                        df.write(f"[WARN] Auto-overwrite triggered for '{path}' (no SEARCH blocks, file not empty)\n")
                    content = diff_instructions
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
                            # File exists with content — treat as full overwrite (safer than blocking)
                            content = replace_part
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
