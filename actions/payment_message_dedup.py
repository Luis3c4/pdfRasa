"""In-memory deduplication for payment screenshot messages.

This prevents the same incoming image message from being processed twice
when both the CALM flow action and the free-response fallback can see it.
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Dict

_CACHE: Dict[str, float] = {}
_LOCK = Lock()
_TTL_SECONDS = 15 * 60


def build_scoped_message_id(sender_id: str, message_id: str) -> str:
    """Build a dedup key scoped to the conversation/session."""
    raw_message_id = (message_id or "").strip()
    if not raw_message_id:
        return ""

    scope = (sender_id or "").strip()
    if not scope:
        return raw_message_id

    return f"{scope}:{raw_message_id}"


def _prune(now: float) -> None:
    expired = [message_id for message_id, ts in _CACHE.items() if now - ts > _TTL_SECONDS]
    for message_id in expired:
        _CACHE.pop(message_id, None)


def should_process(message_id: str) -> bool:
    """Return True if this message_id has not been seen recently."""
    if not message_id:
        return True

    now = time.monotonic()
    with _LOCK:
        _prune(now)
        return message_id not in _CACHE


def mark_processed(message_id: str) -> None:
    """Record that a message_id is already being handled."""
    if not message_id:
        return

    now = time.monotonic()
    with _LOCK:
        _prune(now)
        _CACHE[message_id] = now
