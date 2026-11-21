"""llm.complete_tools against a fake SDK client (real SDK response types, no network), and the spend meter."""

import unittest
from unittest import mock

import anthropic
from anthropic.types import Message

from filingroom import llm

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False}
TOOLS = [{"name": "search_filings", "description": "d", "input_schema": {"type": "object", "properties": {}}}]


def message(content, stop="tool_use", usage=None, model="claude-sonnet-5"):
    return Message.model_validate({
        "id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": content,
        "stop_reason": stop, "stop_sequence": None,
        "usage": usage or {"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 2000,
                           "cache_creation_input_tokens": 400}})


class FakeClient:
    def __init__(self, resp):
        self.resp, self.calls, self.options = resp, [], []
        self.messages = self
        self.beta = self

    def with_options(self, **kw):
        self.options.append(kw)
        return self

    def create(self, **kw):
        self.calls.append(kw)
        if isinstance(self.resp, Exception):
            raise self.resp
        return self.resp


THINK = {"type": "thinking", "thinking": "", "signature": "sig-abc=="}
TOOL_USE = {"type": "tool_use", "id": "toolu_1", "name": "search_filings", "input": {"query": "total revenue"}}


class CompleteToolsTest(unittest.TestCase):
    def setUp(self):
        self.spend = mock.patch.object(llm, "_command_spend", 0.0)
        self.spend.start()

    def tearDown(self):
        self.spend.stop()

    def call(self, resp, **kw):
        fake = FakeClient(resp)
        with mock.patch.object(llm, "client", lambda: fake):
            out = llm.complete_tools("claude-sonnet-5", "SYSTEM", [{"role": "user", "content": "Q"}], TOOLS,
                                     llm.CostMeter(), schema=SCHEMA, effort="medium", **kw)
        return out, fake

    def test_request_shape(self):
        _, fake = self.call(message([THINK, TOOL_USE]))
        kw = fake.calls[0]
        self.assertEqual(kw["model"], "claude-sonnet-5")
        self.assertEqual(kw["max_tokens"], 16000)
        self.assertEqual(kw["output_config"], {"format": {"type": "json_schema", "schema": SCHEMA}, "effort": "medium"})
        self.assertEqual(kw["system"], [{"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}])
        self.assertEqual(kw["cache_control"], {"type": "ephemeral"})
        self.assertIs(kw["tools"], TOOLS)
        self.assertNotIn("tool_choice", kw)
        self.assertNotIn("thinking", kw)  # same as the pipeline: the model's default
        self.assertEqual(fake.options, [{"timeout": llm.TOOLS_TIMEOUT_S}])
        _, fake = self.call(message([{"type": "text", "text": '{"a": "x"}'}], stop="end_turn"),
                            tool_choice={"type": "none"})
        self.assertEqual(fake.calls[0]["tool_choice"], {"type": "none"})

    def test_content_comes_back_as_sendable_dicts_in_order(self):
        out, _ = self.call(message([THINK, {"type": "text", "text": "Searching."}, TOOL_USE]))
        self.assertEqual(out["content"], [THINK, {"type": "text", "text": "Searching."}, TOOL_USE])
        self.assertEqual(out["stop_reason"], "tool_use")
        redacted = {"type": "redacted_thinking", "data": "opaque"}
        out, _ = self.call(message([redacted, TOOL_USE]))
        self.assertEqual(out["content"][0], redacted)

    def test_usage_and_cost_count_cache_at_real_rates(self):
        out, _ = self.call(message([TOOL_USE]))
        self.assertEqual(out["usage"], {"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 2000,
                                        "cache_creation_input_tokens": 400})
        want = (1000 * 2.0 + 2000 * 0.2 + 400 * 2.5 + 100 * 10.0) / 1e6
        self.assertAlmostEqual(out["usd"], want)
        self.assertAlmostEqual(llm._command_spend, want)

    def test_bad_stops_raise(self):
        for stop in ("refusal", "max_tokens", "pause_turn"):
            with self.assertRaises(llm.LLMError, msg=stop):
                self.call(message([TOOL_USE], stop=stop))

    def test_spend_caps_still_stop(self):
        with mock.patch.object(llm, "_command_spend", llm.MAX_USD_PER_COMMAND):
            with self.assertRaises(SystemExit):
                self.call(message([TOOL_USE]))
        m = llm.CostMeter(limit=0.0)
        with mock.patch.object(llm, "client", lambda: FakeClient(message([TOOL_USE]))), self.assertRaises(SystemExit):
            llm.complete_tools("claude-sonnet-5", "S", [], TOOLS, m, schema=SCHEMA)


class MeterTest(unittest.TestCase):
    def test_pipeline_spend_is_unchanged_without_cache(self):
        """complete_json never caches: the per-command spend is the old formula, to the last bit."""
        class U:  # an SDK usage with cache fields absent or None
            input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens = 10123, 777, None, 0
        for model in llm.PRICES:
            pin, pout = llm.PRICES[model]
            old = ((U.input_tokens or 0) * pin + (U.output_tokens or 0) * pout) / 1e6
            self.assertEqual(llm.usage_cost(model, U), old, model)
            with mock.patch.object(llm, "_command_spend", 0.0):
                llm.CostMeter().add(model, U)
                self.assertEqual(llm._command_spend, old, model)

    def test_meter_cost_and_command_spend_agree_with_cache(self):
        u = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 1000,
             "cache_creation_input_tokens": 300}

        class U:
            pass
        for k, v in u.items():
            setattr(U, k, v)
        with mock.patch.object(llm, "_command_spend", 0.0):
            m = llm.CostMeter()
            m.add("claude-sonnet-5", U)
            self.assertAlmostEqual(llm._command_spend, m.cost())
            self.assertAlmostEqual(llm.usage_cost("claude-sonnet-5", u), m.cost())


if __name__ == "__main__":
    unittest.main()
