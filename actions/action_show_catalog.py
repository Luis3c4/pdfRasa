from typing import Any, Dict, List, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher

from actions.catalog import get_all_books


class ActionShowCatalog(Action):
    def name(self) -> str:
        return "action_show_catalog"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        books = get_all_books(tracker.sender_id)

        if not books:
            dispatcher.utter_message(text="Por el momento no tenemos libros disponibles. ¡Vuelve pronto!")
            return []

        lines = ["📚 *Catálogo de eBooks disponibles:*\n"]
        for book in books:
            lines.append(
                f"📖 *{book.title}*\n"
                f"   💰 Precio: {book.currency} {book.price}\n"
                f"   📄 {book.pages} páginas\n"
            )
        dispatcher.utter_message(text="\n".join(lines))
        return []
