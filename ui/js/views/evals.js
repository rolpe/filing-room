import { api, emptyState, esc, expectedText, gradeMark, icon, pct, statusMark, usd } from "../lib.js";

const PASS_BAR = 85;

function groupOf(run) {
  if (run.tickers.includes("BOX")) return "Held-out company";
  return run.metrics.n_items > 40 ? "Full checklist (80 items)" : "First golden set (38 items)";
}

function label(run) {
  return run.label || run.name;
}

/** Accuracy by run: one series, grouped by golden set, with the pre-registered pass bar. */
function chart(runs) {
  const W = 760, H = 240, L = 44, R = 16, T = 18, B = 58;
  const yMin = 80, yMax = 100;
  const groups = [];
  runs.forEach((r) => {
    const g = groupOf(r);
    if (!groups.length || groups.at(-1).name !== g) groups.push({ name: g, runs: [] });
    groups.at(-1).runs.push(r);
  });
  const gap = 34;
  const slots = runs.length;
  const step = (W - L - R - gap * (groups.length - 1)) / slots;
  const y = (v) => T + (1 - (Math.max(yMin, Math.min(yMax, v)) - yMin) / (yMax - yMin)) * (H - T - B);
  let x0 = L;
  let marks = "", lines = "", glabels = "", xlabels = "";
  groups.forEach((g, gi) => {
    const pts = g.runs.map((r, i) => ({ r, x: x0 + step * (i + 0.5), yv: y(r.metrics.accuracy) }));
    if (pts.length > 1) lines += `<polyline class="c-line" points="${pts.map((p) => `${p.x},${p.yv}`).join(" ")}"/>`;
    pts.forEach((p) => {
      marks += `<g class="c-pt" tabindex="0" data-run="${esc(p.r.name)}" role="button" aria-label="${esc(label(p.r))}: ${pct(p.r.metrics.accuracy)} accuracy">
        <rect class="c-hit" x="${p.x - step / 2}" y="${T}" width="${step}" height="${H - T - B}"/>
        <circle class="c-dot ${g.name.startsWith("Held") ? "c-dot--hold" : ""}" cx="${p.x}" cy="${p.yv}" r="5"/>
        <text class="c-val" x="${p.x}" y="${p.yv - 11}" text-anchor="middle">${pct(p.r.metrics.accuracy)}</text>
      </g>`;
      xlabels += `<text class="c-x" x="${p.x}" y="${H - B + 16}" text-anchor="middle">${esc(label(p.r).slice(0, 14))}</text>`;
    });
    const gx1 = x0, gx2 = x0 + step * g.runs.length;
    glabels += `<line class="c-bracket" x1="${gx1 + 4}" x2="${gx2 - 4}" y1="${H - B + 30}" y2="${H - B + 30}"/>
      <text class="c-group" x="${(gx1 + gx2) / 2}" y="${H - B + 46}" text-anchor="middle">${esc(g.name)}</text>`;
    x0 = gx2 + gap;
    if (gi < groups.length - 1) glabels += `<line class="c-sep" x1="${x0 - gap / 2}" x2="${x0 - gap / 2}" y1="${T}" y2="${H - B}"/>`;
  });
  let grid = "";
  for (let v = yMin; v <= yMax; v += 5) grid += `<line class="c-grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="c-y" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v}%</text>`;
  const bar = `<line class="c-bar" x1="${L}" x2="${W - R}" y1="${y(PASS_BAR)}" y2="${y(PASS_BAR)}"/>
    <text class="c-bar-label" x="${W - R}" y="${y(PASS_BAR) - 6}" text-anchor="end">Pass bar ${PASS_BAR}%, set before building</text>`;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Answer accuracy by eval run">${grid}${bar}${lines}${marks}${glabels}${xlabels}</svg>`;
}

function runsTable(runs, selected) {
  return `<div class="table-wrap"><table class="data">
    <thead><tr>
      <th>Run</th><th>What changed</th><th>Companies</th><th class="r">Items</th><th class="r">Accuracy</th>
      <th class="r">Citation support</th><th class="r">Abstention P / R</th><th class="r">Retrieval</th><th class="r">Cost</th>
    </tr></thead>
    <tbody>${runs
      .map((r) => {
        const m = r.metrics;
        return `<tr class="${r.name === selected ? "is-active" : ""}" data-run="${esc(r.name)}" tabindex="0">
          <td class="nowrap"><strong>${esc(label(r))}</strong><br><span class="muted small">${esc(r.timestamp.replace("_", " "))}</span></td>
          <td class="note">${esc(r.note || "–")}</td>
          <td>${esc(r.tickers.join(", "))}</td>
          <td class="r num">${m.n_items}</td>
          <td class="r num"><strong>${pct(m.accuracy)}</strong></td>
          <td class="r num">${pct(m.citation_support_rate)}</td>
          <td class="r num">${pct(m.abstention_precision)} / ${pct(m.abstention_recall)}</td>
          <td class="r num">${pct(m.retrieval_recall)}</td>
          <td class="r num">${usd(m.cost_usd.answer + m.cost_usd.judge)}</td>
        </tr>`;
      })
      .join("")}</tbody></table></div>`;
}

