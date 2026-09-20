# Bookmark Hub embed: the Hub frames HaloWebUI and signs its admin in

The Bookmark Hub (AICheckIn, `https://best.acedylan.us:5526`) is the outer page.
Its **"AI chat" tab** holds an iframe pointing at HaloWebUI, so one place manages
the bookmarks and opens the chat. Two things live on this side:

1. **Framing allow-list.** With `HUB_URL` set, every response carries
   `Content-Security-Policy: frame-ancestors 'self' <origin of HUB_URL>`. Exactly one
   foreign origin, never a wildcard. `X-Frame-Options` is dropped because it cannot
   express "same origin plus one site". With `HUB_URL` empty nothing is added.
2. **Sign-in bridge, Hub admin → HaloWebUI (one way).** The Hub's backend signs a
   short-lived, single-use ticket for its unlocked administrator and points the
   iframe at `/auth#hub_ticket=<ticket>`. The sign-in page takes the ticket out of
   the address fragment (it never reaches a server log or a Referer) and posts it
   to `POST /api/v1/hub/session`, which issues an ordinary HaloWebUI session.

The reverse direction (HaloWebUI framing the Hub, HaloWebUI admin → Hub) was
implemented once and reverted; nothing of it remains.

3. **A question typed in the Hub arrives here as a new chat.** The Hub's
   "send to AI chat" buttons open
   `/auth?redirect=%2F%3Fq%3D<prompt>#hub_ticket=<ticket>`: the sign-in page takes the
   ticket, then follows `?redirect=` to `/?q=<prompt>`, where `Chat.svelte` fills the
   composer and submits. Nothing had to change here for that — `?q=` has always been
   read — but `?redirect=` now goes through `safeRedirectPath()` first.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `HUB_URL` | `https://best.acedylan.us:5526` | Origin of the Hub. The only origin allowed to frame HaloWebUI and the only ticket issuer accepted. Empty string = feature off (no header, both endpoints 404). |
| `HUB_TRUSTED_EMBED_ADMIN_SECRET` | unset | Shared secret, ≥ 32 characters, same value as the Hub's variable of the same name. Generated at deploy time, never committed. Unset = framing still works, the admin signs in by hand. |
| `HUB_EMBED_USER_EMAIL` | unset | Account a ticket signs in as. Default: the primary admin. An explicitly named ordinary user is allowed (a way to give the Hub less than admin); a pending account never is. |
| `HUB_EMBED_SESSION_TTL` | `43200` | Lifetime in seconds of a ticket-opened session, clamped to 5 minutes .. 30 days. |

The live deployment's compose file passes environment through an `environment:` block
and a `.env` next to it: add `HUB_URL` and `HUB_TRUSTED_EMBED_ADMIN_SECRET` there (the
`.env` should be mode 0600), then `docker compose up -d`.

## Where `?redirect=` may point

`?redirect=` is attacker-reachable: anybody can send a link to our own sign-in page
with any value in it. `src/lib/utils/safe-redirect.ts` accepts only a path on this
site and rebuilds it from a parsed URL; everything else silently becomes `/`.

Refused: absolute URLs, protocol-relative `//host`, `javascript:` and `data:`,
backslashes (a browser reads `/\evil.example` as `//evil.example`), control
characters a browser would strip back out (`/\thttps://evil.example`), and anything
over 2048 characters. `..` segments are resolved away rather than passed on.

Allowed, because the Hub depends on it: a path with a query string and a fragment,
with its percent-encoding preserved byte for byte — `/?q=%E4%BD%A0%E5%A5%BD`.

## Ticket format

```
v2.<purpose>.<expiry unix ts>.<nonce>.<issuer b64url>.<audience b64url>.<HMAC-SHA256 hex>
```

- key = `sha256("hub-chat-admin|" + shared secret)`; the label differs from the
  retired reverse direction, so a ticket minted for that flow never verifies here;
- `purpose` is `chat` (opens a session) or `probe` (handshake only, opens nothing);
- `issuer` = the Hub's origin, `audience` = HaloWebUI's origin;
- the Hub signs 60 seconds; anything claiming more than 120 seconds is refused.

`POST /api/v1/hub/session` checks, in order: signature, purpose, expiry, issuer ==
origin of `HUB_URL`, audience == the `Origin` header the browser put on the request
(set by the browser, not by page script: the ticket only works from a page served by
the origin the Hub addressed it to), nonce unused. Only then is a session created,
with `HUB_EMBED_SESSION_TTL` as its lifetime and a `hub_exp` claim; `GET /api/v1/auths/`
renews such a session with its original expiry instead of a fresh full-length one.

`POST /api/v1/hub/handshake` takes a `probe` ticket and answers `{ok, frame_ancestors,
session_ttl, session_user_ready}` so the Hub can explain a misconfiguration (secret
mismatch, Hub address not on the list, no account to sign in as) instead of showing a
blank frame.

Failures that look like guessing (malformed, bad signature) are throttled per client
and globally (`429` + `Retry-After`); expired or replayed tickets are not counted, since
they prove the caller holds the secret. Nonces live in process memory until the ticket
expires: exact with one worker (the default); with N workers a ticket could be replayed
once per worker within its 60 seconds.

## Verifying

```bash
# framing allow-list on every response
curl -sI https://<halowebui>/ | grep -i -E 'content-security-policy|x-frame-options'
# endpoints exist only once the secret is configured
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/json' \
  -d '{"ticket":"x"}' https://<halowebui>/api/v1/hub/session      # 404 unset, 401 configured
```

Backend unit tests: `backend/open_webui/test/unit/test_hub_embed.py`.
Frontend unit tests: `src/lib/utils/hub-embed.test.ts` and
`src/lib/utils/safe-redirect.test.ts`
(`npx vitest run src/lib/utils/hub-embed.test.ts src/lib/utils/safe-redirect.test.ts`).
