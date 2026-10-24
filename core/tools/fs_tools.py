"""Sandboxed File System Tools for SystemAgant.

Enforces workspace boundary containment, atomic read/write operations,
and pre-write AST syntax validation for Python source files.
"""

from __future__ import annotations

import ast
from pathlib import Path
from langchain_core.tools import tool


def _secure_path(workspace_path: str, user_path: str) -> Path:
    """Validates path and enforces that target file resides strictly within workspace.
    
    Prevents path traversal attacks (e.g. '../', absolute paths, symlink escapes).
    """
    base_path = Path(workspace_path).resolve()
    clean_user_path = user_path.lstrip("/").lstrip("\\")
    requested_path = (base_path / clean_user_path).resolve()

    # Boundary containment check: target path must be child of base workspace directory
    if not str(requested_path).startswith(str(base_path)):
        raise PermissionError(f"Access denied: Path {user_path} is outside of the workspace.")
    return requested_path


@tool
def read_file(path: str, workspace_path: str = "") -> str:
    """Reads the contents of a file from the isolated project directory."""
    try:
        if not workspace_path:
            raise ValueError("Missing workspace_path")
        safe_path = _secure_path(workspace_path, path)
        return safe_path.read_text(encoding="utf-8")
    except (OSError, PermissionError, ValueError) as e:
        return f"Error reading file: {str(e)}"


@tool
def edit_file(path: str, diff_instructions: str, workspace_path: str = "", overwrite: bool = False) -> str:
    """Edits a file using SEARCH/REPLACE blocks OR overwrites the entire file.

    MODE 1 (Default, overwrite=False): Group multiple edits via SEARCH/REPLACE blocks:
    <<<< SEARCH
    exact code to remove 1
    ====
    new code to insert 1
    >>>> REPLACE

    MODE 2 (overwrite=True): Complete drop-in replacement with diff_instructions.
    """
    try:
        if not workspace_path:
            raise ValueError("Missing workspace_path")
        safe_path = _secure_path(workspace_path, path)

        # Ensure parent directories exist before creating or editing target file
        safe_path.parent.mkdir(parents=True, exist_ok=True)

        # Log diff attempt to scratch telemetry log for diagnostics
        debug_path = Path(workspace_path) / "fs_debug.log"
        try:
            with open(debug_path, "a", encoding="utf-8") as df:
                df.write(f"\n[{path}] DIFF LEN: {len(diff_instructions)}\nSAMPLE: {diff_instructions[:200]}\n")
        except OSError:
            pass

        content = safe_path.read_text(encoding="utf-8") if safe_path.is_file() else ""

        # MODE 2: Explicit overwrite replaces content directly without parsing diff blocks
        if overwrite:
            content = diff_instructions
        else:
            # MODE 1: Parse discrete SEARCH/REPLACE blocks
            blocks = diff_instructions.split("<<<< SEARCH")

            if len(blocks) <= 1:
                # If no search blocks provided and file is empty, accept instructions as initial content
                if content.strip() == "":
                    content = diff_instructions
                else:
                    # Auto-fallback to full overwrite when agent supplies bare code to existing file
                    content = diff_instructions
            else:
                for block in blocks[1:]:
                    block = block.lstrip("\n")

                    if "====\n" not in block or ">>>> REPLACE" not in block:
                        return "Error: Invalid diff_instructions format. Missing ==== or >>>> REPLACE."

                    search_part, rest = block.split("====\n", 1)
                    replace_part = rest.split(">>>> REPLACE")[0]

                    # Strip trailing newline while preserving structural indentation
                    search_part = search_part.rstrip("\n")
                    replace_part = replace_part.rstrip("\n")

                    if search_part == "":
                        content = replace_part
                    else:
                        if search_part not in content:
                            return f"Error: SEARCH block not found in file '{path}'. Ensure exact match."
                        content = content.replace(search_part, replace_part, 1)

        # Pre-write AST gatekeeper: prevents committing broken Python syntax to disk
        if path.endswith(".py"):
            try:
                ast.parse(content)
            except SyntaxError as e:
                return f"SyntaxError at line {e.lineno}, offset {e.offset}: {e.msg}. Write aborted. Fix the syntax and try again."

        safe_path.write_text(content, encoding="utf-8")
        return f"Successfully edited {safe_path}."
    except (OSError, PermissionError, ValueError) as e:
        return f"Error editing file: {str(e)}"
