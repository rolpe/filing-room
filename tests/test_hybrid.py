"""Hybrid mode: the pipeline first, agent mode only on a non-answer. Scripted fake models, free."""

import contextlib
import inspect
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from filingroom import agent, answer, cli, config, devtools, evaluate, golden, hybrid, llm, modes, pipeline
from filingroom.agent import prompts
from tests.fixture_corpus import P, Corpus
from tests.test_agent_eval import ITEMS, ag, row, script
from tests.test_agent_graph import REAL, Q, FakeModel, answer_turn, draft, search, tool_turn

FABRICATED = (REAL[0], "Total revenue was $9,999 million for fiscal 2026")
NF = draft("not_found", cites=())

# Every test here uses scripted models; this makes sure none of them could reach the real API.
_no_network = mock.patch.object(llm, "client", side_effect=AssertionError("a test reached the Anthropic client"))


def setUpModule():
    _no_network.start()


def tearDownModule():
    _no_network.stop()


class Pipeline:
    """Stands in for llm.complete_json: a scripted answer (a dict, a function of the user message, or an exception
    to raise), copied on every call. Records the meter it was given."""

    def __init__(self, out, sleep=0.0):
        self.out, self.sleep, self.meters = out, sleep, []

    def __call__(self, model, system, user, schema, meter, effort=None, **kw):
        self.meters.append(meter)
        time.sleep(self.sleep)
        if isinstance(self.out, BaseException):
            raise self.out
        return json.loads(json.dumps(self.out(user) if callable(self.out) else self.out))


def recording(fake, meters):
    """call_model that notes the meter it was given, then plays `fake`."""
    def call(model, system, messages, tools, meter, **kw):
        meters.append(meter)
        return fake(model, system, messages, tools, meter, **kw)
    return call


def slow(turn, seconds=0.12):
    return lambda messages, tool_choice: (time.sleep(seconds), turn)[1]


