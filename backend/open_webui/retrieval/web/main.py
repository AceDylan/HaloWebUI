import validators

from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel


def get_filtered_results(results, filter_list):
    if not filter_list:
        return results
    filtered_results = []
    for result in results:
        url = result.get("url") or result.get("link", "")
        if not validators.url(url):
            continue
        domain = urlparse(url).netloc
        if any(domain.endswith(filtered_domain) for filtered_domain in filter_list):
            filtered_results.append(result)
    return filtered_results


class SearchResult(BaseModel):
    link: str
    title: Optional[str]
    snippet: Optional[str]
    favicon: Optional[str] = None
    # Page text the engine already fetched (Smart Search research evidence);
    # web search uses it instead of downloading the page again.
    content: Optional[str] = None
    # Which upstream search found the page (Smart Search: zhipu, tavily,
    # exa, ...); shown with the search status.
    provider: Optional[str] = None
