"""The agent loop as a LangGraph state machine. The only module that imports langgraph (see PLAN_AGENT.md §3).

    START -> agent --(asked for tools, within budget)--> tools --(calls left)--> agent
                   --(asked for tools, tool-call cap or token budget spent)--> finalize -> verify
                   --(returned an answer, or error)--> verify
             tools --(the next call is the last one allowed)--> finalize
             verify --(no quote verified, repair on and unused, budget left)--> agent
                    --(otherwise)--> END

Data about the run lives in State. Everything else (the company's index, the meter, the limits, and the function
that calls the model) is runtime context: a test passes a scripted fake model there, so the graph is tested for
free. Budgets are counters in State that the routing functions read; LangGraph's recursion_limit is only a
backstop, and GraphRecursionError becomes an `error` row.
"""

import copy
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, Callable, TypedDict
import operator

# ---------------------------------------------------------------- tracing off, before langgraph loads
# langsmith (a dependency of langchain-core) can send traces to a hosted service. It is off unless an environment
# variable turns it on; langsmith reads LANGSMITH_/LANGCHAIN_ TRACING_V2 first, then TRACING, and caches the
# lookup. This tool is local and private, so all four are forced off, and langsmith's global switch, which takes
# precedence over the environment, is set to False as well.
TRACING_VARS = ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2")
for _v in TRACING_VARS:
    os.environ[_v] = "false"

import langsmith  # noqa: E402
import langsmith.utils  # noqa: E402

langsmith.utils.get_env_var.cache_clear()
langsmith.configure(enabled=False)

from langgraph.errors import GraphRecursionError  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.runtime import Runtime  # noqa: E402

from .. import answer, llm  # noqa: E402
from ..index import Index  # noqa: E402
from . import tools  # noqa: E402

DEFAULT_MAX_MODEL_CALLS = 6
DEFAULT_MAX_TOOL_CALLS = 8
DEFAULT_MAX_TOKENS = 30_000

# TODO(increment 4): load these two from prompts/agent.md with the system prompt.
LIMIT_TEXT = ("Limit reached: no more tool calls for this question. Answer now from the passages already shown, "
              "or return not_found.")
LAST_ROUND_TEXT = ("Those were your last tool results for this question. Answer now from the passages shown, "
                   "or return not_found.")
REPAIR_TEXT = ("None of the quotes in your answer could be found in the passage it names:\n{failed}\n\n"
               "A quote must be copied word for word from the chunk it cites. Answer again with exact quotes "
               "(you can reread a passage with get_chunk), or return not_found.")


# ---------------------------------------------------------------- state and context

def _union(left: list, right: list) -> list:
    """Reducer: append, keeping each id once and in first-seen order."""
    return left + [x for x in right if x not in left]


class State(TypedDict, total=False):
    messages: Annotated[list, operator.add]  # Anthropic-format messages; assistant content stored as returned
    seen: Annotated[list, _union]            # chunk ids whose text a tool showed the model -> row["retrieved"]
    trace: Annotated[list, operator.add]     # one entry per tool call
    model_calls: Annotated[int, operator.add]
    tool_calls: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]     # input + cached input + output, summed over calls
    usd: Annotated[float, operator.add]
    draft: dict | None                       # the model's answer JSON, before verification
    error: str | None
    repairs: int
    repair_pending: bool                     # verify asked for one more answer
    stop: str                                # model_done | step_limit | token_limit | error
    row: dict


@dataclass
class Limits:
    model_calls: int = DEFAULT_MAX_MODEL_CALLS   # every model call counts, including the final forced answer
    tool_calls: int = DEFAULT_MAX_TOOL_CALLS
    tokens: int = DEFAULT_MAX_TOKENS             # exploration budget; the final forced answer is always allowed
    repair: bool = False

    def __post_init__(self):
        if self.model_calls < 2:
            raise ValueError("the agent needs at least 2 model calls: one to search, one to answer")


@dataclass
class Context:
    """What a run needs that isn't data about the run. `call_model` has llm.complete_tools' signature:
    call_model(model, system, messages, tools, meter, *, effort, tool_choice) -> turn dict with
    content (list of block dicts), stop_reason, usage (dict of token counts) and usd."""
    ticker: str
    q: dict
    ix: Index
    manifest: list[dict]
    P: dict
    meter: llm.CostMeter
    system: str
    call_model: Callable[..., dict]
    model: str = answer.DEFAULT_MODEL
    effort: str | None = answer.DEFAULT_EFFORT
    limits: Limits = field(default_factory=Limits)
    started: float = field(default_factory=time.time)
    tool_specs: list[dict] = field(default=None)

    def __post_init__(self):
        if self.tool_specs is None:
            self.tool_specs = tools.specs(self.ix)


# ---------------------------------------------------------------- helpers

def _tool_uses(msg: dict) -> list[dict]:
    content = msg.get("content")
    return [b for b in content if b.get("type") == "tool_use"] if isinstance(content, list) else []