class HybridAnswerTest(unittest.TestCase):
    def setUp(self):
        self.corpus = Corpus().__enter__()
        self.ix = self.corpus.ix

    def tearDown(self):
        self.corpus.__exit__(None, None, None)

    def ask(self, pipe_out, fake=None, meter=None, sleep=0.0, **agent_opts):
        stub = Pipeline(pipe_out, sleep)
        with mock.patch.object(llm, "complete_json", stub):
            r = hybrid.answer_question("ACME", Q, self.ix, meter or llm.CostMeter(), call_model=fake, **agent_opts)
        return r, stub

    def pipeline_row(self, pipe_out):
        with mock.patch.object(llm, "complete_json", Pipeline(pipe_out)):
            return answer.answer_question("ACME", Q, self.ix, llm.CostMeter())

    def assert_pipeline_shape(self, r, pipe):
        self.assertTrue(set(pipe) <= set(r))
        for k, v in pipe.items():
            if k in ("k", "expand") and r[k] is None:
                continue  # an agent row's retrieval settings, as in agent mode
            if v is not None and r[k] is not None:
                self.assertIs(type(r[k]), type(v), k)
        json.dumps(r)  # run files are JSON

    def test_a_pipeline_answer_is_kept_and_the_agent_never_runs(self):
        fake = FakeModel()
        r, stub = self.ask(draft(), fake)
        pipe = self.pipeline_row(draft())
        self.assertEqual(fake.calls, [])
        self.assertEqual(len(stub.meters), 1)
        self.assertEqual(set(r) - set(pipe), {"mode", "hybrid"})
        self.assertEqual(list(r)[:len(pipe)], list(pipe))
        drop = lambda d: {k: v for k, v in d.items() if k not in ("seconds", "mode", "hybrid")}
        self.assertEqual(drop(r), drop(pipe))
        self.assertEqual(r["mode"], "hybrid")
        self.assertEqual(r["hybrid"], {"escalated": False, "pipeline_status": "answered",
                                       "pipeline_seconds": r["seconds"]})
        self.assertNotIn("agent", r)
        self.assert_pipeline_shape(r, pipe)

    def test_not_found_escalates_and_the_agent_answer_replaces_it(self):
        meter, meters = llm.CostMeter(), []
        fake = FakeModel([slow(tool_turn(search())), answer_turn(draft())])
        r, stub = self.ask(NF, recording(fake, meters), meter=meter, sleep=0.12)
        self.assertEqual((r["status"], r["mode"], r["citations_verified"]), ("answered", "hybrid", 1))
        self.assertEqual((r["k"], r["expand"]), (None, None))  # the agent's row
        self.assertIn(REAL[0], r["retrieved"])
        self.assertEqual((r["agent"]["model_calls"], r["agent"]["tool_calls"], r["agent"]["stop"]),
                         (2, 1, "model_done"))
        h = r["hybrid"]
        self.assertEqual({k: h[k] for k in ("escalated", "pipeline_status", "agent_status", "used")},
                         {"escalated": True, "pipeline_status": "not_found", "agent_status": "answered", "used": "agent"})
        self.assertNotIn("agent_error", h)
        self.assertGreater(h["pipeline_seconds"], 0)
        self.assertGreater(h["agent_seconds"], 0)
        self.assertEqual(r["seconds"], round(h["pipeline_seconds"] + h["agent_seconds"], 1))
        # one meter for both steps, so run totals and the spend caps cover both
        self.assertEqual(len(stub.meters), 1)
        self.assertIs(stub.meters[0], meter)
        self.assertTrue(meters and all(m is meter for m in meters))
        # the agent is called as agent mode would be: same model and effort, the same first message
        self.assertEqual((fake.calls[0]["model"], fake.calls[0]["effort"]), (answer.DEFAULT_MODEL, answer.DEFAULT_EFFORT))
        self.assertEqual(fake.calls[0]["messages"][0]["content"], prompts.first_message("ACME", Q, P))
        self.assert_pipeline_shape(r, self.pipeline_row(NF))

    def test_unsupported_escalates(self):
        fake = FakeModel([tool_turn(search()), answer_turn(draft())])
        self.assertEqual(self.pipeline_row(draft(cites=[FABRICATED]))["status"], "unsupported")
        r, _ = self.ask(draft(cites=[FABRICATED]), fake)
        self.assertEqual((r["status"], r["hybrid"]["pipeline_status"], r["hybrid"]["used"]),
                         ("answered", "unsupported", "agent"))
        self.assertEqual(len(fake.calls), 2)

    def test_a_pipeline_error_is_not_escalated(self):
        fake = FakeModel()
        r, _ = self.ask(llm.LLMError("refusal: test"), fake)
        self.assertEqual(fake.calls, [])
        self.assertEqual((r["status"], r["error"]), ("error", "refusal: test"))
        self.assertEqual(r["hybrid"], {"escalated": False, "pipeline_status": "error", "pipeline_seconds": r["seconds"]})

    def test_an_agent_error_keeps_the_pipeline_row(self):
        fake = FakeModel([llm.LLMError("refusal: agent")])
        r, _ = self.ask(NF, fake)
        pipe = self.pipeline_row(NF)
        drop = lambda d: {k: v for k, v in d.items() if k not in ("seconds", "mode", "hybrid", "agent")}
        self.assertEqual(drop(r), drop(pipe))
        self.assertEqual((r["status"], r["mode"]), ("not_found", "hybrid"))
        h = r["hybrid"]
        self.assertEqual((h["escalated"], h["agent_status"], h["used"], h["agent_error"]),
                         (True, "error", "pipeline", "refusal: agent"))
        self.assertEqual(r["seconds"], round(h["pipeline_seconds"] + h["agent_seconds"], 1))
        # the failed step's calls stay on record
        self.assertEqual((r["agent"]["stop"], r["agent"]["model_calls"]), ("error", 1))

    def test_an_agent_not_found_is_used(self):
        note = {**NF, "answer": "The filings report net retention only."}
        fake = FakeModel([tool_turn(search()), answer_turn(note)])
        r, _ = self.ask(NF, fake)
        self.assertEqual((r["status"], r["answer"], r["hybrid"]["used"], r["hybrid"]["agent_status"]),
                         ("not_found", note["answer"], "agent", "not_found"))
        self.assertEqual(r["retrieved"], r["agent"]["trace"][0]["shown"])

    def test_the_quote_check_holds_on_the_escalated_row(self):
        fake = FakeModel([tool_turn(search()), answer_turn(draft(cites=[FABRICATED]))])
        r, _ = self.ask(NF, fake)
        self.assertEqual((r["status"], r["model_status"], r["citations_verified"]), ("unsupported", "answered", 0))
        self.assertEqual((r["hybrid"]["agent_status"], r["hybrid"]["used"]), ("unsupported", "agent"))
        self.assertFalse(r["citations"][0]["verified"])

    def test_agent_options_reach_the_agent_step(self):
        fake = FakeModel(then=tool_turn(search()), forced=answer_turn(draft()))
        r, _ = self.ask(NF, fake, max_model_calls=3)
        self.assertEqual((r["agent"]["model_calls"], r["agent"]["stop"]), (3, "step_limit"))

    def test_an_unknown_agent_option_fails_before_any_call(self):
        stub = Pipeline(NF)
        with mock.patch.object(llm, "complete_json", stub), self.assertRaises(TypeError):
            hybrid.answer_question("ACME", Q, self.ix, llm.CostMeter(), max_steps=3)
        self.assertEqual(stub.meters, [])


