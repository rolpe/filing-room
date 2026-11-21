"""Agent mode: the model drives retrieval through three read-only tools in a loop (see PLAN_AGENT.md).

answer_question has the pipeline's signature (answer.answer_question) and returns a row of the same shape plus
`mode` and `agent`. Nothing here imports langgraph at module load: filingroom/agent/graph.py is the only module
that does, and it is imported inside answer_question, so pipeline mode never loads the framework.
"""

import functools
import time

DEFAULT_MAX_MODEL_CALLS = 6      # every model call counts, the forced final answer included
DEFAULT_MAX_TOOL_CALLS = 8
DEFAULT_MAX_TOKENS = 100_000     # input + cached input + output, summed over calls; set from increment 4's spike
                                 # (see PLAN_AGENT.md §14): 30,000 bound a 6-call list question; ~$0.10-0.17 worst case


_DEFAULT = object()  # "the pipeline's default", resolved at call time so importing this module stays light


def answer_question(ticker: str, q: dict, ix, meter, model: str | None = None, effort=_DEFAULT,
                    k: int | None = None, expand: int | None = None, *,
                    max_model_calls: int = DEFAULT_MAX_MODEL_CALLS, max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
                    max_tokens: int = DEFAULT_MAX_TOKENS, repair: bool = False, call_model=None) -> dict:
    """Answer one question in agent mode. `k` and `expand` are the pipeline's retrieval settings and are ignored
    (the model chooses its own searches); they are accepted so both modes can be called the same way."""
    from .. import answer, checklist, edgar, llm
    from . import graph, prompts  # graph imports langgraph

    started = time.time()
    if effort is _DEFAULT:
        effort = answer.DEFAULT_EFFORT  # same as the pipeline, so the two modes cannot drift apart
    P = checklist.periods(ticker)
    limits = graph.Limits(model_calls=max_model_calls, tool_calls=max_tool_calls, tokens=max_tokens, repair=repair)
    ctx = graph.Context(
        ticker=ticker, q=q, ix=ix, manifest=edgar.manifest(ticker), P=P, meter=meter,
        system=prompts.system(max_model_calls, max_tool_calls),
        call_model=call_model or functools.partial(llm.complete_tools, schema=answer.ANSWER_SCHEMA),
        model=model or answer.DEFAULT_MODEL, effort=effort, limits=limits, started=started)
    return graph.run(ctx, prompts.first_message(ticker, q, P))
