import logging
from typing import Any, Awaitable, Dict, List, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher

from actions.ocr_validator import validate_payment_async
from actions.catalog import get_book_by_id

logger = logging.getLogger(__name__)

YAPE_NUMBER = "923252274"


class ValidatePaymentScreenshotUrl(Action):
    """Detects an image URL from message metadata and validates the Yape payment via OCR.

    Sets two slots:
      - payment_screenshot_url: the image URL (or None if no image was found)
      - payment_validation_status: "approved" | "needs_review" | "rejected" (or None)
    """

    def name(self) -> str:
        return "validate_payment_screenshot_url"

    async def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        metadata = tracker.latest_message.get("metadata", {})
        image_url = self._extract_image_url(metadata)

        if not image_url:
            # No image found – return None so the collect step re-asks
            return [
                SlotSet("payment_screenshot_url", None),
                SlotSet("payment_validation_status", None),
            ]

        # Run OCR in a thread pool — non-blocking, concurrent users are served in parallel
        expected_amount = self._get_expected_amount(tracker)
        try:
            result = await validate_payment_async(
                image_url=image_url,
                expected_amount=expected_amount,
                yape_number=YAPE_NUMBER,
            )
            validation_status = result["status"]
        except Exception as exc:
            logger.error("OCR validation error: %s", exc)
            validation_status = "needs_review"

        return [
            SlotSet("payment_screenshot_url", image_url),
            SlotSet("payment_validation_status", validation_status),
        ]

    def _extract_image_url(self, metadata: dict) -> str:
        # Chatwoot Agent Bot connector (primary)
        attachments = metadata.get("attachments") or []
        if attachments:
            image_url = attachments[0].get("data_url") or attachments[0].get("url")
            if image_url:
                return image_url

        # Meta Business API (Cloud API)
        image_data = metadata.get("image", {})
        image_url = image_data.get("link") or image_data.get("id")
        if image_url:
            return image_url

        # Twilio WhatsApp connector
        image_url = metadata.get("MediaUrl0")
        if image_url:
            return image_url

        # Generic fallback
        return metadata.get("image_url", "")

    def _get_expected_amount(self, tracker: Tracker) -> int:
        """Resolve expected payment amount from slots or catalog."""
        # book_price slot is set as a formatted string like "S/ 25", extract digits
        book_price = tracker.get_slot("book_price")
        if book_price:
            import re
            match = re.search(r"(\d+)", str(book_price))
            if match:
                return int(match.group(1))

        # Fallback: look up the book from the catalog
        book_id = tracker.get_slot("selected_book_id")
        if book_id:
            book = get_book_by_id(tracker.sender_id, str(book_id))
            if book:
                return book.price

        return 0
