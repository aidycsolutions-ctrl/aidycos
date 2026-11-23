"""Sender-side echo collapse and local conversation cleanup."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging" / "aidylink"))

from aidylink.chat_history import ChatHideStore, plan_message_batch  # noqa: E402


def _msg(mid: int, sender: int, content: str, kind: str = "text") -> dict:
    return {"id": mid, "sender_id": sender, "content": content, "message_type": kind}


class PlanMessageBatchTests(unittest.TestCase):
    def test_own_echo_replaces_the_optimistic_send(self) -> None:
        pending = [{"chat_id": 4, "content": "hola", "kind": "text", "row": "bubble"}]
        steps, last_id, forgotten = plan_message_batch(
            [_msg(9, 3, "hola")],
            pending=pending,
            my_id=3,
            chat_id=4,
            hidden=set(),
            cleared_before=0,
            last_id=0,
            initial=False,
        )
        self.assertEqual(steps, [("replace", _msg(9, 3, "hola"), {"chat_id": 4, "content": "hola", "kind": "text", "row": "bubble"})])
        self.assertEqual(pending, [])
        self.assertEqual(last_id, 9)
        self.assertEqual(forgotten, [])

    def test_same_text_from_the_other_person_stays_visible(self) -> None:
        pending = [{"chat_id": 4, "content": "hola", "kind": "text"}]
        steps, _last_id, forgotten = plan_message_batch(
            [_msg(8, 7, "hola")],
            pending=pending,
            my_id=3,
            chat_id=4,
            hidden=set(),
            cleared_before=0,
            last_id=0,
            initial=False,
        )
        self.assertEqual([step[0] for step in steps], ["append"])
        self.assertEqual(len(pending), 1)
        self.assertEqual(forgotten, [])

    def test_two_identical_sends_match_in_order(self) -> None:
        pending = [
            {"chat_id": 4, "content": "ok", "kind": "text", "dropped": True},
            {"chat_id": 4, "content": "ok", "kind": "text", "dropped": False, "row": "second"},
        ]
        steps, last_id, forgotten = plan_message_batch(
            [_msg(10, 3, "ok"), _msg(11, 3, "ok")],
            pending=pending,
            my_id=3,
            chat_id=4,
            hidden=set(),
            cleared_before=0,
            last_id=0,
            initial=False,
        )
        self.assertEqual(forgotten, [(10, False)])
        self.assertEqual(steps[0][0], "replace")
        self.assertEqual(steps[0][1]["id"], 11)
        self.assertEqual(steps[0][2]["row"], "second")
        self.assertEqual(pending, [])
        self.assertEqual(last_id, 11)

    def test_later_poll_does_not_paint_the_echo_again(self) -> None:
        steps, last_id, _forgotten = plan_message_batch(
            [_msg(9, 3, "hola")],
            pending=[],
            my_id=3,
            chat_id=4,
            hidden=set(),
            cleared_before=0,
            last_id=9,
            initial=False,
        )
        self.assertEqual(steps, [])
        self.assertEqual(last_id, 9)

    def test_cleared_and_hidden_messages_are_skipped(self) -> None:
        steps, last_id, forgotten = plan_message_batch(
            [_msg(4, 7, "viejo"), _msg(6, 7, "oculto"), _msg(8, 7, "nuevo")],
            pending=[],
            my_id=3,
            chat_id=4,
            hidden={6},
            cleared_before=5,
            last_id=0,
            initial=True,
        )
        self.assertEqual([step[1]["id"] for step in steps], [8])
        self.assertEqual(last_id, 8)
        self.assertEqual(forgotten, [])

    def test_unknown_self_does_not_swallow_a_message(self) -> None:
        pending = [{"chat_id": 4, "content": "hola", "kind": "text"}]
        steps, _last_id, _forgotten = plan_message_batch(
            [_msg(9, 3, "hola")],
            pending=pending,
            my_id=0,
            chat_id=4,
            hidden=set(),
            cleared_before=0,
            last_id=0,
            initial=False,
        )
        self.assertEqual(steps[0][0], "append")
        self.assertEqual(len(pending), 1)

    def test_duplicate_ids_in_one_page_paint_once(self) -> None:
        steps, last_id, _forgotten = plan_message_batch(
            [_msg(9, 7, "hola"), _msg(9, 7, "hola")],
            pending=[],
            my_id=3,
            chat_id=4,
            hidden=set(),
            cleared_before=0,
            last_id=0,
            initial=True,
        )
        self.assertEqual(len(steps), 1)
        self.assertEqual(last_id, 9)


class ChatHideStoreTests(unittest.TestCase):
    def test_hide_and_clear_roundtrip(self) -> None:
        path = Path(self.id().replace(".", "_") + ".json")
        path = Path("/tmp") / path.name
        path.unlink(missing_ok=True)
        store = ChatHideStore(path)
        store.hide(4, 3)
        store.hide(4, 6)
        store.clear_through(4, 5)
        store.hide(4, 9)
        again = ChatHideStore(path)
        self.assertTrue(again.hides(4, 3))
        self.assertTrue(again.hides(4, 5))
        self.assertTrue(again.hides(4, 6))
        self.assertTrue(again.hides(4, 9))
        self.assertFalse(again.hides(4, 10))
        self.assertEqual(again.cleared_before(4), 5)
        self.assertEqual(again.hidden_ids(4), {6, 9})
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
