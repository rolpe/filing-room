"""Agent mode's prompt text: prompts/agent.md (system) and prompts/agent_notes.md (in-loop messages)."""

from .. import checklist, config
from ..answer import load_prompt


def system(max_model_calls: int, max_tool_calls: int) -> str:
    """The system prompt. Nothing in it varies by question, so the tools and system prefix cache across a
    company's questions; it varies only with the budget settings of a run."""
    return (load_prompt("agent.md").replace("{max_model_calls}", str(max_model_calls))
            .replace("{max_tool_calls}", str(max_tool_calls)))


def notes() -> dict[str, str]:
    """The `## name` sections of agent_notes.md."""
    out, name = {}, None
    for line in load_prompt("agent_notes.md").splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            out[name] = []
        elif name:
            out[name].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def first_message(ticker: str, q: dict, P: dict) -> str:
    """The question block, identical to the pipeline's (answer.answer_question) up to </question>, with no
    excerpts and none of the checklist's `where`/`search` hints: the agent finds the passages itself."""
    co = config.company(ticker)
    fye = co["fiscal_year_end"]
    return (f"<question id=\"{q['id']}\">\n"
            f"Company: {co['name']} (ticker {ticker}); fiscal year ends {fye[:2]}/{fye[2:]}.\n"
            f"Question: {q['question']}\n"
            f"Answer type: {q['answer_type']}\n"
            f"Target period: {checklist.describe_period(q, P)}\n"
            f"</question>\n\nSearch this company's filings with the tools, then answer.")
