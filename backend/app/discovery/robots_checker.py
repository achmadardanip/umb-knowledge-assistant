from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests


@lru_cache(maxsize=256)
def _robot_parser(base_url: str) -> RobotFileParser:
    parser = RobotFileParser()
    robots_url = base_url.rstrip("/") + "/robots.txt"
    parser.set_url(robots_url)
    try:
        response = requests.get(robots_url, timeout=10)
        if response.status_code == 404:
            parser.allow_all = True
            return parser
        if response.status_code in {401, 403}:
            parser.disallow_all = True
            return parser
        if response.status_code >= 500:
            parser.allow_all = True
            return parser
        parser.parse(response.text.splitlines())
    except Exception:
        parser.allow_all = True
        return parser
    return parser


def can_fetch(url: str, user_agent: str = "UMBKnowledgeAssistant/0.1") -> bool:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False
    parser = _robot_parser(f"{parsed.scheme}://{parsed.netloc}")
    try:
        return parser.can_fetch(user_agent, url)
    except Exception:
        return True
