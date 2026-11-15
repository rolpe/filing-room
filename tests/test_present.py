import unittest

from filingroom import llm, present

Q = {"id": "gov_activist", "label": "Activist involvement", "question": "Has the company...?", "answer_type": "text"}
ROW = {"qid": "gov_activist", "status": "answered", "period": "as of October 15, 2025",
       "answer": "Yes. On October 15, 2025, BILL entered into a cooperation agreement with Starboard Value. "
                 "The board grew from 12 to 13 directors.",
       "citations": [{"quote": "on October 15, 2025, we entered into a cooperation agreement", "verified": True},
                     {"quote": "a quote that was not found", "verified": False},
                     {"quote": "increased the size of the Board from 12 to 13 directors", "verified": True}]}
GOOD = {"gist": "Cooperation agreement with Starboard Value, Oct 15, 2025",
        "points": [{"text": "BILL entered into a cooperation agreement with Starboard Value on October 15, 2025.", "cites": [1]},
                   {"text": "The board grew from 12 to 13 directors.", "cites": [3]}],
        "value_label": "Yes"}


def stub(out):
    calls = []

    def complete(model, system, user, schema, meter, effort=None, max_tokens=0):
        calls.append({"model": model, "user": user, "schema": schema, "effort": effort})
        if isinstance(out, Exception):
            raise out
        return out
    complete.calls = calls
    return complete


