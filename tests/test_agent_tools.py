"""Agent mode's read-only tools: plain functions over a synthetic index. Free and deterministic."""

import unittest

from filingroom import answer
from filingroom.agent import tools
from tests.fixture_corpus import CHUNKS, ER, K25, K26, MANIFEST, P, PX, Q1, Corpus


def ids_in(text):
    return [line.split('"')[1] for line in text.splitlines() if line.startswith("<excerpt ")]


class ToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = Corpus().__enter__()
        cls.ix = cls.corpus.ix

    @classmethod
    def tearDownClass(cls):
        cls.corpus.__exit__(None, None, None)

    def search(self, seen=(), **args):
        return tools.run("search_filings", args, ix=self.ix, manifest=MANIFEST, P=P, seen=set(seen))

    def test_valid_values_come_from_the_index(self):
        vv = tools.valid_values(self.ix)
        self.assertEqual(vv["forms"], ["10-K", "10-Q", "8-K", "DEF 14A"])
        self.assertEqual(vv["topics"], ["mdna", "press_release", "proxy", "risk_factors"])
        self.assertEqual(vv["periods"], ["2026 annual meeting", "FY2025", "FY2026", "Q1 FY2027"])
        spec = {s["name"]: s for s in tools.specs(self.ix)}
        self.assertEqual(set(spec), {"search_filings", "get_chunk", "list_filings"})
        self.assertEqual(spec["search_filings"]["input_schema"]["properties"]["forms"]["items"]["enum"], vv["forms"])
        self.assertNotIn("ticker", str(spec))  # the company is bound in code, never a parameter

    def test_search_renders_chunks_in_the_pipeline_excerpt_format(self):
        r = self.search(query="total revenue", k=2)
        self.assertFalse(r.is_error)
        self.assertEqual(len(r.shown), 2)
        self.assertEqual(r.shown, r.refs)
        for cid in r.shown:
            self.assertIn(answer._excerpt(self.ix.by_id[cid]), r.text)
        self.assertIn("Result 1 (score ", r.text)

    def test_forms_filter_excludes_other_forms(self):
        r = self.search(query="total revenue", forms=["10-Q"])
        self.assertEqual(r.shown, [f"{Q1}#partI-item2#000"])
        r = self.search(query="revenue", forms="8-K")  # a bare string is accepted as a one-item list
        self.assertEqual(r.shown, [f"{ER}#ex99#000"])

    def test_topic_and_period_boosts_reorder(self):
        plain = self.search(query="total revenue fiscal", k=8).shown
        by_period = self.search(query="total revenue fiscal", k=8, periods=["FY2025"]).shown
        self.assertNotEqual(plain[0], f"{K25}#item7#000")
        self.assertEqual(by_period[0], f"{K25}#item7#000")
        self.assertEqual(sorted(plain), sorted(by_period))  # a boost reorders, never filters
        by_topic = self.search(query="revenue", k=8, topics=["press_release"]).shown
        self.assertEqual(by_topic[0], f"{ER}#ex99#000")

    def test_k_is_clamped(self):
        self.assertEqual(len(self.search(query="revenue", k=0).shown), 1)
        self.assertLessEqual(len(self.search(query="revenue", k=50).shown), tools.K_MAX)
        self.assertEqual(len(self.search(query="revenue").shown), tools.K_DEFAULT)
        self.assertTrue(self.search(query="revenue", k="many").is_error)

    def test_bad_filters_are_error_results_listing_valid_values(self):
        r = self.search(query="revenue", periods=["FY 2026"])
        self.assertTrue(r.is_error)
        self.assertIn("'FY 2026'", r.text)
        self.assertIn("FY2026", r.text)
        for args in [dict(forms=["10-KT"]), dict(topics=["revenue"]), dict(forms=[3]), dict(query="")]:
            r = self.search(**{"query": "revenue", **args})
            self.assertTrue(r.is_error, args)
            self.assertEqual(r.shown, [])

    def test_no_hits_is_not_an_error(self):
        r = self.search(query="zebra")
        self.assertFalse(r.is_error)
        self.assertEqual(r.shown, [])
        self.assertIn("No results", r.text)

    def test_already_shown_chunk_is_returned_by_id_only(self):
        first = self.search(query="total revenue", k=3)
        again = self.search(seen=first.shown, query="total revenue", k=4)
        self.assertEqual(again.refs[:3], first.shown)
        self.assertEqual(len(again.shown), 1)
        self.assertNotIn(again.shown[0], first.shown)
        for cid in first.shown:
            self.assertIn(f"chunk {cid} was already shown", again.text)
            self.assertNotIn(self.ix.by_id[cid]["text"], again.text)

    def test_get_chunk_with_neighbours_in_reading_order(self):
        r = tools.run("get_chunk", {"chunk_id": f"{K26}#item7#002"}, ix=self.ix, manifest=MANIFEST, P=P, seen=set())
        self.assertEqual(r.shown, [f"{K26}#item7#001", f"{K26}#item7#002", f"{K26}#item7#003"])
        self.assertEqual(ids_in(r.text), r.shown)
        r = tools.run("get_chunk", {"chunk_id": f"{K26}#item7#000", "neighbors": 0}, ix=self.ix, manifest=MANIFEST,
                      P=P, seen=set())
        self.assertEqual(r.shown, [f"{K26}#item7#000"])
        r = tools.run("get_chunk", {"chunk_id": f"{K26}#item7#003"}, ix=self.ix, manifest=MANIFEST, P=P,
                      seen={f"{K26}#item7#002"})
        self.assertEqual(r.refs, [f"{K26}#item7#002", f"{K26}#item7#003"])  # last in its section: no next
        self.assertEqual(r.shown, [f"{K26}#item7#003"])

    def test_get_chunk_errors(self):
        for args in [{"chunk_id": "NOPE#x#000"}, {}, {"chunk_id": f"{K26}#item7#000", "neighbors": 2},
                     {"chunk_id": f"{K26}#item7#000", "neighbors": True}]:
            r = tools.run("get_chunk", args, ix=self.ix, manifest=MANIFEST, P=P, seen=set())
            self.assertTrue(r.is_error, args)

    def test_list_filings_matches_the_manifest(self):
        r = tools.run("list_filings", {}, ix=self.ix, manifest=MANIFEST, P=P, seen=set())
        self.assertFalse(r.is_error)
        lines = [l for l in r.text.splitlines() if l.startswith("- ACME_")]
        self.assertEqual([l.split(":")[0][2:] for l in lines], [Q1, ER, PX, K26, K25])  # newest first
        self.assertIn("item7 (4), item1a (1)", next(l for l in lines if l.startswith(f"- {K26}")))
        self.assertIn(f"latest fiscal year: FY2026 (ended 2026-06-30), {K26}", r.text)
        self.assertIn("periods: 2026 annual meeting, FY2025, FY2026, Q1 FY2027", r.text)
        self.assertEqual(r.shown, [])

    def test_unknown_tool_and_bad_arguments(self):
        self.assertTrue(tools.run("fetch_url", {}, ix=self.ix, manifest=MANIFEST, P=P, seen=set()).is_error)
        self.assertTrue(tools.run("search_filings", "revenue", ix=self.ix, manifest=MANIFEST, P=P, seen=set()).is_error)

    def test_tools_do_not_mutate_the_callers_seen_set(self):
        seen = {CHUNKS[0]["chunk_id"]}
        r = tools.run("search_filings", {"query": "revenue", "k": 8}, ix=self.ix, manifest=MANIFEST, P=P, seen=seen)
        self.assertGreater(len(r.shown), 1)
        self.assertEqual(seen, {CHUNKS[0]["chunk_id"]})


if __name__ == "__main__":
    unittest.main()
