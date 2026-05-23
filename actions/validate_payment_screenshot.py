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
        logger.info("=== validate_payment_screenshot_url START ===")
        logger.info("tracker.latest_message: %s", tracker.latest_message)

        current_message_id = str(tracker.latest_message.get("message_id") or "")
        last_validated_message_id = str(tracker.get_slot("last_validated_payment_message_id") or "")
        
        metadata = tracker.latest_message.get("metadata", {})
        logger.info("metadata extracted: %s", metadata)
        
        image_url = self._extract_image_url(metadata)
        logger.info("image_url extracted: %s", image_url)

        if not image_url:
            # No image found – return None so the collect step re-asks
            logger.warning("No image URL found in metadata. Available keys: %s", list(metadata.keys()))
            return [
                SlotSet("payment_screenshot_url", None),
                SlotSet("payment_validation_status", None),
            ]

        # Dedup guard: same message_id has already been validated in this conversation.
        # Returning url=null sends the flow through the "null" branch of validate_screenshot
        # (back to wait_for_screenshot) WITHOUT sending another rejection message,
        # breaking both within-turn and cross-turn (Chatwoot retry) loops.
        if (
            current_message_id
            and last_validated_message_id
            and current_message_id == last_validated_message_id
        ):
            logger.info(
                "Dedup: message_id=%s already validated — returning null to break loop",
                current_message_id,
            )
            return [
                SlotSet("payment_screenshot_url", None),
                SlotSet("payment_validation_status", None),
            ]

        # Run OCR in a thread pool — non-blocking, concurrent users are served in parallel
        expected_amount = self._get_expected_amount(tracker)
        logger.info("expected_amount resolved to: %s", expected_amount)
        
        try:
            logger.info("Starting OCR validation for URL: %s", image_url)
            result = await validate_payment_async(
                image_url=image_url,
                expected_amount=expected_amount,
                yape_number=YAPE_NUMBER,
            )
            validation_status = result["status"]
            logger.info("OCR result: status=%s, checks=%s", validation_status, result.get("checks"))

            # Dispatch a specific rejection message so the customer knows exactly why
            # their screenshot was rejected (wrong amount vs. unreadable).
            if validation_status == "rejected":
                detected_monto = result["data"].get("monto")
                if detected_monto is not None:
                    dispatcher.utter_message(
                        text=(
                            f"⚠️ El monto detectado en tu captura (S/ {detected_monto:.2f}) "
                            f"no coincide con el precio del libro (S/ {expected_amount:.2f}). "
                            f"Asegúrate de pagar el monto exacto e intenta nuevamente."
                        )
                    )
                else:
                    dispatcher.utter_message(
                        text=(
                            "⚠️ No pude leer el monto en tu captura. "
                            "Asegúrate de enviar la pantalla completa de Yape o Plin "
                            "donde se vea claramente el monto, el número destino y el estado 'Exitoso'."
                        )
                    )

        except Exception as exc:
            logger.error("OCR validation error: %s", exc, exc_info=True)
            validation_status = "needs_review"

        logger.info("=== validate_payment_screenshot_url END: status=%s ===", validation_status)
        return [
            SlotSet("payment_screenshot_url", image_url),
            SlotSet("payment_validation_status", validation_status),
            SlotSet("last_validated_payment_message_id", current_message_id or None),
        ]

    def _extract_image_url(self, metadata: dict) -> str:
        logger.info("Attempting to extract image URL from metadata keys: %s", list(metadata.keys()))
        
        # Chatwoot Agent Bot connector (primary)
        attachments = metadata.get("attachments") or []
        if attachments:
            logger.info("Found %d attachments, examining first one: %s", len(attachments), attachments[0])
            image_url = attachments[0].get("data_url") or attachments[0].get("url")
            if image_url:
                logger.info("Extracted from attachments.data_url or .url: %s", image_url)
                return image_url

        # Meta Business API (Cloud API)
        image_data = metadata.get("image", {})
        if image_data:
            logger.info("Found 'image' key in metadata: %s", image_data)
            image_url = image_data.get("link") or image_data.get("id")
            if image_url:
                logger.info("Extracted from image.link or .id: %s", image_url)
                return image_url

        # Twilio WhatsApp connector
        image_url = metadata.get("MediaUrl0")
        if image_url:
            logger.info("Extracted from MediaUrl0: %s", image_url)
            return image_url

        # Generic fallback
        image_url = metadata.get("image_url", "")
        if image_url:
            logger.info("Extracted from generic image_url: %s", image_url)
            return image_url
        
        logger.warning("No image URL found. Metadata structure: %s", metadata)
        return ""

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
