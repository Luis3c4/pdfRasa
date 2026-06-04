from typing import Any, Dict, List, Text
import uuid

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher

from actions.catalog import create_order, get_book_by_id


class ActionCreateOrder(Action):
    def name(self) -> str:
        return "action_create_order"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        existing_order_id = str(tracker.get_slot("order_id") or "").strip()
        book_id = tracker.get_slot("selected_book_id")
        book_title = tracker.get_slot("book_title")
        screenshot_url = tracker.get_slot("payment_screenshot_url")
        validation_status = tracker.get_slot("payment_validation_status") or "needs_review"
        # Use WhatsApp sender ID (phone number) as buyer identifier
        buyer_name = tracker.sender_id

        if existing_order_id:
            return [
                SlotSet("order_id", existing_order_id),
                SlotSet("return_value", "success"),
            ]

        if not all([book_id, book_title, screenshot_url]):
            return [SlotSet("return_value", "error")]

        # Guard against accidental slot filling with plain text instead of a real image URL.
        screenshot_value = str(screenshot_url).strip()
        if not screenshot_value.startswith(("http://", "https://")):
            return [SlotSet("return_value", "error")]

        order = create_order(
            session_id=tracker.sender_id,
            book_id=str(book_id),
            book_title=str(book_title),
            buyer_name=buyer_name,
            screenshot_url=screenshot_value,
            status=validation_status,
        )

        order_id = getattr(order, "order_id", None) or str(uuid.uuid4())[:8].upper()

        return [
            SlotSet("order_id", order_id),
            SlotSet("return_value", "success"),
        ]
