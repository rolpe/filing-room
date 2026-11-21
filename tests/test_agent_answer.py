"""agent.answer_question wiring: prompt text, first message, hints withheld, row. Fake model, free."""

import json
import unittest

from filingroom import agent, answer, llm
from filingroom.agent import prompts
from tests.fixture_corpus import P, Corpus
from tests.test_agent_graph import REAL, FakeModel, answer_turn, draft, search, tool_turn

Q = {"id": "rev_total", "category": "Financials", "question": "What was total revenue?", "answer_type": "currency",
     "period": "latest_fy", "where": {"forms": ["10-K"], "topics": ["mdna"]}, "search": "zzhint topline sales"}


class AgentAnswerTest(unittest.TestCase):
    def setUp(self):
        self.corpus = Corpus().__enter__()

    def tearDown(self):
        self.corpus.__exit__(None, None, None)

    def test_first_message_matches_the_pipeline_question_block(self):
        seen = {}

        def capture(*a, **k):
            seen["user"] = a[2]
            return json.loads(json.dumps(draft("not_found", cites=())))
        from unittest import mock
        with mock.patch.object(llm, "complete_json", capture):
            answer.answer_question("ACME", Q, self.corpus.ix, llm.CostMeter())
        pipe_block = seen["user"][:seen["user"].index("</question>") + len("</question>")]
        first = prompts.first_message("ACME", Q, P)
        self.assertTrue(first.startswith(pipe_block))
        self.assertNotIn("<excerpt", first)

    def test_system_prompt_states_the_budget_and_keeps_the_answering_rules(self):
        s = prompts.system(6, 8)
        self.assertIn("at most 6 turns and 8 tool calls", s)
        self.assertNotIn("{", s)
        rules = answer.load_prompt("answer.md").split("How to answer:")[1]
        mine = s.split("How to answer:")[1]
        norm = (lambda t: t.replace("excerpts", "passages").replace("excerpt", "passage"))
        self.assertEqual(mine.strip(), norm(rules).strip())  # same rules, "excerpts" -> "passages" only

    def test_notes_sections(self):
        n = prompts.notes()
        self.assertEqual(set(n), {"limit", "last_round", "repair"})
        self.assertIn("{failed}", n["repair"])

    def test_answer_question_end_to_end_with_a_fake_model(self):
        fake = FakeModel([tool_turn(search()), answer_turn(draft())])
        row = agent.answer_question("ACME", Q, self.corpus.ix, llm.CostMeter(), k=99, expand=9, call_model=fake)
        self.assertEqual((row["status"], row["mode"], row["k"], row["expand"]), ("answered", "agent", None, None))
        self.assertEqual((row["model"], row["effort"]), (answer.DEFAULT_MODEL, answer.DEFAULT_EFFORT))
        self.assertEqual(fake.calls[0]["effort"], answer.DEFAULT_EFFORT)
        self.assertIn(REAL[0], row["retrieved"])
        sent = json.dumps(fake.calls)
        for hint in ("zzhint", "topline sales"):  # the checklist's search hint is withheld
            self.assertNotIn(hint, sent)
        self.assertEqual(fake.calls[0]["messages"][0]["content"], prompts.first_message("ACME", Q, P))

    def test_budget_arguments_reach_the_graph(self):
        fake = FakeModel(then=tool_turn(search()), forced=answer_turn(draft()))
        row = agent.answer_question("ACME", Q, self.corpus.ix, llm.CostMeter(), call_model=fake, max_model_calls=3)
        self.assertEqual((row["agent"]["model_calls"], row["agent"]["stop"]), (3, "step_limit"))


if __name__ == "__main__":
    unittest.main()
