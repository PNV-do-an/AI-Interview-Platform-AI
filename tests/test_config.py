import os
import unittest
from unittest.mock import patch

from app.config import Settings


class SettingsTests(unittest.TestCase):
    def test_allowed_origins_splits_and_trims_explicit_origins(self):
        with patch.dict(os.environ, {
            "AI_ALLOWED_ORIGIN": "https://aiinterview-vn.vercel.app, http://localhost:3000 ",
        }, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.allowed_origins, [
            "https://aiinterview-vn.vercel.app",
            "http://localhost:3000",
        ])

    def test_allowed_origins_ignores_empty_entries(self):
        with patch.dict(os.environ, {"AI_ALLOWED_ORIGIN": "https://example.test, ,"}, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.allowed_origins, ["https://example.test"])


if __name__ == "__main__":
    unittest.main()
