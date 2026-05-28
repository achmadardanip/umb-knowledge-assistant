from __future__ import annotations

import json
from bs4 import BeautifulSoup


def extract_html_metadata(html: str) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    metadata: dict = {"title": title, "meta": {}, "open_graph": {}, "schema_org": []}
    for tag in soup.find_all("meta"):
        name = tag.get("name") or tag.get("property")
        content = tag.get("content")
        if not name or not content:
            continue
        if str(name).startswith("og:"):
            metadata["open_graph"][name] = content
        else:
            metadata["meta"][name] = content
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            metadata["schema_org"].append(json.loads(script.string or "{}"))
        except json.JSONDecodeError:
            continue
    return metadata

