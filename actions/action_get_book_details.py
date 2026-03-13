from typing import Any, Dict, List, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher

from actions.catalog import get_all_books, get_book_by_id


def _resolve_book_id(tracker: Tracker) -> str | None:
    """Try to match selected_book_id slot against catalog by id or title (case-insensitive).
    Falls back to searching in the latest user message text."""
    session_id = tracker.sender_id
    books = get_all_books(session_id)

    def match(text: str) -> str | None:
        if not text:
            return None
        text_lower = text.lower().strip()
        # exact id match
        for book in books:
            if book.id == text_lower:
                return book.id
        # slot value is substring of title
        for book in books:
            if text_lower in book.title.lower():
                return book.id
        # any keyword from text found in title
        words = [w for w in text_lower.split() if len(w) > 2]
        for book in books:
            title_lower = book.title.lower()
            if any(w in title_lower for w in words):
                return book.id
        return None

    # try slot first
    raw = tracker.get_slot("selected_book_id")
    result = match(raw)
    if result:
        return result

    # fallback: search in the latest user message text
    last_text = tracker.latest_message.get("text", "")
    return match(last_text)


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

        return [
            SlotSet("selected_book_id", book.id),
            SlotSet("book_title", book.title),
            SlotSet("book_price", f"{book.currency} {book.price}"),
            SlotSet("book_description", book.description),
            SlotSet("book_pages", str(book.pages)),
            SlotSet("book_preview", book.preview),
            SlotSet("return_value", "success"),
        ]
