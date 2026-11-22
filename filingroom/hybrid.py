"""Hybrid mode: the pipeline answers first, and only a non-answer is asked again in agent mode.

answer_question has the other two modes' signature (answer.answer_question). The pipeline's call is made exactly as
in pipeline mode. When its row's final status (after quote verification) is not_found or unsupported, agent mode
answers the same question, sharing the same meter, and its row replaces the pipeline's unless it is an error. A
pipeline error row is not escalated. The agent package is imported only at the point of escalation, so a question
the pipeline answers never loads it or langgraph.
"""

from . import answer

ESCALATE = ("not_found", "unsupported")
# agent.answer_question's keyword-only options, checked before the pipeline call so a typo costs nothing
AGENT_OPTIONS = ("max_model_calls", "max_tool_calls", "max_tokens", "repair", "call_model")


def answer_question(ticker: str, q: dict, ix, meter, model: str = answer.DEFAULT_MODEL,
                    effort: str | None = answer.DEFAULT_EFFORT, k: int = answer.DEFAULT_K,
                    expand: int = answer.DEFAULT_EXPAND, **agent_opts) -> dict:
    """Answer one question in hybrid mode. `k` and `expand` go to the pipeline; `agent_opts` (AGENT_OPTIONS) go to
    the agent step. The row has every pipeline key plus `mode: "hybrid"` and `hybrid`: escalated, pipeline_status,
    pipeline_seconds, and when escalated agent_status, agent_seconds, used ("agent" or "pipeline") and, if the agent
    failed, agent_error. Every escalated row also carries the agent's own `agent` block, so the calls and cost of
    the second step are recorded whichever answer is kept. `seconds` is the whole question: both steps when
    escalated."""
    unknown = sorted(set(agent_opts) - set(AGENT_OPTIONS))
    if unknown:
        raise TypeError(f"unknown agent options for hybrid mode: {unknown}")
    pipe = answer.answer_question(ticker, q, ix, meter, model=model, effort=effort, k=k, expand=expand)
    info = {"escalated": False, "pipeline_status": pipe["status"], "pipeline_seconds": pipe["seconds"]}
    if pipe["status"] not in ESCALATE:
        return {**pipe, "mode": "hybrid", "hybrid": info}

    from . import agent  # the agent package, and langgraph with it, loads here and nowhere else in this mode
    second = agent.answer_question(ticker, q, ix, meter, model=model, effort=effort, **agent_opts)
    info.update(escalated=True, agent_status=second["status"], agent_seconds=second["seconds"])
    if second["status"] == "error":
        info.update(used="pipeline", agent_error=second["error"])
        row = {**pipe, "agent": second["agent"]}
    else:
        info["used"] = "agent"
        row = second
    return {**row, "mode": "hybrid", "seconds": round(pipe["seconds"] + second["seconds"], 1), "hybrid": info}
