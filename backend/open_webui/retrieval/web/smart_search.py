"""Adapter for the separately installed smart-search CLI."""

import json
import os
import subprocess
from urllib.parse import urlparse

import validators
from open_webui.retrieval.web.main import SearchResult, get_filtered_results


def search_smart_search(
    query: str, count: int, filter_list: list[str] | None = None
) -> list[SearchResult]:
    command = os.getenv("SMART_SEARCH_CLI", "smart-search").strip()
    if not command:
        raise RuntimeError("SMART_SEARCH_CLI must name an executable")
    if count <= 0:
        return []

    # Source-oriented commands suit web search; the model-backed command remains
    # available for installations configured without either source provider.
    commands = (
        ("zhipu-search", ["--count", str(count)]),
        ("exa-search", ["--num-results", str(count)]),
        ("search", ["--validation", "balanced", "--timeout", "30"]),
    )
    failures = []
    had_valid_response = False
    for subcommand, options in commands:
        try:
            completed = subprocess.run(
                [command, subcommand, query, *options, "--format", "json"],
                capture_output=True,
                text=True,
                timeout=35,
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

        if completed.returncode != 0:
            failures.append(f"{subcommand}: exit {completed.returncode}")
            continue
        try:
            payload = json.loads(completed.stdout)
        except (ValueError, TypeError):
            failures.append(f"{subcommand}: invalid JSON")
            continue
        source_key = "sources" if subcommand == "search" else "results"
        if (
            not isinstance(payload, dict)
            or payload.get("ok") is not True
            or not isinstance(payload.get(source_key), list)
        ):
            failures.append(f"{subcommand}: unsuccessful response")
            continue

        had_valid_response = True
        sources = []
        seen = set()
        for item in payload[source_key]:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not isinstance(url, str):
                continue
            url = url.strip()
            parsed = urlparse(url)
            if (
                parsed.scheme not in {"http", "https"}
                or not validators.url(url)
                or parsed.username
            ):
                continue
            if url in seen:
                continue
            seen.add(url)
            sources.append(
                {
                    "link": url,
                    "title": str(item.get("title") or parsed.netloc),
                    "snippet": str(item.get("description") or ""),
                }
            )

        if sources:
            filtered = get_filtered_results(sources, filter_list)
            return [SearchResult(**item) for item in filtered[:count]]

    if had_valid_response:
        return []
    raise RuntimeError(f"smart-search CLI search failed ({'; '.join(failures)})")
