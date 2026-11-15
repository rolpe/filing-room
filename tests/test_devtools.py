import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from filingroom import config, devtools, evaluate


class PureHelpersTest(unittest.TestCase):
    def test_pass_bar(self):
        ok = {"accuracy": 89.7, "citation_support_rate": 100.0, "unsupported_claim_rate": 0.0}
        self.assertTrue(devtools.passes(ok)["all"])
        p = devtools.passes({**ok, "accuracy": 84.9})
        self.assertFalse(p["accuracy"])
        self.assertFalse(p["all"])
        self.assertFalse(devtools.passes({**ok, "unsupported_claim_rate": 10.1})["all"])
        self.assertTrue(devtools.passes({**ok, "unsupported_claim_rate": 10.0})["all"])
        self.assertFalse(devtools.passes({"accuracy": 99})["all"])  # missing metric doesn't pass

    def test_flips_only_items_in_both_runs_that_changed(self):
        now = [{"id": "a", "correct": True}, {"id": "b", "correct": False}, {"id": "c", "correct": True}]
        before = [{"id": "a", "correct": False}, {"id": "b", "correct": False}]
        self.assertEqual(devtools.flips(now, before), [{"id": "a", "before": False, "after": True}])

    def test_per_item_estimate_from_recorded_runs(self):
        run = lambda n, a, j: {"rows": [{}] * n, "metrics": {"cost_usd": {"answer": a, "judge": j}}}  # noqa: E731
        self.assertEqual(devtools.per_item_estimate([run(80, 1.9, 0.5), run(40, 1.0, 0.24)]), 0.0305)
        self.assertEqual(devtools.per_item_estimate([run(5, 1, 1)]), devtools.FALLBACK_PER_ITEM_USD)  # too small
        self.assertEqual(devtools.estimate_usd(80, 0.0306), 2.45)
        self.assertEqual(devtools.estimate_usd(0, 0.03), 0.01)

    def test_expected_text(self):
        self.assertEqual(devtools.expected_text({"value": -73447000, "unit": "USD", "period": "FY2026"}), "($73.4M) · FY2026")
        self.assertEqual(devtools.expected_text({"value": 95, "unit": "percent"}), "95%")
        self.assertEqual(devtools.expected_text({"not_found": True}), "Not in the filings")
        self.assertEqual(devtools.expected_text({"text": "Starboard agreement"}), "Starboard agreement")

    def test_validate_refuses_holdout_and_large_spot_checks(self):
        with self.assertRaises(ValueError):
            devtools._validate({"kind": "full", "tickers": ["BOX"]})
        with self.assertRaises(ValueError):
            devtools._validate({"kind": "spot", "tickers": ["BILL"], "ids": []})
        ids = [f"BILL:{q}" for q in ("rev_total", "op_income", "net_income", "cf_ocf", "bs_cash", "cf_capex",
                                     "op_sbc", "gm_gross_profit", "rev_rpo", "emp_count", "gov_board")]
        with self.assertRaises(ValueError):
            devtools._validate({"kind": "spot", "tickers": ["BILL"], "ids": ids})
        s = devtools._validate({"kind": "spot", "tickers": ["BILL", "RPD"], "ids": ["BILL:rev_total", "X:nope"],
                                "label": "demo run!", "note": "a|b"})
        self.assertEqual((s["ids"], s["label"], s["note"]), (["BILL:rev_total"], "spot-demo-run", "a/b"))


class EvaluateHooksTest(unittest.TestCase):
    """evaluate.run's optional hooks: subset, progress, separate output, no changelog. Model calls are stubbed."""

    def test_spot_hooks_write_elsewhere_and_skip_the_changelog(self):
        items = [{"id": "T:a", "ticker": "T", "qid": "a", "grade": "abstain", "expected": {"not_found": True}},
                 {"id": "T:b", "ticker": "T", "qid": "b", "grade": "abstain", "expected": {"not_found": True}}]
        ans = lambda t, q, ix, meter, **k: {"qid": q["id"], "status": "not_found", "model_status": "not_found",  # noqa: E731
                                            "answer": "", "value": "", "parsed_value": None, "period": "",
                                            "citations": [], "citations_verified": 0, "retrieved": [], "error": None,
                                            "question": "q"}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(evaluate.golden, "load", return_value=items), \
                mock.patch.object(evaluate.checklist, "by_id", return_value={"a": {"id": "a"}, "b": {"id": "b"}}), \
                mock.patch.object(evaluate, "Index", return_value=None), \
                mock.patch.object(evaluate.answer, "answer_question", side_effect=ans), \
                mock.patch.object(evaluate, "append_changelog") as changelog:
            seen = []
            with mock.patch("sys.stdout"):
                r = evaluate.run(["T"], "m", None, 8, only={"T:b"}, progress=lambda d, n: seen.append((d, n)),
                                 out_dir=Path(tmp), changelog=False, label="spot", workers=1)
            self.assertEqual([x["id"] for x in r["rows"]], ["T:b"])
            self.assertEqual(seen, [(1, 1)])
            changelog.assert_not_called()
            self.assertTrue((Path(tmp) / f"{r['name']}.json").exists())
            self.assertTrue((Path(tmp) / "last_eval_rows.json").exists())
            self.assertEqual(json.loads((Path(tmp) / f"{r['name']}.json").read_text())["metrics"]["accuracy"], 100.0)


class SwitchTest(unittest.TestCase):
    def test_switch_values(self):
        for v, on in (("0", False), ("off", False), ("False", False), ("no", False), ("1", True), ("", True), (None, True)):
            self.assertEqual(devtools.switch_on(v), on, v)


if __name__ == "__main__":
    unittest.main()
