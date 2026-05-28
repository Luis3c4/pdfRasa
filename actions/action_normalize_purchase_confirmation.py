from typing import Any, Dict, List, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher


def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def _is_affirmative(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False

    affirmative_tokens = {
        "si",
        "yes",
        "ok",
        "dale",
        "correcto",
        "confirmo",
        "acepto",
        "proceder",
        "vamos",
        "quiero",
    }
    return normalized in affirmative_tokens


def _is_negative(text: str) -> bool:
    normalized = _normalize(text)
    if not normalized:
        return False

    negative_tokens = {
        "no",
        "cancelar",
        "no quiero",
        "mejor no",
        "detener",
        "stop",
    }
    return normalized in negative_tokens


class ActionNormalizePurchaseConfirmation(Action):
    def name(self) -> str:
        return "action_normalize_purchase_confirmation"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        current = tracker.get_slot("purchase_confirmation")
        if current is True or current is False:
            return []

        user_text = tracker.latest_message.get("text") or ""

        if _is_affirmative(user_text):
            return [SlotSet("purchase_confirmation", True)]

        if _is_negative(user_text):
            return [SlotSet("purchase_confirmation", False)]

        return []
