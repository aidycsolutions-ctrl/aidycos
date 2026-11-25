"""Notification action routing for AidyChat."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging" / "aidylink"))

from aidylink import notify  # noqa: E402
from aidylink.daemon import AidylinkDaemon, _cloud_chat_id  # noqa: E402
from aidylink.messages import LinkMessage  # noqa: E402


class NotificationActionTests(unittest.TestCase):
    def test_cloud_notification_sender_id_contains_conversation_id(self) -> None:
        self.assertEqual(_cloud_chat_id("cloud:142"), 142)
        self.assertIsNone(_cloud_chat_id("cloud:unknown"))
        self.assertIsNone(_cloud_chat_id("peer:142"))

    def test_cloud_notification_offers_open_and_reply_actions(self) -> None:
        proc = mock.Mock()
        with mock.patch.object(notify.shutil, "which", return_value="/usr/bin/notify-send"):
            with mock.patch.object(notify.subprocess, "Popen", return_value=proc) as popen:
                with mock.patch.object(notify.threading, "Thread") as thread:
                    notify._notify_send(
                        "María",
                        "Hola",
                        urgency="normal",
                        target="cloud:142",
                        reply_chat_id=142,
                    )

        args = popen.call_args.args[0]
        self.assertIn("default=Ver conversación", args)
        self.assertIn("reply=Responder", args)
        self.assertIn("0", args[args.index("-t") + 1 : args.index("-A")])
        self.assertNotIn("-e", args)
        self.assertEqual(
            thread.call_args.kwargs["args"],
            (proc, "cloud:142", 142, "María", "Hola"),
        )

    def test_default_action_routes_to_the_target_conversation(self) -> None:
        proc = mock.Mock()
        proc.communicate.return_value = (b"default\n", None)
        with mock.patch.object(notify, "raise_or_open_ui") as open_ui:
            notify._open_on_action(proc, "cloud:142", 142, "María", "Hola")
        open_ui.assert_called_once_with("cloud:142")

    def test_reply_action_starts_compact_reply_prompt(self) -> None:
        proc = mock.Mock()
        proc.communicate.return_value = (b"reply\n", None)
        with mock.patch.object(notify, "_spawn_quick_reply") as quick_reply:
            notify._open_on_action(proc, "cloud:142", 142, "María", "Hola")
        quick_reply.assert_called_once_with(142, "María", "Hola")

    def test_cloud_batch_keeps_conversation_id_for_open_and_reply(self) -> None:
        daemon = AidylinkDaemon.__new__(AidylinkDaemon)
        daemon._last_cloud_notify_key = ""
        daemon._persist = mock.Mock()
        daemon._schedule_mobile_fanout = mock.Mock()
        message = LinkMessage.create(
            from_id="cloud:142",
            from_name="María",
            to_id="local-node",
            text="Hola",
            team_id="team",
            via="cloud",
        )
        with mock.patch("aidylink.daemon.notify") as show_notification:
            daemon._on_cloud_batch([message])
        self.assertEqual(
            show_notification.call_args.kwargs["target"], "cloud:142"
        )
        self.assertEqual(show_notification.call_args.kwargs["reply_chat_id"], 142)


if __name__ == "__main__":
    unittest.main()
