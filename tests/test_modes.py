"""Choosing a mode, and a whole-checklist run in agent mode with a fake model (free)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from filingroom import answer, llm, modes, pipeline
from tests.fixture_corpus import Corpus
from tests.test_agent_graph import FakeModel, answer_turn, draft, search, tool_turn


def nf(messages, tool_choice):
    n = sum(m["role"] == "assistant" for m in messages)
    return tool_turn(search()) if n == 0 else answer_turn(draft("not_found", cites=()))


class ModesTest(unittest.TestCase):
    def test_answerer(self):
        self.assertIs(modes.answerer("pipeline"), answer.answer_question)
        with self.assertRaises(ValueError):
            modes.answerer("pipeline", max_model_calls=3)
        with self.assertRaises(ValueError):
            modes.answerer("chain")
        self.assertEqual(modes.answerer("agent", max_model_calls=3).keywords, {"max_model_calls": 3})
        self.assertEqual(modes.row_mode({}), "pipeline")
        self.assertEqual(modes.row_mode({"mode": "agent"}), "agent")


class RunChecklistTest(unittest.TestCase):
    def setUp(self):
        self.corpus = Corpus().__enter__()
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        # the SEC number check fetches XBRL company facts over the network; not under test here
        self.nc = mock.patch.object(pipeline, "number_check", lambda t, rows: {"checked": 0, "matched": 0, "items": []})
        self.nc.start()

    def tearDown(self):
        self.nc.stop()
        self.tmp.cleanup()
        self.corpus.__exit__(None, None, None)

    def test_agent_run_writes_its_own_run_file(self):
        fake = FakeModel(then=nf)
        path = pipeline.run_checklist("ACME", llm.CostMeter(), out_dir=self.out, workers=3, mode="agent",
                                      agent_opts={"max_model_calls": 4, "call_model": fake})
        self.assertTrue(path.name.endswith("_agent.json"))
        self.assertTrue(path.with_suffix(".md").exists())
        data = json.loads(path.read_text())
        self.assertEqual(data["meta"]["mode"], "agent")
        self.assertEqual(data["meta"]["agent_opts"]["max_model_calls"], 4)
        self.assertEqual({r["mode"] for r in data["answers"]}, {"agent"})
        self.assertEqual({r["status"] for r in data["answers"]}, {"not_found"})
        self.assertEqual(len(fake.calls), 2 * len(data["answers"]))

    def test_pipeline_run_file_keeps_its_shape_and_resume_ignores_other_modes(self):
        partial = self.out / "answers.partial.jsonl"
        agent_row = {"qid": "rev_total", "status": "answered", "mode": "agent"}
        partial.write_text(json.dumps(agent_row) + "\n")
        out = json.loads(json.dumps(draft("not_found", cites=())))
        with mock.patch.object(llm, "complete_json", lambda *a, **k: json.loads(json.dumps(out))):
            path = pipeline.run_checklist("ACME", llm.CostMeter(), out_dir=self.out, workers=3, partial=partial)
        data = json.loads(path.read_text())
        self.assertFalse(path.stem.endswith("_agent"))
        self.assertEqual(set(data["meta"]), {"timestamp", "model", "cost_usd", "n_filings", "usage", "number_check",
                                             "reused_answers"})
        self.assertEqual(data["meta"]["reused_answers"], 0)  # the agent row was not reused
        self.assertTrue(all("mode" not in r for r in data["answers"]))


if __name__ == "__main__":
    unittest.main()
