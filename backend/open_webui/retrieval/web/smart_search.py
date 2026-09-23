"""Adapter for the separately installed smart-search CLI."""

import json
import os
import subprocess
from urllib.parse import urlparse

import validators
from open_webui.retrieval.web.main import SearchResult, get_filtered_results

_SOURCE_COMMANDS = {
    "zhipu": ("zhipu-search", "--count"),
    "zhipu-mcp": ("zhipu-mcp-search", "--count"),
    "exa": ("exa-search", "--num-results"),
    "anysearch": ("anysearch-search", "--max-results"),
}
_ERROR_TYPES = {
    "config_error",
    "parameter_error",
    "network_error",
    "provider_error",
    "evidence_error",
    "runtime_error",
}


def _run(command: str, args: list[str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [command, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "smart-search CLI is not installed in the backend environment "
            f"({command!r}); install it in the backend image or set "
            "SMART_SEARCH_CLI to an executable visible to the backend process"
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"smart-search CLI could not run {args[0]}") from exc


def _response(
    completed: subprocess.CompletedProcess, stage: str
) -> tuple[dict | None, str | None]:
    try:
        payload = json.loads(completed.stdout)
    except (ValueError, TypeError):
        payload = None
    if completed.returncode != 0:
        error_type = payload.get("error_type") if isinstance(payload, dict) else None
        detail = (
            f" ({error_type})"
            if isinstance(error_type, str) and error_type in _ERROR_TYPES
            else ""
        )
        return (
            payload if isinstance(payload, dict) else None,
            f"{stage}: exit {completed.returncode}{detail}",
        )
    if not isinstance(payload, dict):
        return None, f"{stage}: invalid JSON"
    if payload.get("ok") is not True:
        return None, f"{stage}: unsuccessful response"
    return payload, None


def _source_commands(capabilities: dict, count: int) -> list[list[str]]:
    commands = []
    seen = set()
    for capability in ("web_search", "docs_search", "vertical_search"):
        status = capabilities.get(capability)
        if not isinstance(status, dict) or not isinstance(
            status.get("configured"), list
        ):
            continue
        for provider in status["configured"]:
            if not isinstance(provider, str) or provider in seen:
                continue
            spec = _SOURCE_COMMANDS.get(provider)
            if spec is None:
                continue
            seen.add(provider)
            subcommand, count_option = spec
            commands.append([subcommand, count_option, str(min(count, 10))])
    return commands


def _results_from_items(items: list, *, require_evidence: bool) -> list[dict]:
    results = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        if require_evidence and (
            item.get("verified") is not True
            or not isinstance(item.get("content"), str)
            or not item["content"].strip()
        ):
            continue
        url = item.get("url")
        if not isinstance(url, str):
            continue
        url = url.strip()
        try:
            parsed = urlparse(url)
        except ValueError:
            continue
        if (
            parsed.scheme not in {"http", "https"}
            or not validators.url(url)
            or parsed.username is not None
            or parsed.password is not None
            or url in seen
        ):
            continue
        seen.add(url)
        title = item.get("title")
        description = (
            item.get("content")
            if require_evidence
            else item.get("description") or item.get("snippet") or item.get("text")
        )
        results.append(
            {
                "link": url,
                "title": title.strip()
                if isinstance(title, str) and title.strip()
                else parsed.netloc,
                "snippet": " ".join(description[:500].split())
                if isinstance(description, str)
                else "",
            }
        )
    return results


def search_smart_search(
    query: str, count: int, filter_list: list[str] | None = None
) -> list[SearchResult]:
    command = os.getenv("SMART_SEARCH_CLI", "smart-search").strip()
    if not command:
        raise RuntimeError("SMART_SEARCH_CLI must name an executable")
    if count <= 0:
        return []

    failures = []
    unavailable = []
    had_valid_response = False
    results = []
    seen = set()

    def add_items(items: list, *, require_evidence: bool = False) -> None:
        for item in get_filtered_results(
            _results_from_items(items, require_evidence=require_evidence), filter_list
        ):
            if item["link"] not in seen:
                seen.add(item["link"])
                results.append(SearchResult(**item))

    try:
        research_help = _run(command, ["research", "--help"], 5)
    except subprocess.TimeoutExpired:
        failures.append("research help: timeout")
        research_help = None
    if research_help is not None and research_help.returncode not in (0, 2):
        failures.append(f"research help: exit {research_help.returncode}")
    if research_help is not None and research_help.returncode == 2:
        unavailable.append("research: unavailable in installed CLI")

    commands = []
    if research_help is not None and research_help.returncode == 0:
        commands.append(
            (
                "research",
                ["--budget", "quick", "--fallback", "auto"],
                90,
                "evidence_items",
            )
        )
    commands.append(
        (
            "search",
            [
                "--validation",
                "balanced",
                "--timeout",
                "30",
                "--extra-sources",
                str(min(count, 3)),
            ],
            35,
            "sources",
        )
    )
    for subcommand, options, timeout, source_key in commands:
        try:
            completed = _run(
                command, [subcommand, query, *options, "--format", "json"], timeout
            )
        except subprocess.TimeoutExpired:
            failures.append(f"{subcommand}: timeout")
            continue
        payload, failure = _response(completed, subcommand)
        if failure:
            failures.append(failure)
            continue
        if not isinstance(payload.get(source_key), list):
            failures.append(f"{subcommand}: unsuccessful response")
            continue

        had_valid_response = True
        add_items(payload[source_key], require_evidence=subcommand == "research")
        if subcommand == "research" and isinstance(
            payload.get("discovery_sources"), list
        ):
            add_items(payload["discovery_sources"])
        if len(results) >= count:
            return results[:count]

    try:
        completed = _run(command, ["doctor", "--format", "json"], 30)
    except subprocess.TimeoutExpired:
        failures.append("doctor: timeout")
        completed = None
    if completed is not None:
        payload, failure = _response(completed, "doctor")
        if failure:
            failures.append(failure)
        if isinstance(payload, dict) and isinstance(
            payload.get("capability_status"), dict
        ):
            for options in _source_commands(payload["capability_status"], count):
                subcommand = options[0]
                try:
                    completed = _run(
                        command,
                        [subcommand, query, *options[1:], "--format", "json"],
                        35,
                    )
                except subprocess.TimeoutExpired:
                    failures.append(f"{subcommand}: timeout")
                    continue
                source_payload, failure = _response(completed, subcommand)
                if failure:
                    failures.append(failure)
                    continue
                if not isinstance(source_payload.get("results"), list):
                    failures.append(f"{subcommand}: unsuccessful response")
                    continue
                had_valid_response = True
                add_items(source_payload["results"])
                if len(results) >= count:
                    return results[:count]
        elif not failure:
            failures.append("doctor: missing capability status")

    if results:
        return results[:count]
    if had_valid_response and not failures:
        return []
    raise RuntimeError(
        f"smart-search CLI search failed ({'; '.join([*unavailable, *failures])})"
    )
