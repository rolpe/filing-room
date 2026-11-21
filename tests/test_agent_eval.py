"""Agent-mode evals go to results/agent/ with their own changelog; compare() pairs two results files. Free."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from filingroom import config, devtools, evaluate, golden, llm
from tests.fixture_corpus import Corpus
from tests.test_agent_graph import REAL, FakeModel, answer_turn, draft, search, tool_turn

ITEMS = [{"id": "ACME:rev_total", "ticker": "ACME", "qid": "rev_total", "grade": "numeric",
          "expected": {"value": 1234500000, "unit": "USD"}, "source": {"method": "xbrl", "concepts": ["Rev"]}},
         {"id": "ACME:na_cac", "ticker": "ACME", "qid": "na_cac", "grade": "abstain",
          "expected": {"text": "Not disclosed."}, "source": {}}]


def script(messages, tool_choice):
    q = messages[0]["content"]
    if sum(m["role"] == "assistant" for m in messages) == 0:
        return tool_turn(search())
    if "na_cac" in q:
        return answer_turn(draft("not_found", cites=()))
    return answer_turn(draft(value="1,234,500,000"))


class AgentEvalTest(unittest.TestCase):
    def setUp(self):
        self.corpus = Corpus().__enter__()
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.results, self.agent_dir = d / "results", d / "results" / "agent"
        self.cl, self.acl = d / "CHANGELOG-evals.md", d / "CHANGELOG-agent-evals.md"
        self.patches = [mock.patch.object(config, "RESULTS", self.results), mock.patch.object(config, "RUNS", d / "runs"),
                        mock.patch.object(evaluate, "AGENT_RESULTS", self.agent_dir),
                        mock.patch.object(evaluate, "CHANGELOG", self.cl),
                        mock.patch.object(evaluate, "AGENT_CHANGELOG", self.acl),
                        mock.patch.object(golden, "load", lambda tickers: [dict(i) for i in ITEMS])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()
        self.corpus.__exit__(None, None, None)

    def test_agent_eval_writes_only_to_the_agent_area(self):
        r = evaluate.run(["ACME"], "claude-sonnet-5", "medium", 8, 2, use_judge=False, label="t", workers=2,
                         only={"ACME:rev_total", "ACME:na_cac"}, mode="agent",
                         agent_opts={"max_model_calls": 4, "call_model": FakeModel(then=script)})
        self.assertEqual([p.name for p in self.agent_dir.glob("*.json")], [f"{r['name']}.json"])
        self.assertEqual(list(self.results.glob("*.json")), [])
        self.assertFalse(self.cl.exists())
        self.assertIn("(subset)", self.acl.read_text())
        saved = json.loads((self.agent_dir / f"{r['name']}.json").read_text())
        self.assertEqual((saved["mode"], saved["agent_opts"], saved["only"]),
                         ("agent", {"max_model_calls": 4}, ["ACME:na_cac", "ACME:rev_total"]))
        self.assertEqual((saved["k"], saved["expand"]), (None, None))
        self.assertEqual(saved["metrics"]["accuracy"], 100.0)
        a = saved["metrics"]["agent"]
        self.assertEqual((a["n"], a["model_calls_mean"], a["tool_calls_mean"], a["hit_limit"]), (2, 2, 1, 0))
        self.assertTrue((config.RUNS / "last_agent_eval_rows.json").exists())
        self.assertFalse((config.RUNS / "last_eval_rows.json").exists())

    def test_pipeline_eval_is_unchanged(self):
        out = draft(cites=[REAL], value="1,234,500,000")
        with mock.patch.object(llm, "complete_json", lambda *a, **k: json.loads(json.dumps(out))):
            r = evaluate.run(["ACME"], "claude-sonnet-5", "medium", 8, 2, use_judge=False, label="p", workers=2)
        self.assertEqual(set(r) - {"name"}, {"timestamp", "label", "note", "tickers", "model", "effort", "k", "expand",
                                              "judge_model", "metrics", "usage", "rows"})
        self.assertNotIn("agent", r["metrics"])
        self.assertTrue(self.cl.exists())
        self.assertFalse(self.acl.exists())
        self.assertFalse(self.agent_dir.exists())
        self.assertTrue(all("mode" not in row for row in r["rows"]))


def row(i, correct, grade="numeric", status="answered", agent=None, seconds=4.0):
    r = {"id": i, "ticker": "ACME", "grade": grade, "correct": correct, "status": status, "model_status": status,
         "citations_verified": 1 if status == "answered" else 0, "citations": [], "supported": "yes",
         "value_in_context": None, "seconds": seconds, "confidence": "high"}
    if agent:
        r["mode"], r["agent"] = "agent", agent
    return r


def ag(calls=3, tools=2, stop="model_done", usd=0.04):
    return {"model_calls": calls, "tool_calls": tools, "tokens": 20000, "usd": usd, "stop": stop, "repairs": 0,
            "cited_unseen": [], "trace": []}


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.p = [mock.patch.object(devtools, "_golden_by_id", lambda: {}),
                  mock.patch.object(devtools, "_docs_by_ticker", lambda t: {})]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_compare_pairs_items_and_counts_flips(self):
        base = {"timestamp": "2026-09-27_1616", "label": "recency", "tickers": ["ACME"],
                "metrics": {"cost_usd": {"answer": 0.12, "judge": 0.05}},
                "rows": [row("a", True), row("b", False), row("c", True), row("d", True, "abstain", "not_found"),
                         row("only_base", True)]}
        other = {"timestamp": "2026-11-21_1700", "label": "agent20", "tickers": ["ACME"], "mode": "agent",
                 "rows": [row("a", True, agent=ag(), seconds=2.0), row("b", True, agent=ag(usd=0.06), seconds=9.0),
                          row("c", False, agent=ag(6, 5, "step_limit", 0.08), seconds=20.0),
                          row("d", True, "abstain", "not_found", agent=ag(2, 1, usd=0.02), seconds=5.0)]}
        c = evaluate.compare(base, other)
        self.assertEqual((c["n"], c["ids"]), (4, ["a", "b", "c", "d"]))
        b, o = c["sides"]["base"], c["sides"]["other"]
        self.assertEqual((b["accuracy"]["k"], b["accuracy"]["n"], o["accuracy"]["k"]), (3, 4, 3))
        self.assertEqual((c["flips"]["better"], c["flips"]["worse"], c["flips"]["p"]), (["b"], ["c"], 1.0))
        self.assertEqual(b["usd_per_question"], 0.024)  # run average: 0.12 over its 5 items
        self.assertEqual(o["usd_per_question"], 0.05)   # (0.04 + 0.06 + 0.08 + 0.02) / 4
        self.assertEqual((b["model_calls"], b["tool_calls"], o["hit_limit"]), (1, 0, 1))
        self.assertEqual(o["model_calls"], 3.5)
        self.assertEqual(o["latency"], {"mean": 9.0, "median": 5.0, "p90": 20.0})
        self.assertEqual(o["by_grade"]["abstain"]["k"], 1)
        md = evaluate.compare_md(c)
        self.assertIn("| Accuracy | 75.0% (3/4; ", md)
        self.assertIn("Right only in other: b", md)
        self.assertIn("Right only in base: c", md)
        self.assertIn("| Questions that hit a limit | 0 | 1 |", md)

    def test_percentile_and_latency(self):
        self.assertEqual(evaluate._pctile(list(range(1, 11)), 0.9), 9)
        self.assertEqual(evaluate._pctile([3, 1, 2], 0.5), 2)
        self.assertIsNone(evaluate._pctile([], 0.5))
        self.assertEqual(evaluate.latency([]), {"mean": None, "median": None, "p90": None})


if __name__ == "__main__":
    unittest.main()
