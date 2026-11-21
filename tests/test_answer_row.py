"""Characterisation of answer.answer_question: the exact row the pipeline builds from a given model reply.

Written before build_row was extracted from answer_question, so the extraction is proven behaviour-preserving.
No API calls: the model is stubbed, and the index is a few synthetic chunks in a temporary folder.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from filingroom import answer, config, llm
from filingroom.index import Index

T = "ACME"
URL = "https://www.sec.gov/Archives/edgar/data/1/acme-10k.htm"
URL_Q = "https://www.sec.gov/Archives/edgar/data/1/acme-10q.htm"


def _chunk(doc, form, period, url, sec, n, text, topic="mdna", sub="Results of Operations"):
    return {"chunk_id": f"{doc}#{sec}#{n:03d}", "doc_id": doc, "ticker": T, "form": form, "period": period,
            "filing_date": "2026-08-20" if form == "10-K" else "2026-11-05", "section": sec, "topic": topic,
            "heading": "Item 7. Management's Discussion and Analysis", "subheading": sub, "url": url, "text": text}


K = "ACME_10-K_FY2026"
Q10 = "ACME_10-Q_Q1FY2027"
CHUNKS = [
    _chunk(K, "10-K", "FY2026", URL, "item7", 0, "Overview. Acme sells widgets to small businesses."),
    _chunk(K, "10-K", "FY2026", URL, "item7", 1,
           "Total revenue was $1,234.5 million for fiscal 2026, an increase of 12% from fiscal 2025."),
    _chunk(K, "10-K", "FY2026", URL, "item7", 2,
           "[TABLE]\nItem | 2026 | 2025\nTotal revenue | $ 1,234.5 | $ 1,102.2\n[/TABLE]"),
    _chunk(K, "10-K", "FY2026", URL, "item7", 3, "Liquidity. Cash and equivalents were $400 million."),
    _chunk(Q10, "10-Q", "Q1 FY2027", URL_Q, "partI-item2", 0, "Total revenue for the quarter was $330 million."),
]
CO = {"ticker": T, "name": "Acme Corp", "fiscal_year_end": "0630", "split": "tune"}
P = {"latest_periodic": "Q1 FY2027", "latest_periodic_doc": Q10, "latest_periodic_filed": "2026-11-05",
     "latest_release_filed": "2026-11-04", "latest_fy": "FY2026", "latest_fy_end": "2026-06-30", "latest_fy_doc": K,
     "prior_fy": "FY2025", "prior_fy_end": "2025-06-30", "latest_release": "Q1 FY2027",
     "latest_release_doc": "ACME_8-K_Q1FY2027", "latest_proxy": "FY2026", "latest_proxy_doc": "ACME_DEF14A_FY2026",
     "latest_filing": "2026-11-05"}
Q = {"id": "rev_total", "category": "Financials", "question": "What was total revenue?", "answer_type": "currency",
     "period": "latest_fy", "where": {"forms": ["10-K"], "topics": ["mdna"]}, "search": "total revenue fiscal"}


def reply(status="answered", citations=(), value="1234.5"):
    return {"status": status, "answer": "Total revenue was $1,234.5 million." if status == "answered" else "",
            "value": value if status == "answered" else "", "unit": "USD" if status == "answered" else "",
            "period": "FY2026" if status == "answered" else "", "citations": [dict(c) for c in citations],
            "confidence": "high"}


class AnswerRowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / f"{T}.jsonl").write_text("".join(json.dumps(c) + "\n" for c in CHUNKS))
        self.patches = [mock.patch.object(config, "INDEX", d),
                        mock.patch.object(config, "company", lambda t: CO),
                        mock.patch("filingroom.checklist.periods", lambda t: P)]
        for p in self.patches:
            p.start()
        self.ix = Index(T)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def run_with(self, out):
        calls = []

        def fake(model, system, user, schema, meter, effort=None, max_tokens=16000):
            calls.append({"model": model, "system": system, "user": user, "schema": schema, "effort": effort})
            if isinstance(out, Exception):
                raise out
            return json.loads(json.dumps(out))  # a fresh dict, as json.loads gives the real call

        with mock.patch.object(llm, "complete_json", fake), mock.patch("filingroom.answer.time.time", side_effect=[100.0, 102.34]):
            row = answer.answer_question(T, Q, self.ix, llm.CostMeter())
        return row, calls

    # The row keys and their order: present.py, memo.py, findings.py, the judge and the run files all read these.
    KEYS = ["qid", "ticker", "question", "category", "status", "model_status", "answer", "value", "parsed_value",
            "unit", "period", "confidence", "citations", "citations_verified", "retrieved", "model", "effort", "k",
            "expand", "seconds", "error"]
    RETRIEVED = [f"{K}#item7#000", f"{K}#item7#001", f"{K}#item7#002", f"{K}#item7#003"]  # the 10-Q is filtered out

    def base(self, **kw):
        row = {"qid": "rev_total", "ticker": T, "question": "What was total revenue?", "category": "Financials",
               "status": "answered", "model_status": "answered", "answer": "Total revenue was $1,234.5 million.",
               "value": "1234.5", "parsed_value": 1234.5, "unit": "USD", "period": "FY2026", "confidence": "high",
               "citations": [], "citations_verified": 0, "retrieved": self.RETRIEVED, "model": "claude-sonnet-5",
               "effort": "medium", "k": 8, "expand": 2, "seconds": 2.3, "error": None}
        row.update(kw)
        return row

    def test_prompt_sent_to_the_model(self):
        _, calls = self.run_with(reply("not_found"))
        self.assertEqual(len(calls), 1)
        c = calls[0]
        self.assertEqual((c["model"], c["effort"]), ("claude-sonnet-5", "medium"))
        self.assertIs(c["schema"], answer.ANSWER_SCHEMA)
        self.assertEqual(c["system"], answer.load_prompt("answer.md"))
        self.assertTrue(c["user"].startswith(
            '<question id="rev_total">\nCompany: Acme Corp (ticker ACME); fiscal year ends 06/30.\n'
            "Question: What was total revenue?\nAnswer type: currency\n"
            f"Target period: fiscal year FY2026 (ended 2026-06-30), the most recent 10-K ({K})\n"
            "</question>\n\n<excerpts>\n"))
        self.assertTrue(c["user"].endswith("\n</excerpts>"))
        order = [line.split('"')[1] for line in c["user"].splitlines() if line.startswith("<excerpt ")]
        self.assertEqual(order, self.RETRIEVED)

    def test_verified_unverified_and_unknown_citations(self):
        cites = [{"chunk_id": f"{K}#item7#001", "quote": "Total revenue was $1,234.5 million for fiscal 2026"},
                 {"chunk_id": f"{K}#item7#002", "quote": "Total revenue | 1,234.5 | ... 1,102.2"},
                 {"chunk_id": f"{K}#item7#003", "quote": "Total revenue was $9 billion"},
                 {"chunk_id": "NOPE#item7#000", "quote": "anything"}]
        row, _ = self.run_with(reply("answered", cites))
        sec = "Item 7. Management's Discussion and Analysis"
        want = self.base(citations_verified=2, citations=[
            {**cites[0], "verified": True, "url": URL, "doc_id": K, "section": sec},
            {**cites[1], "verified": True, "url": URL, "doc_id": K, "section": sec},
            {**cites[2], "verified": False, "url": URL, "doc_id": K, "section": sec},
            {**cites[3], "verified": False}])
        self.assertEqual(row, want)
        self.assertEqual(list(row), self.KEYS)
        self.assertEqual([list(c) for c in row["citations"]],
                         [["chunk_id", "quote", "verified", "url", "doc_id", "section"]] * 3
                         + [["chunk_id", "quote", "verified"]])

    def test_answered_with_no_verified_quote_is_unsupported(self):
        cites = [{"chunk_id": f"{K}#item7#001", "quote": "Total revenue was $2 billion"}]
        row, _ = self.run_with(reply("answered", cites))
        self.assertEqual(row, self.base(status="unsupported", citations=[
            {**cites[0], "verified": False, "url": URL, "doc_id": K,
             "section": "Item 7. Management's Discussion and Analysis"}]))

    def test_not_found_passes_through(self):
        row, _ = self.run_with(reply("not_found"))
        self.assertEqual(row, self.base(status="not_found", model_status="not_found", answer="", value="",
                                        parsed_value=None, unit="", period=""))

    def test_unparseable_value(self):
        cites = [{"chunk_id": f"{K}#item7#001", "quote": "an increase of 12%"}]
        row, _ = self.run_with(reply("answered", cites, value="about twelve"))
        self.assertIsNone(row["parsed_value"])
        self.assertEqual(row["citations_verified"], 1)

    def test_model_error_gives_an_error_row(self):
        row, _ = self.run_with(llm.LLMError("refusal: cyber"))
        self.assertEqual(row, self.base(status="error", model_status="error", answer="", value="", parsed_value=None,
                                        unit="", period="", confidence="low", error="refusal: cyber"))
        self.assertEqual(list(row), self.KEYS)


    def test_build_row_directly_with_agent_style_arguments(self):
        out = reply("answered", [{"chunk_id": f"{K}#item7#001", "quote": "an increase of 12%"}])
        with mock.patch("filingroom.answer.time.time", return_value=107.25):
            row = answer.build_row(T, Q, self.ix, out, retrieved=[f"{K}#item7#001"], model="claude-sonnet-5",
                                   effort="medium", k=None, expand=None, started=100.0, error=None)
        self.assertEqual(row, self.base(citations=out["citations"], citations_verified=1,
                                        retrieved=[f"{K}#item7#001"], k=None, expand=None, seconds=7.2))
        self.assertIs(row["citations"], out["citations"])  # annotated in place, as before the extraction
        self.assertTrue(row["citations"][0]["verified"])


if __name__ == "__main__":
    unittest.main()
