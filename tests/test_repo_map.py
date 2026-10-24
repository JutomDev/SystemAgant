"""Unit tests for the AST repository map generator."""

from pathlib import Path
from core.repo_map import (
    parse_python_symbols,
    parse_js_symbols,
    parse_html_symbols,
    generate_repo_map,
)


def test_parse_python_symbols():
    code = """
import os
from math import sqrt, ceil

class Store(BaseModel):
    def __init__(self, name: str):
        self.name = name

    def get_inventory(self):
        return []

def calculate_discount(price: float, rate: float) -> float:
    return price * (1 - rate)
"""
    symbols = parse_python_symbols(code)
    assert "os" in symbols["imports"]
    assert any("sqrt" in imp for imp in symbols["imports"])
    assert len(symbols["classes"]) == 1
    assert "Store" in symbols["classes"][0]["name"]
    assert any("get_inventory" in m for m in symbols["classes"][0]["methods"])
    assert any("calculate_discount" in f for f in symbols["functions"])


def test_parse_js_symbols():
    code = """
import { createStore } from 'redux';
export function setupCart(items) {
    return items.length;
}
class FlowerCatalog {
    render() {}
}
"""
    symbols = parse_js_symbols(code)
    assert any("redux" in imp for imp in symbols["imports"])
    assert any("setupCart" in fn for fn in symbols["functions"])
    assert any("FlowerCatalog" in exp for exp in symbols["exports"])


def test_parse_html_symbols():
    html = """<!DOCTYPE html>
<html>
<head>
    <title>Kwiaciarnia-Mex Toruń</title>
    <link rel="stylesheet" href="style.css">
    <script src="app.js"></script>
</head>
<body>
    <header id="main-nav"></header>
    <section id="flower-catalog"></section>
    <footer id="footer"></footer>
</body>
</html>"""
    symbols = parse_html_symbols(html)
    assert symbols["title"] == "Kwiaciarnia-Mex Toruń"
    assert "style.css" in symbols["stylesheets"]
    assert "app.js" in symbols["scripts"]
    assert "#flower-catalog" in symbols["sections"]


def test_generate_repo_map(tmp_path: Path):
    py_file = tmp_path / "models.py"
    py_file.write_text("class Product:\n    def get_price(self): pass\n", encoding="utf-8")

    html_file = tmp_path / "index.html"
    html_file.write_text("<title>Store</title><section id='hero'></section>", encoding="utf-8")

    css_file = tmp_path / "style.css"
    css_file.write_text(":root { --accent: #22c55e; }", encoding="utf-8")

    repo_map = generate_repo_map(tmp_path)
    assert "[models.py]" in repo_map
    assert "class Product" in repo_map
    assert "[index.html]" in repo_map
    assert "[style.css]" in repo_map
    assert "--accent" in repo_map
