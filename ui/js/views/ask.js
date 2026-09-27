import { renderAnswer } from "../answer.js";
import { api, emptyState, esc, icon, usd } from "../lib.js";

const EXAMPLES = {
  BILL: ["What was BILL's net dollar-based retention rate in fiscal 2026?", "How much did BILL spend on share repurchases in fiscal 2026?"],
  RPD: ["Who is Rapid7's chief executive officer?", "What was Rapid7's ARR at the end of the latest quarter?"],
  BOX: ["What was Box's net retention rate in the latest quarter?", "How much did Box spend on share repurchases in fiscal 2026?"],
};
const history = {}; // per company, this browser session only

export function mountAsk(root, ctx) {
  const { ticker, company } = ctx;
  const past = (history[ticker] ||= []);
  const examples = EXAMPLES[ticker] || [`Who is ${company.name}'s chief executive officer?`, `What was ${company.name}'s total revenue in the most recent fiscal year?`];
  root.innerHTML = `
    <div class="split">
      <aside class="pane pane--list">
        <form class="ask">
          <h1 class="co-name">Ask ${esc(company.name)} a question</h1>
          <p class="muted small">Answered only from ${esc(company.name)}'s SEC filings, with a quote checked against the source. Each question is a live call to Claude.${company.split === "holdout" ? " Live answers are separate from Box's recorded test run, which stays unchanged." : ""}</p>
          <label class="sr-only" for="ask-q">Your question</label>
          <textarea id="ask-q" name="q" rows="4" maxlength="500" placeholder="e.g. ${esc(examples[0])}"></textarea>
          <div class="ask__row">
            <p class="ask__cost small"></p>
            <button class="btn btn--primary" type="submit">Ask</button>
          </div>
          <p class="ask__examples small">Try: ${examples.map((q) => `<button type="button" class="link" data-ex="${esc(q)}">${esc(q)}</button>`).join(" · ")}</p>
        </form>
        <div class="ask-history"></div>
      </aside>
      <section class="pane pane--detail" aria-live="polite"><div class="filing-slot filing-slot--empty">${icon("doc")}<p>The answer and the filing passage behind it will appear here.</p></div></section>
    </div>`;
  const form = root.querySelector("form");
  const btn = form.querySelector("button[type=submit]");
  const cost = form.querySelector(".ask__cost");
  const detail = root.querySelector(".pane--detail");
  const hist = root.querySelector(".ask-history");

  function renderCost() {
    const s = ctx.spend();
    const left = s.cap_usd - s.today_usd;
    cost.innerHTML = `Costs about $0.02–0.05. Today: <span class="num">${usd(s.today_usd)}</span> of <span class="num">${usd(s.cap_usd)}</span> used.`;
    btn.disabled = left < s.ask_estimate_usd;
    if (btn.disabled) cost.innerHTML += ` <strong>Daily limit reached.</strong>`;
  }
  function renderHistory() {
    hist.innerHTML = past.length
      ? `<h2 class="q-group">Asked this session</h2><ul>${past
          .map((p, i) => `<li><button class="q-row ${i === 0 ? "is-active" : ""}" data-i="${i}"><span class="q-row__text">${esc(p.question)}</span><span class="num muted small">${usd(p.cost_usd)}</span></button></li>`)
          .join("")}</ul>`
      : "";
    hist.querySelectorAll("[data-i]").forEach((b) =>
      b.addEventListener("click", () => {
        hist.querySelectorAll(".q-row").forEach((x) => x.classList.toggle("is-active", x === b));
        show(past[Number(b.dataset.i)]);
      }),
    );
  }
  function show(r) {
    renderAnswer(detail, {
      ticker,
      item: { question: r.question, answer: r, citations: r.citations },
      note: `Live answer · cost <span class="num">${usd(r.cost_usd)}</span>`,
    });
  }

  form.querySelectorAll("[data-ex]").forEach((b) => b.addEventListener("click", () => (form.q.value = b.dataset.ex, form.q.focus())));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = form.q.value.trim();
    if (!q) return form.q.focus();
    btn.disabled = true;
    btn.textContent = "Asking…";
    detail.innerHTML = `<div class="filing-slot filing-slot--empty"><p>Retrieving passages and asking Claude…</p></div>`;
    try {
      const r = await api(`/api/ask/${ticker}`, { method: "POST", body: { question: q } });
      ctx.setSpend(r.spend);
      past.unshift(r);
      renderHistory();
      show(r);
    } catch (err) {
      detail.innerHTML = emptyState("alert", err.status === 402 ? "Daily limit reached" : "The question couldn't be answered", esc(err.message));
    } finally {
      btn.textContent = "Ask";
      renderCost();
    }
  });
  renderCost();
  renderHistory();
  if (past.length) show(past[0]);
  return { spendChanged: renderCost };
}
