"""Automated integrity and link validation test for the Botanical Shop workspace."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from web.server import app

client = TestClient(app)
WORKSPACE_DIR = Path("workspaces/run_01_botanical_shop")


def test_botanical_shop_files_exist():
    assert (WORKSPACE_DIR / "index.html").is_file()
    assert (WORKSPACE_DIR / "catalog.html").is_file()
    assert (WORKSPACE_DIR / "contact.html").is_file()
    assert (WORKSPACE_DIR / "style.css").is_file()


def test_botanical_shop_hamburger_menu_integrity():
    for fname in ["index.html", "catalog.html", "contact.html"]:
        content = (WORKSPACE_DIR / fname).read_text(encoding="utf-8")
        assert 'id="mobileMenuToggle"' in content, f"Missing mobileMenuToggle in {fname}"
        assert content.count('<span class="bar"></span>') == 3, f"Missing 3 hamburger bars in {fname}"
        assert 'id="navLinks"' in content, f"Missing navLinks in {fname}"
        assert "Botanica Studio" in content, f"Missing brand in {fname}"


def test_botanical_shop_all_links_and_anchors_valid():
    html_files = {
        "index.html": (WORKSPACE_DIR / "index.html").read_text(encoding="utf-8"),
        "catalog.html": (WORKSPACE_DIR / "catalog.html").read_text(encoding="utf-8"),
        "contact.html": (WORKSPACE_DIR / "contact.html").read_text(encoding="utf-8"),
    }

    # Extract all href attributes
    link_pattern = re.compile(r'href=["\']([^"\']+)["\']')

    for fname, html in html_files.items():
        links = link_pattern.findall(html)
        for link in links:
            if link.startswith(("http://", "https://", "mailto:", "tel:")):
                continue
            if link == "#":
                continue

            # Link with hash e.g. contact.html#faq
            if "#" in link:
                target_file_name, anchor = link.split("#", 1)
                target_file_name = target_file_name or fname
                target_path = WORKSPACE_DIR / target_file_name
                assert target_path.is_file(), f"Broken file link: {link} in {fname}"
                if anchor:
                    target_html = target_path.read_text(encoding="utf-8")
                    assert f'id="{anchor}"' in target_html, (
                        f"Broken anchor #{anchor} in {target_file_name} from {fname}"
                    )
            else:
                target_path = WORKSPACE_DIR / link
                assert target_path.is_file(), f"Broken file link: {link} in {fname}"


def test_botanical_shop_preview_http_endpoints():
    client.post("/api/workspace/load", json={"project_name": "run_01_botanical_shop"})

    # 1. Preview index.html
    res_index = client.get("/api/workspace/preview/index.html")
    assert res_index.status_code == 200
    assert "Botanica Studio" in res_index.text
    assert '<base href="/api/workspace/preview/">' in res_index.text

    # 2. Preview catalog.html
    res_cat = client.get("/api/workspace/preview/catalog.html")
    assert res_cat.status_code == 200
    assert "Artisanal Floral Catalog" in res_cat.text

    # 3. Preview contact.html
    res_contact = client.get("/api/workspace/preview/contact.html")
    assert res_contact.status_code == 200
    assert 'id="faq"' in res_contact.text
    assert 'id="shipping"' in res_contact.text
    assert 'id="returns"' in res_contact.text

    # 4. Preview style.css
    res_css = client.get("/api/workspace/preview/style.css")
    assert res_css.status_code == 200
    assert "text/css" in res_css.headers.get("content-type", "")
    assert "--primary-color" in res_css.text

    # 5. Direct fallback route /api/workspace/style.css
    res_direct_css = client.get("/api/workspace/style.css")
    assert res_direct_css.status_code == 200
    assert "text/css" in res_direct_css.headers.get("content-type", "")
