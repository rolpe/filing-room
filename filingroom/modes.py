"""Pick the answering function for a mode. All have answer.answer_question's signature and return the same row
shape; agent rows add `mode` and `agent`, hybrid rows add `mode` and `hybrid` (and `agent` when escalated).
Choosing pipeline never imports the agent package's graph (langgraph); hybrid imports it only on escalation."""

from functools import partial

from . import answer

MODES = ("pipeline", "agent", "hybrid")


def answerer(mode: str = "pipeline", **agent_opts):
    """agent_opts: max_model_calls, max_tool_calls, max_tokens, repair (agent mode, and hybrid mode's agent step)."""
    if mode == "pipeline":
        if agent_opts:
            raise ValueError(f"agent options given in pipeline mode: {sorted(agent_opts)}")
        return answer.answer_question
    if mode == "agent":
        from . import agent
        return partial(agent.answer_question, **agent_opts)
    if mode == "hybrid":
        from . import hybrid
        return partial(hybrid.answer_question, **agent_opts)
    raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")


def row_mode(row: dict) -> str:
    return row.get("mode", "pipeline")