class PresentTest(unittest.TestCase):
    def test_good_output_is_kept_and_only_verified_quotes_are_sent(self):
        c = stub(GOOD)
        r = present.present_one(Q, ROW, llm.CostMeter(), complete=c)
        self.assertTrue(r["presented"])
        self.assertEqual(r["gist"], GOOD["gist"])
        self.assertEqual(r["points"][1]["cites"], [3])
        self.assertEqual(r["value_label"], "Yes")
        user = c.calls[0]["user"]
        self.assertIn("[1] on October 15", user)
        self.assertIn("[3] increased", user)
        self.assertNotIn("not found", user)
        self.assertEqual(c.calls[0]["model"], present.MODEL)
        self.assertIn("value_label", c.calls[0]["schema"]["properties"])

    def test_numeric_types_get_no_value_label(self):
        c = stub({**GOOD, "value_label": "Yes"})
        r = present.present_one({**Q, "answer_type": "currency"}, ROW, llm.CostMeter(), complete=c)
        self.assertNotIn("value_label", c.calls[0]["schema"]["properties"])
        self.assertEqual(r["value_label"], "")

    def test_guard_rejects_what_cannot_be_repaired_after_one_retry(self):
        cases = [
            {**GOOD, "points": [{"text": "The board grew to 14 directors.", "cites": [3]}]},  # new number
            {**GOOD, "points": [{"text": "Something.", "cites": [2]}]},                         # only an unverified cite
            {**GOOD, "points": [{"text": "Something.", "cites": []}]},                          # no cite
            {**GOOD, "value_label": "Yes with four words"},                                     # label too long
            {**GOOD, "value_label": "13 of 14"},                                                # label number guard
        ]
        for out in cases:
            c = stub(out)
            r = present.present_one(Q, ROW, llm.CostMeter(), complete=c)
            self.assertFalse(r["presented"], out)
            self.assertTrue(r["reason"])
            self.assertTrue(r["retried"])
            self.assertEqual(len(c.calls), 2)
            self.assertIn("Your previous output broke this rule:", c.calls[1]["user"])
            self.assertIn(r["reason"], c.calls[1]["user"])

    def test_repairs_trim_points_drop_stray_cites_and_swap_long_gist(self):
        out = {"gist": " ".join(["word"] * 13),
               "points": [{"text": "BILL entered into a cooperation agreement on October 15, 2025.", "cites": [1, 2, 9]}]
                         + [{"text": "The board grew from 12 to 13 directors.", "cites": [3]}] * 6,
               "value_label": "Yes"}
        c = stub(out)
        r = present.present_one(Q, ROW, llm.CostMeter(), complete=c)
        self.assertTrue(r["presented"])
        self.assertFalse(r["retried"])
        self.assertEqual(len(c.calls), 1)
        self.assertEqual(len(r["points"]), 5)
        self.assertEqual(r["points"][0]["cites"], [1])
        self.assertEqual(r["gist"], "Yes. On October 15, 2025, BILL entered into a cooperation agreement with Starboard Value")
        self.assertEqual(len(r["repairs"]), 3)

    def test_repair_does_not_invent_a_cite(self):
        fixed, done = present.repair({**GOOD, "points": [{"text": "x", "cites": [2]}]}, ROW)
        self.assertEqual(fixed["points"][0]["cites"], [2])  # left for the guard to reject
        self.assertEqual(done, [])

    def test_retry_succeeds_after_a_broken_rule(self):
        outs = iter([{**GOOD, "points": [{"text": "The board grew to 14 directors.", "cites": [3]}]}, GOOD])
        calls = []

        def complete(model, system, user, schema, meter, effort=None, max_tokens=0):
            calls.append(user)
            return next(outs)
        r = present.present_one(Q, ROW, llm.CostMeter(), complete=complete)
        self.assertTrue(r["presented"])
        self.assertTrue(r["retried"])
        self.assertIn("number 14 is not in the answer", calls[1])

    def test_reformatted_numbers_from_the_answer_pass(self):
        row = {**ROW, "answer": "Total revenue was $1,653,160 thousand for FY2026."}
        out = {"gist": "Revenue $1,653,160 thousand in FY2026", "points": [{"text": "Revenue was 1,653,160.", "cites": [1]}],
               "value_label": ""}
        self.assertTrue(present.present_one(Q, row, llm.CostMeter(), complete=stub(out))["presented"])

    def test_fallback_on_model_error_and_for_unanswered(self):
        r = present.present_one(Q, ROW, llm.CostMeter(), complete=stub(llm.LLMError("refusal")))
        self.assertFalse(r["presented"])
        self.assertEqual(r["gist"], "Yes. On October 15, 2025, BILL entered into a cooperation agreement with Starboard Value.")
        self.assertEqual(r["points"], [{"text": ROW["answer"], "cites": [1, 3]}])
        nf = present.present_one(Q, {**ROW, "status": "not_found"}, llm.CostMeter(), complete=stub(GOOD))
        self.assertFalse(nf["presented"])

    def test_present_all_counts_fallbacks_repairs_retries_and_skips_ineligible(self):
        rows = [ROW, {**ROW, "qid": "x"}, {**ROW, "qid": "y"}, {**ROW, "qid": "rev_arr", "status": "not_found"}]
        qs = [Q, {**Q, "id": "x"}, {**Q, "id": "y"}, {**Q, "id": "rev_arr"}]
        bad = {**GOOD, "gist": ""}
        long_gist = {**GOOD, "gist": " ".join(["word"] * 13)}
        outs = iter([GOOD, bad, bad, long_gist])

        def complete(*a, **k):
            return next(outs)
        res = present.present_all(qs, rows, llm.CostMeter(), workers=1, complete=complete)
        self.assertEqual(res["attempted"], 3)
        self.assertEqual(res["fallbacks"], 1)
        self.assertEqual(res["retried"], 1)
        self.assertEqual(res["repaired"], 1)
        self.assertEqual(set(res["items"]), {"gov_activist", "x", "y"})

    def test_first_sentence(self):
        self.assertEqual(present.first_sentence("Revenue was $1.65 billion. It grew 13%."), "Revenue was $1.65 billion.")
        self.assertEqual(present.first_sentence("No. The company does not disclose ARR. More."),
                         "No. The company does not disclose ARR.")


if __name__ == "__main__":
    unittest.main()
