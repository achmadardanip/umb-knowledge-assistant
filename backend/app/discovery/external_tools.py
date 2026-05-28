from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.redaction import redact_sensitive


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolResult:
    name: str
    status: str
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""


def _candidate_project_roots() -> list[Path]:
    cwd = Path.cwd().resolve()
    roots = [cwd, *cwd.parents]
    return roots[:5]


def _tool_path() -> str:
    parts: list[str] = []
    for root in _candidate_project_roots():
        parts.extend([str(root / ".tools" / "bin"), str(root / ".tools" / "go" / "bin")])
    parts.append(os.environ.get("PATH", ""))
    return os.pathsep.join(parts)


def is_tool_available(name: str) -> bool:
    return shutil.which(name, path=_tool_path()) is not None


def tool_status(name: str, enabled: bool = True) -> str:
    if not enabled:
        return "disabled"
    return "available" if is_tool_available(name) else "missing"


def run_tool(
    name: str,
    args: list[str],
    *,
    enabled: bool = True,
    timeout_seconds: int = 60,
    stdin: str | None = None,
    output_path: str | Path | None = None,
) -> ToolResult:
    if not enabled:
        return ToolResult(name=name, status="disabled")
    executable = shutil.which(name, path=_tool_path())
    if not executable:
        logger.warning("%s is missing; skipping.", name)
        return ToolResult(name=name, status="missing")

    try:
        env = {**os.environ, "PATH": _tool_path()}
        safe_args = [executable, *args[1:]] if args else [executable]
        completed = subprocess.run(
            safe_args,
            input=stdin,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning("%s timed out after %s seconds.", name, timeout_seconds)
        return ToolResult(name=name, status="timeout", stderr=redact_sensitive(str(exc)))

    stdout = redact_sensitive(completed.stdout or "")
    stderr = redact_sensitive(completed.stderr or "")
    if output_path and stdout:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(stdout, encoding="utf-8")
    status = "available" if completed.returncode == 0 else "error"
    if completed.returncode != 0:
        logger.warning("%s exited with %s: %s", name, completed.returncode, stderr[:500])
    return ToolResult(name=name, status=status, returncode=completed.returncode, stdout=stdout, stderr=stderr)
