from typing import Any, Dict, List, Text

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
        book_id = tracker.get_slot("selected_book_id")
        book_title = tracker.get_slot("book_title")
        screenshot_url = tracker.get_slot("payment_screenshot_url")
        # Use WhatsApp sender ID (phone number) as buyer identifier
        buyer_name = tracker.sender_id

        if not all([book_id, book_title, screenshot_url]):
            return [SlotSet("return_value", "error")]

        order = create_order( 
            session_id=tracker.sender_id,
            book_id=str(book_id),
            book_title=str(book_title),
            buyer_name=buyer_name,
            screenshot_url=str(screenshot_url),
        )

        dispatcher.utter_message(
            response="utter_order_created",
            order_id=order.order_id,
        )

        return [
            SlotSet("order_id", order.order_id),
            SlotSet("return_value", "success"),
        ]
