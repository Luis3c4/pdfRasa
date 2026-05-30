import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Text

from openai import OpenAI
from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher

from actions.action_normalize_purchase_confirmation import _parse_purchase_confirmation

logger = logging.getLogger(__name__)

_CATALOG_PATH = Path(__file__).parent.parent / "db" / "catalog.json"


def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def _is_payment_method_question(text: str) -> bool:
    lower = _normalize(text)
    if not lower:
        return False

    payment_tokens = (
        "pago",
        "pagos",
        "metodo",
        "método",
        "yape",
        "plin",
        "aceptan",
        "aceptas",
    )
    return any(token in lower for token in payment_tokens)


def _is_purchase_intent(text: str) -> bool:
    """Return True if the user message clearly expresses intent to buy the book."""
    lower = _normalize(text)
    if not lower:
        return False

    purchase_tokens = (
        "comprarlo",
        "comprar",
        "lo quiero",
        "quiero el libro",
        "quiero pagar",
        "me lo llevo",
        "lo compro",
        "adquirirlo",
    )
    return any(token in lower for token in purchase_tokens)


def _is_affirmative(text: str) -> bool:
    return _parse_purchase_confirmation(text) is True


def _is_negative(text: str) -> bool:
    return _parse_purchase_confirmation(text) is False


def _get_default_book_data() -> Dict[str, str] | None:
    """Return first catalog item data for deterministic purchase fallback replies."""
    try:
        catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        if not catalog:
            return None

        first = catalog[0]
        price = f'{first.get("currency", "")} {first.get("price", "")}'.strip()
        return {
            "book_id": str(first.get("id") or ""),
            "book_title": str(first.get("title") or "200 recetas KETO"),
            "book_price": price or "S/ 7",
            "book_preview": str(first.get("preview") or ""),
        }
    except Exception:
        return None


def _was_asking_purchase_confirmation(tracker: Tracker) -> bool:
    last_bot_text = ""
    for event in reversed(tracker.events):
        if event.get("event") == "bot":
            text = event.get("text") or ""
            if text:
                last_bot_text = text
                break

    lower = _normalize(last_bot_text)
    return "yape o plin" in lower and "(si - no)" in lower and "es correcto" in lower


def _build_system_prompt() -> str:
    try:
        catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        books_text = "\n".join(
            f'- "{b["title"]}" — {b["description"]} '
            f'({b["pages"]} páginas, precio: {b["currency"]} {b["price"]})'
            for b in catalog
        )
        book_titles = ", ".join(f'"{b["title"]}"' for b in catalog)
    except Exception:
        books_text = "(catálogo no disponible)"
        book_titles = ""

    return f"""Eres el asistente virtual de una tienda de eBooks en línea. \
Respondes siempre en español de forma amable, concisa y natural.

## Lo que puedes hacer
- Dar información detallada del libro disponible.
- Guiar al usuario para comprar el eBook y pagar por Yape o Plin.

## Producto actual
{books_text}

## Contexto comercial y de compra
- Vendemos un solo eBook (producto digital, no físico): {book_titles}.
- Métodos de pago habilitados: Yape y Plin.
- Número para pago por Yape o Plin: 923252274.
- Flujo de compra: confirmar compra -> pagar por Yape o Plin -> enviar captura -> recibir link de descarga en este chat.
- No enviamos el producto por correo; la entrega se hace por link en la conversación.

## Reglas de respuesta
0. Responde siempre en español. Nunca respondas en inglés.
0.1 Si preguntan por descuentos, promociones, ofertas o rebajas, responde exactamente: "Lo siento, no contamos con descuentos por el momento."
1. Responde únicamente lo que el usuario preguntó, de forma clara y directa. No añadas preguntas de seguimiento, sugerencias de catálogo ni frases como "¿Te gustaría ver el catálogo?" o "¿Quieres ver más libros?". Solo responde la pregunta.
2. Si el usuario pregunta algo que no tiene que ver con el libro o la tienda \
(clima, chistes, etc.), responde brevemente y redirige: \
"¿Puedo ayudarte con información sobre nuestro eBook {book_titles}?"
3. Nunca inventes precios, links de descarga ni información que no esté en el \
producto.
3.1 Si no tienes información suficiente, responde de forma breve: "Lo siento, no cuento con esa información en este momento."
4. Si el usuario quiere comprar, dile que escriba "quiero comprar".
5. Nunca repitas literalmente el mensaje del usuario como respuesta principal.
6. Si el usuario pregunta por métodos de pago (Yape/Plin), responde directo y breve, sin hacer preguntas de seguimiento.
7. Máximo 2 oraciones por respuesta. No hagas preguntas al cliente al final de la respuesta."""


