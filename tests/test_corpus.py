import json
import tempfile
import unittest
from pathlib import Path

from filingroom import config, parse


class LoadParsedTest(unittest.TestCase):
    """Filings a corpus refresh replaced stay on disk but must not be indexed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (config.RAW, config.PARSED, config.INDEX)
        config.use_filing_cache(Path(self.tmp.name))
        (config.PARSED / "XYZ").mkdir(parents=True)
        for d in ("XYZ_10K_FY2026", "XYZ_DEF14A_2025", "XYZ_DEF14A_2026"):
            (config.PARSED / "XYZ" / f"{d}.json").write_text(json.dumps({"doc_id": d, "sections": []}))

    def tearDown(self):
        config.RAW, config.PARSED, config.INDEX = self.saved
        self.tmp.cleanup()

    def test_only_manifest_documents_are_loaded(self):
        (config.RAW / "XYZ").mkdir(parents=True)
        (config.RAW / "XYZ" / "manifest.json").write_text(json.dumps([{"doc_id": "XYZ_10K_FY2026"}, {"doc_id": "XYZ_DEF14A_2026"}]))
        self.assertEqual([d["doc_id"] for d in parse.load_parsed("XYZ")], ["XYZ_10K_FY2026", "XYZ_DEF14A_2026"])

    def test_without_a_manifest_everything_parsed_is_loaded(self):
        self.assertEqual(len(parse.load_parsed("XYZ")), 3)

    def test_filing_cache_switch_leaves_the_cli_cache_constant(self):
        self.assertEqual(config.CLI_RAW, config.DATA / "raw")
        self.assertNotEqual(config.RAW, config.CLI_RAW)


if __name__ == "__main__":
    unittest.main()
