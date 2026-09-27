"""Render an answered checklist as Markdown (the analyst-facing deliverable)."""

from . import config

STATUS_NOTE = {"not_found": "_Not found in the filings._", "unsupported": "⚠ _Answer given but no citation verified; treat as unsupported._",
               "error": "⚠ _Error while answering._"}


def checklist_md(ticker: str, rows: list[dict], meta: dict) -> str:
    co = config.company(ticker)
    lines = [f"# {co['name']} ({ticker}): diligence checklist", "",
             f"Generated {meta['timestamp']} from {meta['n_filings']} SEC filings · model `{meta['model']}` · "
             f"cost ${meta['cost_usd']:.2f}. Every answer cites a passage that was mechanically verified to appear "
             "in the filing; answers without a verified citation are flagged.", ""]
    category = None
    for r in rows:
        if r["category"] != category:
            category = r["category"]
            lines += [f"## {category}", ""]
        lines.append(f"**{r['question']}**  ")
        if r["status"] == "answered" or r["status"] == "unsupported":
            lines.append(r["answer"])
        if r["status"] in STATUS_NOTE:
            if r["status"] == "not_found" and r["answer"]:
                lines.append(r["answer"] + "  ")
            lines.append(STATUS_NOTE[r["status"]])
        for c in r["citations"]:
            if c.get("verified"):
                lines.append(f"> “{c['quote']}” ([{c['doc_id']} · {c['section'][:60]}]({c['url']}))")
        lines.append("")
    return "\n".join(lines)
