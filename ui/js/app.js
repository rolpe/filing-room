// Shell and router: top bar, result strip, and one mounted view at a time.
import { api, esc, icon, pct, usd } from "./lib.js";
import { mountAsk } from "./views/ask.js";
import { mountChecklist } from "./views/checklist.js";
import { mountEvals } from "./views/evals.js";
import { mountGolden } from "./views/golden.js";
import { mountMemo } from "./views/memo.js";
import { mountSearch } from "./views/search.js";

const COMPANY_VIEWS = { checklist: ["Checklist", mountChecklist], memo: ["Memo", mountMemo], search: ["Search", mountSearch], ask: ["Ask", mountAsk] };
const GLOBAL_VIEWS = { evals: ["Evals", mountEvals], golden: ["Golden set", mountGolden] };

const state = { companies: {}, order: [], spend: { today_usd: 0, cap_usd: 1, ask_estimate_usd: 0.05 }, ticker: null, current: null };
const view = document.getElementById("view");

function parse(hash) {
  const [path, query = ""] = hash.replace(/^#\/?/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const q = new URLSearchParams(query);
  if (parts[0] === "evals") return { view: "evals", run: parts[1] };
  if (parts[0] === "golden") return { view: "golden" };
  const ticker = state.companies[parts[0]?.toUpperCase()] ? parts[0].toUpperCase() : state.order[0];
  const v = COMPANY_VIEWS[parts[1]] ? parts[1] : "checklist";
  return { view: v, ticker, qid: parts[2], q: q.get("q") || "" };
}

function renderTop(route) {
  const t = route.ticker || state.ticker;
  const companyView = COMPANY_VIEWS[route.view] ? route.view : "checklist";
  document.querySelector(".cos").innerHTML = state.order
    .map((k) => {
      const c = state.companies[k];
      const on = route.ticker === k;
      const name = c.name.replace(/,? Inc\.?$/, "");
      const rest = name.toUpperCase().startsWith(k) ? name.slice(k.length).trim() : name;
      return `<a class="co ${on ? "is-on" : ""}" href="#/${k}/${companyView}" title="${esc(c.name)}" ${on ? 'aria-current="page"' : ""}>
        <strong>${k}</strong>${rest ? `<span>${esc(rest)}</span>` : ""}
      </a>`;
    })
    .join("");
  const tab = (href, label, on) => `<a class="tab ${on ? "is-on" : ""}" href="${href}" ${on ? 'aria-current="page"' : ""}>${label}</a>`;
  document.querySelector(".tabs").innerHTML =
    Object.entries(COMPANY_VIEWS).map(([k, [label]]) => tab(`#/${t}/${k}`, label, route.view === k)).join("") +
    '<span class="tabs__sep" aria-hidden="true"></span>' +
    Object.entries(GLOBAL_VIEWS).map(([k, [label]]) => tab(`#/${k}`, label, route.view === k)).join("");
  renderSpend();
}

function renderSpend() {
  const s = state.spend;
  document.querySelector(".spend").innerHTML = `Ask spend today <span class="num">${usd(s.today_usd)}</span> of <span class="num">${usd(s.cap_usd)}</span>`;
}

function renderStrip(evals) {
  const box = state.companies.BOX?.eval;
  const hold = evals.runs.find((r) => r.tickers.length === 1 && r.tickers[0] === "BOX");
  const el = document.querySelector(".strip");
  if (!box || !hold) {
    el.hidden = true;
    return;
  }
  el.innerHTML = `${icon("checkCircle", "strip__icon")}
    <p>Tested once on Box after tuning on BILL and Rapid7: <strong><span class="num">${box.correct}</span> of <span class="num">${box.graded}</span> answers correct (${pct(hold.metrics.accuracy)})</strong>, and ${pct(hold.metrics.citation_support_rate)} of cited quotes supported their answers. The pass bar, set before building, was 85%.</p>
    <a href="#/evals/${encodeURIComponent(hold.name)}">How it's measured ${icon("arrowRight")}</a>`;
}

function route() {
  const r = parse(location.hash);
  if (r.ticker) state.ticker = r.ticker;
  renderTop({ ...r, ticker: r.ticker });
  const cur = state.current;
  if (cur && cur.view === r.view && cur.ticker === r.ticker && cur.instance?.update) {
    cur.instance.update(r);
    return;
  }
  cur?.instance?.destroy?.();
  const mount = (COMPANY_VIEWS[r.view] || GLOBAL_VIEWS[r.view])[1];
  view.innerHTML = "";
  view.className = `view view--${r.view}`;
  const ctx = {
    ticker: r.ticker,
    company: state.companies[r.ticker],
    route: r,
    spend: () => state.spend,
    setSpend: (s) => {
      state.spend = s;
      renderSpend();
    },
  };
  state.current = { view: r.view, ticker: r.ticker, instance: mount(view, ctx) };
}

async function boot() {
  try {
    const [cos, spend, evals] = await Promise.all([api("/api/companies"), api("/api/spend"), api("/api/evals")]);
    cos.forEach((c) => (state.companies[c.ticker] = c));
    state.order = cos.map((c) => c.ticker);
    state.spend = spend;
    renderStrip(evals);
  } catch (e) {
    view.innerHTML = `<div class="page"><div class="empty">${icon("alert")}<h3>Couldn't reach the local server</h3><p>${esc(e.message)}. Start it with <code>./fr ui</code>.</p></div></div>`;
    return;
  }
  if (!location.hash) history.replaceState(null, "", `#/${state.order[0]}/checklist`);
  window.addEventListener("hashchange", route);
  route();
}

boot();