class ModesTest(unittest.TestCase):
    def test_answerer(self):
        self.assertIn("hybrid", modes.MODES)
        f = modes.answerer("hybrid")
        self.assertIs(f.func, hybrid.answer_question)
        self.assertEqual(f.keywords, {})
        self.assertEqual(modes.answerer("hybrid", max_model_calls=3).keywords, {"max_model_calls": 3})
        with self.assertRaises(ValueError):
            modes.answerer("chain")
        self.assertEqual(modes.row_mode({"mode": "hybrid"}), "hybrid")

    def test_signature_matches_the_pipeline_and_the_agent_options(self):
        pipe = list(inspect.signature(answer.answer_question).parameters.values())
        mine = list(inspect.signature(hybrid.answer_question).parameters.values())[:len(pipe)]
        self.assertEqual([(p.name, p.default) for p in mine], [(p.name, p.default) for p in pipe])
        kw = {n for n, p in inspect.signature(agent.answer_question).parameters.items() if p.kind is p.KEYWORD_ONLY}
        self.assertEqual(set(hybrid.AGENT_OPTIONS), kw)


class NoFrameworkTest(unittest.TestCase):
    def test_no_escalation_never_loads_the_agent_or_the_framework(self):
        """In a fresh process, a question the pipeline answers leaves the agent package, langgraph, langsmith and
        langchain_core unloaded, with the CLI, pipeline and evaluate modules imported. The same process then
        escalates one question, which does load them, so the first check is measuring something."""
        code = ("import sys, json\nfrom unittest import mock\n"
                "from filingroom import cli, answer, llm, modes, pipeline, evaluate\n"
                "from tests.fixture_corpus import Corpus\n"
                f"Q = {Q!r}\nD = {draft()!r}\nNF = {NF!r}\n"
                "FW = ('langgraph', 'langsmith', 'langchain_core')\n"
                "loaded = lambda: {'agent': 'filingroom.agent' in sys.modules,\n"
                "                  'framework': sorted({m.split('.')[0] for m in sys.modules if m.split('.')[0] in FW})}\n"
                "def turn(model, system, messages, tools, meter, **k):\n"
                "    return {'content': [{'type': 'text', 'text': json.dumps(NF)}], 'stop_reason': 'end_turn',\n"
                "            'usage': {'input_tokens': 10, 'output_tokens': 5}, 'usd': 0.0}\n"
                "out = {}\n"
                "with Corpus() as c:\n"
                "    for name, reply in (('answered', D), ('escalated', NF)):\n"
                "        with mock.patch.object(llm, 'complete_json', lambda *a, **k: json.loads(json.dumps(reply))):\n"
                "            r = modes.answerer('hybrid', call_model=turn)('ACME', Q, c.ix, llm.CostMeter())\n"
                "        out[name] = [r['status'], r['hybrid']['escalated'], loaded()]\n"
                "print(json.dumps(out))\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("LANGSMITH", "LANGCHAIN"))}
        p = subprocess.run([sys.executable, "-c", code], cwd=config.ROOT, env=env, capture_output=True, text=True,
                           timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(out["answered"], ["answered", False, {"agent": False, "framework": []}])
        status, escalated, loaded = out["escalated"]
        self.assertEqual((status, escalated, loaded["agent"]), ("not_found", True, True))
        self.assertIn("langgraph", loaded["framework"])


class CliTest(unittest.TestCase):
    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = None
        with mock.patch.object(sys, "argv", ["fr", *argv]), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            try:
                cli.main()
            except SystemExit as e:
                code = e.code
        return out.getvalue(), code

    def test_the_parser_accepts_hybrid_and_rejects_unknown_modes(self):
        _, code = self.main("eval", "--mode", "chain")
        self.assertEqual(code, 2)
        _, code = self.main("eval", "--mode", "hybrid")  # accepted, then the full-eval guard stops it
        self.assertIn("hybrid-mode eval", code)

    def test_hybrid_eval_follows_the_agent_rules(self):
        calls = []
        with mock.patch.object(evaluate, "run", lambda *a, **k: calls.append((a, k))):
            _, code = self.main("eval", "--mode", "hybrid", "--full", "--companies", "BOX")
            self.assertIn("held-out", code)  # BOX still needs --final
            self.assertEqual(calls, [])
            _, code = self.main("eval", "--mode", "hybrid", "--full", "--max-steps", "4", "--label", "h")
        self.assertIsNone(code)
        (args, kw), = calls
        self.assertEqual(args[3:5], (answer.DEFAULT_K, answer.DEFAULT_EXPAND))  # the pipeline step's retrieval
        self.assertEqual((kw["mode"], kw["only"], kw["label"]), ("hybrid", None, "h"))
        self.assertEqual(kw["agent_opts"], {"max_model_calls": 4, "max_tool_calls": agent.DEFAULT_MAX_TOOL_CALLS,
                                            "max_tokens": agent.DEFAULT_MAX_TOKENS, "repair": False})

    def test_ask_in_hybrid_mode_prints_both_steps(self):
        fake = FakeModel([tool_turn(search()), answer_turn(draft())])
        real = modes.answerer
        with Corpus() as c, mock.patch.object(cli, "_tickers", lambda *a, **k: ["ACME"]), \
                mock.patch.object(cli.index, "Index", lambda t: c.ix), \
                mock.patch.object(llm, "complete_json", Pipeline(NF)), \
                mock.patch.object(modes, "answerer", lambda mode, **o: real(mode, **o, call_model=fake)):
            out, code = self.main("ask", "ACME", "rev_total", "--mode", "hybrid")
        self.assertIsNone(code)
        self.assertRegex(out, r"turn \d+: search_filings")
        self.assertIn("agent: 2 model calls, 1 tool calls", out)
        self.assertRegex(out, r"hybrid: pipeline not_found in [\d.]+ s; agent mode answered in [\d.]+ s; "
                              r"kept the agent answer")


class HybridEvalTest(unittest.TestCase):
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
                        mock.patch.object(golden, "load", lambda tickers: [dict(i) for i in ITEMS]),
                        mock.patch.object(llm, "complete_json", Pipeline(
                            lambda user: NF if 'id="na_cac"' in user else draft(cites=[REAL], value="1,234,500,000")))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()
        self.corpus.__exit__(None, None, None)

    def test_hybrid_eval_writes_only_to_the_agent_area(self):
        # an agent-mode run of the same items is not this run's "previous"
        self.agent_dir.mkdir(parents=True)
        (self.agent_dir / "2000-01-01_0000_agent.json").write_text(json.dumps(
            {"timestamp": "2000-01-01_0000", "tickers": ["ACME"], "mode": "agent",
             "rows": [{"id": "ACME:rev_total", "correct": False}, {"id": "ACME:na_cac", "correct": False}],
             "metrics": {"accuracy": 50.0}}))
        fake = FakeModel(then=script)
        with contextlib.redirect_stdout(io.StringIO()):
            r = evaluate.run(["ACME"], "claude-sonnet-5", "medium", 8, 2, use_judge=False, label="h", workers=2,
                             only={"ACME:rev_total", "ACME:na_cac"}, mode="hybrid",
                             agent_opts={"max_model_calls": 4, "call_model": fake})
        self.assertEqual(sorted(p.name for p in self.agent_dir.glob("*.json")),
                         ["2000-01-01_0000_agent.json", f"{r['name']}.json"])
        self.assertEqual(list(self.results.glob("*.json")), [])
        self.assertFalse(self.cl.exists())
        saved = json.loads((self.agent_dir / f"{r['name']}.json").read_text())
        self.assertEqual((saved["mode"], saved["agent_opts"], saved["k"], saved["expand"]),
                         ("hybrid", {"max_model_calls": 4}, 8, 2))
        self.assertEqual(saved["metrics"]["accuracy"], 100.0)
        a = saved["metrics"]["agent"]
        self.assertEqual((a["n"], a["escalated"], a["used_agent"], a["model_calls_mean"], a["tool_calls_mean"]),
                         (1, 1, 1, 2, 1))
        rows = {row_["id"]: row_ for row_ in saved["rows"]}
        self.assertEqual({row_["mode"] for row_ in rows.values()}, {"hybrid"})
        self.assertFalse(rows["ACME:rev_total"]["hybrid"]["escalated"])
        self.assertNotIn("agent", rows["ACME:rev_total"])
        self.assertEqual(rows["ACME:na_cac"]["hybrid"]["used"], "agent")
        self.assertEqual(len(fake.calls), 2)  # only na_cac reached the agent
        md = (self.agent_dir / f"{r['name']}.md").read_text()
        self.assertIn("Hybrid mode: 1 of 2 questions escalated to agent mode; the agent's answer was kept for 1.", md)
        self.assertIn("| Accuracy % | 100.0 | – |", md)
        line = self.acl.read_text().splitlines()[-1]
        self.assertIn("| 2 (subset), 1 escalated | - (hybrid, claude-sonnet-5, medium, k=8, expand=2, agent step "
                      '{"max_model_calls": 4}) |', line)
        self.assertIn("| 2.0/1.0 (escalated) | 0 | 0.0 |", line)
        self.assertTrue((config.RUNS / "last_hybrid_eval_rows.json").exists())
        self.assertFalse((config.RUNS / "last_agent_eval_rows.json").exists())


def hy(r, escalated, used=None):
    r["mode"] = "hybrid"
    r["hybrid"] = {"escalated": escalated, "pipeline_status": "not_found" if escalated else r["status"],
                   "pipeline_seconds": 3.0}
    if escalated:
        r["hybrid"].update(agent_status="error" if used == "pipeline" else r["status"], agent_seconds=5.0, used=used)
    return r


class HybridCompareTest(unittest.TestCase):
    def setUp(self):
        self.p = [mock.patch.object(devtools, "_golden_by_id", lambda: {}),
                  mock.patch.object(devtools, "_docs_by_ticker", lambda t: {})]
        for p in self.p:
            p.start()
        self.base = {"timestamp": "2026-09-27_1616", "label": "recency", "tickers": ["ACME"],
                     "metrics": {"cost_usd": {"answer": 0.1, "judge": 0.05}},
                     "rows": [row("a", True), row("b", False), row("c", True), row("d", True, "abstain", "not_found")]}

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_compare_copes_with_escalated_and_plain_rows(self):
        other = {"timestamp": "2026-11-22_1200", "label": "hybrid", "tickers": ["ACME"], "mode": "hybrid",
                 "metrics": {"cost_usd": {"answer": 0.2, "judge": 0.05}},
                 "rows": [hy(row("a", True, seconds=3.0), False),
                          hy(row("b", True, agent=ag(4, 3, usd=0.05), seconds=8.0), True, "agent"),
                          hy(row("c", False, status="not_found", agent=ag(2, 1, "error", 0.01), seconds=4.0),
                             True, "pipeline"),
                          hy(row("d", True, "abstain", "not_found", agent=ag(2, 1, usd=0.03), seconds=9.0),
                             True, "agent")]}
        m = evaluate.agent_metrics(other["rows"])
        self.assertEqual((m["n"], m["escalated"], m["used_agent"], m["model_calls_mean"], m["tool_calls_mean"]),
                         (3, 3, 2, 2.67, 1.67))
        self.assertEqual(m["stops"], {"model_done": 2, "error": 1})
        c = evaluate.compare(self.base, other)
        o = c["sides"]["other"]
        self.assertEqual(o["mode"], "hybrid")
        self.assertEqual((o["usd_per_question"], o["usd_note"]), (0.05, "run average over its 4 items, both steps"))
        self.assertEqual((o["model_calls"], o["tool_calls"], o["hit_limit"]), (2.67, 1.67, 0))
        self.assertEqual(o["latency"], {"mean": 6.0, "median": 4.0, "p90": 9.0})
        self.assertEqual((c["flips"]["better"], c["flips"]["worse"]), (["b"], ["c"]))
        md = evaluate.compare_md(c)
        self.assertIn("| Model calls / tool calls per question | 1 / 0 | 1 / 0, plus 2.67 / 1.67 per escalated "
                      "question |", md)
        self.assertIn("| Questions escalated to agent mode | – | 3 of 4 (agent answer kept for 2) |", md)
        self.assertIn("| Answer cost per question ($) | 0.025 (run average over its 4 items) | "
                      "0.05 (run average over its 4 items, both steps) |", md)

    def test_compare_with_nothing_escalated(self):
        other = {"timestamp": "t", "label": "h", "tickers": ["ACME"], "mode": "hybrid",
                 "metrics": {"cost_usd": {"answer": 0.08, "judge": 0.0}},
                 "rows": [hy(row(i, True), False) for i in "abc"]}
        md = evaluate.compare_md(evaluate.compare(self.base, other))
        self.assertIn("| 1 / 0 | 1 / 0 (none escalated) |", md)
        self.assertIn("| Questions escalated to agent mode | – | 0 of 3 (agent answer kept for 0) |", md)

    def test_agent_mode_comparison_has_no_escalation_row(self):
        other = {"timestamp": "t", "label": "a", "tickers": ["ACME"], "mode": "agent",
                 "rows": [row(i, True, agent=ag()) for i in "abcd"]}
        self.assertNotIn("escalated", evaluate.compare_md(evaluate.compare(self.base, other)))

    def test_changelog_lines(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(evaluate, "AGENT_CHANGELOG", Path(d) / "c.md"):
            m = {"n_items": 80, "accuracy": 94.9, "unsupported_claim_rate": 0.0, "abstention_precision": 80.0,
                 "abstention_recall": 100.0, "cost_usd": {"answer": 2.3628, "judge": 0.5524},
                 "agent": {"n": 80, "model_calls_mean": 2.92, "tool_calls_mean": 2.24, "hit_limit": 1,
                           "usd_per_question": 0.0295}}
            base = {"timestamp": "2026-11-21_1047", "label": "agent80", "tickers": ["BILL", "RPD"], "note": "n",
                    "model": "claude-sonnet-5", "effort": "medium", "agent_opts": {"max_model_calls": 6},
                    "only": None}
            evaluate.append_agent_changelog({**base, "mode": "agent", "k": None, "expand": None, "metrics": m})
            m2 = {**m, "n_items": 2, "cost_usd": {"answer": 0.05, "judge": 0.0},
                  "agent": {"n": 0, "escalated": 0, "used_agent": 0}}
            evaluate.append_agent_changelog({**base, "mode": "hybrid", "k": 8, "expand": 2, "metrics": m2})
            lines = (Path(d) / "c.md").read_text().splitlines()
        # the agent-mode line is unchanged
        self.assertEqual(lines[-2], '| 2026-11-21_1047 agent80 | BILL,RPD | 80 | n (claude-sonnet-5, medium, '
                                    '{"max_model_calls": 6}) | 94.9 | 0.0 | 80.0/100.0 | 2.92/2.24 | 1 | 0.0295 | '
                                    '2.3628/0.5524 |')
        self.assertEqual(lines[-1], '| 2026-11-21_1047 agent80 | BILL,RPD | 2, 0 escalated | n (hybrid, '
                                    'claude-sonnet-5, medium, k=8, expand=2, agent step {"max_model_calls": 6}) | '
                                    '94.9 | 0.0 | 80.0/100.0 | - | 0 | 0.025 | 0.05/0.0 |')


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

    def test_hybrid_run_writes_its_own_run_file(self):
        partial = self.out / "answers.partial.jsonl"
        partial.write_text(json.dumps({"qid": "rev_total", "status": "answered", "mode": "agent"}) + "\n")
        fake = FakeModel(then=lambda m, tc: tool_turn(search()) if len(m) == 1 else answer_turn(NF))
        stub = Pipeline(lambda user: draft(cites=[REAL]) if 'id="rev_total"' in user else NF)
        with mock.patch.object(llm, "complete_json", stub):
            path = pipeline.run_checklist("ACME", llm.CostMeter(), out_dir=self.out, workers=3, partial=partial,
                                          mode="hybrid", agent_opts={"max_model_calls": 4, "call_model": fake})
        self.assertTrue(path.name.endswith("_hybrid.json"))
        data = json.loads(path.read_text())
        self.assertEqual((data["meta"]["mode"], data["meta"]["agent_opts"], data["meta"]["reused_answers"]),
                         ("hybrid", {"max_model_calls": 4}, 0))  # the agent-mode row was not reused
        rows = {r["qid"]: r for r in data["answers"]}
        self.assertEqual({r["mode"] for r in rows.values()}, {"hybrid"})
        self.assertEqual((rows["rev_total"]["status"], rows["rev_total"]["hybrid"]["escalated"]), ("answered", False))
        escalated = [r for r in rows.values() if r["hybrid"]["escalated"]]
        self.assertEqual(len(escalated), len(rows) - 1)
        self.assertEqual(len(stub.meters), len(rows))
        self.assertEqual(len(fake.calls), 2 * len(escalated))
        self.assertEqual(rows["rev_total"]["k"], answer.DEFAULT_K)  # the pipeline step kept its retrieval settings


if __name__ == "__main__":
    unittest.main()
