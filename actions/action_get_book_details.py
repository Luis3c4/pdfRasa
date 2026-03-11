from typing import Any, Dict, List, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher

from actions.catalog import get_all_books, get_book_by_id


def _resolve_book_id(tracker: Tracker) -> str | None:
    """Try to match selected_book_id slot against catalog by id or title (case-insensitive)."""
    session_id = tracker.sender_id
    raw = tracker.get_slot("selected_book_id")
    if raw is None:
        return None

    books = get_all_books(session_id)
    raw_lower = raw.lower().strip()

    # exact id match
    for book in books:
        if book.id == raw_lower:
            return book.id

    # partial title match
    for book in books:
        if raw_lower in book.title.lower():
            return book.id

    return None


class ActionGetBookDetails(Action):
    def name(self) -> str:
        return "action_get_book_details"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        book_id = _resolve_book_id(tracker)

        if book_id is None:
            return [SlotSet("return_value", "not_found")]

        book = get_book_by_id(tracker.sender_id, book_id)
        if book is None:
            return [SlotSet("return_value", "not_found")]

        dispatcher.utter_message(
            text=(
                f"📖 *{book.title}*\n\n"
                f"📝 {book.description}\n\n"
                f"📄 *Páginas:* {book.pages}\n"
                f"💰 *Precio:* {book.currency} {book.price}\n\n"
                f"🔍 *Preview:* {book.preview}\n\n"
                f"¿Te gustaría comprarlo? Solo dime *quiero comprarlo* o *comprar {book.title}*. 😊"
            )
        )

        return [
            SlotSet("selected_book_id", book.id),
            SlotSet("book_title", book.title),
            SlotSet("book_price", f"{book.currency} {book.price}"),
            SlotSet("return_value", "success"),
        ]
