import { api, emptyState, esc, icon, usd } from "../lib.js";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const STAGES = [
  ["register", "Check the company on EDGAR"],
  ["fetch", "Download its filings from EDGAR"],
  ["parse", "Read the filings and split them into sections"],
  ["index", "Build the search index"],
  ["answer", "Answer the 40 checklist questions"],
  ["memo", "Write the memo and check its claims"],
];
const FORMS = [["10-K", "annual reports"], ["10-Q", "quarterly reports"], ["DEF 14A", "proxy statements"], ["8-K", "earnings releases"]];

const fye = (s) => (s && s.length === 4 ? `${MONTHS[Number(s.slice(0, 2)) - 1]} ${Number(s.slice(2))}` : "–");

export function mountAdd(root, ctx) {
  let timer = null;
  let poll = null;
  let selected = null;
  let runs = { spend: { today_usd: 0, cap_usd: 3, estimate_usd: 1.2 }, jobs: [], companies: [] };

  root.innerHTML = `
    <div class="page">
      <header class="page__head">
        <h1>Add a company</h1>
        <p class="lede">Run the 40-question checklist on any US public company that files with the SEC. Downloading and reading the filings is free; answering the questions costs about ${usd(1.2)} per company and takes two to three minutes. There's no hand-built answer key for a company added here, so accuracy can't be scored in full. Instead, the numeric answers are checked automatically against the SEC's own structured data.</p>
      </header>
      <div class="add">
        <section class="add__find">
          <form class="search" role="search">
            <label class="sr-only" for="co-q">Company name or ticker</label>
            <div class="search__row">
              <span class="search__icon">${icon("search")}</span>
              <input id="co-q" type="search" placeholder="Company name or ticker, e.g. Workiva or WK" autocomplete="off">
            </div>
          </form>
          <ol class="results co-results"></ol>
        </section>
        <section class="add__detail" aria-live="polite"></section>
      </div>
      <section class="block mine"></section>
    </div>`;
  const input = root.querySelector("#co-q");
  const results = root.querySelector(".co-results");
  const detail = root.querySelector(".add__detail");
  const mine = root.querySelector(".mine");

  // ---------------------------------------------------------------- search
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      if (!q) return (results.innerHTML = "");
      try {
        const hits = await api(`/api/sec-search?q=${encodeURIComponent(q)}`);
        results.innerHTML = hits.length
          ? hits.map((h) => `<li><button class="co-hit ${selected === h.ticker ? "is-active" : ""}" data-t="${esc(h.ticker)}"><strong>${esc(h.ticker)}</strong><span>${esc(h.name)}</span></button></li>`).join("")
          : `<li class="muted pad">No SEC-registered company matches “${esc(q)}”.</li>`;
        results.querySelectorAll(".co-hit").forEach((b) => b.addEventListener("click", () => pick(b.dataset.t)));
      } catch (e) {
        results.innerHTML = `<li class="error pad">Search failed: ${esc(e.message)}</li>`;
      }
    }, 180);
  });
  root.querySelector("form").addEventListener("submit", (e) => {
    e.preventDefault();
    const first = results.querySelector(".co-hit");
    if (first) pick(first.dataset.t);
  });

  // ---------------------------------------------------------------- preview + run
  async function pick(t) {
    selected = t;
    results.querySelectorAll(".co-hit").forEach((b) => b.classList.toggle("is-active", b.dataset.t === t));
    detail.innerHTML = `<p class="muted pad">Checking ${esc(t)} on EDGAR…</p>`;
    try {
      renderPreview(await api(`/api/sec-company/${encodeURIComponent(t)}`));
    } catch (e) {
      detail.innerHTML = emptyState("alert", `Couldn't look up ${t}`, esc(e.message));
    }
  }

  function renderPreview(p) {
    const job = runs.jobs.find((j) => j.ticker === p.ticker);
    if (job && job.state === "running") return renderJob(job);
    const s = runs.spend;
    const left = s.cap_usd - s.today_usd;
    const caseStudy = p.split === "tune" || p.split === "holdout";
    const hasRun = runs.companies.find((c) => c.ticker === p.ticker)?.has_run;
    const filings = FORMS.map(([f, label]) => `<li><span class="num">${p.filings[f]}</span> ${label}</li>`).join("");
    let action;
    if (caseStudy) {
      action = `<p>${esc(p.ticker)} is one of the three case studies, so its answers are already in the app.</p>
        <a class="btn btn--primary" href="#/${esc(p.ticker)}/checklist">Open ${esc(p.ticker)}'s checklist</a>`;
    } else if (!p.eligible) {
      action = `<p class="add__no">${icon("alert")}<span>${esc(p.reason)}</span></p>`;
    } else {
      action = `
        ${hasRun ? `<p>${esc(p.ticker)} already has a checklist. <a href="#/${esc(p.ticker)}/checklist">Open it</a>, or run it again with the latest filings.</p>` : ""}
        <p class="add__cost">Costs about <strong class="num">${usd(s.estimate_usd)}</strong> and takes two to three minutes. Today: <span class="num">${usd(s.today_usd)}</span> of <span class="num">${usd(s.cap_usd)}</span> used for company runs.</p>
        <div class="add__go">
          <button class="btn btn--primary" data-go ${left < s.estimate_usd || runs.jobs.some((j) => j.state === "running") ? "disabled" : ""}>${hasRun ? "Run the checklist again" : "Run the checklist"}</button>
        </div>
        ${left < s.estimate_usd ? `<p class="error small">Today's company-run budget is used up. Raise RUN_MAX_USD_PER_DAY in .env to run more today.</p>` : ""}
        ${runs.jobs.some((j) => j.state === "running") ? `<p class="muted small">Another company is running; one at a time.</p>` : ""}`;
    }
    detail.innerHTML = `
      <article class="co-preview">
        <h2>${esc(p.name)} <span class="muted">${esc(p.ticker)}</span></h2>
        <dl class="facts">
          <div><dt>Industry</dt><dd>${esc(p.sic || "–")}</dd></div>
          <div><dt>Fiscal year ends</dt><dd>${esc(fye(p.fiscal_year_end))}</dd></div>
          <div><dt>SEC CIK</dt><dd class="num">${esc(p.cik)}</dd></div>
        </dl>
        <div><h3 class="sub-h">Recent filings on EDGAR</h3><ul class="add__filings">${filings}</ul></div>
        <div class="add__action">${action}</div>
      </article>`;
    const go = detail.querySelector("[data-go]");
    if (go) go.addEventListener("click", () => confirmRun(p));
  }

  function confirmRun(p) {
    const s = runs.spend;
    const box = detail.querySelector(".add__go");
    box.innerHTML = `
      <p class="add__confirm">This spends about <strong class="num">${usd(s.estimate_usd)}</strong> of API credit (hard stop at <span class="num">${usd(s.limit_usd)}</span>).</p>
      <button class="btn btn--primary" data-yes>Confirm and run</button>
      <button class="btn" data-no>Cancel</button>`;
    box.querySelector("[data-no]").addEventListener("click", () => renderPreview(p));
    box.querySelector("[data-yes]").addEventListener("click", async (e) => {
      e.target.disabled = true;
      try {
        const job = await api(`/api/runs/${encodeURIComponent(p.ticker)}`, { method: "POST" });
        runs.jobs = runs.jobs.filter((j) => j.ticker !== job.ticker).concat(job);
        renderJob(job);
        startPolling();
      } catch (err) {
        box.insertAdjacentHTML("beforeend", `<p class="error small">${esc(err.message)}</p>`);
        e.target.disabled = false;
      }
    });
  }

  function renderJob(job) {
    const at = STAGES.findIndex(([s]) => s === job.stage);
    const failedAt = job.state === "failed" ? at : -1;
    const steps = STAGES.map(([s, label], i) => {
      const state = job.state === "done" || i < at ? "done" : i === failedAt ? "failed" : i === at ? "now" : "todo";
      const extra = s === "answer" && state === "now" ? ` <span class="num muted">${job.done} of ${job.total}</span>` : "";
      const ic = { done: icon("checkCircle"), failed: icon("xCircle"), now: `<span class="spinner" aria-hidden="true"></span>`, todo: icon("circle") }[state];
      return `<li class="stage stage--${state}">${ic}<span>${label}${extra}</span></li>`;
    }).join("");
    const head = { running: `Running ${esc(job.name)}`, done: `${esc(job.name)} is ready`, failed: `${esc(job.name)} didn't finish` }[job.state];
    detail.innerHTML = `
      <article class="co-preview">
        <h2>${head} <span class="muted">${esc(job.ticker)}</span></h2>
        <ol class="stages">${steps}</ol>
        <p class="muted small">Spent so far: <span class="num">${usd(job.cost_usd)}</span></p>
        ${job.state === "failed" ? `<p class="add__no">${icon("alert")}<span>${esc(job.error || "Unknown error")}</span></p>` : ""}
        ${job.state === "done" ? `<div class="add__go"><a class="btn btn--primary" href="#/${esc(job.ticker)}/checklist">Open the checklist</a><a class="btn" href="#/${esc(job.ticker)}/memo">Open the memo</a></div>` : ""}
      </article>`;
  }

  // ---------------------------------------------------------------- your companies + polling
  function renderMine() {
    const list = runs.companies;
    mine.innerHTML = list.length
      ? `<h2>Your companies</h2>
         <div class="table-wrap"><table class="data"><thead><tr><th>Company</th><th>Added</th><th class="r">Numbers matching SEC data</th><th></th></tr></thead><tbody>
         ${list.map((c) => {
           const job = runs.jobs.find((j) => j.ticker === c.ticker);
           const nc = c.number_check;
           const status = job && job.state === "running" ? `<span class="muted">Running…</span>` : nc ? `<span class="num">${nc.matched} of ${nc.checked}</span>` : `<span class="muted">No checklist yet</span>`;
           return `<tr><td><strong>${esc(c.ticker)}</strong> <span class="muted">${esc(c.name)}</span></td><td class="muted">${esc(c.added || "")}</td><td class="r">${status}</td>
             <td class="r nowrap">${c.has_run ? `<a href="#/${esc(c.ticker)}/checklist">Checklist</a> · <a href="#/${esc(c.ticker)}/memo">Memo</a>` : `<button class="link" data-pick="${esc(c.ticker)}">Run</button>`}</td></tr>`;
         }).join("")}
         </tbody></table></div>`
      : "";
    mine.querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", () => pick(b.dataset.pick)));
  }

  async function refresh() {
    try {
      runs = await api("/api/runs");
    } catch {
      return;
    }
    renderMine();
    const running = runs.jobs.find((j) => j.state === "running");
    const shown = runs.jobs.find((j) => j.ticker === selected) || running;
    if (shown && (shown.state === "running" || detail.querySelector(".stages"))) {
      selected = shown.ticker;
      renderJob(shown);
    }
    if (!running && poll) {
      clearInterval(poll);
      poll = null;
      ctx.refreshCompanies();
    }
  }

  function startPolling() {
    if (!poll) poll = setInterval(refresh, 1500);
  }

  refresh().then(() => {
    if (runs.jobs.some((j) => j.state === "running")) startPolling();
    else if (!runs.companies.length) input.focus();
  });
  if (!selected) detail.innerHTML = `<div class="filing-slot filing-slot--empty">${icon("search")}<p>Search for a company to see whether its filings can support the checklist.</p></div>`;

  return {
    destroy() {
      clearTimeout(timer);
      if (poll) clearInterval(poll);
    },
  };
}
