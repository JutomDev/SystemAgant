"""Repository Map & Symbol Graph Generator for SystemAgant.

Zero-dependency structural AST and symbol analyzer inspired by Tree-sitter and Aider
repository maps. Generates high-density, low-token architectural summaries
of multi-file projects to preserve cross-file consistency in multi-script tasks.
"""

from pathlib import Path
import ast
import re
from typing import List, Dict, Any


def parse_python_symbols(content: str) -> Dict[str, Any]:
    """Extracts classes, methods, functions, and imports using Python's native AST."""
    symbols: Dict[str, Any] = {
        "imports": [],
        "classes": [],
        "functions": [],
    }
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return symbols

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                symbols["imports"].append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names = [alias.name for alias in node.names]
            symbols["imports"].append(f"from {mod} import {', '.join(names[:4])}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args if a.arg != "self"]
            symbols["functions"].append(f"def {node.name}({', '.join(args[:4])})")
        elif isinstance(node, ast.ClassDef):
            bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
            methods: List[str] = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    m_args = [a.arg for a in item.args.args if a.arg != "self"]
                    methods.append(f"{item.name}({', '.join(m_args[:3])})")
            base_str = f"({', '.join(bases)})" if bases else ""
            symbols["classes"].append({
                "name": f"{node.name}{base_str}",
                "methods": methods[:5],
            })
    return symbols


def parse_js_symbols(content: str) -> Dict[str, Any]:
    """Extracts functions, classes, and exported symbols using lightweight regex."""
    symbols: Dict[str, Any] = {"imports": [], "exports": [], "functions": []}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        imp_match = re.search(r"import\s+(?:\{([^}]+)\}|\*\s+as\s+(\w+)|\w+)\s+from\s+['\"]([^'\"]+)['\"]", line)
        if imp_match:
            symbols["imports"].append(line[:60])
            continue
        fn_match = re.search(r"(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_]+)\s*\(([^)]*)\)", line)
        if fn_match:
            symbols["functions"].append(f"{fn_match.group(1)}({fn_match.group(2)[:30]})")
            continue
        class_match = re.search(r"class\s+([a-zA-Z0-9_]+)", line)
        if class_match:
            symbols["exports"].append(f"class {class_match.group(1)}")
    return symbols


def parse_html_symbols(content: str) -> Dict[str, Any]:
    """Extracts linked stylesheets, scripts, and key semantic section IDs."""
    symbols: Dict[str, Any] = {
        "title": "",
        "stylesheets": [],
        "scripts": [],
        "sections": [],
    }
    t_match = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
    if t_match:
        symbols["title"] = t_match.group(1).strip()

    for css in re.finditer(r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)["\']', content, re.IGNORECASE):
        symbols["stylesheets"].append(css.group(1))

    for script in re.finditer(r'<script[^>]+src=["\']([^"\']+)["\']', content, re.IGNORECASE):
        symbols["scripts"].append(script.group(1))

    for sec in re.finditer(r'<(?:section|div|header|footer|nav|main)[^>]+id=["\']([^"\']+)["\']', content, re.IGNORECASE):
        symbols["sections"].append(f"#{sec.group(1)}")

    return symbols


def generate_repo_map(workspace_dir: Path, max_files: int = 20) -> str:
    """Scans workspace directory and formats a compact, high-density repository map."""
    if not workspace_dir.exists() or not workspace_dir.is_dir():
        return ""

    lines: List[str] = []
    files = sorted([
        p for p in workspace_dir.rglob("*")
        if p.is_file() and not p.name.startswith(".") and "__pycache__" not in p.parts
    ])[:max_files]

    if not files:
        return ""

    for f in files:
        rel = f.relative_to(workspace_dir).as_posix()
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        ext = f.suffix.lower()
        if ext == ".py":
            py_sym = parse_python_symbols(content)
            summary: List[str] = []
            if py_sym["classes"]:
                for c in py_sym["classes"][:3]:
                    m_str = f" [{', '.join(c['methods'][:3])}]" if c["methods"] else ""
                    summary.append(f"class {c['name']}{m_str}")
            if py_sym["functions"]:
                summary.extend(py_sym["functions"][:4])
            if py_sym["imports"]:
                summary.append(f"imports: {', '.join(py_sym['imports'][:4])}")
            lines.append(f"[{rel}]")
            for s in summary:
                lines.append(f"  {s}")

        elif ext in (".js", ".ts"):
            js_sym = parse_js_symbols(content)
            summary_js: List[str] = []
            if js_sym["exports"]:
                summary_js.extend(js_sym["exports"][:3])
            if js_sym["functions"]:
                summary_js.extend(js_sym["functions"][:4])
            lines.append(f"[{rel}]")
            for s in summary_js:
                lines.append(f"  {s}")

        elif ext in (".html", ".htm"):
            html_sym = parse_html_symbols(content)
            summary_html: List[str] = []
            if html_sym["title"]:
                summary_html.append(f'title: "{html_sym["title"][:40]}"')
            if html_sym["stylesheets"] or html_sym["scripts"]:
                links = html_sym["stylesheets"] + html_sym["scripts"]
                summary_html.append(f"assets: {', '.join(links[:4])}")
            if html_sym["sections"]:
                summary_html.append(f"ids: {', '.join(html_sym['sections'][:6])}")
            lines.append(f"[{rel}]")
            for s in summary_html:
                lines.append(f"  {s}")

        elif ext == ".css":
            vars_found = re.findall(r"(--[a-zA-Z0-9_\-]+)\s*:", content)
            lines.append(f"[{rel}]")
            if vars_found:
                lines.append(f"  vars: {', '.join(vars_found[:6])}")

    return "\n".join(lines).strip()
