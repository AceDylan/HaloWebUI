# Smart Search as a HaloWebUI search engine

HaloWebUI can use the `smart-search` CLI for its shared web search engine. The custom Docker image built by this repository installs `@konbakuyomu/smart-search` into the backend image and verifies the executable during the image build. The backend tries the CLI's source-oriented `zhipu-search` and `exa-search` commands, then the model-backed `search` command for installations without those providers. It maps URL-bearing `results` or `sources` to normal web search results. Search engine selection remains in **Admin > Settings > Web Search**; select **Smart Search (CLI)** and enable HaloWebUI web search. You can also set `WEB_SEARCH_ENGINE=smart_search` for a new installation.

The Dockerfile defaults to `INSTALL_SMART_SEARCH=true`, so a newly built custom image with the normal `main` runtime profile has the CLI at `/usr/local/bin/smart-search`. Slim runtime builds skip the CLI because they do not include npm. If you build another image, keep that build argument enabled or install the package in the image yourself. Set `SMART_SEARCH_CLI` to another executable path only when you intentionally provide a different CLI.

The CLI reads its own provider configuration and credentials; HaloWebUI does not copy them into its database. Configure at least one of Zhipu Web Search, Exa, or a working main search provider. To reuse a host installation's configuration with the container image, mount the host config directory read-only at the container user's default path (for the root image: `/root/.config/smart-search`), for example:

```yaml
volumes:
  - /root/.config/smart-search:/root/.config/smart-search:ro
```

If the config is stored elsewhere, set `SMART_SEARCH_CONFIG_DIR` to the mounted container path. A CLI or config on the host is not visible to a container unless it is installed in the image or explicitly mounted. Never put provider credentials in `SMART_SEARCH_CLI` or the web UI search settings.

After pulling this source change, wait for the GitHub Action to publish the new custom image, then recreate the HaloWebUI container from that image. Pulling Git source alone does not change an already-running container. Verify the runtime before testing a chat with `docker exec <container> smart-search --version` and `docker exec <container> smart-search doctor --format json`. A nonzero CLI exit shows the attempted command names and exit codes in the search error; provider output and credentials are never included.

Normal models use this engine through Halo/Auto web search and the built-in `search_web` tool when those features and permissions are enabled. Hermes agent models can select Halo/Auto search when Smart Search is the configured engine: HaloWebUI searches before `/v1/runs` and supplies the resulting context to Hermes. The model's explicit `ENABLE_WEB_SEARCH_TOOL=false` still disables this path. **Native** web search and Hermes's own internal search tools execute upstream and do not use this setting. A search response without usable HTTP(S) source URLs tries the next CLI command; an empty result is returned if all successful commands lack usable URLs. The search fails when every CLI command fails.
