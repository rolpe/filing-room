"""Pick the answering function for a mode. Both have answer.answer_question's signature and return the same row
shape; agent rows add `mode` and `agent`. Choosing pipeline never imports the agent package's graph (langgraph)."""

from functools import partial

from . import answer

MODES = ("pipeline", "agent")


def answerer(mode: str = "pipeline", **agent_opts):
    """agent_opts: max_model_calls, max_tool_calls, max_tokens, repair (agent mode only)."""
    if mode == "pipeline":
        if agent_opts:
            raise ValueError(f"agent options given in pipeline mode: {sorted(agent_opts)}")
        return answer.answer_question
    if mode == "agent":
        from . import agent
        return partial(agent.answer_question, **agent_opts)
    raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")


def row_mode(row: dict) -> str:
    return row.get("mode", "pipeline")
