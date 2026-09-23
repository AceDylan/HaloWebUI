"""Adapter for the separately installed smart-search CLI."""

import json
import os
import subprocess
from urllib.parse import urlparse

import validators
from open_webui.retrieval.web.main import SearchResult, get_filtered_results


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
            else item.get("description") or item.get("snippet")
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

    commands = (
        ("research", ["--budget", "quick", "--fallback", "auto"], 90, "evidence_items"),
        ("search", ["--validation", "balanced", "--timeout", "30"], 35, "sources"),
    )
    failures = []
    had_valid_response = False
    for subcommand, options, timeout, source_key in commands:
        try:
            completed = subprocess.run(
                [command, subcommand, query, *options, "--format", "json"],
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
        except subprocess.TimeoutExpired:
            failures.append(f"{subcommand}: timeout")
            continue
        except (OSError, UnicodeError) as exc:
            raise RuntimeError(f"smart-search CLI could not run {subcommand}") from exc

        if completed.returncode != 0:
            failures.append(f"{subcommand}: exit {completed.returncode}")
            continue
        try:
            payload = json.loads(completed.stdout)
        except (ValueError, TypeError):
            failures.append(f"{subcommand}: invalid JSON")
            continue
        if (
            not isinstance(payload, dict)
            or payload.get("ok") is not True
            or not isinstance(payload.get(source_key), list)
        ):
            failures.append(f"{subcommand}: unsuccessful response")
            continue

        had_valid_response = True
        results = _results_from_items(
            payload[source_key], require_evidence=subcommand == "research"
        )
        if results:
            filtered = get_filtered_results(results, filter_list)
            return [SearchResult(**item) for item in filtered[:count]]

    if had_valid_response:
        return []
    raise RuntimeError(f"smart-search CLI search failed ({'; '.join(failures)})")
