"""Custom Rasa input/output channel for Chatwoot Agent Bot integration."""
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Text

import aiohttp
from rasa.core.channels.channel import InputChannel, OutputChannel, UserMessage
from sanic import Blueprint, response
from sanic.request import Request
from sanic.response import HTTPResponse

logger = logging.getLogger(__name__)


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
            "Content-Type": "application/json",
        }

    @property
    def _messages_url(self) -> str:
        return (
            f"{self.url}/api/v1/accounts/{self.account_id}"
            f"/conversations/{self.conversation_id}/messages"
        )

    async def _post(self, content: str) -> None:
        payload = {"content": content, "message_type": "outgoing", "private": False}
        async with aiohttp.ClientSession() as session:
            async with session.post(self._messages_url, json=payload, headers=self._headers) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    logger.error(
                        "Chatwoot API error %s: %s", resp.status, body
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
            url=credentials.get("url", "http://localhost:3000"),
            account_id=credentials.get("account_id", "1"),
            access_token=credentials.get("access_token", ""),
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

            content: str = (payload.get("content") or "").strip()
            conversation_id = str(payload.get("conversation", {}).get("id", ""))
            attachments: List[Dict] = payload.get("attachments") or []

            # Skip bot's own echoed messages
            sender_type = payload.get("sender", {}).get("type", "")
            if sender_type in ("agent_bot", "agent"):
                return response.json({"status": "ignored"})

            if not content and not attachments:
                return response.json({"status": "ignored"})

            # Use conversation_id for session continuity across turns
            user_id = f"chatwoot_{conversation_id}"

            # When user sends only an image, use a descriptive placeholder so the LLM
            # understands the context and does not trigger pattern_cannot_handle
            message_text = content if content else "imagen adjunta"

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

            await on_new_message(msg)
            return response.json({"status": "ok"})

        return webhook
