from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from prepare_data import _load_dotenv


class PrepareScriptTest(unittest.TestCase):
    def test_dotenv_loads_missing_values_without_overriding_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("PERKWATCH_DATA_DIR='/tmp/perk-watch'\nOPENAI_API_KEY=file-key\n", encoding="utf-8")
            old_data = os.environ.get("PERKWATCH_DATA_DIR")
            old_key = os.environ.get("OPENAI_API_KEY")
            try:
                os.environ["OPENAI_API_KEY"] = "shell-key"
                os.environ.pop("PERKWATCH_DATA_DIR", None)
                _load_dotenv(path)
                self.assertEqual(os.environ["PERKWATCH_DATA_DIR"], "/tmp/perk-watch")
                self.assertEqual(os.environ["OPENAI_API_KEY"], "shell-key")
            finally:
                if old_data is None:
                    os.environ.pop("PERKWATCH_DATA_DIR", None)
                else:
                    os.environ["PERKWATCH_DATA_DIR"] = old_data
                if old_key is None:
                    os.environ.pop("OPENAI_API_KEY", None)
                else:
                    os.environ["OPENAI_API_KEY"] = old_key

    def test_blurb_writer_is_skipped_without_an_api_key(self):
        from unittest.mock import patch
        sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
        from perk_watch.prepare.blurbs import default_writer
        with patch("perk_watch.embeddings._api_key", return_value=None):
            self.assertIsNone(default_writer())

    def test_prepare_script_no_longer_wires_merchant_matching(self):
        source = (Path(__file__).parents[1] / "scripts/prepare_data.py").read_text(encoding="utf-8")
        self.assertNotIn("merchant", source)
        self.assertIn("blurb_writer=default_writer", source)


if __name__ == "__main__":
    unittest.main()
