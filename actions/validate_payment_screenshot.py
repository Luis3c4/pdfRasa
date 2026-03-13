from typing import Any, Dict, List, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher


class ValidatePaymentScreenshotUrl(Action):
    """Custom slot validator that detects an image URL from WhatsApp message metadata.

    Works with both Twilio WhatsApp connector (MediaUrl0) and Meta Business API (image.link).
    The slot is only set when an actual image attachment is detected; otherwise the bot
    re-prompts with utter_ask_payment_screenshot_url.
    """

    def name(self) -> str:
        return "validate_payment_screenshot_url"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        metadata = tracker.latest_message.get("metadata", {})

        # Chatwoot Agent Bot connector (primary)
        attachments = metadata.get("attachments") or []
        if attachments:
            image_url = attachments[0].get("data_url") or attachments[0].get("url")
            if image_url:
                return [SlotSet("payment_screenshot_url", image_url)]

        # Meta Business API (Cloud API)
        image_data = metadata.get("image", {})
        image_url = image_data.get("link") or image_data.get("id")

        # Twilio WhatsApp connector
        if not image_url:
            image_url = metadata.get("MediaUrl0")

        # Generic fallback
        if not image_url:
            image_url = metadata.get("image_url")

        if image_url:
            return [SlotSet("payment_screenshot_url", image_url)]

        # No image found – return None so the collect step re-asks with utter_ask_payment_screenshot_url
        return [SlotSet("payment_screenshot_url", None)]
