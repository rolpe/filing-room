// Shared pieces: API client, escaping, icons, formatters, status marks, and the filing pane.

export const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export async function api(path, { method = "GET", body } = {}) {
  const opts = { method, headers: {} };
  if (method !== "GET") {
    opts.headers["X-Filing-Room"] = "1";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body ?? {});
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON error page */ }
  if (!res.ok) {
    const err = new Error(data?.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

// One stroke family (24px grid, 1.75 stroke, round joins), drawn inline so the icons inherit color.
const P = {
  check: '<path d="M20 6 9 17l-5-5"/>',
  checkCircle: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12.3 2.4 2.4 4.6-5"/>',
  xCircle: '<circle cx="12" cy="12" r="9"/><path d="m9.2 9.2 5.6 5.6m0-5.6-5.6 5.6"/>',
  minusCircle: '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
  alert: '<path d="M10.3 4.2 2.9 17.5A2 2 0 0 0 4.6 20.5h14.8a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z"/><path d="M12 9.5v4"/><path d="M12 17h.01"/>',
  external: '<path d="M14 4h6v6"/><path d="M20 4 10.5 13.5"/><path d="M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
  chevronLeft: '<path d="m15 18-6-6 6-6"/>',
  chevronRight: '<path d="m9 18 6-6-6-6"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.8h.01"/>',
  doc: '<path d="M14 3H7a1.5 1.5 0 0 0-1.5 1.5v15A1.5 1.5 0 0 0 7 21h10a1.5 1.5 0 0 0 1.5-1.5V7.5Z"/><path d="M14 3v4.5h4.5"/><path d="M9 12.5h6M9 16h6"/>',
  arrowRight: '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
  circle: '<circle cx="12" cy="12" r="9"/>',
};

export const icon = (name, cls = "") =>
  `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name]}</svg>`;

// ---------------------------------------------------------------- formatting

export function fmtValue(value, unit) {
  if (value === null || value === undefined || value === "") return "";
  const v = Number(String(value).replace(/[,$%\s]/g, ""));
  if (!Number.isFinite(v)) return esc(value);
  const sign = v < 0 ? "−" : "";
  const a = Math.abs(v);
  if (unit === "USD") {
    if (a >= 1e9) return `${sign}$${(a / 1e9).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}B`;
    if (a >= 1e6) return `${sign}$${(a / 1e6).toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}M`;
    return `${sign}$${a.toLocaleString("en-US")}`;
  }
  if (unit === "percent") return `${sign}${a.toLocaleString("en-US", { maximumFractionDigits: 1 })}%`;
  return `${sign}${a.toLocaleString("en-US")}`;
}

export const pct = (v) => (v === null || v === undefined ? "–" : `${Number(v).toLocaleString("en-US", { maximumFractionDigits: 1 })}%`);
export const usd = (v) => `$${Number(v || 0).toFixed(2)}`;

const FORMS = {
  "10-K": "Annual report (10-K)",
  "10-Q": "Quarterly report (10-Q)",
  "DEF 14A": "Proxy statement (DEF 14A)",
  "8-K": "Earnings release (8-K)",
};
export const formLabel = (form) => FORMS[form] || form;

export function docLabel(docId) {
  // BILL_10K_FY2026 -> "10-K · FY2026"
  const m = /^[A-Z]+_(10K|10Q|8K|DEF14A)_(.+)$/.exec(docId || "");
  if (!m) return docId || "";
  const form = { "10K": "10-K", "10Q": "10-Q", "8K": "8-K", DEF14A: "Proxy" }[m[1]];
  const period = m[2].replace(/^Q(\d)FY/, "Q$1 FY");
  return `${form} · ${period}`;
}

const HEADINGS = { proxy: "Proxy statement", press_release: "Earnings press release", cover: "Cover page" };
const SMALL = new Set(["a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"]);
const KEEP = new Set(["U.S.", "GAAP", "SEC", "MD&A", "CEO", "CFO", "LLC", "II", "III", "IV", "ESG", "AI", "IT", "R&D", "US"]);

/** SEC headings arrive in capitals ("FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA"); set them in title case. */
export function titleCase(s) {
  const letters = (s || "").replace(/[^A-Za-z]/g, "");
  if (!letters || letters.replace(/[^A-Z]/g, "").length / letters.length < 0.7) return s || "";
  return s
    .split(/(\s+)/)
    .map((w, i) => {
      if (/^\s+$/.test(w) || KEEP.has(w.replace(/[,:;.]$/, "")) || !/[A-Z]/.test(w)) return w;
      const lower = w.toLowerCase();
      if (i > 0 && SMALL.has(lower.replace(/[,:;]$/, ""))) return lower;
      return lower.replace(/^([^a-z]*)([a-z])/, (_, p, c) => p + c.toUpperCase());
    })
    .join("");
}
export const prettyHeading = (h) => HEADINGS[h] || titleCase(h || "");

/** A quote as readers see it: table-row pipes become thin cell dividers; the verbatim text stays in the DOM. */
export function quoteHTML(q) {
  return String(q ?? "")
    .split(" | ")
    .map(esc)
    .join('<span class="sep"><span class="sr-only"> | </span></span>');
}

/** "2026-09-27_1535" -> "Sep 27, 15:35" */
export function fmtStamp(stamp) {
  const m = /^(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})/.exec(stamp || "");
  return m ? `${fmtDate(m[1]).replace(/, \d{4}$/, "")}, ${m[2]}:${m[3]}` : stamp || "";
}

export function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

// ---------------------------------------------------------------- status marks

const STATUS = {
  answered: ["checkCircle", "ok", "Verified quote"],
  not_found: ["minusCircle", "neutral", "Not in filings"],
  unsupported: ["alert", "warn", "Unsupported"],
  error: ["xCircle", "bad", "Error"],
};

export function statusMark(status, { short = false } = {}) {
  const [ic, tone, word] = STATUS[status] || STATUS.error;
  return `<span class="mark mark--${tone}">${icon(ic)}${short ? "" : `<span>${word}</span>`}</span>`;
}

export function statusIcon(status) {
  const [ic, tone, word] = STATUS[status] || STATUS.error;
  return `<span class="mark mark--${tone}" title="${word}">${icon(ic)}<span class="sr-only">${word}</span></span>`;
}

export function gradeMark(graded, { short = false } = {}) {
  if (!graded) return "";
  if (graded.correct === true) return `<span class="grade grade--ok" title="Graded correct against the golden answer">${icon("check")}${short ? "" : "<span>Graded correct</span>"}</span>`;
  if (graded.correct === false) return `<span class="grade grade--bad" title="Graded wrong against the golden answer">${icon("xCircle")}${short ? "" : "<span>Graded wrong</span>"}</span>`;
  return short ? "" : `<span class="grade grade--none" title="Judgment question: only citation support is graded">${icon("circle")}<span>Support only</span></span>`;
}

export function expectedText(expected) {
  if (!expected) return "";
  if (expected.not_found) return `Not in the filings. ${expected.text || ""}`;
  if (expected.text) return expected.text;
  if ("value" in expected) return `${fmtValue(expected.value, expected.unit)}${expected.period ? ` (${expected.period})` : ""}`;
  return "";
}

// ---------------------------------------------------------------- filing pane

const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function segs(segments) {
  return segments.map((s) => (s.m ? `<mark class="quote" data-q="${s.q ?? 0}">${esc(s.t)}</mark>` : esc(s.t))).join("");
}

const cellText = (cell) => cell.map((s) => s.t).join("").trim();
const valueLike = (t) => /^[($\-—–]?\s*[\d.,]+%?\)?$|^—$|^[\d]{4}$/.test(t);

function renderBlocks(blocks) {
  return blocks
    .map((b) => {
      if (b.type === "p") return `<p>${segs(b.segments)}</p>`;
      const width = Math.max(...b.rows.map((r) => r.length));
      // The column-label row (years) near the top of a table stays visible while the quote is centred.
      const yearRow = b.rows.slice(0, 3).findIndex((r) => r.length > 1 && r.every((c) => valueLike(cellText(c))));
      const rows = b.rows
        .map((row, ri) => {
          const hit = row.some((cell) => cell.some((s) => s.m));
          let cells;
          if (row.length === 1 && width > 1) cells = `<td colspan="${width}" class="span">${segs(row[0])}</td>`;
          else if (row.length < width && valueLike(cellText(row[0]))) {
            // A header row of years (or a label-less value row) lines up with the value columns on the right.
            cells = `<td></td>`.repeat(width - row.length) + row.map((c) => `<td>${segs(c)}</td>`).join("");
          } else cells = row.map((c) => `<td>${segs(c)}</td>`).join("") + `<td></td>`.repeat(width - row.length);
          const cls = [hit ? "hit" : "", ri === yearRow ? "cols" : ""].filter(Boolean).join(" ");
          return `<tr${cls ? ` class="${cls}"` : ""}>${cells}</tr>`;
        })
        .join("");
      return `<div class="table-wrap"><table>${rows}</table></div>`;
    })
    .join("");
}

/** Filing pane: shows one passage with the quotes highlighted; prev/next walk the filing. */
export async function mountFiling(el, { ticker, chunkId, quotes = [] }) {
  el.classList.add("filing");
  el.innerHTML = `<div class="filing__loading">Opening the filing…</div>`;
  let data;
  try {
    const qs = new URLSearchParams({ id: chunkId });
    quotes.forEach((q) => qs.append("q", q));
    data = await api(`/api/passage/${ticker}?${qs}`);
  } catch (e) {
    el.innerHTML = `<div class="filing__empty">${icon("alert")}<p>Couldn't open this passage: ${esc(e.message)}</p></div>`;
    return;
  }
  const sub = data.subheading && data.subheading !== data.heading ? `<span class="filing__sub">${esc(titleCase(data.subheading))}</span>` : "";
  el.innerHTML = `
    <header class="filing__head">
      <div class="filing__id">
        ${icon("doc")}
        <div>
          <p class="filing__doc">${esc(formLabel(data.form))} · ${esc(data.period)} · filed ${esc(fmtDate(data.filing_date))}</p>
          <p class="filing__section">${esc(prettyHeading(data.heading))}${sub ? " · " : ""}${sub}</p>
        </div>
      </div>
      <div class="filing__nav">
        <button class="btn btn--ghost btn--icon" data-nav="prev" ${data.prev_id ? "" : "disabled"} aria-label="Previous passage" title="Previous passage">${icon("chevronLeft")}</button>
        <button class="btn btn--ghost btn--icon" data-nav="next" ${data.next_id ? "" : "disabled"} aria-label="Next passage" title="Next passage">${icon("chevronRight")}</button>
        <a class="btn btn--ghost" href="${esc(data.url)}" target="_blank" rel="noopener noreferrer">sec.gov ${icon("external")}</a>
      </div>
    </header>
    <div class="filing__body" tabindex="0" aria-label="Filing passage">${renderBlocks(data.blocks)}</div>
    ${quotes.length && !data.found ? `<p class="filing__note">${icon("info")} The quote isn't in this passage; use the arrows to read the neighbouring passages.</p>` : ""}`;
  el.querySelectorAll("[data-nav]").forEach((b) =>
    b.addEventListener("click", () => mountFiling(el, { ticker, chunkId: b.dataset.nav === "prev" ? data.prev_id : data.next_id, quotes })),
  );
  const first = el.querySelector("mark.quote");
  const body = el.querySelector(".filing__body");
  if (first && body) {
    const top = first.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop - body.clientHeight / 3;
    body.scrollTop = Math.max(0, top);
    const r = first.getBoundingClientRect();
    // Desktop panes have fixed height, so bring the quote on screen; on narrow screens the page scrolls and must not jump.
    if (window.matchMedia("(min-width: 861px)").matches && (r.bottom > window.innerHeight || r.top < 0)) first.scrollIntoView({ block: "nearest" });
    if (!reduceMotion()) {
      el.querySelectorAll("mark.quote").forEach((m) => {
        m.classList.remove("sweep");
        void m.offsetWidth;
        m.classList.add("sweep");
      });
    }
  }
}

/** Mark (or unmark) one quote's highlight in a mounted filing pane: the hover half of the signature interaction. */
export function focusQuote(el, qi, on) {
  el?.querySelectorAll(`mark.quote[data-q="${qi}"]`).forEach((m) => m.classList.toggle("is-focus", on));
}

export function emptyState(iconName, title, body = "") {
  return `<div class="empty">${icon(iconName)}<h3>${esc(title)}</h3>${body ? `<p>${body}</p>` : ""}</div>`;
}
