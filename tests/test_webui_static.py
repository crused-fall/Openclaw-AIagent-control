from pathlib import Path
import unittest


class WebUiStaticTests(unittest.TestCase):
    def test_status_chip_uses_sanitized_tone_class(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "openclaw_v2" / "webui" / "app.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("function statusChipTone(value)", source)
        self.assertIn('return `<span class=\"status-chip ${tone}\">${escapeHtml(normalized)}</span>`;', source)
        self.assertNotIn('class=\"status-chip ${normalized}\"', source)


if __name__ == "__main__":
    unittest.main()
