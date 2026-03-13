from typing import Any, Dict, List, Text

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher


def _has_image_attachment(tracker: Tracker) -> bool:
    """Return True if the latest message contains an image attachment."""
    metadata = tracker.latest_message.get("metadata", {})

    # Chatwoot attachments
    attachments = metadata.get("attachments") or []
    if attachments:
        return True

    # Meta / Twilio / generic
    if metadata.get("image") or metadata.get("MediaUrl0") or metadata.get("image_url"):
        return True

    return False


class ActionCannotHandle(Action):
    def name(self) -> str:
        return "action_cannot_handle"

    def run(
        self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[str, Any]
    ) -> List[Dict[Text, Any]]:
        # If the user sent an image, stay silent — another action will handle it
        if _has_image_attachment(tracker):
            return []

        dispatcher.utter_message(response="utter_cannot_handle")
        return []
