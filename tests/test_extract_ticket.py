"""Malformed / ambiguous ticket extraction."""

from __future__ import annotations

import unittest

from codex_dispatcher.github import extract_ticket


class ExtractTicketTests(unittest.TestCase):
    def test_raw_json_object(self) -> None:
        ticket = extract_ticket('{"id": "a", "summary": "x"}')
        self.assertEqual(ticket["id"], "a")
        self.assertIsInstance(ticket, dict)

    def test_single_fenced_json(self) -> None:
        body = "intro\n\n```json\n{\"id\": \"b\"}\n```\n"
        ticket = extract_ticket(body)
        self.assertEqual(ticket["id"], "b")

    def test_rejects_json_array(self) -> None:
        with self.assertRaises(ValueError):
            extract_ticket("[1, 2, 3]")

    def test_rejects_malformed_json(self) -> None:
        with self.assertRaises(ValueError):
            extract_ticket("{not json")

    def test_rejects_ambiguous_multiple_fences(self) -> None:
        body = "```json\n{\"id\": 1}\n```\n```json\n{\"id\": 2}\n```"
        with self.assertRaises(ValueError):
            extract_ticket(body)

    def test_rejects_braces_outside_fence(self) -> None:
        body = "see {note}\n```json\n{\"id\": 1}\n```"
        with self.assertRaises(ValueError):
            extract_ticket(body)


if __name__ == "__main__":
    unittest.main()