def _usage_tokens(u: dict) -> int:
    return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens",
                                            "cache_creation_input_tokens", "output_tokens"))


def _parse_draft(turn: dict) -> tuple[dict | None, str | None]:
    text = "".join(b.get("text", "") for b in turn["content"] if b.get("type") == "text")
    try:
        d = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"bad JSON: {e}: {text[:200]}"
    req = answer.ANSWER_SCHEMA["required"]
    if not isinstance(d, dict) or any(k not in d for k in req) or d["status"] not in ("answered", "not_found") \
            or not isinstance(d["citations"], list):
        return None, f"answer JSON does not match the schema: {text[:200]}"
    return d, None


def _call(state: State, ctx: Context, tool_choice: dict | None) -> tuple[dict, dict]:
    """One model call. Returns (state update, turn); on LLMError the update carries the error and turn is None."""
    try:
        turn = ctx.call_model(ctx.model, ctx.system, state["messages"], ctx.tool_specs, ctx.meter,
                              effort=ctx.effort, tool_choice=tool_choice)
    except llm.LLMError as e:
        return {"model_calls": 1, "error": str(e), "stop": "error"}, None
    upd = {"messages": [{"role": "assistant", "content": turn["content"]}], "model_calls": 1,
           "tokens": _usage_tokens(turn.get("usage") or {}), "usd": float(turn.get("usd") or 0.0)}
    return upd, turn


def _refuse_reason(state: State, lim: Limits) -> str | None:
    """After a turn that asked for tools: refuse them if they would pass the tool-call cap, or if the token budget
    is already spent (running them would make the overshoot unbounded). The tool-call cap is checked first."""
    pending = len(_tool_uses(state["messages"][-1]))
    if state["tool_calls"] + pending > lim.tool_calls:
        return "step_limit"
    if state["tokens"] >= lim.tokens:
        return "token_limit"
    return None


def _last_round(state: State, lim: Limits) -> bool:
    """True when the next model call is the last one allowed, so it must be the answer (tools off)."""
    return state["model_calls"] + 1 >= lim.model_calls


# ---------------------------------------------------------------- nodes

def agent_node(state: State, runtime: Runtime[Context]) -> dict:
    upd, turn = _call(state, runtime.context, None)
    if turn is None or any(b.get("type") == "tool_use" for b in turn["content"]):
        return upd
    draft, err = _parse_draft(turn)
    return {**upd, "draft": draft, "error": err, "stop": "error" if err else "model_done"}


def tools_node(state: State, runtime: Runtime[Context]) -> dict:
    ctx = runtime.context
    seen = set(state.get("seen", []))
    results, trace, shown = [], [], []
    for tu in _tool_uses(state["messages"][-1]):
        r = tools.run(tu["name"], tu.get("input") or {}, ix=ctx.ix, manifest=ctx.manifest, P=ctx.P, seen=seen)
        seen.update(r.shown)
        shown += r.shown
        results.append({"type": "tool_result", "tool_use_id": tu["id"], "content": r.text,
                        **({"is_error": True} if r.is_error else {})})
        trace.append({"turn": state["model_calls"], "tool": tu["name"], "input": tu.get("input") or {},
                      "shown": r.shown, "refs": r.refs, "error": r.is_error})
    if _last_round(state, ctx.limits):
        results.append({"type": "text", "text": LAST_ROUND_TEXT})  # finalize follows: say so after the results
    return {"messages": [{"role": "user", "content": results}], "seen": shown, "trace": trace,
            "tool_calls": len(results) - (results[-1]["type"] == "text")}


def finalize_node(state: State, runtime: Runtime[Context]) -> dict:
    """A budget ran out; one call with tools off. Two entries: from agent, with tool requests to refuse (tool-call
    cap or token budget), which get 'limit reached' results; from tools, after the last allowed tool round,
    whose results already end with a note to answer now (step limit)."""
    ctx = runtime.context
    pending = _tool_uses(state["messages"][-1])
    if pending:
        reason = _refuse_reason(state, ctx.limits) or "step_limit"
        note = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tu["id"], "content": LIMIT_TEXT,
                                             "is_error": True} for tu in pending]
                + [{"type": "text", "text": LIMIT_TEXT}]}
        state = {**state, "messages": state["messages"] + [note]}
        extra = [note]
    else:
        reason, extra = "step_limit", []
    upd, turn = _call(state, ctx, {"type": "none"})
    upd["messages"] = extra + upd.get("messages", [])
    if turn is None:
        return upd
    if _tool_uses({"content": turn["content"]}):
        return {**upd, "error": "model asked for tools after the limit", "stop": "error"}
    draft, err = _parse_draft(turn)
    return {**upd, "draft": draft, "error": err, "stop": "error" if err else reason}


