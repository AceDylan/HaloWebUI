# WebObsidian vault, read-only, as a workspace tool

`webobsidian_tool.py` lets a model in HaloWebUI **search and read** the notes in a
[WebObsidian](https://github.com/AceDylan/webobsidian) vault through WebObsidian's
own Agent API (`/api/v1`). It is not imported by the application: it is pasted into
**Workspace → Tools**, the way every other Open WebUI tool is installed.

Four calls are offered to the model, and nothing else:

| Call | Vault endpoint | Scope needed |
|---|---|---|
| `search_notes(query, limit)` | `GET /api/v1/search` | `search` |
| `read_note(path)` | `GET /api/v1/notes/{path}` | `read` |
| `list_notes(folder, limit)` | `GET /api/v1/notes` | `read` |
| `find_backlinks(path)` | `GET /api/v1/backlinks` | `read` |

## Why read-only

The key this tool holds is reachable by anything the model can be talked into —
a web page it summarises, a file somebody uploads. With `read` + `search` the
worst case is that the vault can be quoted back. With `write` the worst case is a
vault edit nobody asked for, and the deployment this was built for has
`git.autoCommitOnSave = false`, i.e. no version history to undo it with.

Writing into the vault is the Bookmark Hub's job instead: it holds a **separate**
key and its backend refuses any path outside one inbox folder. Two keys, two
scopes, two blast radii.

## Install

1. **Create the key.** In WebObsidian: *Settings → API Keys → New*. Name it
   something like `halowebui-read`, and give it **`read` and `search` only** —
   not `write`. The raw key (`wok_…`) is shown exactly once.
2. **Make WebObsidian reachable from the HaloWebUI container.** The HaloWebUI
   container is on a bridge network and WebObsidian typically listens on the
   host's loopback only, so the request goes out through the public reverse
   proxy. If that vhost is behind HTTP basic auth, add an exception for the
   Agent API — see below.
3. **Add the tool.** HaloWebUI → *Workspace → Tools → +*, paste the whole of
   `webobsidian_tool.py`, save.
4. **Fill the valves** (the gear next to the tool):

   | Valve | Example | Notes |
   |---|---|---|
   | `base_url` | `https://notes.example.com:3003` | Origin only, no path, no trailing slash. Empty = the tool answers "not configured" and calls nothing. |
   | `api_key` | `wok_…` | The key from step 1. Stored by HaloWebUI, never in this repository. |
   | `timeout_seconds` | `8` | Clamped to 1–30. A chat must not hang on the vault. |
   | `max_results` | `10` | Ceiling the model cannot argue its way past. |
   | `max_note_chars` | `8000` | Longer notes come back truncated, with `"truncated": true`. |
   | `verify_tls` | `true` | Only turn off for a self-signed lab instance. |

5. Enable the tool on the models that should have it (*Workspace → Models →
   edit → Tools*), or per chat from the **+** menu.

## The reverse-proxy exception

A vhost that protects WebObsidian's web UI with basic auth will also reject the
Agent API, which authenticates with its own key. Give `/api/v1/` its own
location:

```nginx
# Inside the existing WebObsidian server { } block, before `location / { }`.
location /api/v1/ {
    auth_basic off;                 # the Agent API authenticates with X-API-Key

    proxy_pass http://127.0.0.1:18787;
    proxy_http_version 1.1;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;

    # Do NOT include the trusted-proxy snippet here: that header is what turns a
    # request into an authenticated session without a key, and it must stay on the
    # browser-facing location only.

    # Optional and recommended: only the machines that are meant to call this.
    # allow 203.0.113.10;  # the Bookmark Hub
    # allow 198.51.100.7;  # this host
    # deny all;
}
```

Two things to know about nginx here:

- `add_header` does **not** inherit into a location that declares its own. If the
  server block sets security headers, either repeat them in this location or set
  none at all — do not add one and silently drop the rest.
- Some vhosts clear `Authorization` (`proxy_set_header Authorization "";`) so the
  upstream never sees the basic-auth credentials. That is why this tool sends the
  key as `X-API-Key` and never as `Authorization: Bearer`.

Check it without a browser:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "X-API-Key: $KEY" https://notes.example.com:3003/api/v1/health   # 200
curl -s -o /dev/null -w '%{http_code}\n' \
  https://notes.example.com:3003/api/v1/health                        # 401
```

## Behaviour worth knowing

- **Paths are cleaned before they are sent.** `..`, backslashes, control
  characters, dot-directories (`.git`, `.trash`, `.obsidian`) and anything over
  400 characters are refused locally, so a confused model gets a sentence rather
  than a 400. A leading `/` is dropped, which is what WebObsidian does too.
- **Failures are sentences, not exceptions.** A timeout, a dead host, 401, 403,
  429 and 5xx each come back as one line the model can relay.
- **WebObsidian logs the paths it serves** (`[api] <key name> GET /notes/…`).
  Note titles therefore end up in that container's log.
- Tests: `backend/open_webui/test/unit/test_webobsidian_tool.py` loads this file
  the way HaloWebUI does and pins the tool surface, the path handling and the
  timeout/header contract.
