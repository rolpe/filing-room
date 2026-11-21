"""Agent graph with a scripted fake model: loop, limits, backstop, verification, row shape, threads. Free.

The fake model is passed through the graph's runtime context, exactly where the real llm.complete_tools goes.
"""

import json
import os
import subprocess
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from filingroom import answer, config, findings, llm, memo, present
from filingroom.agent import graph
from tests.fixture_corpus import K25, K26, MANIFEST, P, Corpus

REAL = (f"{K26}#item7#001", "Total revenue was $1,234.5 million for fiscal 2026")
Q = {"id": "rev_total", "category": "Financials", "question": "What was total revenue?", "answer_type": "currency",
     "period": "latest_fy", "where": {"forms": ["10-K"]}, "search": "total revenue"}


def tool_turn(*calls, tokens=1000):
    return {"content": [{"type": "tool_use", "id": f"tu_{i}_{name}", "name": name, "input": args}
                        for i, (name, args) in enumerate(calls)],
            "stop_reason": "tool_use", "usage": {"input_tokens": tokens - 50, "output_tokens": 50}, "usd": 0.002}


def draft(status="answered", cites=(REAL,), value="1234.5"):
    return {"status": status, "answer": "Total revenue was $1,234.5 million." if status == "answered" else "",
            "value": value if status == "answered" else "", "unit": "USD" if status == "answered" else "",
            "period": "FY2026" if status == "answered" else "", "confidence": "high",
            "citations": [{"chunk_id": c, "quote": qt} for c, qt in cites]}


def answer_turn(d, tokens=1000):
    return {"content": [{"type": "text", "text": json.dumps(d) if isinstance(d, dict) else d}],
            "stop_reason": "end_turn", "usage": {"input_tokens": tokens - 50, "output_tokens": 50}, "usd": 0.002}


class FakeModel:
    """Plays back a script. Each entry is a turn, a callable(messages, tool_choice) -> turn, or an exception.
    When the script runs out, `then` is used. A forced call (tool_choice none) uses `forced`."""

    def __init__(self, script=(), then=None, forced=None):
        self.script, self.then, self.forced = list(script), then, forced
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, model, system, messages, tools, meter, *, effort=None, tool_choice=None):
        with self.lock:
            self.calls.append({"messages": json.loads(json.dumps(messages)), "tool_choice": tool_choice,
                               "tools": [t["name"] for t in tools], "model": model, "effort": effort})
            if tool_choice == {"type": "none"} and self.forced is not None:
                step = self.forced
            else:
                step = self.script.pop(0) if self.script else self.then
        if callable(step):
            step = step(messages, tool_choice)
        if isinstance(step, BaseException):
            raise step
        return json.loads(json.dumps(step))


def search(query="total revenue", **kw):
    return ("search_filings", {"query": query, **kw})


class GraphTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = Corpus().__enter__()
        cls.ix = cls.corpus.ix

    @classmethod
    def tearDownClass(cls):
        cls.corpus.__exit__(None, None, None)

    def ctx(self, fake, q=Q, **limits):
        return graph.Context(ticker="ACME", q=q, ix=self.ix, manifest=MANIFEST, P=P, meter=llm.CostMeter(),
                             system="SYSTEM", call_model=fake, limits=graph.Limits(**limits))

    def run_graph(self, fake, q=Q, **limits):
        return graph.run(self.ctx(fake, q, **limits), "QUESTION")

    # ------------------------------------------------------------ the loop

    def test_search_then_answer(self):
        fake = FakeModel([tool_turn(search()), answer_turn(draft())])
        row = self.run_graph(fake)
        self.assertEqual(row["status"], "answered")
        self.assertEqual(row["citations_verified"], 1)
        a = row["agent"]
        self.assertEqual((a["model_calls"], a["tool_calls"], a["stop"], a["repairs"]), (2, 1, "model_done", 0))
        self.assertEqual(a["tokens"], 2000)
        self.assertAlmostEqual(a["usd"], 0.004)
        self.assertEqual(len(row["retrieved"]), 5)
        self.assertIn(REAL[0], row["retrieved"])
        self.assertEqual(row["retrieved"], a["trace"][0]["shown"])
        self.assertEqual(a["trace"][0]["tool"], "search_filings")
        self.assertEqual(a["cited_unseen"], [])
        self.assertEqual([c["tool_choice"] for c in fake.calls], [None, None])
        self.assertEqual(fake.calls[0]["tools"], ["search_filings", "get_chunk", "list_filings"])
        second = fake.calls[1]["messages"]
        self.assertEqual([m["role"] for m in second], ["user", "assistant", "user"])
        self.assertEqual(second[2]["content"][0]["type"], "tool_result")
        self.assertEqual(second[2]["content"][0]["tool_use_id"], "tu_0_search_filings")
        self.assertIn(answer._excerpt(self.ix.by_id[row["retrieved"][0]]), second[2]["content"][0]["content"])

    def test_several_tools_in_one_turn_share_one_result_message(self):
        fake = FakeModel([tool_turn(search(k=1), ("get_chunk", {"chunk_id": REAL[0]}), ("list_filings", {})),
                          answer_turn(draft())])
        row = self.run_graph(fake)
        results = fake.calls[1]["messages"][2]["content"]
        self.assertEqual([r["tool_use_id"] for r in results],
                         ["tu_0_search_filings", "tu_1_get_chunk", "tu_2_list_filings"])
        self.assertEqual(row["agent"]["tool_calls"], 3)
        self.assertEqual(len(row["retrieved"]), len(set(row["retrieved"])))  # seen is append-unique

    def test_bad_tool_arguments_come_back_as_error_results(self):
        fake = FakeModel([tool_turn(search(periods=["FY 2026"])), answer_turn(draft("not_found"))])
        row = self.run_graph(fake)
        res = fake.calls[1]["messages"][2]["content"][0]
        self.assertTrue(res["is_error"])
        self.assertIn("Valid values", res["content"])
        self.assertTrue(row["agent"]["trace"][0]["error"])
        self.assertEqual(row["status"], "not_found")

    # ------------------------------------------------------------ verification

    def test_fabricated_quote_is_unsupported(self):
        row = self.run_graph(FakeModel([tool_turn(search()), answer_turn(draft(cites=[(REAL[0], "revenue was $9")]))]))
        self.assertEqual((row["status"], row["model_status"], row["citations_verified"]),
                         ("unsupported", "answered", 0))

    def test_not_found_passes_through(self):
        row = self.run_graph(FakeModel([answer_turn(draft("not_found", cites=()))]))
        self.assertEqual((row["status"], row["agent"]["model_calls"], row["retrieved"]), ("not_found", 1, []))

    def test_verified_quote_from_a_chunk_never_shown_is_reported(self):
        unseen = (f"{K25}#item7#000", "Total revenue was $1,102.2 million")
        row = self.run_graph(FakeModel([tool_turn(search(forms=["10-Q"])), answer_turn(draft(cites=[unseen]))]))
        self.assertEqual(row["status"], "answered")  # the verifier only checks the quote is in the chunk it names
        self.assertEqual(row["agent"]["cited_unseen"], [unseen[0]])

    def test_model_error_and_bad_json_give_error_rows(self):
        for script, msg in [([llm.LLMError("refusal: x")], "refusal: x"), ([answer_turn("not json")], "bad JSON"),
                            ([answer_turn({"status": "maybe"})], "does not match")]:
            row = self.run_graph(FakeModel(script))
            self.assertEqual((row["status"], row["model_status"], row["agent"]["stop"]), ("error", "error", "error"))
            self.assertIn(msg, row["error"])

    def test_spend_cap_still_stops_the_command(self):
        with self.assertRaises(SystemExit):
            self.run_graph(FakeModel([SystemExit("Stopped: cap")]))

    # ------------------------------------------------------------ limits

    def test_step_limit_runs_the_last_tools_then_finalizes_once_with_tools_off(self):
        fake = FakeModel(then=tool_turn(search()), forced=answer_turn(draft()))
        row = self.run_graph(fake, model_calls=6, tool_calls=100, tokens=10**9)
        a = row["agent"]
        self.assertEqual((a["model_calls"], a["tool_calls"], a["stop"]), (6, 5, "step_limit"))
        self.assertEqual([c["tool_choice"] for c in fake.calls], [None] * 5 + [{"type": "none"}])
        last = fake.calls[-1]["messages"][-1]
        self.assertEqual(last["role"], "user")
        self.assertEqual(last["content"][0]["type"], "tool_result")  # call 5's request ran: real results
        self.assertNotIn("is_error", last["content"][0])
        self.assertNotEqual(last["content"][0]["content"], graph.LIMIT_TEXT)
        self.assertEqual(last["content"][-1], {"type": "text", "text": graph.LAST_ROUND_TEXT})
        self.assertEqual(len(a["trace"]), 5)
        # earlier tool rounds carry no note
        self.assertTrue(all(b["type"] == "tool_result" for b in fake.calls[-2]["messages"][-1]["content"]))
        self.assertEqual(row["status"], "answered")
        roles = [m["role"] for m in fake.calls[-1]["messages"]]
        self.assertTrue(all(a != b for a, b in zip(roles, roles[1:])))  # roles alternate, as the API requires

    def test_tool_call_limit(self):
        three = tool_turn(search("a"), search("b"), search("c"))
        fake = FakeModel(then=three, forced=answer_turn(draft("not_found", cites=())))
        row = self.run_graph(fake, model_calls=10, tool_calls=8, tokens=10**9)
        a = row["agent"]
        self.assertEqual((a["model_calls"], a["tool_calls"], a["stop"]), (4, 6, "step_limit"))  # 6 + 3 > 8
        refused = fake.calls[-1]["messages"][-1]["content"]
        self.assertEqual([b.get("content") for b in refused[:3]], [graph.LIMIT_TEXT] * 3)
        self.assertTrue(all(b.get("is_error") for b in refused[:3]))
        self.assertEqual(refused[-1], {"type": "text", "text": graph.LIMIT_TEXT})

    def test_token_limit(self):
        fake = FakeModel(then=tool_turn(search(), tokens=20_000), forced=answer_turn(draft(), tokens=25_000))
        row = self.run_graph(fake, model_calls=10, tool_calls=100, tokens=30_000)
        a = row["agent"]
        self.assertEqual((a["model_calls"], a["tool_calls"], a["stop"]), (3, 1, "token_limit"))
        self.assertEqual(a["tokens"], 65_000)  # the forced final answer is always allowed
        self.assertEqual(fake.calls[-1]["tool_choice"], {"type": "none"})
        self.assertEqual(fake.calls[-1]["messages"][-1]["content"][0]["content"], graph.LIMIT_TEXT)  # refused

    def test_model_asking_for_tools_after_the_limit_is_an_error(self):
        fake = FakeModel(then=tool_turn(search()), forced=tool_turn(search()))
        row = self.run_graph(fake, model_calls=2)
        self.assertEqual((row["status"], row["agent"]["stop"]), ("error", "error"))

    def test_recursion_backstop_gives_an_error_row_with_partial_counts(self):
        fake = FakeModel(then=tool_turn(search()))
        with mock.patch.object(graph, "recursion_limit", lambda lim: 5):
            row = self.run_graph(fake, model_calls=100, tool_calls=100, tokens=10**9)
        self.assertEqual((row["status"], row["agent"]["stop"]), ("error", "error"))
        self.assertIn("recursion limit", row["error"])
        a = row["agent"]
        # 5 super-steps ran (agent, tools, agent, tools, agent); state after the last completed step is kept
        self.assertEqual((a["model_calls"], a["tool_calls"], len(fake.calls)), (3, 2, 3))
        self.assertEqual(len(row["retrieved"]), 5)

    def test_every_path_respects_the_call_budget_and_fits_under_the_backstop(self):
        """Exhaustive over every script of tool turns, fabricated answers and good answers, with repair on and off:
        never more than M model calls, never more than 2M super-steps, never the backstop."""
        import itertools
        M = 4
        turns = {"t": tool_turn(search()), "b": answer_turn(draft(cites=[(REAL[0], "made up")])),
                 "g": answer_turn(draft())}
        orig = graph.compiled().stream
        longest = 0
        for repair in (False, True):
            for script in itertools.product("tbg", repeat=M):
                steps = []

                def counting(*a, **k):
                    for v in orig(*a, **k):
                        steps.append(v)
                        yield v
                fake = FakeModel([turns[c] for c in script], forced=turns["g"])
                with mock.patch.object(graph.compiled(), "stream", counting):
                    row = self.run_graph(fake, model_calls=M, tool_calls=100, tokens=10**9, repair=repair)
                a = row["agent"]
                self.assertNotEqual(a["stop"], "error", script)
                self.assertLessEqual(len(fake.calls), M, script)
                self.assertEqual(a["model_calls"], len(fake.calls))
                self.assertLessEqual(len(steps) - 1, 2 * M, script)  # values stream: the input, then one per step
                longest = max(longest, len(steps) - 1)
        self.assertEqual(longest, 2 * M)  # tool rounds all the way, then finalize and verify
        self.assertGreater(graph.recursion_limit(graph.Limits(model_calls=M)), 2 * M + 1)

    def test_no_repair_once_the_step_budget_is_nearly_spent(self):
        bad = answer_turn(draft(cites=[(REAL[0], "made up")]))
        row = self.run_graph(FakeModel(then=tool_turn(search()), forced=bad), repair=True)
        self.assertEqual((row["agent"]["stop"], row["agent"]["repairs"]), ("step_limit", 0))
        row = self.run_graph(FakeModel([tool_turn(search())] * 4 + [bad, bad]), repair=True)  # 5 calls used
        self.assertEqual((row["agent"]["model_calls"], row["agent"]["repairs"]), (5, 0))

    # ------------------------------------------------------------ repair edge

    def test_repair_off_by_default(self):
        self.assertFalse(graph.Limits().repair)
        fake = FakeModel([answer_turn(draft(cites=[(REAL[0], "made up")]))])
        self.assertEqual(self.run_graph(fake)["agent"]["model_calls"], 1)

    def test_repair_runs_exactly_one_extra_round(self):
        bad = answer_turn(draft(cites=[(REAL[0], "made up")]))
        fake = FakeModel([tool_turn(search()), bad, answer_turn(draft())])
        row = self.run_graph(fake, repair=True)
        self.assertEqual((row["status"], row["agent"]["repairs"], row["agent"]["model_calls"]), ("answered", 1, 3))
        msg = fake.calls[2]["messages"][-1]
        self.assertEqual(msg["role"], "user")
        self.assertIn(f'[{REAL[0]}] "made up"', msg["content"])
        fake = FakeModel([bad, bad, answer_turn(draft())])
        row = self.run_graph(fake, repair=True)
        self.assertEqual((row["status"], row["agent"]["repairs"], len(fake.calls)), ("unsupported", 1, 2))

    def test_at_least_two_model_calls(self):
        with self.assertRaises(ValueError):
            graph.Limits(model_calls=1)

    def test_no_repair_when_a_quote_verifies(self):
        fake = FakeModel([answer_turn(draft(cites=[REAL, (REAL[0], "made up")]))])
        row = self.run_graph(fake, repair=True)
        self.assertEqual((row["status"], row["agent"]["repairs"], len(fake.calls)), ("answered", 0, 1))

    # ------------------------------------------------------------ row shape

    def test_agent_row_has_every_pipeline_key_with_matching_types(self):
        out = draft()
        with mock.patch.object(llm, "complete_json", lambda *a, **k: json.loads(json.dumps(out))):
            pipe = answer.answer_question("ACME", Q, self.ix, llm.CostMeter())
        agent = self.run_graph(FakeModel([tool_turn(search()), answer_turn(out)]))
        self.assertEqual(set(agent) - set(pipe), {"mode", "agent"})
        self.assertEqual(list(agent)[:len(pipe)], list(pipe))
        for k, v in pipe.items():
            if k in ("k", "expand"):
                self.assertIsNone(agent[k])
            else:
                self.assertIs(type(agent[k]), type(v), k)
        self.assertEqual([set(c) for c in agent["citations"]], [set(c) for c in pipe["citations"]])
        self.assertTrue(present.eligible(agent))
        self.assertIn("rev_total", memo.usable([agent]))
        self.assertEqual(findings.derive_status(agent)["status"], findings.derive_status(pipe)["status"])
        json.dumps(agent)  # run files are JSON

    # ------------------------------------------------------------ threads

    def test_one_compiled_graph_six_threads_no_state_crosses(self):
        """Six threads, one compiled graph, each with its own question; the fake echoes the question id into its
        search query and answer, so any state crossing between runs would show up in the rows."""
        qids = [f"q{i}" for i in range(12)]
        barrier = threading.Barrier(6)

        def model_for(qid):
            def step(messages, tool_choice):
                assert messages[0]["content"] == f"QUESTION {qid}", messages[0]
                n = sum(m["role"] == "assistant" for m in messages)
                if n < 3:
                    if n == 0 and qid in qids[:6]:
                        barrier.wait(timeout=5)  # all six runs are inside the graph at once
                    return tool_turn(search(f"revenue {qid} {n}"))
                return answer_turn({**draft(), "answer": f"answer for {qid}"})
            return FakeModel(then=step)

        def one(qid):
            q = {**Q, "id": qid}
            return graph.run(self.ctx(model_for(qid), q), f"QUESTION {qid}")

        self.assertIs(graph.compiled(), graph.compiled())
        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(pool.map(one, qids))
        for qid, row in zip(qids, rows):
            self.assertEqual((row["qid"], row["answer"]), (qid, f"answer for {qid}"))
            self.assertEqual([t["input"]["query"] for t in row["agent"]["trace"]],
                             [f"revenue {qid} {n}" for n in range(3)])
            self.assertEqual((row["agent"]["model_calls"], row["agent"]["tool_calls"]), (4, 3))