def _looks_like_english_fallback(text: str) -> bool:
    lower = _normalize(text)
    if not lower:
        return True

    blocked_patterns = [
        "i am afraid",
        "i don't know",
        "i do not know",
        "knowledge base",
        "at this point",
    ]
    return any(pattern in lower for pattern in blocked_patterns)


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks produced by Qwen3 reasoning models."""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return cleaned.strip()


def _has_image_attachment(tracker: Tracker) -> bool:
    """Return True when latest message includes an image attachment/metadata."""
    metadata = tracker.latest_message.get("metadata", {}) or {}

    attachments = metadata.get("attachments") or []
    if attachments:
        return True

    if metadata.get("image") or metadata.get("MediaUrl0") or metadata.get("image_url"):
        return True

    return False


class ActionFreeResponse(Action):
    def name(self) -> str:
        return "action_free_response"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[str, Any],
    ) -> List[Dict[Text, Any]]:
        # Never send free-response LLM messages for screenshot/image turns.
        # Those turns must be handled by the purchase screenshot flow.
        if _has_image_attachment(tracker):
            return []

        user_text = tracker.latest_message.get("text") or ""

        # Keep purchase confirmation deterministic: answer payment FAQ briefly.
        # Do NOT re-send utter_ask_purchase_confirmation here — the CALM flow's
        # rejection mechanism already does it and re-sending would cause a duplicate.
        if _was_asking_purchase_confirmation(tracker) and _is_payment_method_question(user_text):
            dispatcher.utter_message(
                text="Sí, también aceptamos pago mediante Plin. Puedes pagar usando Yape o Plin."
            )
            return []

        # Safety net: if yes/no confirmation is misrouted to free response,
        # set the slot so the CALM purchase flow can advance.
        # Do NOT send the payment instructions or cancellation message here —
        # the CALM flow sends them via utter_payment_instructions /
        # utter_purchase_cancelled, and sending them here too causes duplicates.
        if _was_asking_purchase_confirmation(tracker):
            if _is_affirmative(user_text):
                return [SlotSet("purchase_confirmation", True)]

            if _is_negative(user_text):
                return [SlotSet("purchase_confirmation", False)]

        # Safety net: if the command generator misroutes a purchase intent to
        # free response, show the same purchase confirmation prompt expected by
        # the purchase flow instead of asking the user to repeat themselves.
        if _is_purchase_intent(user_text):
            book = _get_default_book_data()
            if book:
                if book["book_preview"]:
                    dispatcher.utter_message(text=f"🔍 *Preview:* {book['book_preview']}")
                dispatcher.utter_message(
                    text=f"Quieres comprar *{book['book_title']}* por *{book['book_price']}* yape o plin ¿Es correcto? (si - no)"
                )
                return [
                    SlotSet("selected_book_id", book["book_id"]),
                    SlotSet("book_title", book["book_title"]),
                    SlotSet("book_price", book["book_price"]),
                    SlotSet("book_preview", book["book_preview"]),
                ]

            dispatcher.utter_message(
                text="Quieres comprar *200 recetas KETO* por *S/ 7* yape o plin ¿Es correcto? (si - no)"
            )
            return []

        try:
            client = OpenAI(
                api_key=os.environ.get("NVIDIA_API_KEY"),
                base_url="https://integrate.api.nvidia.com/v1",
                timeout=20.0,  # hard cap so Rasa never waits indefinitely
            )

            messages: List[Dict[str, str]] = [{"role": "system", "content": _build_system_prompt()}]

            # Add recent conversation history for context (skip current user message)
            history_events = [
                e for e in tracker.events if e.get("event") in ("user", "bot")
            ]
            # Limit to last 10 turns (20 events), excluding the latest user message
            for event in history_events[-21:-1]:
                if event["event"] == "user":
                    text = event.get("text") or ""
                    if text:
                        messages.append({"role": "user", "content": text})
                elif event["event"] == "bot":
                    text = event.get("text") or ""
                    if text:
                        messages.append({"role": "assistant", "content": text})

            # Add the current user message
            messages.append({"role": "user", "content": user_text})

            response = client.chat.completions.create(
                model="meta/llama-3.1-8b-instruct",
                messages=messages,
                max_tokens=256,
                temperature=0.5,
            )
            raw = response.choices[0].message.content or ""
            # Strip any residual <think>...</think> blocks as a safety net.
            answer = _strip_thinking_tags(raw)
            if not answer:
                logger.warning(
                    "action_free_response: LLM returned empty answer. Raw: %r", raw
                )
                answer = "Lo siento, no cuento con esa información en este momento."
            elif _looks_like_english_fallback(answer):
                if _is_payment_method_question(user_text):
                    answer = "Sí, aceptamos pagos por Yape o Plin al 923252274."
                else:
                    answer = "Lo siento, no cuento con esa información en este momento. ¿Te ayudo con alguno de nuestros eBooks?"
            dispatcher.utter_message(text=answer)
        except Exception:
            logger.exception("action_free_response: LLM call failed")
            dispatcher.utter_message(response="utter_cannot_handle")

        return []
