"""Design tokens (ui_qt/theme.TOKENS): the colours of the plan and their measured contrast (WCAG 2.1)."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

THEME = Path("src/accounting_converter/ui_qt/theme.py")


def _dict(name: str) -> dict:
    tree = ast.parse(THEME.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == name for t in node.targets):
            return ast.literal_eval(node.value) if name == "TOKENS" else {
                k.value: v for k, v in zip(node.value.keys, node.value.values)}
    raise AssertionError(name)


def _luminance(colour: str) -> float:
    channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class TokenTest(unittest.TestCase):
    def setUp(self):
        self.t = _dict("TOKENS")

    def test_the_planned_colours(self):
        expected = {"bg.page": "#F7F8FA", "bg.surface": "#FFFFFF", "accent": "#1F3A68",
                    "status.ready": "#146C43", "status.block": "#8A4B00"}
        self.assertEqual({k: self.t[k] for k in expected}, expected)

    def test_text_status_and_control_contrast(self):
        t = self.t
        for fg, bg, minimum in (
                ("text.primary", "bg.page", 7), ("text.primary", "bg.surface", 7),
                ("text.secondary", "bg.surface", 4.5), ("text.secondary", "bg.page", 4.5),
                ("bg.surface", "accent", 4.5), ("accent", "accent.soft", 4.5),
                ("status.ready", "status.ready.bg", 4.5), ("status.block", "status.block.bg", 4.5),
                ("status.pending", "status.pending.bg", 4.5), ("status.evidence", "status.evidence.bg", 4.5),
                ("status.error", "status.error.bg", 4.5), ("status.neutral", "status.neutral.bg", 4.5),
                ("border.control", "bg.surface", 3), ("border.control", "bg.page", 3), ("focus", "bg.surface", 3),
                ("text.disabled", "bg.disabled", 3)):
            with self.subTest(fg=fg, bg=bg):
                self.assertGreaterEqual(contrast(t[fg], t[bg]), minimum)

    def test_ready_and_block_never_share_a_colour(self):
        self.assertNotEqual(self.t["status.ready"], self.t["status.block"])
        self.assertNotEqual(self.t["status.block"], self.t["status.error"])

    def test_the_old_colour_keys_remain_and_come_from_tokens(self):
        colours = _dict("COLORS")
        for key in ("page", "surface", "text", "muted", "accent", "ready", "confirm", "blocked", "disabled_text",
                    "input_border", "focus"):
            self.assertIn(key, colours)
            self.assertIsInstance(colours[key], ast.Subscript, key)   # TOKENS["..."], not a literal


if __name__ == "__main__":
    unittest.main()
