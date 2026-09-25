# Smart Search as a HaloWebUI search engine

HaloWebUI runs the separately installed `smart-search` CLI for its shared web search engine. Select **Smart Search (CLI)** in **Admin > Settings > Web Search**, enable web search, or set `WEB_SEARCH_ENGINE=smart_search` for a new installation. The backend process needs the CLI executable and its provider configuration. HaloWebUI does not store CLI credentials.

Selecting the engine does not force every chat to search. In the chat composer, choose **HaloWebUI Search** to search on that turn, or **Smart Web Search** to let HaloWebUI decide whether a search is needed. **Model Native Web Search** runs through the model provider instead of this CLI, and **Off** never searches. A model-level `ENABLE_WEB_SEARCH_TOOL=false` also disables HaloWebUI search for that model. After changing the engine in Admin settings, the authenticated chat configuration must refresh so the composer can route Hermes models to HaloWebUI; older builds fetched the anonymous configuration after saving and incorrectly left the composer on **Off**.

## Reusing the host's CLI (deployed configuration)

The deployed `docker-compose.yaml` runs the **host's** smart-search install inside the container instead of a second copy, the same way it runs the host's `agy` binary. Three read-only bind mounts and one variable do it:

| Mount / setting | Purpose |
| --- | --- |
| `/usr/local/lib/node_modules/@konbakuyomu` → `/opt/host-smart-search` | The npm global package with its bundled Python venv (`.smart-search-python`). The scope directory is mounted, not the package directory, so `npm i -g @konbakuyomu/smart-search` on the host replaces the package and the container sees the new version on the next search. |
| `/usr/local/share/uv/python` → same path | The venv's `bin/python` symlinks point at the host's uv-managed interpreter by absolute path, so that tree must be visible at the same path inside the container. |
| `/root/.config/smart-search` → same path | The CLI's provider configuration and credentials. |
| `SMART_SEARCH_CLI=/opt/host-smart-search/smart-search/npm/bin/smart-search.js` | The node wrapper the adapter executes (the container ships node). |

With this the container runs exactly the host's CLI version and provider set; `smart-search doctor` on the host describes what HaloWebUI will use. If the host venv is ever recreated with an interpreter outside `/usr/local/share/uv/python`, the wrapper exits 5 and HaloWebUI reports `smart-search CLI search failed (research help: exit 5; ...)`; mount that interpreter's directory at the same path, or remove `SMART_SEARCH_CLI` to use the image copy.

The config mount is read-only on purpose: the container cannot change host configuration. The CLI then prints `activity recording unavailable; the command will continue` on stderr for every call and does not persist provider cooldown state. That is expected and harmless; HaloWebUI discards CLI stderr.

### Fallback: the copy baked into the image

The custom Docker image also installs `@konbakuyomu/smart-search` (`INSTALL_SMART_SEARCH=true`, version `SMART_SEARCH_VERSION` in the Dockerfile). It is used when `SMART_SEARCH_CLI` is unset, for deployments that cannot mount the host install. Slim runtime builds skip it because they do not include npm. For another image, install a compatible CLI or set `SMART_SEARCH_CLI` to an executable path visible inside the backend container. A host executable alone is not visible inside a container; it needs the mounts above.

Configure the CLI's providers and credentials in its own config; if it lives elsewhere, mount it and set `SMART_SEARCH_CONFIG_DIR` to the container path. Do not put credentials in `SMART_SEARCH_CLI` or HaloWebUI web search settings. Use `smart-search doctor --format json` inside the backend runtime to check configured capabilities and connection status; diagnostic output can contain private configuration details, so inspect it privately.

## CLI compatibility and routing

The adapter calls the CLI the way Hermes's `smart-search-cli` skill does. It checks `research --help` at runtime and, when available, runs `research QUERY --budget quick --fallback auto --format json`. When research fetched pages, the verified HTTP(S) `evidence_items` come first, as in Hermes's acceptance gate (fetched original-source evidence answers the query; discovery-only candidates do not). Each result carries the page text research extracted, so web search puts that text in the chat context instead of downloading the page again with the web loader. The text is capped at 100,000 characters per page, the cap the embedding path applies to downloaded pages.

When research fetched fewer than `N` pages, the adapter tops the evidence up with the configured providers that return page text themselves, which today is only Exa: `exa-search QUERY --num-results N --include-text --format json`, 20 s timeout. Research's web discovery stops at the first provider that returns anything, so a Zhipu reply with a single link used to leave the query with that one page (two of three queries in a 2026-09-25 chat, both 2025 articles). On the host on 2026-09-25 the Exa call took about 1.1 s and returned five 2026 articles with 1.6–3.8k characters of text each for the same queries. Results without text, and the providers whose pages would still have to be downloaded, are not used for the top-up; if Exa is not configured or fails, the research evidence is returned as it is.

The adapter never runs the CLI's model-backed `search`. Hermes does not call it either; on this host its main-search model needs 13–21 s, gets 15 s of the 30 s timeout per candidate, and exited 4 in three of three runs on 2026-09-25, so the old `research` → `search` step added 19–22 s and returned nothing whenever research found fewer than `N` URLs.

If research is unavailable, fails, or fetched no page, the adapter first takes research's URL-bearing `discovery_sources` (candidates it did not fetch) and then runs supported source commands directly, in CLI provider order. Exa results carry their page text; the others carry none, so the web loader downloads them:

| CLI capability | Configured provider | Source command |
| --- | --- | --- |
| `web_search` | Zhipu REST | `zhipu-search QUERY --count N --format json` |
| `web_search` | Zhipu MCP | `zhipu-mcp-search QUERY --count N --format json` |
| `docs_search` | Exa | `exa-search QUERY --num-results N --include-text --format json` |
| `vertical_search` | AnySearch | `anysearch-search QUERY --max-results N --format json` |

