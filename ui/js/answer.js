// The answer panel: question, answer, marks, golden answer, cited quotes, and the filing open at the quote.
import { docLabel, esc, expectedText, fmtValue, focusQuote, gradeMark, icon, mountFiling, prettyHeading, quoteHTML, statusMark } from "./lib.js";

const CONFIDENCE = { high: "High", medium: "Medium", low: "Low" };

export function renderAnswer(el, { ticker, item, note = "" }) {
  const a = item.answer;
  if (!a) {
    el.innerHTML = `<div class="answer-panel"><h2 class="q-title">${esc(item.question)}</h2><p class="muted">No answer was recorded for this question.</p></div>`;
    return;
  }
  const verified = (item.citations || []).filter((c) => c.verified);
  const found = a.status === "answered" || a.status === "unsupported";
  const value = found && a.value ? fmtValue(a.value, a.unit) : "";
  const g = item.graded;
  const golden =
    g && g.expected
      ? `<details class="golden">
          <summary>${icon("chevronDown", "golden__chev")}Compare with the golden answer</summary>
          <p>${esc(expectedText(g.expected))}</p>
          ${g.judge_reason ? `<p class="muted">Grader's note: ${esc(g.judge_reason)}</p>` : ""}
          ${g.eval_run ? `<p class="muted">Graded in eval run “${esc(g.eval_run.replace(/^\d{4}-\d{2}-\d{2}_\d{4}_?/, ""))}”.</p>` : ""}
        </details>`
      : "";

  el.innerHTML = `
    <article class="answer-panel">
      <h2 class="q-title">${esc(item.question)}</h2>
      ${note ? `<p class="muted small">${note}</p>` : ""}
      <div class="answer-text ${found ? "" : "answer-text--nf"}">
        ${found ? esc(a.answer) : `<strong>Not found in the filings.</strong> ${esc(a.answer)}`}
      </div>
      <dl class="facts">
        <div><dt>Status</dt><dd>${statusMark(a.status)}</dd></div>
        ${value ? `<div><dt>Value</dt><dd class="num">${value}</dd></div>` : ""}
        ${a.period && found ? `<div><dt>Period</dt><dd>${esc(a.period)}</dd></div>` : ""}
        ${found ? `<div><dt>Confidence</dt><dd>${esc(CONFIDENCE[a.confidence] || a.confidence || "–")}</dd></div>` : ""}
        ${g ? `<div><dt>Eval</dt><dd>${gradeMark(g)}</dd></div>` : ""}
      </dl>
      ${golden}
      ${
        verified.length
          ? `<section class="sources" aria-label="Cited quotes">
              <h3 class="sub-h">Cited ${verified.length === 1 ? "quote" : `quotes (${verified.length})`}</h3>
              <ol class="source-list">
                ${verified
                  .map(
                    (c, i) => `<li><button class="source ${i === 0 ? "is-active" : ""}" data-i="${i}" aria-pressed="${i === 0}">
                      <span class="source__quote">“${quoteHTML(c.quote)}”</span>
                      <span class="source__doc">${esc(docLabel(c.doc_id))} · ${esc(prettyHeading(c.section || ""))}</span>
                    </button></li>`,
                  )
                  .join("")}
              </ol>
            </section>
            <div class="filing-slot"></div>`
          : `<div class="filing-slot filing-slot--empty">${icon("doc")}<p>No passage is cited. ${
              found ? "" : `The model found nothing that answers this in the retrieved passages. <a href="#/${ticker}/search?q=${encodeURIComponent(item.question)}">Search the filings yourself</a>.`
            }</p></div>`
      }
    </article>`;

  if (!verified.length) return;
  const slot = el.querySelector(".filing-slot");
  let shown = null; // chunk currently open in the filing pane
  const qIndex = (j) => {
    // index of citation j among the quotes highlighted in the open passage, or -1
    const same = verified.filter((x) => x.chunk_id === shown);
    return verified[j].chunk_id === shown ? same.indexOf(verified[j]) : -1;
  };
  el.querySelectorAll(".source").forEach((b) => {
    const j = Number(b.dataset.i);
    const on = () => qIndex(j) >= 0 && focusQuote(slot, qIndex(j), true);
    const off = () => qIndex(j) >= 0 && focusQuote(slot, qIndex(j), false);
    b.addEventListener("mouseenter", on);
    b.addEventListener("focus", on);
    b.addEventListener("mouseleave", off);
    b.addEventListener("blur", off);
  });
  const open = (i) => {
    el.querySelectorAll(".source").forEach((b) => {
      const on = Number(b.dataset.i) === i;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-pressed", String(on));
    });
    const c = verified[i];
    // Highlight every cited quote that lives in the same passage.
    const quotes = verified.filter((x) => x.chunk_id === c.chunk_id).map((x) => x.quote);
    shown = c.chunk_id;
    mountFiling(slot, { ticker, chunkId: c.chunk_id, quotes });
  };
  el.querySelectorAll(".source").forEach((b) => b.addEventListener("click", () => open(Number(b.dataset.i))));
  open(0);
}
