import { api, emptyState, esc, expectedText, icon } from "../lib.js";

const GRADE = { numeric: "Number, within 0.5%", judged: "Text, graded by model", abstain: "Should be “not found”", support_only: "Citation support only" };

export function mountGolden(root) {
  root.innerHTML = `<div class="page"><p class="muted">Loading the golden set…</p></div>`;
  const page = root.firstElementChild;
  let items = [];
  let co = "all";
  let show = "todo";

  function progress() {
    const done = items.filter((i) => i.verified === "human").length;
    return `<span class="num"><strong>${done}</strong> of ${items.length}</span> verified`;
  }

  function render() {
    const list = items.filter((i) => (co === "all" || i.ticker === co) && (show === "all" || (show === "todo") === (i.verified !== "human")));
    page.querySelector(".g-progress").innerHTML = progress();
    page.querySelector(".g-list").innerHTML = list.length
      ? list
          .map((i) => {
            const src = i.source || {};
            const quotes = (src.quote ? [{ doc_id: src.doc_id, quote: src.quote }] : []).concat(src.quotes || []);
            const done = i.verified === "human";
            return `<li class="g-item ${done ? "is-done" : ""}">
              <button class="g-check" data-id="${esc(i.id)}" aria-pressed="${done}" aria-label="${done ? "Mark as not verified" : "Mark as verified"}">${icon(done ? "checkCircle" : "circle")}<span>${done ? "Verified" : "Verify"}</span></button>
              <div class="g-body">
                <p class="g-meta"><span class="mono">${esc(i.id)}</span> · ${esc(i.category)} · ${esc(GRADE[i.grade] || i.grade)}</p>
                <h3>${esc(i.question)}</h3>
                <p class="g-expected">${esc(expectedText(i.expected))}</p>
                ${quotes.slice(0, 3).map((q) => `<blockquote class="g-quote"><mark class="quote">${esc(q.quote)}</mark><cite>${esc(q.doc_id || "")}</cite></blockquote>`).join("")}
                ${!quotes.length && src.method ? `<p class="muted small">How it was checked: ${esc(src.method)}</p>` : ""}
                ${i.note || src.note ? `<p class="muted small">Note: ${esc(i.note || src.note)}</p>` : ""}
              </div>
            </li>`;
          })
          .join("")
      : `<li>${emptyState("checkCircle", show === "todo" ? "Nothing left to verify here" : "No items match")}</li>`;
    page.querySelectorAll(".g-check").forEach((b) =>
      b.addEventListener("click", async () => {
        const it = items.find((x) => x.id === b.dataset.id);
        b.disabled = true;
        try {
          const r = await api(`/api/golden/${encodeURIComponent(it.id)}/verify`, { method: "POST", body: { verified: it.verified !== "human" } });
          it.verified = r.verified;
          render();
        } catch (e) {
          b.disabled = false;
          b.insertAdjacentHTML("afterend", `<p class="error small">Couldn't save: ${esc(e.message)}</p>`);
        }
      }),
    );
  }

  api("/api/golden")
    .then((d) => {
      items = d;
      const tickers = [...new Set(items.map((i) => i.ticker))];
      page.innerHTML = `
        <header class="page__head">
          <h1>Golden set review</h1>
          <p class="lede">The golden set is the answer key every eval is graded against. Numeric answers come straight from the SEC's structured XBRL data; the answers below were drafted from the filings and each needs a human check. Read the quote, confirm it supports the expected answer for the right period, then mark it verified.</p>
          <p class="g-progress"></p>
        </header>
        <div class="toolbar">
          <div class="seg" role="group" aria-label="Company">${["all", ...tickers].map((t) => `<button class="seg__btn ${co === t ? "is-on" : ""}" data-co="${t}">${t === "all" ? "All companies" : t}</button>`).join("")}</div>
          <div class="seg" role="group" aria-label="Status">${[["todo", "To verify"], ["done", "Verified"], ["all", "All"]].map(([v, l]) => `<button class="seg__btn ${show === v ? "is-on" : ""}" data-show="${v}">${l}</button>`).join("")}</div>
        </div>
        <ul class="g-list"></ul>`;
      page.querySelectorAll("[data-co]").forEach((b) =>
        b.addEventListener("click", () => {
          co = b.dataset.co;
          page.querySelectorAll("[data-co]").forEach((x) => x.classList.toggle("is-on", x === b));
          render();
        }),
      );
      page.querySelectorAll("[data-show]").forEach((b) =>
        b.addEventListener("click", () => {
          show = b.dataset.show;
          page.querySelectorAll("[data-show]").forEach((x) => x.classList.toggle("is-on", x === b));
          render();
        }),
      );
      render();
    })
    .catch((e) => (page.innerHTML = emptyState("alert", "Couldn't load the golden set", esc(e.message))));
  return {};
}
