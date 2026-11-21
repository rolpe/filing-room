"""Thin wrapper over the Anthropic SDK: JSON-schema outputs, per-run cost metering, refusal handling."""

import json
import os
import threading
from dataclasses import dataclass, field

import anthropic

from . import config  # noqa: F401  (loads .env so ANTHROPIC_API_KEY is visible)

# $ per million tokens (input, output). Cache reads bill at 0.1x input, cache writes at 1.25x.
PRICES = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-haiku-5-5": (0.10, 0.50),  # presentation pass (app)
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-fable-5-1": (10.00, 50.00),
}
# Models where we opt in to server-side refusal fallbacks (routes by refusal category).
FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5-1"}
NO_EFFORT_MODELS = {"claude-haiku-4-5"}

_client: anthropic.Anthropic | None = None

# Hard stop for any single ./fr command. Override with FILINGROOM_MAX_USD in .env.
MAX_USD_PER_COMMAND = float(os.environ.get("FILINGROOM_MAX_USD", "3.00"))
_command_spend = 0.0
_spend_lock = threading.Lock()


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            raise SystemExit("No Anthropic API key. Add ANTHROPIC_API_KEY=... to filing-room/.env (see README).")
        _client = anthropic.Anthropic(max_retries=4)
    return _client


@dataclass
class CostMeter:
    by_model: dict = field(default_factory=dict)
    limit: float | None = None  # hard stop for this meter's work (e.g. one UI run)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, model: str, usage) -> None:
        global _command_spend
        with _spend_lock:
            # Cached tokens at their real rates. complete_json never asks for caching, so for it the cache terms
            # are zero and this is the same sum as before.
            _command_spend += usage_cost(model, usage)
        with self._lock:
            m = self.by_model.setdefault(model, {"calls": 0, "input": 0, "output": 0,
                                                 "cache_read": 0, "cache_write": 0})
            m["calls"] += 1
            m["input"] += usage.input_tokens or 0
            m["output"] += usage.output_tokens or 0
            m["cache_read"] += getattr(usage, "cache_read_input_tokens", 0) or 0
            m["cache_write"] += getattr(usage, "cache_creation_input_tokens", 0) or 0

    def cost(self) -> float:
        total = 0.0
        for model, m in self.by_model.items():
            pin, pout = PRICES.get(model, PRICES["claude-opus-5"])
            total += (m["input"] * pin + m["cache_read"] * pin * 0.1 + m["cache_write"] * pin * 1.25
                      + m["output"] * pout) / 1e6
        return total

    def summary(self) -> dict:
        return {"usd": round(self.cost(), 4), "by_model": self.by_model}


def usage_cost(model: str, usage) -> float:
    """Dollars for one response's usage: input, cache reads (0.1x), cache writes (1.25x, 5-minute TTL), output."""
    pin, pout = PRICES.get(model, PRICES["claude-opus-5"])
    n = (lambda k: (usage.get(k) if isinstance(usage, dict) else getattr(usage, k, 0)) or 0)
    return (n("input_tokens") * pin + n("cache_read_input_tokens") * pin * 0.1
            + n("cache_creation_input_tokens") * pin * 1.25 + n("output_tokens") * pout) / 1e6


class LLMError(Exception):
    pass


