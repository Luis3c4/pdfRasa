from typing import Any, Dict, List, Text
from urllib.parse import parse_qs, urlparse

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher

from actions.catalog import get_book_by_id


def _to_direct_download_link(url: str) -> str:
    """Convert supported Google Drive share URLs to direct download URLs."""
    raw = (url or "").strip()
    if not raw:
        return raw

    parsed = urlparse(raw)
    if "drive.google.com" not in parsed.netloc:
        return raw

    file_id = ""
    parts = [segment for segment in parsed.path.split("/") if segment]

    # Example: /file/d/<FILE_ID>/view
    if "d" in parts:
        idx = parts.index("d")
        if idx + 1 < len(parts):
            file_id = parts[idx + 1]

    # Example: /open?id=<FILE_ID>
    if not file_id:
        query = parse_qs(parsed.query)
        file_id = (query.get("id") or [""])[0]

    if not file_id:
        return raw

    return f"https://drive.google.com/uc?export=download&id={file_id}"


def _build_pdf_filename(book_title: str) -> str:
    raw = (book_title or "").strip().lower()
    if not raw:
        return "ebook.pdf"

    safe = "".join(ch for ch in raw if ch.isalnum() or ch in (" ", "-", "_"))
    safe = " ".join(safe.split())
    if not safe:
        safe = "ebook"

    if not safe.endswith(".pdf"):
        safe = f"{safe}.pdf"
    return safe


class ActionReleaseDownload(Action):
    def name(self) -> str:
        return "action_release_download"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        if tracker.get_slot("payment_flow_completed"):
            return [SlotSet("return_value", "success")]

        book_id = tracker.get_slot("selected_book_id")
        order_id = tracker.get_slot("order_id")

        book = get_book_by_id(tracker.sender_id, book_id) if book_id else None

        if book is None:
            dispatcher.utter_message(
                text="Hubo un problema al recuperar tu libro. Contáctanos directamente al 912201963."
            )
            return [SlotSet("return_value", "error")]

        download_link = _to_direct_download_link(book.download_link)
        pdf_filename = _build_pdf_filename(book.title)

        dispatcher.utter_message(
            text=(
                f"🎉 ¡Pago confirmado! Tu orden está lista.\n\n"
                f"📦 Orden #{order_id}\n\n"
                f"Te envío tu PDF como documento en este chat."
            )
        )
        dispatcher.utter_message(
            attachment={
                "type": "file",
                "payload": {
                    "src": download_link,
                    "filename": pdf_filename,
                },
            }
        )
        dispatcher.utter_message(text="¡Disfruta tu lectura! 😊")

        return [
            SlotSet("return_value", "success"),
            SlotSet("purchase_confirmation", None),
            SlotSet("payment_flow_completed", True),
        ]
