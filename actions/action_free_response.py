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

## Reglas de respuesta
1. Si el usuario pregunta por un libro, menciona su título exacto y precio, \
y ofrécele verlo o comprarlo.
2. Si el usuario pregunta algo que no tiene que ver con los libros o la tienda \
(clima, chistes, etc.), responde brevemente y redirige: \
"¿Puedo ayudarte con alguno de nuestros eBooks? Tenemos {book_titles}."
3. Nunca inventes precios, links de descarga ni información que no esté en el \
catálogo.
4. Si el usuario quiere comprar, dile que escriba "quiero comprar [nombre del libro]".
5. Si quiere ver el catálogo, dile que escriba "ver catálogo".
6. Máximo 3 oraciones por respuesta."""

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
            api_key=os.environ.get("VLLM_API_KEY", "fake-key"),
            base_url="http://localhost:8000/v1",
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
                model="Qwen/Qwen2.5-7B-Instruct",
                messages=messages,
                max_tokens=512,
                temperature=0.7,
            )
            answer = response.choices[0].message.content.strip()
            dispatcher.utter_message(text=answer)
        except Exception:
            dispatcher.utter_message(response="utter_cannot_handle")

        return []
