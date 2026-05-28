"""Custom Rasa input/output channel for Chatwoot Agent Bot integration."""
import asyncio
import logging
import os
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Text

import aiohttp
from rasa.core.channels.channel import InputChannel, OutputChannel, UserMessage
from sanic import Blueprint, response
from sanic.request import Request
from sanic.response import HTTPResponse

logger = logging.getLogger(__name__)

# Simple in-memory dedup cache for webhook retries from Chatwoot.
_SEEN_MESSAGE_IDS: Dict[str, float] = {}
_SEEN_TTL_SECONDS = 600


def _mark_message_seen(message_id: str) -> bool:
    """Return True if message was seen recently, otherwise mark and return False."""
    if not message_id:
        return False

    now = time.time()
    expired = [mid for mid, ts in _SEEN_MESSAGE_IDS.items() if now - ts > _SEEN_TTL_SECONDS]
    for mid in expired:
        _SEEN_MESSAGE_IDS.pop(mid, None)

    if message_id in _SEEN_MESSAGE_IDS:
        return True

    _SEEN_MESSAGE_IDS[message_id] = now
    return False


def _build_dedup_key(account_id: str, conversation_id: str, message_id: str) -> str:
    """Build a stable dedup key scoped to the conversation.

    Chatwoot payload ids can collide across different conversations, so keying by
    message id only may incorrectly drop valid messages from other chats.
    """
    if not message_id:
        return ""
    return f"{account_id}:{conversation_id}:{message_id}"


def _resolve_credential(value: Any, default: str) -> str:
    if value is None:
        return default

    resolved = str(value).strip()
    if resolved.startswith("${") and resolved.endswith("}"):
        env_name = resolved[2:-1].strip()
        return os.getenv(env_name, default)

    return resolved or default


class ChatwootOutput(OutputChannel):
    """Sends Rasa bot responses back to Chatwoot via its REST API."""

    @classmethod
    def name(cls) -> Text:
        return "chatwoot"

    def __init__(self, url: str, account_id: str, access_token: str, conversation_id: str) -> None:
        self.url = url.rstrip("/")
        self.account_id = account_id
        self.access_token = access_token
        self.conversation_id = conversation_id

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "api_access_token": self.access_token,
            # Some proxy setups only forward standard Authorization headers.
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    @property
    def _messages_url(self) -> str:
        return (
            f"{self.url}/api/v1/accounts/{self.account_id}"
            f"/conversations/{self.conversation_id}/messages"
        )

    async def _post(self, content: str) -> None:
        logger.info("Sending message to Chatwoot conversation %s: %s", self.conversation_id, content)
        payload = {"content": content, "message_type": "outgoing", "private": False}
        async with aiohttp.ClientSession() as session:
            async with session.post(self._messages_url, json=payload, headers=self._headers) as resp:
                logger.info(
                    "Chatwoot response for conversation %s: status=%s",
                    self.conversation_id,
                    resp.status,
                )
                if resp.status not in (200, 201):
                    body = await resp.text()
                    logger.error(
                        "Chatwoot API error %s: %s", resp.status, body
                    )
                    if resp.status == 401:
                        logger.error(
                            "Chatwoot returned 401 Unauthorized. Verify CHATWOOT_ACCESS_TOKEN and, "
                            "if using Nginx/reverse proxy, ensure headers with underscores are allowed "
                            "(underscores_in_headers on;)."
                        )

    async def send_text_message(self, recipient_id: Text, text: Text, **kwargs: Any) -> None:
        if not text or text.strip() in ("-", ""):
            return
        await self._post(text)

    async def send_text_with_buttons(
        self, recipient_id: Text, text: Text, buttons: List[Dict], **kwargs: Any
    ) -> None:
        lines = [text, ""]
        for btn in buttons:
            lines.append(f"• {btn['title']}")
        await self._post("\n".join(lines))

    async def send_image_url(self, recipient_id: Text, image: Text, **kwargs: Any) -> None:
        await self._post(image)


class ChatwootInput(InputChannel):
    """Receives messages from Chatwoot Agent Bot webhooks."""

    @classmethod
    def name(cls) -> Text:
        return "chatwoot"

    @classmethod
    def from_credentials(cls, credentials: Optional[Dict[Text, Any]]) -> "ChatwootInput":
        credentials = credentials or {}
        return cls(
            url=_resolve_credential(credentials.get("url"), "http://localhost:3000"),
            account_id=_resolve_credential(credentials.get("account_id"), "1"),
            access_token=_resolve_credential(credentials.get("access_token"), ""),
        )

    def __init__(self, url: str, account_id: str, access_token: str) -> None:
        self.url = url
        self.account_id = account_id
        self.access_token = access_token

    def blueprint(
        self, on_new_message: Callable[[UserMessage], Awaitable[Any]]
    ) -> Blueprint:
        webhook = Blueprint("chatwoot_webhook", __name__)

        @webhook.route("/", methods=["GET"])
        async def health(request: Request) -> HTTPResponse:
            return response.json({"status": "ok"})

        @webhook.route("/webhook", methods=["POST"])
        async def receive(request: Request) -> HTTPResponse:
            payload: Dict = request.json or {}

            event = payload.get("event")
            message_type = payload.get("message_type")

            # Only handle new incoming messages from contacts
            if event != "message_created" or message_type != "incoming":
                return response.json({"status": "ignored"})

            conversation_id = str(payload.get("conversation", {}).get("id", ""))

            # Ignore duplicate deliveries from retries, scoped by conversation.
            message_id = str(payload.get("id") or "")
            dedup_key = _build_dedup_key(self.account_id, conversation_id, message_id)
            if _mark_message_seen(dedup_key):
                logger.info(
                    "Ignoring duplicated Chatwoot webhook message id=%s conversation_id=%s",
                    message_id,
                    conversation_id,
                )
                return response.json({"status": "ignored_duplicate"})

            content: str = (payload.get("content") or "").strip()
            attachments: List[Dict] = payload.get("attachments") or []

            # Skip bot's own echoed messages
            sender_type = payload.get("sender", {}).get("type", "")
            if sender_type in ("agent_bot", "agent"):
                return response.json({"status": "ignored"})

            if not content and not attachments:
                return response.json({"status": "ignored"})

            # Use conversation_id for session continuity across turns
            user_id = f"chatwoot_{conversation_id}"

            # When user sends only an image, extract the image URL and use it as the
            # message text so the LLM can fill payment_screenshot_url directly without
            # accidentally re-triggering the purchase flow from its description.
            if content:
                message_text = content
            else:
                _image_url = ""
                for _att in (attachments or []):
                    _url = _att.get("data_url") or _att.get("url") or ""
                    if _url:
                        _image_url = _url
                        break
                message_text = _image_url or "imagen adjunta"

            output = ChatwootOutput(
                url=self.url,
                account_id=self.account_id,
                access_token=self.access_token,
                conversation_id=conversation_id,
            )

            msg = UserMessage(
                text=message_text,
                output_channel=output,
                sender_id=user_id,
                # Pass attachments in metadata so validate_payment_screenshot can read them
                metadata={"attachments": attachments},
            )

            # Process asynchronously so webhook returns quickly and avoids provider retries.
            async def _safe_process() -> None:
                try:
                    await on_new_message(msg)
                except Exception:
                    logger.exception("Error processing Chatwoot message id=%s", message_id)

            asyncio.create_task(_safe_process())
            return response.json({"status": "accepted"})

        return webhook
