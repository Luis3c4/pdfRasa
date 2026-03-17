from typing import Any, Dict, List, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher

from actions.catalog import get_all_books


def _fuzzy_match_book(text: str, books) -> str | None:
    """Return book.id if text (partial or full) matches any book title, else None."""
    if not text:
        return None
    text_lower = text.lower().strip()

    # exact id match
    for book in books:
        if book.id == text_lower:
            return book.id

    # text is substring of title  (e.g. "bitcoin" in "Mastering Bitcoin")
    for book in books:
        if text_lower in book.title.lower():
            return book.id

    # any meaningful word from text found in title
    words = [w for w in text_lower.split() if len(w) > 2]
    for book in books:
        title_lower = book.title.lower()
        if any(w in title_lower for w in words):
            return book.id

    return None


class ActionResolveBook(Action):
    """Pre-fills selected_book_id using fuzzy matching on the latest user message.
    If a match is found the collect step in the purchase flow is skipped."""

    def name(self) -> str:
        return "action_resolve_book"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        books = get_all_books(tracker.sender_id)
        last_text = tracker.latest_message.get("text", "")
        book_id = _fuzzy_match_book(last_text, books)
        if book_id:
            return [SlotSet("selected_book_id", book_id)]
        return []
