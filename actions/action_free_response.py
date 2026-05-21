import json
import os
from pathlib import Path
from typing import Any, Dict, List, Text

from openai import OpenAI
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher

_CATALOG_PATH = Path(__file__).parent.parent / "db" / "catalog.json"


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
- Mostrar el catálogo completo de eBooks disponibles.
- Dar información detallada de un libro específico.
- Guiar al usuario para comprar un eBook y pagar por Yape.

## Catálogo actual
{books_text}

## Contexto comercial y de compra
- Solo vendemos eBooks (producto digital, no físico).
- Métodos de pago habilitados: Yape y Plin.
- Número para pago por Yape o Plin: 923252274.
- Flujo de compra: confirmar compra -> pagar por Yape o Plin -> enviar captura -> recibir link de descarga en este chat.
- No enviamos el producto por correo; la entrega se hace por link en la conversación.

## Reglas de respuesta
0. Responde siempre en español. Nunca respondas en inglés.
0.1 Si preguntan por descuentos, promociones, ofertas o rebajas, responde exactamente: "Lo siento, no contamos con descuentos por el momento."
1. Si el usuario pregunta por un libro, menciona su título exacto y precio, \
y ofrécele verlo o comprarlo.
2. Si el usuario pregunta algo que no tiene que ver con los libros o la tienda \
(clima, chistes, etc.), responde brevemente y redirige: \
"¿Puedo ayudarte con alguno de nuestros eBooks? Tenemos {book_titles}."
3. Nunca inventes precios, links de descarga ni información que no esté en el \
catálogo.
3.1 Si no tienes información suficiente, responde de forma breve: "Lo siento, no cuento con esa información en este momento." y redirige al catálogo o compra.
4. Si el usuario quiere comprar, dile que escriba "quiero comprar [nombre del libro]".
5. Si quiere ver el catálogo, dile que escriba "ver catálogo".
6. Nunca repitas literalmente el mensaje del usuario como respuesta principal.
7. Máximo 3 oraciones por respuesta."""


def _looks_like_english_fallback(text: str) -> bool:
    lower = (text or "").strip().lower()
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

class ActionFreeResponse(Action):
    def name(self) -> str:
        return "action_free_response"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[str, Any],
    ) -> List[Dict[Text, Any]]:
        client = OpenAI(
            api_key=os.environ.get("NVIDIA_API_KEY"),
            base_url="https://integrate.api.nvidia.com/v1",
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
        user_text = tracker.latest_message.get("text") or ""
        messages.append({"role": "user", "content": user_text})

        try:
            response = client.chat.completions.create(
                model="qwen/qwen3-coder-480b-a35b-instruct",
                messages=messages,
                max_tokens=256,
                temperature=0.2,
                top_p=0.9,
            )
            answer = response.choices[0].message.content.strip()
            # Defensive guard: if provider returns generic English fallback, force a Spanish-safe response.
            if _looks_like_english_fallback(answer):
                user_lower = (user_text or "").lower()
                if "método de pago" in user_lower or "metodo de pago" in user_lower or "pago" in user_lower:
                    answer = "Aceptamos pagos por Yape o Plin al 923252274. Si deseas, te guío para comprar el eBook y enviarte el link por este chat."
                else:
                    answer = "Lo siento, no cuento con esa información en este momento. ¿Te ayudo con alguno de nuestros eBooks?"
            dispatcher.utter_message(text=answer)
        except Exception:
            dispatcher.utter_message(response="utter_cannot_handle")

        return []
