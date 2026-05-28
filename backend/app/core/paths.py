from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings


def project_path(*parts: str) -> Path:
    cwd = Path.cwd().resolve()
    if cwd.name == "backend" and (cwd.parent / "frontend").exists():
        return cwd.parent.joinpath(*parts)
    if (cwd / "data").exists() or (cwd / "backend").exists():
        return cwd.joinpath(*parts)
    return get_settings().project_root.joinpath(*parts)
