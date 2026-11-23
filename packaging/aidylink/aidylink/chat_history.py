"""Decide which AidyChat messages to paint, and remember local cleanups.

The desktop shell draws an optimistic bubble before the server answers.
The following poll returns that same message once. These helpers collapse
the echo so the sender does not see two copies, and they keep deletions
that only this installation should hide.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def plan_message_batch(
    messages: list[Any],
    *,
    pending: list[dict[str, Any]],
    my_id: int,
    chat_id: int,
    hidden: set[int],
    cleared_before: int,
    last_id: int,
    initial: bool,
) -> tuple[list[tuple[str, dict[str, Any], dict[str, Any] | None]], int, list[tuple[int, bool]]]:
    """Turn a server page into paint steps.

    Returns ``(steps, last_id, forgotten_ids)``. Each step is
    ``("replace", message, pending_item)`` when it is the server copy of an
    optimistic send, or ``("append", message, None)`` otherwise.
    ``pending`` is mutated: a matched send is removed. A pending send the
    user already deleted becomes ``(message_id, purge)`` in ``forgotten_ids``
    and is not painted. ``purge`` means the row should also be deleted
    on the server.
    """
    steps: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []
    forgotten: list[tuple[int, bool]] = []
    seen: set[int] = set()
    cursor = int(last_id or 0)
    floor = int(cleared_before or 0)
    me = int(my_id or 0)
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        mid = _positive_int(raw.get("id")) or 0
        if mid and mid in seen:
            continue
        if mid and not initial and mid <= cursor:
            continue
        if mid and (mid in hidden or (floor and mid <= floor)):
            cursor = max(cursor, mid)
            seen.add(mid)
            continue
        matched = _take_pending(pending, chat_id=chat_id, msg=raw, my_id=me)
        if mid:
            cursor = max(cursor, mid)
            seen.add(mid)
        if matched is not None:
            if matched.get("dropped"):
                if mid:
                    forgotten.append((mid, bool(matched.get("purge"))))
                continue
            steps.append(("replace", raw, matched))
            continue
        steps.append(("append", raw, None))
    return steps, cursor, forgotten


def _take_pending(
    pending: list[dict[str, Any]],
    *,
    chat_id: int,
    msg: dict[str, Any],
    my_id: int,
) -> dict[str, Any] | None:
    if not my_id:
        return None
    sender = _positive_int(msg.get("sender_id"))
    if sender != my_id:
        return None
    kind = str(msg.get("message_type") or "text")
    content = str(msg.get("content") or "")
    for index, item in enumerate(pending):
        if int(item.get("chat_id") or 0) != int(chat_id):
            continue
        if item.get("failed"):
            continue
        if str(item.get("kind") or "text") != kind:
            continue
        if str(item.get("content") or "") != content:
            continue
        return pending.pop(index)
    return None


class ChatHideStore:
    """Message ids this installation should not show again."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._hidden: dict[int, set[int]] = {}
        self._cleared: dict[int, int] = {}
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return
        if not isinstance(raw, dict):
            return
        hidden = raw.get("hidden")
        cleared = raw.get("cleared_before")
        if isinstance(hidden, dict):
            for key, values in hidden.items():
                chat_id = _positive_int(key)
                if chat_id is None or not isinstance(values, list):
                    continue
                ids = {number for value in values if (number := _positive_int(value))}
                if ids:
                    self._hidden[chat_id] = ids
        if isinstance(cleared, dict):
            for key, value in cleared.items():
                chat_id = _positive_int(key)
                floor = _positive_int(value)
                if chat_id is not None and floor is not None:
                    self._cleared[chat_id] = floor

    def save(self) -> None:
        payload = {
            "hidden": {str(chat_id): sorted(ids) for chat_id, ids in self._hidden.items() if ids},
            "cleared_before": {str(chat_id): floor for chat_id, floor in self._cleared.items() if floor > 0},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    def hides(self, chat_id: int, message_id: int) -> bool:
        message_id = _positive_int(message_id) or 0
        if not message_id:
            return False
        if message_id <= self._cleared.get(int(chat_id), 0):
            return True
        return message_id in self._hidden.get(int(chat_id), set())

    def hidden_ids(self, chat_id: int) -> set[int]:
        return set(self._hidden.get(int(chat_id), set()))

    def cleared_before(self, chat_id: int) -> int:
        return int(self._cleared.get(int(chat_id), 0))

    def hide(self, chat_id: int, message_id: int) -> None:
        message_id = _positive_int(message_id) or 0
        chat_id = int(chat_id)
        if not message_id or message_id <= self._cleared.get(chat_id, 0):
            return
        self._hidden.setdefault(chat_id, set()).add(message_id)
        self.save()

    def clear_through(self, chat_id: int, message_id: int) -> None:
        chat_id = int(chat_id)
        message_id = _positive_int(message_id) or 0
        if message_id <= self._cleared.get(chat_id, 0):
            return
        self._cleared[chat_id] = message_id
        leftover = {mid for mid in self._hidden.get(chat_id, set()) if mid > message_id}
        if leftover:
            self._hidden[chat_id] = leftover
        else:
            self._hidden.pop(chat_id, None)
        self.save()
