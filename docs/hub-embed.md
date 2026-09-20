# Bookmark Hub embed (`/hub`)

HaloWebUI can show the Bookmark Hub ([AICheckIn](https://github.com/AceDylan/AICheckIn)) inside
its own window: a **Bookmarks** entry in the sidebar opens `/hub`, which frames the Hub, and
**Open Bookmark Hub** in the user menu opens it in a new tab as a fallback. Both are shown to
**admins only**, because opening the Hub this way signs the viewer in as the Hub's administrator.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `HUB_URL` | `https://best.acedylan.us:5526` | Origin of the Hub (`scheme://host[:port]`, nothing else). Empty string removes the feature. |
| `HUB_TRUSTED_EMBED_ADMIN_SECRET` | unset | Secret shared with the Hub, at least 32 characters. Unset: the frame still loads, the Hub asks for its own password. |

The Hub needs the matching settings in its own `.env` (see its `SECURITY.md`):

```bash
HUB_FRAME_ANCESTORS=https://host.acedylan.us:3001      # the address HaloWebUI is served from
HUB_TRUSTED_EMBED_ADMIN_SECRET=<the same value as on HaloWebUI>
```

Generate the secret when deploying, on the machine, and paste it into both `.env` files:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**Never commit it.** Whoever holds it can become the Hub's administrator. It belongs in the
deployment's `.env` (mode `0600`), passed through the compose file as
`HUB_TRUSTED_EMBED_ADMIN_SECRET: ${HUB_TRUSTED_EMBED_ADMIN_SECRET}`.

## How the sign-in bridge works

The two sites are different hosts, so neither can read the other's cookie. A signed,
single-use ticket carries the sign-in across, in one direction only (HaloWebUI → Hub):

1. `/hub` calls `POST /api/v1/hub/embed`. The endpoint requires a HaloWebUI **admin** session.
2. The backend signs `v1.enter.<expiry>.<nonce>.<HMAC-SHA256>` with a key derived from the
   shared secret (`open_webui/utils/hub_embed.py`). The ticket lives two minutes. Nothing is
   fetched from the Hub to build it.
3. The iframe loads `<HUB_URL>/embed/enter?ticket=…`. The Hub checks signature, purpose, expiry
   and that the nonce is unused, sets its ordinary HMAC session cookie (12 hours by default) and
   redirects to a URL without the ticket.

The secret itself never leaves either server: not to the browser, not into a URL, not over the
network between the two. The ticket does appear in a URL (and therefore in the Hub's reverse-proxy
access log), which is why it is single-use and short-lived — by the time it is logged it is spent.

The frame is sandboxed (`allow-scripts allow-same-origin allow-forms allow-popups
allow-popups-to-escape-sandbox allow-downloads allow-modals`, no `allow-top-navigation`) and sent
with `referrerpolicy="no-referrer"`.

### Start-up handshake

On start-up (in the background, never blocking) the backend posts a `probe` ticket to
`<HUB_URL>/api/embed/handshake`. A probe ticket cannot be traded for a session; the Hub only
answers whether the secrets match and which origins it allows to frame it. The result drives the
hints on `/hub`:

| Handshake result | What `/hub` does |
|---|---|
| ok | frames the Hub through the ticket exchange |
| ok, but this site is not in the Hub's allow-list | same, plus a hint to fix `HUB_FRAME_ANCESTORS` (the browser will refuse the frame) |
| secret mismatch / Hub has no secret | frames the plain Hub page **without** a ticket and says why (a refused ticket would count against the Hub's brute-force limit) |
| Hub unreachable from the backend | still uses a ticket — the browser reaches the Hub on its own |

A handshake that has not succeeded is retried when an admin opens `/hub` (at most once a minute),
so fixing the Hub's configuration needs no restart here.

## Requirements and limits

- Both servers need roughly correct clocks (NTP): a ticket is valid for two minutes.
- Both sites must share a registrable domain (`host.acedylan.us` / `best.acedylan.us` do) so the
  Hub's `SameSite=Lax` cookie is sent inside the frame. On unrelated domains browsers treat it as a
  third-party cookie and may drop it.
- Signing out of HaloWebUI does not end a Hub session that was already issued; it expires on its
  own (12 hours by default, `HUB_TRUSTED_EMBED_SESSION_TTL` on the Hub).
- Rotating the secret: change it on both sides, recreate both containers.

## Tests

```bash
cd backend && python -m pytest open_webui/test/unit/test_hub_embed.py -q
```