def complete_json(model: str, system: str, user: str, schema: dict, meter: CostMeter,
                  effort: str | None = None, max_tokens: int = 16000) -> dict:
    """One request, schema-constrained JSON back. Raises LLMError on refusal or truncation."""
    if meter.limit is not None and meter.cost() >= meter.limit:
        raise SystemExit(f"Stopped: this job reached its ${meter.limit:.2f} limit.")
    if _command_spend >= MAX_USD_PER_COMMAND:
        raise SystemExit(f"Stopped: this command has spent ${_command_spend:.2f}, over the "
                         f"${MAX_USD_PER_COMMAND:.2f} cap (FILINGROOM_MAX_USD).")
    output_config: dict = {"format": {"type": "json_schema", "schema": schema}}
    if effort and model not in NO_EFFORT_MODELS:
        output_config["effort"] = effort
    kwargs = dict(model=model, max_tokens=max_tokens, system=system,
                  messages=[{"role": "user", "content": user}], output_config=output_config)
    try:
        if model in FALLBACK_MODELS:
            resp = client().beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                                 fallbacks="default", **kwargs)
        else:
            resp = client().messages.create(**kwargs)
    except anthropic.BadRequestError as e:
        if "credit balance" in str(e):
            raise SystemExit("Out of Anthropic API credits: add credits under Billing in the Console, then rerun.")
        raise
    meter.add(resp.model, resp.usage)
    if resp.stop_reason == "refusal":
        raise LLMError(f"refusal: {getattr(resp.stop_details, 'category', None)}")
    if resp.stop_reason == "max_tokens":
        raise LLMError("hit max_tokens before finishing JSON")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"bad JSON: {e}: {text[:200]}")


# ---------------------------------------------------------------- tool loop turns (agent mode)

TOOLS_TIMEOUT_S = 180.0  # per request; the SDK retries a timeout like any connection error (max_retries=4)


def _block(b) -> dict:
    """A response content block as a dict that can be sent back unchanged. Thinking blocks keep their text and
    signature exactly; fields the API returned as null (TextBlock.citations, ToolUseBlock.caller) are left out."""
    return b.model_dump(mode="json", exclude_none=True)


def complete_tools(model: str, system: str, messages: list, tools: list, meter: CostMeter, *,
                   schema: dict, effort: str | None = None, tool_choice: dict | None = None,
                   max_tokens: int = 16000, timeout: float = TOOLS_TIMEOUT_S) -> dict:
    """One turn of a tool loop. The final answer is constrained to `schema`, as in complete_json.

    Returns {content: [block dicts as returned], stop_reason, usage: {token counts}, usd, model}. Raises LLMError
    on refusal, on max_tokens (a truncated turn may hold a truncated tool input, so it is never run), and on any
    other stop that is not end_turn or tool_use. Same spend caps and refusal handling as complete_json.

    Caching: tools render first, then system, then messages. One breakpoint on the system prompt caches the tools
    and system for every question of one company; top-level automatic caching caches the growing conversation, so
    each turn of a question reads the previous turn's prefix."""
    if meter.limit is not None and meter.cost() >= meter.limit:
        raise SystemExit(f"Stopped: this job reached its ${meter.limit:.2f} limit.")
    if _command_spend >= MAX_USD_PER_COMMAND:
        raise SystemExit(f"Stopped: this command has spent ${_command_spend:.2f}, over the "
                         f"${MAX_USD_PER_COMMAND:.2f} cap (FILINGROOM_MAX_USD).")
    output_config: dict = {"format": {"type": "json_schema", "schema": schema}}
    if effort and model not in NO_EFFORT_MODELS:
        output_config["effort"] = effort
    kwargs = dict(model=model, max_tokens=max_tokens, tools=tools, messages=messages, output_config=output_config,
                  system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                  cache_control={"type": "ephemeral"})
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    c = client().with_options(timeout=timeout)
    try:
        if model in FALLBACK_MODELS:
            resp = c.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            resp = c.messages.create(**kwargs)
    except anthropic.BadRequestError as e:
        if "credit balance" in str(e):
            raise SystemExit("Out of Anthropic API credits: add credits under Billing in the Console, then rerun.")
        raise
    meter.add(resp.model, resp.usage)
    if resp.stop_reason == "refusal":
        raise LLMError(f"refusal: {getattr(resp.stop_details, 'category', None)}")
    if resp.stop_reason == "max_tokens":
        raise LLMError("hit max_tokens before finishing the turn")
    if resp.stop_reason not in ("end_turn", "tool_use"):
        raise LLMError(f"unexpected stop_reason: {resp.stop_reason}")
    u = resp.usage
    usage = {k: getattr(u, k, 0) or 0 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                 "cache_creation_input_tokens")}
    return {"content": [_block(b) for b in resp.content], "stop_reason": resp.stop_reason, "usage": usage,
            "usd": usage_cost(resp.model, u), "model": resp.model}
