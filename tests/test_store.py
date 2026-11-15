import os
import tempfile
import threading
import unittest
from pathlib import Path

from filingroom import store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("FILINGROOM_APP_DIR")
        os.environ["FILINGROOM_APP_DIR"] = self.tmp.name

    def tearDown(self):
        if self.old is None:
            os.environ.pop("FILINGROOM_APP_DIR", None)
        else:
            os.environ["FILINGROOM_APP_DIR"] = self.old
        self.tmp.cleanup()

    def test_starts_empty_and_round_trips(self):
        self.assertEqual(store.coverage(), [])
        store.add("BILL")
        store.add("BILL")
        self.assertEqual(store.coverage(), ["BILL"])
        store.put("BILL", "company.json", {"name": "BILL Holdings"})
        self.assertEqual(store.get("BILL", "company.json"), {"name": "BILL Holdings"})
        self.assertIsNone(store.get("BILL", "memo.json"))

    def test_rejects_bad_or_unknown_tickers(self):
        for bad in ("../etc", "bill", "B/X", "", "A" * 11, ".."):
            with self.assertRaises((ValueError, KeyError)):
                store.add(bad) if bad else store.company_dir(bad)
        with self.assertRaises(KeyError):
            store.company_dir("RPD")  # valid pattern, not in coverage

    def test_atomic_write_leaves_no_temp_files_and_survives_threads(self):
        store.add("WK")

        def work(i):
            for j in range(20):
                store.annotate("WK", f"q{i}", note=f"n{j}")
        threads = [threading.Thread(target=work, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        ann = store.get("WK", "annotations.json")
        self.assertEqual({k: v["note"] for k, v in ann.items()}, {f"q{i}": "n19" for i in range(5)})
        self.assertEqual([p.name for p in store.company_dir("WK").iterdir() if p.name.endswith(".tmp")], [])

    def test_annotate_removes_cleared_fields_and_remove_deletes_folder(self):
        store.add("RPD")
        store.annotate("RPD", "x", flagged=True, flagged_at="t")
        self.assertEqual(store.annotate("RPD", "x", flagged=None, flagged_at=None), {})
        self.assertEqual(store.get("RPD", "annotations.json"), {})
        d = store.company_dir("RPD")
        store.remove("RPD")
        self.assertFalse(Path(d).exists())
        self.assertEqual(store.coverage(), [])

    def test_jsonl_skips_torn_lines(self):
        store.add("BOX")
        p = store.path("BOX", "questions.jsonl")
        store.append_jsonl(p, {"id": "a"})
        with open(p, "a") as f:
            f.write('{"id": "b"')
        self.assertEqual(store.read_jsonl(p), [{"id": "a"}])


if __name__ == "__main__":
    unittest.main()
