"""Adapter for the separately installed smart-search CLI.

It routes the way Hermes's smart-search skill does: `research` first, and when
research fetched pages, that evidence, carrying the page text so the web loader
does not download the page again. When research fetched fewer pages than asked
for (its web discovery stops at the first provider with any result, often a
single page), providers that return page text themselves (Exa) top it up. The
CLI's model-backed `search` is never run. Without evidence, research's unfetched
candidates and the direct provider commands supply URLs for the web loader to
fetch.
"""

import json
import os
import subprocess
from urllib.parse import parse_qsl, unquote, urlparse

import validators
from open_webui.retrieval.web.main import SearchResult, get_filtered_results

# Direct provider commands: subcommand, its count option, extra options, and the
# result field holding the page text (None: the web loader downloads the page).
_SOURCE_COMMANDS = {
    "zhipu": ("zhipu-search", "--count", (), None),
    "zhipu-mcp": ("zhipu-mcp-search", "--count", (), None),
    "exa": ("exa-search", "--num-results", ("--include-text",), "text"),
    "anysearch": ("anysearch-search", "--max-results", (), None),
}
# Result listings of these engines link to sources but are not sources.
_SEARCH_RESULT_HOSTS = {
    "duckduckgo.com",
    "html.duckduckgo.com",
    "lite.duckduckgo.com",
    "bing.com",
    "cn.bing.com",
    "baidu.com",
    "sogou.com",
    "so.com",
    "search.yahoo.com",
    "yandex.com",
    "yandex.ru",
}
_SEARCH_QUERY_PARAMS = {"q", "wd", "word", "query", "p", "text"}
# Simplified/traditional conversion gateways of Chinese government sites
# (big5.xxx.gov.cn/gate/big5/<any host>/...) re-serve any other site under
# the government domain; search engines index spam through them, and the
# page itself usually answers 403.
_MIRROR_GATEWAY_PREFIXES = ("/gate/big5/", "/gate/gb/")
# Research returns pages as markdown, sometimes several hundred KB; keep the
# per-page cap web search's embedding path applies to downloaded pages.
_MAX_CONTENT_CHARS = 100_000
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
        return payload, f"{stage}: unsuccessful response"
    return payload, None


def _capability_status(payload: dict | None) -> dict | None:
    """The CLI's configured-provider summary, present in research and doctor
    responses (including failed ones), so the slow doctor probe is only needed
    when research did not carry it."""
    if isinstance(payload, dict) and isinstance(payload.get("capability_status"), dict):
        return payload["capability_status"]
    return None


def _source_commands(
    capabilities: dict, count: int
) -> list[tuple[list[str], str | None, str]]:
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
            subcommand, count_option, options, text_key = spec
            commands.append(
                (
                    [subcommand, count_option, str(min(count, 10)), *options],
                    text_key,
                    provider,
                )
            )
    return commands


def _search_results_page(parsed) -> bool:
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    if host not in _SEARCH_RESULT_HOSTS and not host.startswith("google."):
        return False
    return any(
        key.lower() in _SEARCH_QUERY_PARAMS
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
    )


def _mirror_gateway_page(parsed) -> bool:
    return (parsed.path or "").lower().startswith(_MIRROR_GATEWAY_PREFIXES)


def _url_key(url: str) -> tuple[str, str, str]:
    """Percent-encoded and plain spellings, http/https and a trailing slash or
    fragment do not make a different page."""
    parsed = urlparse(url)
    return (
        parsed.netloc.lower(),
        unquote(parsed.path).rstrip("/"),
        unquote(parsed.query),
    )


