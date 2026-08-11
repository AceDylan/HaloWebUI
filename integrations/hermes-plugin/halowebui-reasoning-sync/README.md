# HaloWebUI reasoning-effort sync for Hermes

This user-installable Hermes plugin reads HaloWebUI's current Message Gateway
default reasoning effort before every model API call. It uses `llm_request`
middleware to update only the effective outbound provider request; it does not
alter user or system messages.

The endpoint defaults to:

```text
http://127.0.0.1:3000/api/v1/haloclaw/runtime/reasoning-effort
```

Override it in the Hermes gateway service environment when needed:

```bash
export HALOWEBUI_REASONING_SYNC_URL=http://127.0.0.1:3000/api/v1/haloclaw/runtime/reasoning-effort
```

Requests use a short timeout and fail open. Values outside
`none|low|medium|high|xhigh|max`, malformed responses, and connection failures
leave the original Hermes request unchanged. There is no cache: each LLM
request reads the endpoint again.

## Install

From the HaloWebUI repository, either symlink the plugin:

```bash
mkdir -p ~/.hermes/plugins
ln -s "$PWD/integrations/hermes-plugin/halowebui-reasoning-sync" \
  ~/.hermes/plugins/halowebui-reasoning-sync
```

or copy it:

```bash
mkdir -p ~/.hermes/plugins
cp -R integrations/hermes-plugin/halowebui-reasoning-sync \
  ~/.hermes/plugins/halowebui-reasoning-sync
```

Add the plugin name to `~/.hermes/config.yaml`, preserving any plugins already
enabled:

```yaml
plugins:
  enabled:
    - halowebui-reasoning-sync
```

Reload or restart the Hermes gateway service once after installing/enabling the
plugin so the gateway process discovers it. After that one reload, saving a new
reasoning effort in HaloWebUI applies to the next LLM request; setting changes
do not require another Hermes service reload.