The configured-provider list comes from the `capability_status` block that `research` includes in its JSON output, including failed responses. Only when no earlier response carried it does the adapter run `doctor --format json`; doctor tests every upstream connection and has been measured at 10–25 seconds, so skipping it keeps the recovery path to a few seconds. `N` is capped at ten for each direct provider call. The adapter domain-filters results and accepts only valid HTTP(S) URLs without embedded credentials. It deduplicates URLs after percent-decoding, ignoring the scheme, a trailing slash and the fragment, and drops search-engine result listings (for example `duckduckgo.com/html/?q=…`, `google.*/search?q=…`, `baidu.com/s?wd=…`) that providers sometimes return as sources. It does not turn raw model text, Context7 library IDs, or URL-free AnySearch records into search results.

The host's `smart-search 0.1.14` exposes `research`, `search`, `doctor` and the source commands above (the adapter does not use `search`); CLI builds can report the same version while exposing different commands, and a build whose `research --help` exits 2 is skipped after the help check and goes straight to the direct provider stage. The adapter preserves the command, exit code, and recognized JSON `error_type` in errors, but never includes CLI stdout, stderr, provider messages, or credentials. A valid empty result is returned only when no attempted route failed; partial valid results may be returned when another route fails.

**Zhipu only contributes when its engine returns links.** On this host (2026-09-24) the Zhipu Web Search API returned every result with an empty `link` for the `search_std` and `search_pro` engines, while `search_pro_sogou`, `search_pro_quark` and `search_pro_jina` returned real URLs. The CLI maps `link` to `url`, and both the CLI's own `research` web discovery and this adapter drop URL-less items. With the host's current `ZHIPU_SEARCH_ENGINE=search_std`, Zhipu is therefore tried first for current-events and Chinese queries but contributes nothing: `research` records the attempt as `empty` and continues with Tavily, and the adapter's `zhipu-search` stage returns `ok` with no usable result and continues with `exa-search`. To make Zhipu contribute, switch the CLI's engine (`smart-search config set ZHIPU_SEARCH_ENGINE search_pro_quark`; the pro engines are billed at a different rate) and verify with `smart-search zhipu-search QUERY --count 3 --format json` that `results[].url` is non-empty.

Tavily and Firecrawl do not have direct general-search subcommands in these CLI builds. They contribute through `research`. Context7 is a documentation lookup, Jina is a URL fetcher, and neither supplies general web search URLs through this adapter. Provider access and query behavior remain governed by the installed CLI; HaloWebUI cannot make an unconfigured or failing upstream service succeed. The CLI's Sciverse academic commands are excluded from default routing by its provider contract, so HaloWebUI does not launch them for general web search.

## Result count and concurrency

`N` in the commands above is **Admin > Settings > Web Search > Search Result Count** (`WEB_SEARCH_RESULT_COUNT`, persisted as `rag.web.search.result_count`; the source default is 3, and the persisted value wins over the environment default once an admin has saved the page). It is the number of unique URLs the adapter returns per query, not a per-provider request size:

- `research` takes no count. The CLI's `research` asks its web-discovery chain for 5 results (`count=5` in the CLI's `service.py`), asks Exa or AnySearch for 5, and fetches at most 6 candidate URLs, so a successful `research` yields at most about 5 pages whatever `N` is; above that, and whenever it fetched fewer than `N`, the Exa top-up supplies the rest (up to 10). Research alone measured 4–16 s per query in the container on 2026-09-25.
- The direct provider commands, which run when research fetched no page (all of them) or fewer than `N` pages (Exa only), receive `min(N, 10)`.

**Concurrent Requests** (`WEB_SEARCH_CONCURRENT_REQUESTS`, `rag.web.search.concurrent_requests`, source default 10) never reaches the CLI. HaloWebUI uses it only when it downloads returned URLs that carry no page text (the fallback path above): with the default `safe_web` loader it is the size of an `asyncio.Semaphore` bounding simultaneous page downloads per query (langchain's `WebBaseLoader` names the parameter `requests_per_second` but uses it as a semaphore), and with the Tavily, Firecrawl and Playwright loaders it is a true requests-per-second interval. Keep it at 1 or more: the `safe_web` loader waits forever on a semaphore of 0. The CLI's own parallelism is fixed in its code and has no config key: `research` runs its discovery providers and candidate fetches one after another. The remaining parallelism is HaloWebUI's chat handler, which keeps at most three generated queries per turn and runs up to three of them at once, so one turn can have up to three CLI processes and, on the fallback path, 3 × Concurrent Requests page downloads in flight.

## Operations

A compose-only change (mounts, `SMART_SEARCH_CLI`) takes effect after `docker compose up -d` recreates the container; an adapter change needs the published custom image. Native web search and Hermes's own internal search tools execute upstream and do not use this setting. For Hermes agent models using Halo/Auto search, HaloWebUI searches before `/v1/runs` and supplies result context; `ENABLE_WEB_SEARCH_TOOL=false` still disables that path. If the CLI is installed and the engine is saved but no CLI call occurs, check the chat composer's current mode and any model-level opt-out first. A search skipped by Smart Web Search's intent decision also makes no CLI call; use HaloWebUI Search for a deterministic route check.

To check the route end to end without the chat UI, run the adapter inside the container (it prints only URLs and titles):

```sh
docker exec -w /app/backend halowebui python3 -c "from open_webui.retrieval.web.smart_search import search_smart_search as s; print([r.link for r in s('OpenAI GPT-5 release date', 5)])"
```
