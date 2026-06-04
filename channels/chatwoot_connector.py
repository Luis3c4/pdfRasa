"""Custom Rasa input/output channel for Chatwoot Agent Bot integration."""
import asyncio
import logging
import os
import time
from urllib.parse import urlparse
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


def _extract_image_url_from_attachments(attachments: List[Dict]) -> str:
    """Return first attachment URL from Chatwoot payload, if any."""
    for attachment in attachments or []:
        url = attachment.get("data_url") or attachment.get("url") or ""
        if url:
            return str(url)
    return ""


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
    def _auth_headers(self) -> Dict[str, str]:
        return {
            "api_access_token": self.access_token,
            # Some proxy setups only forward standard Authorization headers.
            "Authorization": f"Bearer {self.access_token}",
        }

    @property
    def _json_headers(self) -> Dict[str, str]:
        return {**self._auth_headers, "Content-Type": "application/json"}

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
            async with session.post(self._messages_url, json=payload, headers=self._json_headers) as resp:
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

    async def _post_attachment_from_url(
        self, file_url: str, caption: str = "", filename_hint: str = ""
    ) -> bool:
        file_url = (file_url or "").strip()
        if not file_url:
            return False

        timeout = aiohttp.ClientTimeout(total=60)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(file_url, allow_redirects=True) as download_resp:
                    if download_resp.status != 200:
                        logger.error(
                            "Failed to download file for attachment. status=%s url=%s",
                            download_resp.status,
                            file_url,
                        )
                        return False

                    file_bytes = await download_resp.read()
                    content_type = download_resp.headers.get(
                        "Content-Type", "application/octet-stream"
                    )

                parsed = urlparse(file_url)
                filename = (filename_hint or "").strip() or os.path.basename(parsed.path) or "document.pdf"

                form = aiohttp.FormData()
                if caption:
                    form.add_field("content", caption)
                form.add_field("message_type", "outgoing")
                form.add_field("private", "false")
                form.add_field(
                    "attachments[]",
                    file_bytes,
                    filename=filename,
                    content_type=content_type,
                )

                async with session.post(
                    self._messages_url, data=form, headers=self._auth_headers
                ) as upload_resp:
                    if upload_resp.status not in (200, 201):
                        body = await upload_resp.text()
                        logger.error(
                            "Chatwoot attachment API error %s: %s",
                            upload_resp.status,
                            body,
                        )
                        return False

                    return True
        except Exception:
            logger.exception("Error uploading attachment to Chatwoot from url=%s", file_url)
            return False

    async def send_attachment(self, recipient_id: Text, attachment: Any, **kwargs: Any) -> None:
        file_url = ""
        caption = ""
        filename = ""

        if isinstance(attachment, str):
            file_url = attachment
        elif isinstance(attachment, dict):
            payload = attachment.get("payload") if isinstance(attachment.get("payload"), dict) else {}
            file_url = (
                payload.get("src")
                or payload.get("url")
                or attachment.get("url")
                or attachment.get("src")
                or ""
            )
            caption = str(attachment.get("text") or "")
            filename = str(
                payload.get("filename")
                or payload.get("file_name")
                or attachment.get("filename")
                or attachment.get("file_name")
                or ""
            )

        if file_url and file_url.lower().startswith(("http://", "https://")):
            sent = await self._post_attachment_from_url(
                file_url=file_url,
                caption=caption,
                filename_hint=filename,
            )
            if sent:
                return

        # Fallback: send as plain text if upload is not possible.
        fallback = file_url or caption or "No pude adjuntar el archivo."
        await self._post(fallback)

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
        image_url = (image or "").strip()
        if not image_url or image_url.lower() in {"none", "null", "{book_image_url}"}:
            return

        if image_url.lower().startswith(("http://", "https://")):
            sent = await self._post_attachment_from_url(file_url=image_url)
            if sent:
                return

        # Fallback for non-URL images or upload failures.
        await self._post(image_url)


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

            # If a user sends a screenshot with or without caption, prioritize the
            # image URL as message text so CALM collect can fill payment_screenshot_url
            # deterministically and avoid routing this turn to free-response LLM.
            image_url = _extract_image_url_from_attachments(attachments)
            if image_url:
                message_text = image_url
            elif content:
                message_text = content
            else:
                message_text = "imagen adjunta"

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
                metadata={
                    "attachments": attachments,
                    "chatwoot_message_id": message_id,
                    "conversation_id": conversation_id,
                },
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
