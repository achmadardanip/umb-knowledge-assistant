from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.config import get_settings
from app.core.paths import project_path
from app.discovery.external_tools import run_tool, tool_status
from app.discovery.safe_wordlists import write_safe_wordlist
from app.discovery.scope_validator import validate_url_scope
from app.discovery.url_normalizer import normalize_url


logger = logging.getLogger(__name__)


def discovery_dir() -> Path:
    return project_path("data", "discovery")


def read_allowed_hosts(path: str | Path | None = None) -> list[str]:
    target = Path(path) if path else discovery_dir() / "allowed_hosts.txt"
    if not target.exists():
        return []
    return [line.strip() for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]


def _scheme_hosts(hosts: list[str]) -> list[str]:
    return [f"https://{host}" if not host.startswith(("http://", "https://")) else host for host in hosts]


def _cap_output_file(path: Path, max_lines: int) -> int:
    if max_lines <= 0 or not path.exists():
        return 0
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(lines) <= max_lines:
        return len(lines)
    path.write_text("\n".join(lines[:max_lines]) + "\n", encoding="utf-8")
    logger.info("Capped %s to %s discovered URL candidates.", path, max_lines)
    return max_lines


def discover_urls(domain: str, max_depth: int = 3) -> dict:
    settings = get_settings()
    target_dir = discovery_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    hosts = read_allowed_hosts()
    if not hosts:
        hosts = [domain]
        (target_dir / "allowed_hosts.txt").write_text(domain + "\n", encoding="utf-8")

    host_lines = "\n".join(_scheme_hosts(hosts)) + "\n"
    host_urls_path = target_dir / "allowed_hosts_urls.txt"
    host_urls_path.write_text(host_lines, encoding="utf-8")
    tools: dict[str, str] = {}

    katana_result = run_tool(
        "katana",
        [
            "katana",
            "-list",
            str(host_urls_path),
            "-o",
            str(target_dir / "urls_katana.txt"),
            "-silent",
            "-jc",
            "-d",
            str(max_depth),
            "-rl",
            str(settings.discovery_rate_limit),
            "-hrl",
            str(settings.discovery_rate_limit),
            "-mdp",
            str(max(1, settings.discovery_max_urls // max(len(hosts), 1))),
        ],
        enabled=settings.enable_katana,
        timeout_seconds=max(settings.discovery_timeout_seconds, 300),
    )
    tools["katana"] = katana_result.status if katana_result.status != "error" else "available"
    katana_count = _cap_output_file(target_dir / "urls_katana.txt", settings.discovery_max_urls)

    hakrawler_result = run_tool(
        "hakrawler",
        ["hakrawler", "-depth", str(max_depth), "-plain"],
        enabled=settings.enable_hakrawler,
        timeout_seconds=max(settings.discovery_timeout_seconds, 300),
        stdin=host_lines,
        output_path=target_dir / "urls_hakrawler.txt",
    )
    tools["hakrawler"] = hakrawler_result.status if hakrawler_result.status != "error" else "available"
    hakrawler_count = _cap_output_file(target_dir / "urls_hakrawler.txt", settings.discovery_max_urls)

    gau_result = run_tool(
        "gau",
        ["gau", "--subs"],
        enabled=settings.enable_gau,
        timeout_seconds=max(settings.discovery_timeout_seconds, 300),
        stdin="\n".join(hosts) + "\n",
        output_path=target_dir / "urls_gau.txt",
    )
    tools["gau"] = gau_result.status if gau_result.status != "error" else "available"
    gau_count = _cap_output_file(target_dir / "urls_gau.txt", settings.discovery_max_urls)

    wayback_result = run_tool(
        "waybackurls",
        ["waybackurls"],
        enabled=settings.enable_waybackurls,
        timeout_seconds=max(settings.discovery_timeout_seconds, 300),
        stdin="\n".join(hosts) + "\n",
        output_path=target_dir / "urls_wayback.txt",
    )
    tools["waybackurls"] = wayback_result.status if wayback_result.status != "error" else "available"
    wayback_count = _cap_output_file(target_dir / "urls_wayback.txt", settings.discovery_max_urls)

    tools["ffuf"] = "disabled"
    if settings.enable_ffuf:
        write_safe_wordlist(settings.safe_wordlist_path)
        ffuf_urls: list[str] = []
        for host in hosts:
            out = target_dir / f"ffuf_{host}.json"
            result = run_tool(
                "ffuf",
                [
                    "ffuf",
                    "-w",
                    settings.safe_wordlist_path,
                    "-u",
                    f"https://{host}/FUZZ",
                    "-o",
                    str(out),
                    "-of",
                    "json",
                    "-rate",
                    str(settings.ffuf_rate_limit),
                ],
                enabled=True,
                timeout_seconds=max(settings.discovery_timeout_seconds, 60),
            )
            tools["ffuf"] = result.status if result.status != "error" else "available"
            if out.exists():
                try:
                    payload = json.loads(out.read_text(encoding="utf-8"))
                    ffuf_urls.extend(item.get("url", "") for item in payload.get("results", []))
                except json.JSONDecodeError:
                    logger.warning("Could not parse %s", out)
        (target_dir / "urls_ffuf.txt").write_text("\n".join(ffuf_urls) + "\n", encoding="utf-8")

    tools["dirsearch"] = "disabled"
    if settings.enable_dirsearch:
        write_safe_wordlist(settings.safe_wordlist_path)
        dirsearch_urls: list[str] = []
        for host in hosts:
            result = run_tool(
                "dirsearch",
                [
                    "dirsearch",
                    "-u",
                    f"https://{host}/",
                    "-w",
                    settings.safe_wordlist_path,
                    "--max-rate",
                    str(settings.dirsearch_rate_limit),
                    "--plain-text-report",
                    str(target_dir / f"dirsearch_{host}.txt"),
                ],
                enabled=True,
                timeout_seconds=max(settings.discovery_timeout_seconds, 60),
            )
            tools["dirsearch"] = result.status if result.status != "error" else "available"
        (target_dir / "urls_dirsearch.txt").write_text("\n".join(dirsearch_urls) + "\n", encoding="utf-8")

    return {
        "tools": tools,
        "hosts": len(hosts),
        "raw_url_counts": {
            "katana": katana_count,
            "hakrawler": hakrawler_count,
            "gau": gau_count,
            "waybackurls": wayback_count,
        },
    }


def filter_allowed_urls(urls: list[str], domain: str) -> tuple[list[str], list[dict]]:
    allowed: list[str] = []
    rejected: list[dict] = []
    seen: set[str] = set()
    for raw_url in urls:
        if not raw_url.strip():
            continue
        normalized = normalize_url(raw_url)
        decision = validate_url_scope(normalized, domain)
        if not decision.is_allowed:
            rejected.append({"url": normalized, "reason": decision.reason})
            continue
        if normalized not in seen:
            seen.add(normalized)
            allowed.append(normalized)
    return allowed, rejected
