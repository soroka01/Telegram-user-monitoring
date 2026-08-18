from __future__ import annotations

import unittest

from main import diff_snapshots, format_diff


def snapshot_with_gift(gift: dict) -> dict:
    return {
        "taken_at": "2026-08-17T08:22:56+03:00",
        "identity": {"id": 8096108910, "display": "Карна @tadmo", "username": "tadmo"},
        "profile": {},
        "photos": {"ids": []},
        "gifts": {
            "available": True,
            "error": None,
            "visible_count": 1,
            "listed_count": 1,
            "items": [gift],
        },
    }


class GiftDiffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gift = {
            "key": "saved:1",
            "saved_id": 1,
            "date": "2026-08-13T08:48:54+00:00",
            "from": "id 979807884",
            "from_peer": "user:979807884",
            "pinned_to_top": False,
            "gift": {"id": 6046178578163303744, "title": "🎂", "stars": 50},
        }

    def test_sender_display_label_does_not_mark_gift_changed(self) -> None:
        current_gift = {**self.gift, "from": "17"}
        diff = diff_snapshots(snapshot_with_gift(self.gift), snapshot_with_gift(current_gift))
        self.assertEqual(diff["gift_changed"], [])

    def test_changed_gift_lists_exact_field(self) -> None:
        current_gift = {**self.gift, "pinned_to_top": True}
        current = snapshot_with_gift(current_gift)
        diff = diff_snapshots(snapshot_with_gift(self.gift), current)

        self.assertEqual(diff["gift_changed"][0]["changes"], [{"path": "pinned_to_top", "old": False, "new": True}])
        message = format_diff(current, diff)
        self.assertIn("закрепление", message)
        self.assertIn("нет</code> -&gt; <code>да", message)
        self.assertNotIn("Текущие детали", message)


if __name__ == "__main__":
    unittest.main()
