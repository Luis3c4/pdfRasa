from typing import Any, Dict, List, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher

from actions.catalog import get_book_by_id


class ActionReleaseDownload(Action):
    def name(self) -> str:
        return "action_release_download"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        book_id = tracker.get_slot("selected_book_id")
        order_id = tracker.get_slot("order_id")

        book = get_book_by_id(tracker.sender_id, book_id) if book_id else None

        if book is None:
            dispatcher.utter_message(
                text="Hubo un problema al recuperar tu libro. Contáctanos directamente al 912201963."
            )
            return [SlotSet("return_value", "error")]

        dispatcher.utter_message(
            text=(
                f"🎉 ¡Pago confirmado! Tu orden está lista.\n\n"
                f"Aquí está tu link de descarga para *{book.title}*:\n\n"
                f"🔗 {book.download_link}\n\n"
                f"📦 Orden #{order_id}\n\n"
                f"¡Disfruta tu lectura! Si tienes alguna duda, escríbenos. 😊"
            )
        )

        return [SlotSet("return_value", "success")]