class SpikeTest(unittest.TestCase):
    """What increment 3 pinned down about the framework (recorded in PLAN_AGENT.md §14)."""

    def test_recursion_limit_counts_super_steps(self):
        with Corpus() as c:
            ctx = graph.Context(ticker="ACME", q=Q, ix=c.ix, manifest=MANIFEST, P=P, meter=llm.CostMeter(),
                                system="S", call_model=None)
            # step-limit path with 6 model calls: agent x5, tools x5, finalize, verify = 12 super-steps
            from langgraph.errors import GraphRecursionError
            for limit, raises in [(13, False), (12, True)]:
                ctx.call_model = FakeModel(then=tool_turn(search()), forced=answer_turn(draft()))
                nodes, raised = [], False
                try:
                    for u in graph.compiled().stream({"messages": [{"role": "user", "content": "Q"}]},
                                                     {"recursion_limit": limit}, context=ctx, stream_mode="updates"):
                        nodes += list(u)
                except GraphRecursionError:
                    raised = True
                # at 12 every node, verify included, has run, and LangGraph raises anyway
                self.assertEqual((len(nodes), nodes[-1], raised), (12, "verify", raises), limit)
            # run() keeps the row verify finished in that case, and gives an error row when cut short
            for limit, stop in [(12, "step_limit"), (11, "error")]:
                ctx.call_model = FakeModel(then=tool_turn(search()), forced=answer_turn(draft()))
                with mock.patch.object(graph, "recursion_limit", lambda lim: limit):
                    self.assertEqual(graph.run(ctx, "Q")["agent"]["stop"], stop, limit)

    def _python(self, code, env=None):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("LANGSMITH", "LANGCHAIN"))}
        e.update(env or {})
        return subprocess.run([sys.executable, "-c", code], cwd=config.ROOT, env=e, capture_output=True, text=True,
                              timeout=120)

    def test_pipeline_mode_never_loads_the_framework(self):
        code = ("import sys, json\nfrom unittest import mock\n"
                "from filingroom import cli, answer, llm, pipeline, evaluate\n"
                "import filingroom.agent, filingroom.agent.tools\n"
                "from tests.fixture_corpus import Corpus\n"
                f"Q = {Q!r}\n"
                f"D = {draft()!r}\n"
                "with Corpus() as c, mock.patch.object(llm, 'complete_json', lambda *a, **k: json.loads(json.dumps(D))):\n"
                "    r = answer.answer_question('ACME', Q, c.ix, llm.CostMeter())\n"
                "assert r['status'] == 'answered', r\n"
                "print(json.dumps(sorted(m for m in sys.modules if m.split('.')[0] in "
                "('langgraph', 'langsmith', 'langchain_core'))))\n")
        r = self._python(code)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1]), [])

    def test_tracing_is_off_even_when_the_environment_turns_it_on(self):
        """An agent run opens no network connection at all with a fake model, even with every tracing variable
        set to true and an API key present, and langsmith never builds a client."""
        code = ("import json, socket, time\n"
                "attempts = []\n"
                "real_connect = socket.socket.connect\n"
                "def connect(self, addr):\n    attempts.append(str(addr)); raise OSError('blocked by test')\n"
                "socket.socket.connect = connect\n"
                "socket.socket.connect_ex = lambda self, addr: (attempts.append(str(addr)), 111)[1]\n"
                "socket.create_connection = lambda addr, *a, **k: (attempts.append(str(addr)), "
                "(_ for _ in ()).throw(OSError('blocked')))[1]\n"
                "real_gai = socket.getaddrinfo\n"
                "def gai(host, *a, **k):\n    attempts.append('dns:' + str(host)); raise OSError('blocked')\n"
                "socket.getaddrinfo = gai\n"
                "import langsmith.client\n"
                "made = []\n"
                "orig = langsmith.client.Client.__init__\n"
                "def init(self, *a, **k):\n    made.append(1); orig(self, *a, **k)\n"
                "langsmith.client.Client.__init__ = init\n"
                "from filingroom.agent import graph\n"
                "import langsmith.utils\n"
                "from tests.fixture_corpus import Corpus, MANIFEST, P\n"
                "from tests.test_agent_graph import FakeModel, Q, answer_turn, draft, search, tool_turn\n"
                "from filingroom import llm\n"
                "with Corpus() as c:\n"
                "    ctx = graph.Context(ticker='ACME', q=Q, ix=c.ix, manifest=MANIFEST, P=P, meter=llm.CostMeter(),\n"
                "                        system='S', call_model=FakeModel([tool_turn(search()), answer_turn(draft())]))\n"
                "    row = graph.run(ctx, 'Q')\n"
                "time.sleep(1.0)\n"
                "print(json.dumps({'status': row['status'], 'attempts': attempts, 'clients': len(made), "
                "'enabled': langsmith.utils.tracing_is_enabled()}))\n")
        env = {"LANGSMITH_TRACING": "true", "LANGSMITH_TRACING_V2": "true", "LANGCHAIN_TRACING_V2": "true",
               "LANGSMITH_API_KEY": "lsv2_test_not_a_real_key", "LANGCHAIN_API_KEY": "lsv2_test_not_a_real_key",
               "LANGSMITH_ENDPOINT": "https://api.smith.langchain.com"}
        r = self._python(code, env)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out, {"status": "answered", "attempts": [], "clients": 0, "enabled": False})

    def test_without_the_switch_the_environment_would_turn_tracing_on(self):
        """Control for the test above: the same environment does enable langsmith when the graph module's switch
        is not applied, so the test above is measuring the switch, not an accident of the environment."""
        r = self._python("import langsmith.utils; print(langsmith.utils.tracing_is_enabled())",
                         {"LANGCHAIN_TRACING_V2": "true"})
        self.assertEqual(r.stdout.strip(), "True", r.stderr)
        r = self._python("import os; os.environ['LANGSMITH_TRACING'] = 'false'\n"
                         "import langsmith.utils; print(langsmith.utils.tracing_is_enabled())",
                         {"LANGCHAIN_TRACING_V2": "true"})
        self.assertEqual(r.stdout.strip(), "True", r.stderr)  # LANGSMITH_TRACING=false alone is not enough


if __name__ == "__main__":
    unittest.main()
