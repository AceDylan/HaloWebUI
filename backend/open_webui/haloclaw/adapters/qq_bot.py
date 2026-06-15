"""QQ official bot (QQ 官方机器人) adapter using the WebSocket gateway.

Message flow:
  1. Adapter authenticates with AppID + AppSecret to obtain an app access_token
  2. Opens a WebSocket to the QQ gateway, identifies, and keeps it alive with
     heartbeats (reconnecting with backoff on drop)
  3. Inbound GROUP_AT_MESSAGE_CREATE / C2C_MESSAGE_CREATE events are dispatched
     to the AI pipeline, and the reply is sent back as a passive message

Config keys:
  app_id      — 机器人 AppID
  app_secret  — 机器人 AppSecret (ClientSecret)

Notes:
  - Only group @-mentions and C2C (private) messages are handled (intent
    GROUP_AND_C2C_EVENT). Group events are only delivered when the bot is
    @-mentioned, so the "mention" group policy is satisfied implicitly.
  - Group / C2C text messages are plain text only (msg_type=0); markdown is
    converted to a readable plain-text form via the qq_bot formatter.
  - Replies are passive (carry the inbound msg_id); each reply to the same
    msg_id must use an incrementing msg_seq.
"""

import asyncio
import json
import logging
import time
from typing import Optional

import aiohttp
import httpx

from open_webui.haloclaw.adapters.base import BaseAdapter
from open_webui.haloclaw.media import image_bytes_to_data_url, load_image_bytes
from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

QQ_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
QQ_API_BASE = "https://api.sgroup.qq.com"

# Intent bitmask: GROUP_AND_C2C_EVENT (1 << 25) covers group @-messages and
# C2C (private) messages — the common surface for a QQ assistant bot.
INTENTS_GROUP_AND_C2C = 1 << 25

# WebSocket opcodes
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

MAX_BACKOFF = 60  # seconds


