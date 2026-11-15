import unittest

from filingroom.findings import derive_status


def row(status="answered", verified=(True,), confidence="high"):
    return {"status": status, "confidence": confidence,
            "citations": [{"quote": f"q{i}", "verified": v} for i, v in enumerate(verified)]}


class StatusTest(unittest.TestCase):
    def test_verified_when_every_quote_checks_out(self):
        s = derive_status(row(verified=(True, True)))
        self.assertEqual(s["status"], "verified")
        self.assertEqual(s["reasons"], [])

    def test_not_found_is_not_disclosed(self):
        self.assertEqual(derive_status(row("not_found", verified=()))["status"], "not_disclosed")

    def test_any_unverified_quote_means_review(self):
        s = derive_status(row(verified=(True, False, True)))
        self.assertEqual(s["status"], "review")
        self.assertIn("1 of 3 quotes not found in the filing", s["reasons"])

    def test_unsupported_error_low_confidence_and_sec_mismatch(self):
        self.assertEqual(derive_status(row("unsupported", verified=(False,)))["status"], "review")
        self.assertEqual(derive_status(row("error", verified=()))["status"], "review")
        self.assertIn("Low confidence", derive_status(row(confidence="low"))["reasons"])
        s = derive_status(row(), sec={"match": False})
        self.assertEqual(s["status"], "review")
        self.assertIn("Differs from SEC structured data", s["reasons"])
        self.assertEqual(derive_status(row(), sec={"match": True})["status"], "verified")

    def test_reviewed_clears_review_but_keeps_reasons(self):
        s = derive_status(row(verified=(True, False)), ann={"reviewed_at": "2026-11-15T10:00:00"})
        self.assertEqual(s["status"], "verified")
        self.assertEqual(s["reviewed_at"], "2026-11-15T10:00:00")
        self.assertIn("1 of 2 quotes not found in the filing", s["reasons"])

    def test_flag_forces_review_and_wins_over_reviewed(self):
        s = derive_status(row(), ann={"flagged": True})
        self.assertEqual(s["status"], "review")
        self.assertEqual(s["reasons"][0], "Flagged for review")
        s = derive_status(row(verified=(False, True)), ann={"flagged": True, "reviewed_at": "2026-11-15"})
        self.assertEqual(s["status"], "review")
        self.assertIsNone(s["reviewed_at"])
        self.assertEqual(derive_status(row("not_found", verified=()), ann={"flagged": True})["status"], "review")

    def test_reviewed_does_not_change_a_clean_or_missing_finding(self):
        self.assertEqual(derive_status(row(), ann={"reviewed_at": "x"})["reviewed_at"], None)
        self.assertEqual(derive_status(None)["status"], "review")


if __name__ == "__main__":
    unittest.main()
