import { api, emptyState, esc, fmtDate, focusQuote, icon, mountFiling } from "../lib.js";

export function mountMemo(root, ctx) {
  const { ticker, company } = ctx;
  root.innerHTML = `
    <div class="split split--memo">
      <section class="pane pane--memo"><p class="muted pad">Loading the memo…</p></section>
      <aside class="pane pane--side" aria-live="polite"></aside>
    </div>`;
  const main = root.querySelector(".pane--memo");
  const side = root.querySelector(".pane--side");
  const hint = () => {
    side.innerHTML = `<div class="side-hint">${icon("info")}<p>Select a bracketed number to see the checklist answer and the filing passage behind that sentence. Sentences the claim check flagged are underlined.</p></div>`;
  };

  api(`/api/memo/${ticker}`)
    .then((m) => {
      const order = [];
      m.memo.sections.forEach((s) => s.sentences.forEach((x) => x.refs.forEach((r) => m.sources[r] && !order.includes(r) && order.push(r))));
      const num = Object.fromEntries(order.map((q, i) => [q, i + 1]));
      const verdicts = Object.fromEntries((m.check?.judged || []).map((v) => [v.n, v]));
      const flagged = new Set(m.check?.unsupported || []);
      let n = 0;
      const sections = m.memo.sections
        .map((s) => {
          const body = s.sentences
            .map((x) => {
              const i = n++;
              const refs = x.refs
                .filter((r) => num[r])
                .map((r) => `<button class="ref" data-ref="${r}" aria-label="Source ${num[r]}: ${esc(r)}">${num[r]}</button>`)
                .join("");
              const flag = flagged.has(i)
                ? ` <button class="flag" data-flag="${i}" aria-label="Flagged by the claim check">${icon("alert")}</button>`
                : "";
              return `<span class="sent ${flagged.has(i) ? "sent--flagged" : ""}">${esc(x.text)}${refs ? `<span class="refs">${refs}</span>` : ""}${flag}</span>`;
            })
            .join(" ");
          return `<h2>${esc(s.heading)}</h2><p>${body}</p>`;
        })
        .join("");
      const date = fmtDate(m.name.match(/\d{4}-\d{2}-\d{2}/)?.[0]);
      const chk = m.check;
      main.innerHTML = `
        <article class="memo">
          <h1>${esc(m.memo.title)}</h1>
          <p class="memo__meta">Written by <span class="mono">${esc(m.meta.model)}</span> from the ${esc(date)} checklist run, using only answers that carry a verified quote.
          ${chk ? `The claim check flagged <strong>${chk.unsupported.length} of ${chk.n_sentences}</strong> sentences as not supported by the answers they cite.` : ""}</p>
          ${sections}
          ${
            m.memo.open_questions?.length
              ? `<h2>Open diligence questions</h2><ul class="open-q">${m.memo.open_questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>`
              : ""
          }
        </article>`;
      hint();

      let current = null;
      const showSource = (qid) => {
        const src = m.sources[qid];
        current = qid;
        main.querySelectorAll(".ref").forEach((b) => b.classList.toggle("is-active", b.dataset.ref === qid));
        const c = src.citations[0];
        side.innerHTML = `
          <div class="side-answer">
            <h3>${esc(src.question)}</h3>
            <p class="side-answer__num">Source ${num[qid]} · <span class="mono">${esc(qid)}</span></p>
            <p class="side-answer__text">${esc(src.answer)}</p>
          </div>
          <div class="filing-slot"></div>`;
        if (c) mountFiling(side.querySelector(".filing-slot"), { ticker, chunkId: c.chunk_id, quotes: src.citations.filter((x) => x.chunk_id === c.chunk_id).map((x) => x.quote) });
      };
      main.querySelectorAll(".ref").forEach((b) => {
        b.addEventListener("click", () => showSource(b.dataset.ref));
        const mark = (on) => b.dataset.ref === current && side.querySelectorAll("mark.quote").forEach((x) => x.classList.toggle("is-focus", on));
        b.addEventListener("mouseenter", () => mark(true));
        b.addEventListener("mouseleave", () => mark(false));
        b.addEventListener("focus", () => mark(true));
        b.addEventListener("blur", () => mark(false));
      });
      if (order.length) showSource(order[0]); // land with a passage beside the text, like the checklist
      main.querySelectorAll(".flag").forEach((b) =>
        b.addEventListener("click", () => {
          const v = verdicts[Number(b.dataset.flag)];
          side.innerHTML = `<div class="side-flag">${icon("alert")}<div><h3>Flagged by the claim check</h3><p>${esc(v?.reason || "This sentence cites an answer that doesn't support it.")}</p><p class="muted small">A separate grading model read this sentence against only the answers it cites. Flags stay visible rather than being edited out.</p></div></div>`;
        }),
      );
    })
    .catch((e) => {
      side.innerHTML = "";
      main.innerHTML =
        e.status === 404
          ? emptyState(
              "doc",
              `No memo for ${company.name}`,
              company.split === "holdout"
                ? "Box was tested with a single checklist run and no memo was generated for it. Its answers are on the Checklist tab."
                : company.split === "user"
                  ? `Run ${esc(company.name)}'s checklist from <a href="#/add">Add a company</a>; the memo is written at the end of the run.`
                  : `Generate one from the command line with <code>./fr memo ${esc(ticker)}</code>.`,
            )
          : emptyState("alert", "Couldn't load the memo", esc(e.message));
    });
  return {};
}