class QQBotAdapter(BaseAdapter):
    def __init__(self, gateway_id: str, config: dict):
        super().__init__(gateway_id, "qq_bot", config)
        self._http: Optional[httpx.AsyncClient] = None
        self._ws_session: Optional[aiohttp.ClientSession] = None

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

        self._ws_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._last_seq: Optional[int] = None

        # Passive-reply bookkeeping: inbound msg_id per chat, and an incrementing
        # msg_seq per msg_id (QQ rejects duplicate msg_seq for the same msg_id).
        self._reply_msg_id: dict[str, str] = {}
        self._seq_counter: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        app_id = self.config.get("app_id", "")
        app_secret = self.config.get("app_secret", "")
        if not app_id or not app_secret:
            raise ValueError(
                f"HaloClaw QQBot [{self.gateway_id}]: missing app_id or app_secret"
            )

        self._http = httpx.AsyncClient(timeout=30.0)
        self._ws_session = aiohttp.ClientSession()

        if not await self._refresh_access_token():
            log.error(f"HaloClaw QQBot [{self.gateway_id}]: failed to get access_token")
            await self._close_clients()
            return

        self._running = True
        self._ws_task = asyncio.create_task(self._ws_loop())
        log.info(f"HaloClaw QQBot [{self.gateway_id}]: started")

    async def stop(self) -> None:
        self._running = False

        for task in (self._heartbeat_task, self._ws_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._heartbeat_task = None
        self._ws_task = None

        await self._close_clients()
        self._access_token = None
        self._reply_msg_id.clear()
        self._seq_counter.clear()
        log.info(f"HaloClaw QQBot [{self.gateway_id}]: stopped")

    async def _close_clients(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None
        if self._ws_session:
            await self._ws_session.close()
            self._ws_session = None

    # ------------------------------------------------------------------
    # Access Token Management
    # ------------------------------------------------------------------

    async def _refresh_access_token(self) -> bool:
        app_id = self.config.get("app_id", "")
        app_secret = self.config.get("app_secret", "")
        if not app_id or not app_secret or not self._http:
            return False

        try:
            resp = await self._http.post(
                QQ_TOKEN_URL,
                json={"appId": app_id, "clientSecret": app_secret},
            )
            data = resp.json()
            token = data.get("access_token")
            if not token:
                log.error(f"HaloClaw QQBot [{self.gateway_id}]: token error: {data}")
                return False

            self._access_token = token
            # expires_in may come back as a string; refresh 5 min before expiry.
            expires_in = int(data.get("expires_in", 7200) or 7200)
            self._token_expires_at = time.time() + expires_in - 300
            return True
        except Exception as e:
            log.error(f"HaloClaw QQBot [{self.gateway_id}]: token refresh failed: {e}")
            return False

    async def _ensure_token(self, force_refresh: bool = False) -> Optional[str]:
        if force_refresh or not self._access_token or time.time() >= self._token_expires_at:
            await self._refresh_access_token()
        return self._access_token

    def _auth_header(self, token: str) -> dict:
        return {"Authorization": f"QQBot {token}", "Content-Type": "application/json"}

    # ------------------------------------------------------------------
    # WebSocket connection
    # ------------------------------------------------------------------

    async def _ws_loop(self) -> None:
        """Outer reconnect loop with exponential backoff."""
        backoff = 1
        try:
            while self._running:
                try:
                    ready = await self._connect_once()
                    # Reset backoff only after a fully established session.
                    backoff = 1 if ready else min(backoff * 2, MAX_BACKOFF)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning(f"HaloClaw QQBot [{self.gateway_id}]: ws error: {e}")
                    backoff = min(backoff * 2, MAX_BACKOFF)

                if not self._running:
                    break
                await asyncio.sleep(backoff)
        except asyncio.CancelledError:
            pass

    async def _connect_once(self) -> bool:
        """Run one WebSocket session. Returns True if it reached READY."""
        token = await self._ensure_token()
        if not token or not self._ws_session:
            return False

        gateway_url = await self._get_gateway_url(token)
        if not gateway_url:
            return False

        reached_ready = False
        async with self._ws_session.ws_connect(gateway_url, heartbeat=None) as ws:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    op = payload.get("op")
                    if op == OP_HELLO:
                        interval = payload.get("d", {}).get("heartbeat_interval", 30000)
                        await self._identify(ws, token)
                        self._start_heartbeat(ws, interval)
                    elif op == OP_DISPATCH:
                        if payload.get("s") is not None:
                            self._last_seq = payload["s"]
                        event_type = payload.get("t")
                        if event_type == "READY":
                            reached_ready = True
                            log.info(
                                f"HaloClaw QQBot [{self.gateway_id}]: gateway READY"
                            )
                        else:
                            asyncio.create_task(
                                self._handle_dispatch(event_type, payload.get("d", {}))
                            )
                    elif op == OP_HEARTBEAT_ACK:
                        continue
                    elif op in (OP_RECONNECT, OP_INVALID_SESSION):
                        log.info(
                            f"HaloClaw QQBot [{self.gateway_id}]: server asked to reconnect (op={op})"
                        )
                        break
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break

        self._stop_heartbeat()
        return reached_ready

    async def _get_gateway_url(self, token: str) -> Optional[str]:
        if not self._http:
            return None
        try:
            resp = await self._http.get(
                f"{QQ_API_BASE}/gateway",
                headers={"Authorization": f"QQBot {token}"},
            )
            return resp.json().get("url")
        except Exception as e:
            log.error(f"HaloClaw QQBot [{self.gateway_id}]: gateway fetch failed: {e}")
            return None

    async def _identify(self, ws, token: str) -> None:
        await ws.send_json(
            {
                "op": OP_IDENTIFY,
                "d": {
                    "token": f"QQBot {token}",
                    "intents": INTENTS_GROUP_AND_C2C,
                    "shard": [0, 1],
                    "properties": {},
                },
            }
        )

    def _start_heartbeat(self, ws, interval_ms: int) -> None:
        self._stop_heartbeat()
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(ws, max(interval_ms, 1000) / 1000.0)
        )

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._heartbeat_task = None

    async def _heartbeat_loop(self, ws, interval: float) -> None:
        try:
            while self._running and not ws.closed:
                await asyncio.sleep(interval)
                if ws.closed:
                    break
                try:
                    await ws.send_json({"op": OP_HEARTBEAT, "d": self._last_seq})
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Inbound dispatch
    # ------------------------------------------------------------------

    async def _handle_dispatch(self, event_type: Optional[str], d: dict) -> None:
        if event_type == "GROUP_AT_MESSAGE_CREATE":
            group_openid = d.get("group_openid", "")
            user_openid = (d.get("author") or {}).get("member_openid", "")
            await self._process_message(
                target_type="group",
                target_openid=group_openid,
                user_openid=user_openid,
                msg_id=d.get("id", ""),
                content=(d.get("content") or "").strip(),
                attachments=d.get("attachments") or [],
                is_group=True,
            )
        elif event_type == "C2C_MESSAGE_CREATE":
            user_openid = (d.get("author") or {}).get("user_openid", "")
            await self._process_message(
                target_type="c2c",
                target_openid=user_openid,
                user_openid=user_openid,
                msg_id=d.get("id", ""),
                content=(d.get("content") or "").strip(),
                attachments=d.get("attachments") or [],
                is_group=False,
            )

    async def _process_message(
        self,
        target_type: str,
        target_openid: str,
        user_openid: str,
        msg_id: str,
        content: str,
        attachments: list,
        is_group: bool,
    ) -> None:
        from open_webui.haloclaw.dispatcher import handle_message
        from open_webui.haloclaw.models import Gateways

        if not target_openid or not user_openid:
            return

        gateway = Gateways.get_by_id(self.gateway_id)
        if not gateway or not gateway.enabled:
            return

        # Group policy. QQ only delivers group events when the bot is @-mentioned,
        # so "mention" is implicitly satisfied; we only honour "disabled" here.
        if is_group:
            group_policy = (gateway.access_policy or {}).get("group_policy", "mention")
            if group_policy == "disabled":
                return

        image_urls = await self._extract_image_urls(attachments)

        if not content and not image_urls:
            return

        chat_id = f"{target_type}:{target_openid}"
        # Remember the inbound msg_id so photo/text replies can reference it.
        # Bound the bookkeeping dicts so a long-running gateway does not leak.
        if len(self._seq_counter) > 1000:
            self._seq_counter.clear()
        if len(self._reply_msg_id) > 1000:
            self._reply_msg_id.clear()
        self._reply_msg_id[chat_id] = msg_id

        result = await handle_message(
            gateway=gateway,
            platform_chat_id=chat_id,
            platform_user_id=user_openid,
            platform_username=user_openid,
            platform_display_name=None,
            text=content,
            image_urls=image_urls,
        )

        if not result:
            return

        if result.error:
            await self.send_message(
                chat_id=chat_id, text=f"⚠️ {result.error}", reply_to_message_id=msg_id
            )
        elif result.text:
            await self.send_message(
                chat_id=chat_id, text=result.text, reply_to_message_id=msg_id
            )
        for img_url in result.images:
            await self.send_photo(chat_id=chat_id, image_url=img_url)

    async def _extract_image_urls(self, attachments: list) -> list[str]:
        """Download QQ image attachments and convert them to data URLs."""
        image_urls: list[str] = []
        for att in attachments:
            if not isinstance(att, dict):
                continue
            content_type = (att.get("content_type") or "").lower()
            url = att.get("url") or ""
            if not url or "image" not in content_type:
                continue
            # QQ attachment URLs may omit the scheme.
            if url.startswith("//"):
                url = f"https:{url}"
            elif not url.startswith(("http://", "https://")):
                url = f"https://{url}"
            loaded = await load_image_bytes(url)
            if loaded:
                image_urls.append(image_bytes_to_data_url(*loaded))
        return image_urls

    # ------------------------------------------------------------------
    # Outbound send
    # ------------------------------------------------------------------

    def _parse_chat_id(self, chat_id: str) -> tuple[str, str]:
        target_type, _, openid = chat_id.partition(":")
        return target_type, openid

    def _messages_endpoint(self, target_type: str, openid: str) -> Optional[str]:
        if target_type == "group":
            return f"{QQ_API_BASE}/v2/groups/{openid}/messages"
        if target_type == "c2c":
            return f"{QQ_API_BASE}/v2/users/{openid}/messages"
        return None

    def _next_seq(self, msg_id: str) -> int:
        seq = self._seq_counter.get(msg_id, 0) + 1
        self._seq_counter[msg_id] = seq
        return seq

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_to_message_id: Optional[str] = None,
    ) -> Optional[str]:
        target_type, openid = self._parse_chat_id(chat_id)
        endpoint = self._messages_endpoint(target_type, openid)
        if not endpoint or not self._http:
            return None

        token = await self._ensure_token()
        if not token:
            return None

        from open_webui.haloclaw.formatters.qq_bot import (
            markdown_to_qq_text,
            split_message,
        )

        msg_id = reply_to_message_id or self._reply_msg_id.get(chat_id)
        formatted = markdown_to_qq_text(text)
        chunks = split_message(formatted)

        last_msg_id = None
        for chunk in chunks:
            body: dict = {"content": chunk, "msg_type": 0}
            if msg_id:
                body["msg_id"] = msg_id
                body["msg_seq"] = self._next_seq(msg_id)

            data = await self._post_json(endpoint, body, token)
            if data is not None:
                last_msg_id = str(data.get("id", "")) or last_msg_id

        return last_msg_id

    async def edit_message(self, chat_id: str, message_id: str, text: str) -> None:
        # QQ official bot does not support editing sent messages.
        pass

    async def send_photo(
        self,
        chat_id: str,
        image_url: str,
        caption: str = "",
    ) -> Optional[str]:
        if caption:
            await self.send_message(chat_id=chat_id, text=caption)

        # QQ rich media is uploaded by URL (server-side fetch), so data: URLs
        # generated locally cannot be delivered.
        if not image_url.startswith(("http://", "https://")):
            log.warning(
                f"HaloClaw QQBot [{self.gateway_id}]: cannot send non-public image url"
            )
            return None

        target_type, openid = self._parse_chat_id(chat_id)
        if not openid or not self._http:
            return None

        token = await self._ensure_token()
        if not token:
            return None

        file_info = await self._upload_media(target_type, openid, image_url, token)
        if not file_info:
            return None

        endpoint = self._messages_endpoint(target_type, openid)
        if not endpoint:
            return None

        msg_id = self._reply_msg_id.get(chat_id)
        body: dict = {"content": " ", "msg_type": 7, "media": {"file_info": file_info}}
        if msg_id:
            body["msg_id"] = msg_id
            body["msg_seq"] = self._next_seq(msg_id)

        data = await self._post_json(endpoint, body, token)
        return str(data.get("id", "")) if data else None

    async def _upload_media(
        self,
        target_type: str,
        openid: str,
        image_url: str,
        token: str,
    ) -> Optional[str]:
        if target_type == "group":
            endpoint = f"{QQ_API_BASE}/v2/groups/{openid}/files"
        elif target_type == "c2c":
            endpoint = f"{QQ_API_BASE}/v2/users/{openid}/files"
        else:
            return None

        body = {"file_type": 1, "url": image_url, "srv_send_msg": False}
        data = await self._post_json(endpoint, body, token)
        return data.get("file_info") if data else None

    async def _post_json(self, endpoint: str, body: dict, token: str) -> Optional[dict]:
        """POST helper with a single token-refresh retry on auth failure."""
        if not self._http:
            return None

        for attempt in range(2):
            try:
                resp = await self._http.post(
                    endpoint, headers=self._auth_header(token), json=body
                )
            except Exception as e:
                log.error(f"HaloClaw QQBot send failed: {e}")
                return None

            if resp.status_code == 401 and attempt == 0:
                refreshed = await self._ensure_token(force_refresh=True)
                if refreshed:
                    token = refreshed
                    continue

            try:
                data = resp.json()
            except Exception:
                data = {}

            if resp.status_code >= 400 or (isinstance(data, dict) and data.get("code")):
                log.error(f"HaloClaw QQBot send error ({resp.status_code}): {data}")
                return None

            return data if isinstance(data, dict) else {}

        return None