function failures(d) {
  const rows = d.rows.filter((r) => r.correct === false || r.supported === "no" || r.supported === "partial");
  if (!rows.length) return `<p class="muted">No failures or partially supported answers in this run.</p>`;
  return `<ul class="fail-list">${rows
    .map(
      (r) => `<li class="fail">
        <div class="fail__head">
          <span class="mono small">${esc(r.id)}</span>
          ${statusMark(r.status)}
          ${r.correct === false ? gradeMark({ correct: false }) : `<span class="grade grade--warn">${icon("alert")}<span>Citation ${esc(r.supported)}</span></span>`}
        </div>
        <p class="fail__q">${esc(r.question)}</p>
        <dl class="fail__cmp">
          <div><dt>Expected</dt><dd>${esc(expectedText(r.expected))}</dd></div>
          <div><dt>Got</dt><dd>${esc(r.answer || "(no answer)")}</dd></div>
          ${r.judge_reason ? `<div><dt>Grader</dt><dd>${esc(r.judge_reason)}</dd></div>` : ""}
        </dl>
      </li>`,
    )
    .join("")}</ul>`;
}

export function mountEvals(root, ctx) {
  root.innerHTML = `<div class="page"><p class="muted">Loading eval history…</p></div>`;
  const page = root.firstElementChild;
  let selected = ctx.route.run;

  api("/api/evals")
    .then((ev) => {
      const runs = ev.runs;
      if (!runs.length) {
        page.innerHTML = emptyState("info", "No eval runs yet", "Run <code>./fr eval</code> to create one.");
        return;
      }
      selected = selected || runs.at(-1).name;
      page.innerHTML = `
        <header class="page__head">
          <h1>How the system is measured</h1>
          <p class="lede">Every eval run answers the golden set: hand-checked answers drawn from the filings. Numbers must match within 0.5%, text answers are compared by a separate grading model, and every quote is checked word-for-word against the filing by code. Box was held out: the system was frozen before Box was ever parsed, then run once.</p>
        </header>
        <section class="block">
          <h2>Accuracy by run</h2>
          <div class="chart-wrap">${chart(runs)}<div class="tip" hidden></div></div>
          <p class="muted small">Runs in different groups aren't directly comparable: the golden set grew from 38 to 80 items between groups, deliberately adding harder questions.</p>
        </section>
        <section class="block">
          <h2>All runs</h2>
          ${runsTable(runs, selected)}
        </section>
        <section class="block" id="run-detail"></section>
        ${
          ev.memo_checks.length
            ? `<section class="block"><h2>Memo claim checks</h2>
              <p class="muted small">Share of memo sentences a grading model found unsupported by the checklist answers they cite.</p>
              <div class="table-wrap"><table class="data"><thead><tr><th>Check</th><th>Company</th><th>Change</th><th class="r">Unsupported</th></tr></thead><tbody>
              ${ev.memo_checks.map((m) => `<tr><td class="mono small">${esc(m.name.slice(0, 15))}</td><td>${esc(m.ticker)}</td><td class="note">${esc(m.note)}</td><td class="r num">${m.unsupported} of ${m.sentences} (${pct(m.rate)})</td></tr>`).join("")}
              </tbody></table></div></section>`
            : ""
        }`;

      const detail = page.querySelector("#run-detail");
      const tip = page.querySelector(".tip");
      const show = (name) => {
        selected = name;
        history.replaceState(null, "", `#/evals/${encodeURIComponent(name)}`);
        page.querySelectorAll("tr[data-run]").forEach((tr) => tr.classList.toggle("is-active", tr.dataset.run === name));
        page.querySelectorAll(".c-pt").forEach((g) => g.classList.toggle("is-active", g.dataset.run === name));
        detail.innerHTML = `<p class="muted">Loading run…</p>`;
        api(`/api/evals/${encodeURIComponent(name)}`).then((d) => {
          detail.innerHTML = `<h2>Failures in “${esc(d.label || d.name)}”</h2>
            ${d.note ? `<p class="muted small">${esc(d.note)}</p>` : ""}
            ${failures(d)}`;
        });
      };
      page.querySelectorAll("tr[data-run]").forEach((tr) => {
        tr.addEventListener("click", () => show(tr.dataset.run));
        tr.addEventListener("keydown", (e) => e.key === "Enter" && show(tr.dataset.run));
      });
      const runByName = Object.fromEntries(runs.map((r) => [r.name, r]));
      page.querySelectorAll(".c-pt").forEach((g) => {
        const r = runByName[g.dataset.run];
        const move = () => {
          const box = g.querySelector(".c-dot").getBoundingClientRect();
          const wrap = page.querySelector(".chart-wrap").getBoundingClientRect();
          tip.innerHTML = `<strong>${esc(label(r))}</strong><span>${esc(r.tickers.join(", "))} · ${r.metrics.n_items} items</span><span>Accuracy ${pct(r.metrics.accuracy)} · citation support ${pct(r.metrics.citation_support_rate)}</span>${r.note ? `<span class="muted">${esc(r.note)}</span>` : ""}`;
          tip.hidden = false;
          tip.style.left = `${box.left - wrap.left + box.width / 2}px`;
          tip.style.top = `${box.top - wrap.top}px`;
        };
        g.addEventListener("mouseenter", move);
        g.addEventListener("focus", move);
        g.addEventListener("mouseleave", () => (tip.hidden = true));
        g.addEventListener("blur", () => (tip.hidden = true));
        g.addEventListener("click", () => show(r.name));
        g.addEventListener("keydown", (e) => e.key === "Enter" && show(r.name));
      });
      show(selected);
    })
    .catch((e) => (page.innerHTML = emptyState("alert", "Couldn't load evals", esc(e.message))));
  return {};
}
