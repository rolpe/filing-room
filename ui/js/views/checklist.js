import { renderAnswer } from "../answer.js";
import { api, emptyState, esc, fmtDate, gradeMark, statusIcon } from "../lib.js";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const FILTERS = [
  ["all", "All"],
  ["answered", "Answered"],
  ["not_found", "Not found"],
  ["wrong", "Graded wrong"],
];

function matches(item, f) {
  const s = item.answer?.status;
  if (f === "answered") return s === "answered";
  if (f === "not_found") return s === "not_found" || s === "unsupported" || s === "error";
  if (f === "wrong") return item.graded?.correct === false;
  return true;
}

export function mountChecklist(root, ctx) {
  const { ticker, company } = ctx;
  let data = null;
  let filter = "all";
  let selected = ctx.route.qid;

  root.innerHTML = `
    <div class="split">
      <aside class="pane pane--list" aria-label="Checklist">
        <div class="co-head"></div>
        <div class="seg filters" role="group" aria-label="Filter answers"></div>
        <p class="list-hint small muted">Use the ↑ and ↓ keys to step through questions.</p>
        <div class="list-key" aria-hidden="true"><span>Status</span><span>Question</span><span>Graded</span></div>
        <nav class="q-list" aria-label="Questions"><p class="muted pad">Loading the checklist…</p></nav>
      </aside>
      <section class="pane pane--detail" aria-live="polite"></section>
    </div>`;
  const head = root.querySelector(".co-head");
  const filters = root.querySelector(".filters");
  const list = root.querySelector(".q-list");
  const detail = root.querySelector(".pane--detail");

  const fye = company.fiscal_year_end;
  head.innerHTML = `
    <h1 class="co-name">${esc(company.name)}</h1>
    <p class="co-sit">${esc(company.situation)}</p>
    <p class="muted small">Fiscal year ends ${MONTHS[Number(fye.slice(0, 2)) - 1]} ${Number(fye.slice(2))} · ${company.filings.length} SEC filings loaded</p>`;

  function renderFilters() {
    filters.innerHTML = FILTERS.map(([id, label]) => {
      const n = data ? data.items.filter((i) => matches(i, id)).length : "";
      return `<button class="seg__btn ${filter === id ? "is-on" : ""}" data-f="${id}" aria-pressed="${filter === id}">${label} <span class="num muted">${n}</span></button>`;
    }).join("");
    filters.querySelectorAll("[data-f]").forEach((b) =>
      b.addEventListener("click", () => {
        filter = b.dataset.f;
        renderFilters();
        renderList();
      }),
    );
  }

  function renderList() {
    const items = data.items.filter((i) => matches(i, filter));
    if (!items.length) {
      list.innerHTML = `<p class="muted pad">No questions match this filter.</p>`;
      return;
    }
    let html = "";
    let cat = null;
    for (const it of items) {
      if (it.category !== cat) {
        if (cat !== null) html += "</ul>";
        cat = it.category;
        html += `<h2 class="q-group">${esc(cat)}</h2><ul>`;
      }
      const on = it.qid === selected;
      html += `<li><a class="q-row ${on ? "is-active" : ""}" href="#/${ticker}/checklist/${it.qid}" data-qid="${it.qid}" ${on ? 'aria-current="true"' : ""}>
        ${statusIcon(it.answer?.status)}
        <span class="q-row__text">${esc(it.question)}</span>
        <span class="q-row__grade">${gradeMark(it.graded, { short: true })}</span>
      </a></li>`;
    }
    list.innerHTML = html + "</ul>";
    const active = list.querySelector(".is-active");
    if (active) active.scrollIntoView({ block: "nearest" });
  }

  function renderDetail() {
    const item = data.items.find((i) => i.qid === selected) || data.items[0];
    selected = item.qid;
    renderAnswer(detail, { ticker, item });
  }

  function select(qid) {
    if (!data || qid === selected) return;
    selected = qid;
    list.querySelectorAll(".q-row").forEach((r) => {
      const on = r.dataset.qid === qid;
      r.classList.toggle("is-active", on);
      if (on) {
        r.setAttribute("aria-current", "true");
        r.scrollIntoView({ block: "nearest" });
      } else r.removeAttribute("aria-current");
    });
    renderDetail();
  }

  function onKey(e) {
    if (!data || e.metaKey || e.ctrlKey || e.altKey) return;
    if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const rows = [...list.querySelectorAll(".q-row")];
    const i = rows.findIndex((r) => r.dataset.qid === selected);
    const next = rows[Math.max(0, Math.min(rows.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
    if (next) {
      e.preventDefault();
      history.replaceState(null, "", next.getAttribute("href"));
      select(next.dataset.qid);
    }
  }
  document.addEventListener("keydown", onKey);

  api(`/api/checklist/${ticker}`)
    .then((d) => {
      data = d;
      if (!selected || !data.items.some((i) => i.qid === selected)) selected = data.items[0].qid;
      const src = d.source;
      const when = src.name ? fmtDate(src.name.match(/\d{4}-\d{2}-\d{2}/)?.[0]) : "";
      head.insertAdjacentHTML(
        "beforeend",
        `<p class="muted small">${src.kind === "run" ? `Answers from the checklist run of ${when}` : `Answers from ${esc(company.name.replace(/,? Inc\.?$/, ""))}'s single test run (${when})`}</p>`,
      );
      renderFilters();
      renderList();
      renderDetail();
    })
    .catch((e) => {
      list.innerHTML = "";
      detail.innerHTML = emptyState("alert", "Couldn't load the checklist", esc(e.message));
    });

  return {
    update(route) {
      if (route.qid) select(route.qid);
    },
    destroy() {
      document.removeEventListener("keydown", onKey);
    },
  };
}
