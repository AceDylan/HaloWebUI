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

The adapter checks `research --help` at runtime. When available, it runs `research QUERY --budget quick --fallback auto --format json` and accepts verified HTTP(S) `evidence_items` and URL-bearing `discovery_sources`. It then runs `search QUERY --validation balanced --timeout 30 --extra-sources N --format json` if more results are needed. `N` is at most three; the CLI decides whether configured Tavily or Firecrawl providers can supply those extra sources. The adapter accepts URL-bearing `sources`, not an answer's unsupported claims as web results.

If those commands do not return enough URLs, the adapter runs supported source commands directly, in CLI provider order:

| CLI capability | Configured provider | Source command |
| --- | --- | --- |
| `web_search` | Zhipu REST | `zhipu-search QUERY --count N --format json` |
| `web_search` | Zhipu MCP | `zhipu-mcp-search QUERY --count N --format json` |
| `docs_search` | Exa | `exa-search QUERY --num-results N --format json` |
| `vertical_search` | AnySearch | `anysearch-search QUERY --max-results N --format json` |

The configured-provider list comes from the `capability_status` block that `research` and `search` include in their JSON output, including failed responses. Only when no earlier response carried it does the adapter run `doctor --format json`; doctor tests every upstream connection and has been measured at 10–25 seconds, so skipping it keeps the recovery path to a few seconds. `N` is capped at ten for each direct provider call. The adapter deduplicates and domain-filters results and accepts only valid HTTP(S) URLs without embedded credentials. It does not turn raw model text, Context7 library IDs, or URL-free AnySearch records into search results.

The host's `smart-search 0.1.14` exposes `research`, `search`, `doctor` and the source commands above; CLI builds can report the same version while exposing different commands, and a build whose `research --help` exits 2 is skipped after the help check. Exit 4 from `search` means a network, upstream provider, or insufficient-evidence failure, and can vary by query; with this host's configuration the main-search model (`OPENAI_COMPATIBLE_MODEL`) has returned empty results for ordinary queries on the host as well as in the container, which is why `research` (Exa + Tavily) is tried first. The CLI's `search` does not fall back to Zhipu or any other source when its main-search model fails or returns nothing: its only main-search fallbacks are another main-search provider (xAI Responses, if configured), a fallback model, and stream/non-stream transport, after which it exits 4 without running its supplemental docs/web providers. Recovery from that failure is entirely the adapter's direct provider stage above. The adapter preserves the command, exit code, and recognized JSON `error_type` in errors, but never includes CLI stdout, stderr, provider messages, or credentials. A valid empty result is returned only when no attempted route failed; partial valid results may be returned when another route fails.

**Zhipu only contributes when its engine returns links.** On this host (2026-09-24) the Zhipu Web Search API returned every result with an empty `link` for the `search_std` and `search_pro` engines, while `search_pro_sogou`, `search_pro_quark` and `search_pro_jina` returned real URLs. The CLI maps `link` to `url`, and both the CLI's own `research` web discovery and this adapter drop URL-less items. With the host's current `ZHIPU_SEARCH_ENGINE=search_std`, Zhipu is therefore tried first for current-events and Chinese queries but contributes nothing: `research` records the attempt as `empty` and continues with Tavily, and the adapter's `zhipu-search` stage returns `ok` with no usable result and continues with `exa-search`. To make Zhipu contribute, switch the CLI's engine (`smart-search config set ZHIPU_SEARCH_ENGINE search_pro_quark`; the pro engines are billed at a different rate) and verify with `smart-search zhipu-search QUERY --count 3 --format json` that `results[].url` is non-empty.

Tavily and Firecrawl do not have direct general-search subcommands in these CLI builds. They can contribute through `research` or `search --extra-sources` when those commands succeed. Context7 is a documentation lookup, Jina is a URL fetcher, and neither supplies general web search URLs through this adapter. Provider access and query behavior remain governed by the installed CLI; HaloWebUI cannot make an unconfigured or failing upstream service succeed. The CLI's Sciverse academic commands are excluded from default routing by its provider contract, so HaloWebUI does not launch them for general web search.

## Operations

A compose-only change (mounts, `SMART_SEARCH_CLI`) takes effect after `docker compose up -d` recreates the container; an adapter change needs the published custom image. Native web search and Hermes's own internal search tools execute upstream and do not use this setting. For Hermes agent models using Halo/Auto search, HaloWebUI searches before `/v1/runs` and supplies result context; `ENABLE_WEB_SEARCH_TOOL=false` still disables that path. If the CLI is installed and the engine is saved but no CLI call occurs, check the chat composer's current mode and any model-level opt-out first. A search skipped by Smart Web Search's intent decision also makes no CLI call; use HaloWebUI Search for a deterministic route check.

To check the route end to end without the chat UI, run the adapter inside the container (it prints only URLs and titles):

```sh
docker exec -w /app/backend halowebui python3 -c "from open_webui.retrieval.web.smart_search import search_smart_search as s; print([r.link for r in s('OpenAI GPT-5 release date', 5)])"
```
