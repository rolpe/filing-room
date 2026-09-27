import { api, docLabel, emptyState, esc, icon, mountFiling, prettyHeading } from "../lib.js";

const FORMS = [["", "All filings"], ["10-K", "Annual reports (10-K)"], ["10-Q", "Quarterly reports (10-Q)"], ["DEF 14A", "Proxy statement"], ["8-K", "Earnings release"]];

function excerpt(text, terms) {
  const flat = text.replace(/\[\/?TABLE\]/g, " ").replace(/\s*\|\s*/g, " · ").replace(/\s+/g, " ").trim();
  const lower = flat.toLowerCase();
  let at = -1;
  for (const t of terms) {
    at = lower.indexOf(t);
    if (at >= 0) break;
  }
  const start = Math.max(0, at - 120);
  const cut = flat.slice(start, start + 340);
  let html = esc(cut);
  for (const t of terms) {
    if (t.length < 3) continue;
    html = html.replace(new RegExp(`(${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"), "<b>$1</b>");
  }
  return `${start > 0 ? "…" : ""}${html}${start + 340 < flat.length ? "…" : ""}`;
}

export function mountSearch(root, ctx) {
  const { ticker, company } = ctx;
  root.innerHTML = `
    <div class="split">
      <aside class="pane pane--list">
        <form class="search" role="search">
          <label class="sr-only" for="q">Search ${esc(company.name)} filings</label>
          <div class="search__row">
            <span class="search__icon">${icon("search")}</span>
            <input id="q" name="q" type="search" placeholder="e.g. net dollar-based retention" autocomplete="off" value="${esc(ctx.route.q || "")}">
          </div>
          <div class="search__row">
            <label class="sr-only" for="form">Filing type</label>
            <select id="form" name="form">${FORMS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>
            <button class="btn btn--primary" type="submit">Search</button>
          </div>
          <p class="muted small">Keyword search over ${esc(company.name)}'s filings: the same retrieval step that feeds the answering model. Free: no AI calls.</p>
        </form>
        <ol class="results"></ol>
      </aside>
      <section class="pane pane--detail"><div class="filing-slot filing-slot--empty">${icon("search")}<p>Search, then pick a result to read the passage.</p></div></section>
    </div>`;
  const form = root.querySelector("form");
  const results = root.querySelector(".results");
  const slot = root.querySelector(".filing-slot");

  async function run() {
    const q = form.q.value.trim();
    if (!q) return;
    history.replaceState(null, "", `#/${ticker}/search?q=${encodeURIComponent(q)}`);
    results.innerHTML = `<li class="muted pad">Searching…</li>`;
    try {
      const hits = await api(`/api/search/${ticker}?${new URLSearchParams({ q, ...(form.form.value ? { form: form.form.value } : {}) })}`);
      const terms = [...new Set(q.toLowerCase().split(/\W+/).filter((t) => t.length > 2))];
      if (!hits.length) {
        results.innerHTML = `<li>${emptyState("search", "No passages matched", "Try different wording, or a different filing type.")}</li>`;
        return;
      }
      results.innerHTML = hits
        .map(
          (h, i) => `<li><button class="result" data-i="${i}">
            <span class="result__doc">${esc(docLabel(h.doc_id))} · ${esc(prettyHeading(h.heading))}</span>
            <span class="result__text">${excerpt(h.text, terms)}</span>
            <span class="result__score num muted small">score ${h.score}</span>
          </button></li>`,
        )
        .join("");
      results.querySelectorAll(".result").forEach((b) =>
        b.addEventListener("click", () => {
          results.querySelectorAll(".result").forEach((x) => x.classList.toggle("is-active", x === b));
          slot.classList.remove("filing-slot--empty");
          mountFiling(slot, { ticker, chunkId: hits[Number(b.dataset.i)].chunk_id });
        }),
      );
    } catch (e) {
      results.innerHTML = `<li>${emptyState("alert", "Search failed", esc(e.message))}</li>`;
    }
  }
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    run();
  });
  if (form.q.value) run();
  else form.q.focus();
  return {};
}
