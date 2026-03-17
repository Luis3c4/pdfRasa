import os
from typing import Any, Dict, List, Text

from openai import OpenAI
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher

SYSTEM_PROMPT = (
    "Eres un asistente amable de una tienda de eBooks. "
    "Responde siempre en español de forma concisa y natural. "
    "Puedes responder preguntas generales con libertad, pero si la pregunta "
    "no tiene relación con libros o lectura, responde brevemente y recuerda "
    "al usuario que puedes ayudarle a ver el catálogo, obtener detalles de un "
    "libro o procesar una compra."
)


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

        messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

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
