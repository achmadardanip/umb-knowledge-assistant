from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import get_settings
from app.core.paths import project_path
from app.discovery.external_tools import run_tool, tool_status
from app.discovery.scope_validator import is_allowed_host, normalize_hostname


logger = logging.getLogger(__name__)


def validate_hosts(hosts: list[str], root_domain: str) -> list[str]:
    cleaned = sorted(
        {
            normalize_hostname(host)
            for host in hosts
            if host and is_allowed_host(host, root_domain)
        }
    )
    if normalize_hostname(root_domain) not in cleaned:
        cleaned.insert(0, normalize_hostname(root_domain))
    return cleaned


def discover_subdomains(
    domain: str,
    *,
    output_path: str | Path | None = None,
    allowed_hosts_path: str | Path | None = None,
) -> dict:
    settings = get_settings()
    output = Path(output_path) if output_path else project_path("data", "discovery", "subdomains_sublist3r.txt")
    output.parent.mkdir(parents=True, exist_ok=True)

    result = run_tool(
        "sublist3r",
        ["sublist3r", "-d", domain, "-o", str(output), "-n"],
        enabled=settings.enable_sublist3r,
        timeout_seconds=max(settings.discovery_timeout_seconds, 300),
    )

    raw_hosts: list[str] = []
    if output.exists():
        raw_hosts = [line.strip() for line in output.read_text(encoding="utf-8", errors="ignore").splitlines()]
    if result.stdout:
        raw_hosts.extend(line.strip() for line in result.stdout.splitlines())

    allowed_hosts = validate_hosts(raw_hosts, domain)
    allowed_path = Path(allowed_hosts_path) if allowed_hosts_path else project_path("data", "discovery", "allowed_hosts.txt")
    allowed_path.parent.mkdir(parents=True, exist_ok=True)
    allowed_path.write_text("\n".join(allowed_hosts) + "\n", encoding="utf-8")

    return {
        "tool": {"sublist3r": tool_status("sublist3r", settings.enable_sublist3r)},
        "subdomains_found": len({normalize_hostname(host) for host in raw_hosts if host}),
        "allowed_hosts": len(allowed_hosts),
    }
