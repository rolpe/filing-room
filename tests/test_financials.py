import unittest

from filingroom import financials

QS = [
    {"id": "rev_total", "xbrl": {"concepts": ["Revenues"], "kind": "duration"}},
    {"id": "gm_gross_profit", "xbrl": {"concepts": ["GrossProfit"], "kind": "duration"}},
    {"id": "op_income", "xbrl": {"concepts": ["OperatingIncomeLoss"], "kind": "duration"}},
    {"id": "net_income", "xbrl": {"concepts": ["NetIncomeLoss"], "kind": "duration"}},
    {"id": "cf_ocf", "xbrl": {"concepts": ["NetCashProvidedByUsedInOperatingActivities"], "kind": "duration"}},
    {"id": "cf_capex", "xbrl": {"concepts": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToDevelopSoftware"],
                                "kind": "duration", "combine": "sum"}},
    {"id": "bs_cash", "xbrl": {"concepts": ["CashAndCashEquivalentsAtCarryingValue"], "kind": "instant"}},
]


def fact(val, end, start=None, form="10-K", filed="2026-08-20", accn="0000000000-26-000001"):
    r = {"val": val, "end": end, "form": form, "filed": filed, "accn": accn}
    if start:
        r["start"] = start
    return r


def facts(concepts):
    return {"facts": {"us-gaap": {c: {"units": {"USD": rows}} for c, rows in concepts.items()}}}


class FinancialsTest(unittest.TestCase):
    def test_table_values_margins_fcf_and_as_reported(self):
        f = facts({
            "Revenues": [fact(1000, "2026-06-30", "2025-07-01", accn="A26"),
                         fact(800, "2025-06-30", "2024-07-01", filed="2025-08-20", accn="A25"),
                         fact(810, "2025-06-30", "2024-07-01", filed="2026-08-20", accn="A26"),  # restated later
                         fact(250, "2026-06-30", "2026-04-01", form="10-K"),                    # Q4 only: not annual
                         fact(900, "2025-09-30", "2024-10-01", form="10-Q")],
            "GrossProfit": [fact(800, "2026-06-30", "2025-07-01")],
            "OperatingIncomeLoss": [fact(-50, "2026-06-30", "2025-07-01")],
            "NetCashProvidedByUsedInOperatingActivities": [fact(300, "2026-06-30", "2025-07-01")],
            "PaymentsToAcquirePropertyPlantAndEquipment": [fact(40, "2026-06-30", "2025-07-01")],
            "PaymentsToDevelopSoftware": [fact(10, "2026-06-30", "2025-07-01")],
            "CashAndCashEquivalentsAtCarryingValue": [fact(500, "2026-06-30")],
        })
        t = financials.table(f, "0630", 123, QS)
        self.assertEqual([y["fy"] for y in t["years"]], ["FY2026", "FY2025"])
        self.assertIn("/123/A26/A26-index.htm", t["years"][0]["url"])
        self.assertIn("/A25/", t["years"][1]["url"])
        v = {r["key"]: r["values"] for r in t["rows"]}
        self.assertEqual(v["revenue"], [1000, 800])           # FY2025 as originally reported, not the restatement
        self.assertEqual(v["growth"], [25.0, None])
        self.assertEqual(v["gross_margin"], [80.0, None])
        self.assertEqual(v["op_margin"], [-5.0, None])
        self.assertEqual(v["capex"], [50, None])               # combine: sum
        self.assertEqual(v["fcf"], [250, None])
        self.assertEqual(v["cash"], [500, None])
        self.assertNotIn("net_income", v)                      # missing concept: row omitted

    def test_52_53_week_years_ending_off_the_nominal_date(self):
        # FYE nominally Dec 31; a 52/53-week retailer-style calendar ends on the Saturday nearest it.
        f = facts({"Revenues": [fact(100, "2027-01-02", "2026-01-04", accn="B27"),   # 52 weeks + 1 day into Jan
                                fact(90, "2026-01-03", "2024-12-29", accn="B26"),    # 53 weeks
                                fact(80, "2024-12-28", "2023-12-31", accn="B25")]})
        t = financials.table(f, "1231", 1, QS)
        self.assertEqual([y["fy"] for y in t["years"]], ["FY2026", "FY2025", "FY2024"])
        self.assertEqual(t["rows"][0]["values"], [100, 90, 80])
        # More than 10 days off the year-end is not this company's fiscal year.
        self.assertIsNone(financials._nominal_end(financials._d("2026-01-20"), "1231"))

    def test_latest_and_labels(self):
        f = facts({"Revenues": [fact(1000, "2026-06-30", "2025-07-01")]})
        latest = financials.latest(financials.table(f, "0630", 1, QS))
        self.assertEqual((latest["fy"], latest["revenue"]), ("FY2026", 1000))
        self.assertEqual(financials.fye_label("0630"), "Jun 30")
        self.assertEqual(financials.table(facts({}), "0630", 1, QS), {"years": [], "rows": []})


if __name__ == "__main__":
    unittest.main()
