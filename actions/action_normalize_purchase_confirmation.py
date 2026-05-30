import re
import unicodedata
from typing import Any, Dict, List, Optional, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher


def _normalize(text: str) -> str:
    base = (text or "").strip().lower()
    # Remove accents and punctuation so variants like "sI", "sí!!", "no..." are robustly parsed.
    base = unicodedata.normalize("NFKD", base)
    base = "".join(ch for ch in base if not unicodedata.combining(ch))
    base = re.sub(r"[^a-z0-9\s]", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return base


def _squash_repeated_letters(word: str) -> str:
    # Turn elongated words into a stable form: siiii -> sii, noooo -> noo.
    return re.sub(r"([a-z])\1{2,}", r"\1\1", word)


def _tokenize(text: str) -> List[str]:
    return [_squash_repeated_letters(w) for w in _normalize(text).split() if w]


def _parse_purchase_confirmation(text: str) -> Optional[bool]:
    tokens = _tokenize(text)
    if not tokens:
        return None

    normalized_text = " ".join(tokens)
    first = tokens[0]

    affirmative_phrases = {
        "si",
        "sii",
        "sip",
        "yes",
        "ok",
        "oki",
        "okay",
        "dale",
        "claro",
        "correcto",
        "confirmo",
        "acepto",
        "proceder",
        "vamos",
        "quiero",
        "de acuerdo",
        "afirmativo",
        "va",
    }
    negative_phrases = {
        "no",
        "nop",
        "nope",
        "nel",
        "cancelar",
        "cancela",
        "cancelado",
        "mejor no",
        "no quiero",
        "detener",
        "stop",
        "parar",
        "abortar",
    }

    if normalized_text in affirmative_phrases:
        return True
    if normalized_text in negative_phrases:
        return False

    if first in {"si", "sii", "sip", "yes", "ok", "oki", "okay", "dale", "claro", "va"}:
        return True
    if first in {"no", "nop", "nope", "nel", "cancelar", "cancela", "stop"}:
        return False

    return None


def _is_affirmative(text: str) -> bool:
    return _parse_purchase_confirmation(text) is True


def _is_negative(text: str) -> bool:
    return _parse_purchase_confirmation(text) is False


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


class ValidatePurchaseConfirmation(Action):
    def name(self) -> str:
        return "validate_purchase_confirmation"

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
