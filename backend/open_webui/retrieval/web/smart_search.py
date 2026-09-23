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

    try:
        completed = subprocess.run(
            [
                command,
                "search",
                query,
                "--validation",
                "balanced",
                "--format",
                "json",
                "--timeout",
                "30",
            ],
            capture_output=True,
            text=True,
            timeout=35,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "smart-search CLI is not installed in the backend environment"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("smart-search CLI timed out") from exc

    if completed.returncode != 0:
        raise RuntimeError("smart-search CLI search failed")
    try:
        payload = json.loads(completed.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("smart-search CLI returned invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RuntimeError("smart-search CLI returned an unsuccessful search")
    if not isinstance(payload.get("sources"), list):
        raise TypeError("smart-search CLI returned no source list")

    sources = []
    seen = set()
    for item in payload["sources"]:
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

    filtered = get_filtered_results(sources, filter_list)
    return [SearchResult(**item) for item in filtered[: max(0, count)]]