def _results_from_items(
    items: list,
    *,
    require_evidence: bool,
    text_key: str | None = None,
    provider: str | None = None,
    found_by: dict | None = None,
) -> list[dict]:
    """``provider`` names the source of every item (a direct provider
    command); otherwise each item's own ``provider`` is used, with
    ``found_by`` (URL key -> the search that found it) taking precedence, so
    research evidence reports the search that found a page rather than the
    service that fetched it."""
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if require_evidence and (
            item.get("verified") is not True
            or not isinstance(item.get("content"), str)
            or not item["content"].strip()
        ):
            continue
        page_text = item.get("content") if require_evidence else None
        if text_key and isinstance(item.get(text_key), str):
            page_text = item[text_key]
        page_text = page_text.strip() if isinstance(page_text, str) else ""
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
            or _search_results_page(parsed)
            or _mirror_gateway_page(parsed)
        ):
            continue
        item_provider = provider or (found_by or {}).get(_url_key(url))
        if not item_provider and isinstance(item.get("provider"), str):
            item_provider = item["provider"].strip() or None
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
                "content": page_text[:_MAX_CONTENT_CHARS] or None,
                "provider": item_provider,
            }
        )
    return results


def _discovery_providers(sources) -> dict:
    """URL key -> the search provider research found the page with."""
    found_by = {}
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, dict):
            continue
        url, provider = source.get("url"), source.get("provider")
        if isinstance(url, str) and isinstance(provider, str) and provider.strip():
            try:
                found_by.setdefault(_url_key(url.strip()), provider.strip())
            except ValueError:
                continue
    return found_by


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
    capability_status = None
    results = []
    seen = set()
    # With research evidence in hand, only providers that return the page text
    # top it up (about a second, nothing left to download); pages that would
    # still have to be downloaded are not worth the wait then.
    topping_up = False

    def add_items(
        items: list,
        *,
        require_evidence: bool = False,
        text_key: str | None = None,
        require_text: bool = False,
        provider: str | None = None,
        found_by: dict | None = None,
    ) -> None:
        for item in get_filtered_results(
            _results_from_items(
                items,
                require_evidence=require_evidence,
                text_key=text_key,
                provider=provider,
                found_by=found_by,
            ),
            filter_list,
        ):
            if require_text and not item["content"]:
                continue
            key = _url_key(item["link"])
            if key not in seen:
                seen.add(key)
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

    if research_help is not None and research_help.returncode == 0:
        try:
            completed = _run(
                command,
                [
                    "research",
                    query,
                    "--budget",
                    "quick",
                    "--fallback",
                    "auto",
                    "--format",
                    "json",
                ],
                90,
            )
        except subprocess.TimeoutExpired:
            failures.append("research: timeout")
        else:
            payload, failure = _response(completed, "research")
            capability_status = _capability_status(payload)
            if failure:
                failures.append(failure)
            elif not isinstance(payload.get("evidence_items"), list):
                failures.append("research: unsuccessful response")
            else:
                had_valid_response = True
                add_items(
                    payload["evidence_items"],
                    require_evidence=True,
                    found_by=_discovery_providers(payload.get("discovery_sources")),
                )
                topping_up = bool(results)
                # Unfetched candidates only stand in for missing evidence.
                if not topping_up and isinstance(
                    payload.get("discovery_sources"), list
                ):
                    add_items(payload["discovery_sources"])
                if len(results) >= count:
                    return results[:count]

    # Direct provider commands recover from a failed or evidence-less research.
    # The provider list normally comes from the research response itself;
    # doctor is a slow probe (it tests every upstream connection), so it only
    # runs when research did not report the configured capabilities.
    if capability_status is None and not topping_up:
        try:
            completed = _run(command, ["doctor", "--format", "json"], 30)
        except subprocess.TimeoutExpired:
            failures.append("doctor: timeout")
        else:
            payload, failure = _response(completed, "doctor")
            if failure:
                failures.append(failure)
            capability_status = _capability_status(payload)
            if capability_status is None and not failure:
                failures.append("doctor: missing capability status")

    for options, text_key, provider in _source_commands(
        capability_status or {}, count
    ):
        if topping_up and text_key is None:
            continue
        subcommand = options[0]
        try:
            completed = _run(
                command,
                [subcommand, query, *options[1:], "--format", "json"],
                20 if topping_up else 35,
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
        add_items(
            source_payload["results"],
            text_key=text_key,
            require_text=topping_up,
            provider=provider,
        )
        if len(results) >= count:
            return results[:count]

    if results:
        return results[:count]
    if had_valid_response and not failures:
        return []
    raise RuntimeError(
        f"smart-search CLI search failed ({'; '.join([*unavailable, *failures])})"
    )
