"""Asset and URL validation tools for generated web applications.

Validates external image URLs (e.g., Unsplash/Pexels) via HEAD requests
and provides graceful inline SVG placeholding for broken or offline links.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple
import urllib.parse
import httpx

SVG_PLACEHOLDER = """<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400">
  <rect width="100%" height="100%" fill="#1a1e24"/>
  <rect x="10" y="10" width="580" height="380" fill="none" stroke="#e6a23c" stroke-width="2" stroke-dasharray="6"/>
  <text x="50%" y="45%" dominant-baseline="middle" text-anchor="middle" fill="#e6a23c" font-family="monospace" font-size="20" font-weight="bold">[ ASSET PLACEHOLDER ]</text>
  <text x="50%" y="58%" dominant-baseline="middle" text-anchor="middle" fill="#8c9ba5" font-family="monospace" font-size="14">{label}</text>
</svg>"""


def validate_and_repair_html_images(html_content: str, workspace_path: Path) -> Tuple[str, List[str]]:
    """Inspects all <img> tags in html_content.
    
    Verifies HTTP links via HEAD request. If a link fails or returns >=400,
    replaces it with an inline SVG placeholder to guarantee zero broken images.
    """
    img_pattern = re.compile(r'<img\s+([^>]*?)src=["\'](.*?)["\']([^>]*?)>', re.IGNORECASE)
    repaired_log: List[str] = []

    def _replace_img(match: re.Match) -> str:
        prefix = match.group(1)
        src = match.group(2).strip()
        suffix = match.group(3)

        if not src:
            return match.group(0)

        # Skip already-embedded data URIs or local existing files
        if src.startswith("data:image"):
            return match.group(0)
        
        if not src.startswith("http://") and not src.startswith("https://"):
            local_file = workspace_path / src
            if local_file.exists():
                return match.group(0)

        # Check HTTP link
        is_valid = False
        try:
            with httpx.Client(timeout=3.0, follow_redirects=True) as client:
                res = client.head(src)
                if res.status_code < 400:
                    is_valid = True
        except Exception:
            is_valid = False

        if is_valid:
            repaired_log.append(f"[VALID] Verified image source: {src[:60]}")
            return match.group(0)
        else:
            label = Path(urllib.parse.urlparse(src).path).name or "Botanical Asset"
            safe_svg = SVG_PLACEHOLDER.format(label=label)
            svg_data_uri = "data:image/svg+xml;utf8," + urllib.parse.quote(safe_svg)
            repaired_log.append(f"[REPAIRED] Broken URL '{src[:40]}...' replaced with responsive SVG placeholder.")
            return f'<img {prefix}src="{svg_data_uri}"{suffix}>'

    repaired_html = img_pattern.sub(_replace_img, html_content)
    return repaired_html, repaired_log
