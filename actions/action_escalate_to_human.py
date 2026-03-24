"""Escalates a conversation to a human agent in Chatwoot.

Sets the conversation status to "pending" so it appears in the agents' queue.
Reads Chatwoot credentials from environment variables:
    CHATWOOT_URL          — e.g. http://localhost:3000
    CHATWOOT_ACCOUNT_ID   — numeric account ID
    CHATWOOT_ACCESS_TOKEN — agent/bot access token with write permissions
"""

import logging
import os
from typing import Any, Dict, List, Text

import httpx
from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet
from rasa_sdk.executor import CollectingDispatcher

logger = logging.getLogger(__name__)

CHATWOOT_URL = os.environ.get("CHATWOOT_URL", "http://localhost:3000")
CHATWOOT_ACCOUNT_ID = os.environ.get("CHATWOOT_ACCOUNT_ID", "2")
CHATWOOT_ACCESS_TOKEN = os.environ.get("CHATWOOT_ACCESS_TOKEN", "")


class ActionEscalateToHuman(Action):
    def name(self) -> str:
        return "action_escalate_to_human"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[str, Any],
    ) -> List[Dict[Text, Any]]:
        # sender_id format from chatwoot_connector.py: "chatwoot_{conversation_id}"
        sender_id = tracker.sender_id
        conversation_id = sender_id.replace("chatwoot_", "") if sender_id.startswith("chatwoot_") else sender_id

        escalated = self._set_pending(conversation_id)

        if escalated:
            dispatcher.utter_message(response="utter_payment_needs_review")
        else:
            # Chatwoot API call failed — still inform the user and log the issue
            logger.error(
                "Failed to escalate conversation %s to human agent. "
                "Manual review required for sender %s.",
                conversation_id,
                sender_id,
            )
            dispatcher.utter_message(response="utter_payment_needs_review")

        return []

    def _set_pending(self, conversation_id: str) -> bool:
        """Set the Chatwoot conversation status to 'pending' (agent queue)."""
        if not CHATWOOT_ACCESS_TOKEN:
            logger.warning("CHATWOOT_ACCESS_TOKEN not set — skipping escalation API call.")
            return False

        url = (
            f"{CHATWOOT_URL.rstrip('/')}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}"
            f"/conversations/{conversation_id}"
        )
        headers = {
            "api_access_token": CHATWOOT_ACCESS_TOKEN,
            "Content-Type": "application/json",
        }
        try:
            response = httpx.patch(url, json={"status": "pending"}, headers=headers, timeout=10)
            if response.status_code in (200, 201):
                logger.info("Conversation %s escalated to human (status=pending).", conversation_id)
                return True
            logger.error(
                "Chatwoot PATCH %s returned %s: %s",
                url,
                response.status_code,
                response.text,
            )
            return False
        except Exception as exc:
            logger.error("Chatwoot escalation request failed: %s", exc)
            return False
