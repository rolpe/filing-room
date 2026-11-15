import json
import unittest
from pathlib import Path

from filingroom import config, devtools, evalstats, evaluate


class WilsonTest(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(evalstats.wilson(35, 39), (76.4, 95.9))  # Box: 35 of 39
        self.assertEqual(evalstats.wilson(0, 10)[0], 0.0)
        self.assertEqual(evalstats.wilson(10, 10)[1], 100.0)
        lo, hi = evalstats.wilson(10, 10)
        self.assertGreater(lo, 65)  # 100% on 10 items is not certainty
        self.assertIsNone(evalstats.wilson(0, 0))
        self.assertEqual(evalstats.rate(1, 4)["pct"], 25.0)


class SignTest(unittest.TestCase):
    def test_exact_two_sided(self):
        self.assertEqual(evalstats.sign_test(0, 0), 1.0)
        self.assertEqual(evalstats.sign_test(2, 0), 0.5)
        self.assertAlmostEqual(evalstats.sign_test(6, 0), 2 / 64)
        self.assertAlmostEqual(evalstats.sign_test(8, 1), 2 * 10 / 512)
        self.assertEqual(evalstats.sign_test(3, 3), 1.0)

    def test_statements(self):
        self.assertEqual(evalstats.flip_statement(0, 0), "No item changed its grade.")
        self.assertIn("too few to tell from noise", evalstats.flip_statement(2, 0))
        self.assertIn("unlikely to be noise", evalstats.flip_statement(8, 0))


def row(i, grade="judged", correct=True, status="answered", verified=(True,), confidence="high"):
    return {"id": f"T:{i}", "ticker": "T", "grade": grade, "correct": correct, "status": status,
            "model_status": "answered" if status != "not_found" else "not_found", "confidence": confidence,
            "citations": [{"quote": "q", "verified": v, "doc_id": "T_10K_FY2026"} for v in verified],
            "citations_verified": sum(verified)}


class TrustTest(unittest.TestCase):
    def test_trust_uses_the_app_status_function(self):
        docs = {"T": {"T_10K_FY2026": {}}}
        rows = [row(1), row(2, correct=False),                                    # verified right, verified wrong
                row(3, correct=False, verified=(True, False)),                    # wrong, flagged by an unverified quote
                row(4, correct=False, status="not_found", verified=()),           # false not found
                row(5, grade="abstain", status="not_found", verified=()),         # correct abstention
                row(6, grade="support_only", correct=None),                       # not counted for correctness
                row(7, grade="numeric", correct=False)]                           # wrong number; SEC check catches it
        gold = {"T:7": {"source": {"method": "xbrl"}}}
        t = evalstats.trust(rows, gold, docs)
        self.assertEqual((t["verified_wrong"]["k"], t["verified_wrong"]["n"]), (1, 2))
        self.assertEqual((t["wrong_caught"]["k"], t["wrong_caught"]["n"]), (2, 4))
        self.assertEqual(t["wrong_by_status"], {"verified": 1, "review": 2, "not_disclosed": 1})
        self.assertEqual((t["false_not_found"]["k"], t["false_not_found"]["n"]), (1, 6))  # judgment-only items are answerable too
        self.assertEqual(t["statuses"]["T:7"], "review")
        self.assertNotIn("T:6", t["statuses"])

    def test_counts_match_evaluate_metrics_on_recorded_runs(self):
        for p in sorted(config.RESULTS.glob("*.json")):
            r = json.loads(p.read_text())
            if "rows" not in r:
                continue
            m, c = evaluate.metrics(r["rows"]), evalstats.counts(r["rows"])
            for k in c:
                self.assertEqual(c[k]["pct"], m[k], (p.name, k))


class ManualEditTest(unittest.TestCase):
    TEXT = ('// comment line, kept\n'
            '{"id": "A:x", "ticker": "A", "expected": {"text": "Café"}, "verified": "claude-draft", "note": "n"}\n'
            '\n'
            '{"id": "A:y", "ticker": "A", "expected": {"value": 1}, "verified": "claude-draft"}\n')

    def test_only_the_item_line_changes_and_key_order_is_kept(self):
        new = devtools.edit_manual_line(self.TEXT, "A:y", "human", None)
        old_lines, new_lines = self.TEXT.split("\n"), new.split("\n")
        self.assertEqual(len(old_lines), len(new_lines))
        changed = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
        self.assertEqual(changed, [3])
        self.assertEqual(new_lines[3], '{"id": "A:y", "ticker": "A", "expected": {"value": 1}, "verified": "human"}')
        for i in (0, 1, 2, 4):
            self.assertEqual(new_lines[i].encode(), old_lines[i].encode())

    def test_needs_fix_adds_a_note_last_and_undo_removes_it(self):
        fixed = devtools.edit_manual_line(self.TEXT, "A:x", "needs-fix", "Wrong period")
        line = fixed.split("\n")[1]
        self.assertTrue(line.endswith('"verified": "needs-fix", "note": "n", "review_note": "Wrong period"}'))
        self.assertIn("Café", line)  # non-ASCII kept as written
        back = devtools.edit_manual_line(fixed, "A:x", "claude-draft", None)
        self.assertEqual(back, self.TEXT)

    def test_unknown_item(self):
        with self.assertRaises(KeyError):
            devtools.edit_manual_line(self.TEXT, "A:z", "human", None)

    def test_real_file_round_trips_unchanged(self):
        text = Path(config.ROOT / "golden" / "manual.jsonl").read_text()
        first = next(json.loads(l)["id"] for l in text.splitlines() if l.strip() and not l.startswith("//"))
        cur = next(json.loads(l)["verified"] for l in text.splitlines() if l.strip() and not l.startswith("//"))
        self.assertEqual(devtools.edit_manual_line(text, first, cur, None), text)


if __name__ == "__main__":
    unittest.main()