def verify_node(state: State, runtime: Runtime[Context]) -> dict:
    """Same verifier as the pipeline: answer.build_row. A repair round may follow (see route_after_verify)."""
    ctx = runtime.context
    row = build_agent_row(state, ctx)
    upd: dict = {"row": row, "repair_pending": False}
    if _wants_repair(state, ctx, row):
        failed = "\n".join(f'- [{c["chunk_id"]}] "{c["quote"]}"' for c in row["citations"])
        upd.update(repairs=state.get("repairs", 0) + 1, repair_pending=True, draft=None, error=None,
                   messages=[{"role": "user", "content": REPAIR_TEXT.format(failed=failed)}])
    return upd


def _wants_repair(state: State, ctx: Context, row: dict) -> bool:
    lim = ctx.limits
    return (lim.repair and state.get("repairs", 0) < 1 and row["status"] == "unsupported"
            and state["model_calls"] + 2 <= lim.model_calls and state["tokens"] < lim.tokens)
    # two calls must be left: the repair turn may ask for tools, and then finalize needs the last call


# ---------------------------------------------------------------- routing

def route_after_agent(state: State, runtime: Runtime[Context]) -> str:
    if state.get("error") or not _tool_uses(state["messages"][-1]):
        return "verify"
    return "finalize" if _refuse_reason(state, runtime.context.limits) else "tools"


def route_after_tools(state: State, runtime: Runtime[Context]) -> str:
    return "finalize" if _last_round(state, runtime.context.limits) else "agent"


def route_after_verify(state: State) -> str:
    return "agent" if state.get("repair_pending") else END


# ---------------------------------------------------------------- the row

def build_agent_row(state: State, ctx: Context, error: str | None = None) -> dict:
    draft, err = state.get("draft"), error or state.get("error")
    out = copy.deepcopy(draft) if draft else {"status": "error", "answer": "", "value": "", "unit": "", "period": "",
                                              "citations": [], "confidence": "low"}
    if draft is None and err is None:
        err = "no answer produced"
    seen = list(state.get("seen", []))
    row = answer.build_row(ctx.ticker, ctx.q, ctx.ix, out, retrieved=seen, model=ctx.model, effort=ctx.effort,
                           k=None, expand=None, started=ctx.started, error=None if draft else err)
    row["mode"] = "agent"
    row["agent"] = {
        "model_calls": state.get("model_calls", 0), "tool_calls": state.get("tool_calls", 0),
        "tokens": state.get("tokens", 0), "usd": round(state.get("usd", 0.0), 6),
        "stop": "error" if error else state.get("stop", "error"), "repairs": state.get("repairs", 0),
        # a verified quote from a chunk no tool showed would mean an answer from memory; it should never happen
        "cited_unseen": [c["chunk_id"] for c in row["citations"] if c.get("verified") and c["chunk_id"] not in seen],
        "trace": list(state.get("trace", [])),
    }
    return row


# ---------------------------------------------------------------- build, compile, run

def build() -> StateGraph:
    g = StateGraph(State, context_schema=Context)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_node("finalize", finalize_node)
    g.add_node("verify", verify_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route_after_agent, ["tools", "finalize", "verify"])
    g.add_conditional_edges("tools", route_after_tools, ["agent", "finalize"])
    g.add_edge("finalize", "verify")
    g.add_conditional_edges("verify", route_after_verify, ["agent", END])
    return g


_compiled = None
_compile_lock = threading.Lock()


def compiled():
    """One compiled graph per process, shared by worker threads (each invoke has its own state and context)."""
    global _compiled
    with _compile_lock:
        if _compiled is None:
            _compiled = build().compile()
        return _compiled


def recursion_limit(lim: Limits) -> int:
    """Backstop above the longest legal path. At most M model calls (agent or finalize) run, and every other step
    (tools, verify) directly follows one of them, so a run is at most 2M super-steps. LangGraph also counts
    writing the input as a step, and raises when the count reaches the limit even if the run just finished, so
    a path of n steps needs a limit of n + 1. Two more on top as margin."""
    return 2 * lim.model_calls + 3


def run(ctx: Context, first_message: str) -> dict:
    """Answer one question. Streams full state after each super-step so that, if the backstop fires, the row still
    reports what the run did before it stopped."""
    last: dict = {}
    try:
        start = {"messages": [{"role": "user", "content": first_message}], "seen": [], "trace": [], "model_calls": 0,
                 "tool_calls": 0, "tokens": 0, "usd": 0.0, "draft": None, "error": None, "repairs": 0,
                 "repair_pending": False, "stop": ""}
        for last in compiled().stream(start,
                                      {"recursion_limit": recursion_limit(ctx.limits)}, context=ctx,
                                      stream_mode="values"):
            pass
    except GraphRecursionError as e:
        if last.get("row") and not last.get("repair_pending"):
            return last["row"]  # verify had finished: LangGraph raises when the last step lands on the limit
        return build_agent_row({**last, "draft": None}, ctx, error=f"recursion limit: {str(e).splitlines()[0]}")
    return last["row"]
