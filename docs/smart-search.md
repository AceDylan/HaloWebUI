# Smart Search as a HaloWebUI search engine

HaloWebUI runs the separately installed `smart-search` CLI for its shared web search engine. Select **Smart Search (CLI)** in **Admin > Settings > Web Search**, enable web search, or set `WEB_SEARCH_ENGINE=smart_search` for a new installation. The backend process needs the CLI executable and its provider configuration. HaloWebUI does not store CLI credentials.

## CLI compatibility and routing

The adapter checks `research --help` at runtime. When available, it runs `research QUERY --budget quick --fallback auto --format json` and accepts verified HTTP(S) `evidence_items` and URL-bearing `discovery_sources`. It then runs `search QUERY --validation balanced --timeout 30 --extra-sources N --format json` if more results are needed. `N` is at most three; the CLI decides whether configured Tavily or Firecrawl providers can supply those extra sources. The adapter accepts URL-bearing `sources`, not an answer's unsupported claims as web results.

If those commands do not return enough URLs, the adapter reads `doctor --format json` and uses its configured capability list to run supported source commands, in CLI provider order:

| CLI capability | Configured provider | Source command |
| --- | --- | --- |
| `web_search` | Zhipu REST | `zhipu-search QUERY --count N --format json` |
| `web_search` | Zhipu MCP | `zhipu-mcp-search QUERY --count N --format json` |
| `docs_search` | Exa | `exa-search QUERY --num-results N --format json` |
| `vertical_search` | AnySearch | `anysearch-search QUERY --max-results N --format json` |

`N` is capped at ten for each direct provider call. `research` and `search` use the CLI's own routing and can also use other providers supported by that installed build. The direct commands are a recovery path when the main search or research execution fails. The adapter deduplicates and domain-filters results and accepts only valid HTTP(S) URLs without embedded credentials. It does not turn raw model text, Context7 library IDs, or URL-free AnySearch records into search results.

CLI builds can report the same version while exposing different commands. The deployed image observed with `smart-search 0.1.14` lacks `research`; its exit 2 means the command is not recognized. The adapter skips it after checking help. Exit 4 from `search` means a network, upstream provider, or insufficient-evidence failure, and can vary by query. The adapter preserves the command, exit code, and recognized JSON `error_type` in errors, but never includes CLI stdout, stderr, provider messages, or credentials. A valid empty result is returned only when no attempted route failed; partial valid results may be returned when another route fails.

Tavily and Firecrawl do not have direct general-search subcommands in these CLI builds. They can contribute through `research` or `search --extra-sources` when those commands succeed. Context7 is a documentation lookup, Jina is a URL fetcher, and neither supplies general web search URLs through this adapter. Provider access and query behavior remain governed by the installed CLI; HaloWebUI cannot make an unconfigured or failing upstream service succeed.

## Configuration

The custom Docker image installs `@konbakuyomu/smart-search` 0.1.24 by default (`INSTALL_SMART_SEARCH=true`). That published release includes `research` and the source commands listed above. Slim runtime builds skip the CLI because they do not include npm. For another image, install a compatible CLI or set `SMART_SEARCH_CLI` to an executable path visible inside the backend container. A host executable alone is not visible inside a container.

Configure the CLI's providers and credentials in its own config. To reuse host configuration with the root-based image, mount it read-only:

```yaml
volumes:
  - /root/.config/smart-search:/root/.config/smart-search:ro
```

If the config is elsewhere, set `SMART_SEARCH_CONFIG_DIR` to the mounted container path. Do not put credentials in `SMART_SEARCH_CLI` or HaloWebUI web search settings. Use `smart-search doctor --format json` inside the backend runtime to check configured capabilities and connection status; diagnostic output can contain private configuration details, so inspect it privately. Use `smart-search research --help` to check command availability, and try a source command matching a configured provider to isolate a main-search failure.

The 0.1.24 CLI also offers explicit Sciverse academic commands. Its provider contract excludes Sciverse from default routing, so HaloWebUI does not launch it for general web search. A custom query workflow must call that CLI command explicitly.

After pulling this source change, wait for the custom image to be published and recreate the container from it. Pulling Git source alone does not change a running container. Native web search and Hermes's own internal search tools execute upstream and do not use this setting. For Hermes agent models using Halo/Auto search, HaloWebUI searches before `/v1/runs` and supplies result context; `ENABLE_WEB_SEARCH_TOOL=false` still disables that path.
