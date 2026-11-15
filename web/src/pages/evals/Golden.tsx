import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import type { Citation } from "../../lib/api";
import { evalApi, type GoldenItem, type KeyReview } from "../../lib/evalApi";
import { Icon } from "../../components/Icons";
import { PassageView, type PassageLoader } from "../../components/PassageView";
import { ErrorState, Notice, Skeleton, SkeletonRows } from "../../components/States";
import "../../styles/findings.css";

const CHECK: Record<KeyReview, [string, string, string]> = {
  human: ["ok", "check", "Checked"],
  "claude-draft": ["none", "none", "Not checked"],
  "needs-fix": ["warn", "flag", "Needs fixing"],
  "sec-data": ["none", "check", "From SEC data"],
};
type Filter = "all" | "unchecked" | "needs-fix" | "human" | "sec-data";

function KeyStatus({ r }: { r: KeyReview }) {
  const [cls, icon, label] = CHECK[r] ?? CHECK["claude-draft"];
  return <span className={`status ${cls}`}><Icon name={icon} />{label}</span>;
}

export function GoldenPage() {
  const q = useQuery({ queryKey: ["golden"], queryFn: evalApi.golden });
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const cos = q.data?.companies ?? [];
  const t = params.get("co");
  const cur = cos.find((c) => c.ticker === t) ?? cos[0];
  const sel = params.get("item");
  const items = useMemo(() => (cur?.items ?? []).filter((i) =>
    (filter === "all" || (filter === "unchecked" ? i.review === "claude-draft" : i.review === filter)) &&
    (!text.trim() || `${i.label} ${i.expected} ${i.grade} ${i.source?.quotes.map((x) => x.quote).join(" ")}`.toLowerCase().includes(text.trim().toLowerCase()))),
  [cur, text, filter]);
  const set = (k: string, v: string | null) => {
    const n = new URLSearchParams(params);
    if (v) n.set(k, v); else n.delete(k);
    if (k !== "p") n.delete("p");
    setParams(n, { replace: true });
  };

  if (q.isLoading) return <div className="page-body"><SkeletonRows rows={8} cols={4} /></div>;
  if (q.isError) return <ErrorState title="Couldn't load the golden set" error={q.error} onRetry={() => q.refetch()} />;
  const pr = q.data!.progress;
  const counts = (f: Filter) => (cur?.items ?? []).filter((i) => f === "all" || (f === "unchecked" ? i.review === "claude-draft" : i.review === f)).length;

  return (
    <div className={`work${sel ? "" : " solo"}`}>
      <div className="scroll page-scroll">
        <div className="ev-page">
          <div>
            <div className="sec-head">
              <h2>Golden set</h2>
              <span className="muted">The answer key: {q.data!.total} items. Numbers come from SEC XBRL data; text answers were drafted from a quoted filing passage and need a person to check them.</span>
            </div>
            <div className="ev-progress">
              <span className="prog wide" role="progressbar" aria-valuemin={0} aria-valuemax={pr.manual} aria-valuenow={pr.checked} aria-label="Answer key checked">
                <span className="track"><i style={{ transform: `scaleX(${pr.manual ? Math.max(0.01, pr.checked / pr.manual) : 0})` }} /></span>
                <b>{pr.checked} of {pr.manual}</b>&nbsp;hand-built items checked
              </span>
              {pr.needs_fix > 0 && <span className="status warn"><Icon name="flag" />{pr.needs_fix} need fixing</span>}
              <span className="muted small">{pr.from_sec} taken from SEC data need no check</span>
            </div>
            <div className="tools" style={{ padding: "0 0 10px" }}>
              <div className="seg" role="group" aria-label="Company">
                {cos.map((c) => <button key={c.ticker} aria-pressed={cur?.ticker === c.ticker} onClick={() => set("co", c.ticker)}>
                  {c.ticker}{c.holdout ? " (held out)" : ""}<i>{c.items.length}</i></button>)}
              </div>
              <div className="seg" role="group" aria-label="Check status">
                {([["all", "All"], ["unchecked", "Not checked"], ["needs-fix", "Needs fixing"], ["human", "Checked"], ["sec-data", "From SEC data"]] as [Filter, string][]).map(([k, l]) => (
                  <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}<i>{counts(k)}</i></button>))}
              </div>
              <label className="filter"><Icon name="search" /><input type="search" placeholder="Filter items" aria-label="Filter items" value={text} onChange={(e) => setText(e.target.value)} /></label>
            </div>
            {cur?.holdout && <p className="muted small" style={{ margin: "0 0 10px" }}>Written before the held-out company was run, and not changed since.</p>}
          </div>
          <div className="tbl-wrap">
            <table className="plain ev-golden">
              <thead><tr><th>Item</th><th>Grade</th><th>Expected</th><th>Source</th><th>Check</th></tr></thead>
              <tbody>
                {items.map((i) => (
                  <tr key={i.id} aria-selected={i.id === sel} onClick={() => set("item", i.id)}>
                    <td><b>{i.label}</b><span className="sub">{i.qid}</span></td>
                    <td>{i.grade}</td>
                    <td className="ev-wrap">{i.expected}</td>
                    <td className="ev-wrap">
                      {i.source?.quotes.slice(0, 1).map((x, n) => <blockquote key={n} className="ev-quote">“{x.quote.length > 220 ? `${x.quote.slice(0, 220)}…` : x.quote}”<span>{x.doc_id.replace(/_/g, " ")}{i.source!.quotes.length > 1 ? ` · +${i.source!.quotes.length - 1} more` : ""}</span></blockquote>)}
                      {i.source?.method === "xbrl" && <span className="muted">XBRL {i.source.concepts?.join(" + ")}{i.source.end ? `, ${i.source.end}` : ""}</span>}
                      {i.source?.method === "derived" && <span className="muted">Computed from other XBRL items</span>}
                    </td>
                    <td><KeyStatus r={i.review} />{i.review_note && <span className="sub">{i.review_note}</span>}</td>
                  </tr>
                ))}
                {items.length === 0 && <tr><td colSpan={5} className="muted">No items match.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      {sel && <KeyPanel key={sel} id={sel} active={Number(params.get("p")) || 1} setActive={(n) => set("p", String(n))} onClose={() => set("item", null)} />}
    </div>
  );
}

function KeyPanel({ id, active, setActive, onClose }: { id: string; active: number; setActive: (n: number) => void; onClose: () => void }) {
  const qc = useQueryClient();
  const scroller = useRef<HTMLDivElement>(null);
  const q = useQuery({ queryKey: ["golden-item", id], queryFn: () => evalApi.goldenItem(id) });
  const [fixing, setFixing] = useState(false);
  const [note, setNote] = useState("");
  const act = useMutation({
    mutationFn: ({ action, note: n }: { action: "checked" | "needs_fix" | "undo"; note?: string }) => evalApi.review(id, action, n),
    onSuccess: (g) => { qc.setQueryData(["golden-item", id], g); qc.invalidateQueries({ queryKey: ["golden"] }); qc.invalidateQueries({ queryKey: ["evals"] }); qc.invalidateQueries({ queryKey: ["eval-run"] }); setFixing(false); },
  });
  const d: GoldenItem | undefined = q.data;
  const citations: Citation[] = (d?.quotes ?? []).map((x) => ({
    n: x.n, chunk_id: x.chunk_id, quote: x.quote, verified: !!x.chunk_id, doc_id: x.doc_id, form: x.form ?? null,
    period: x.period ?? null, filing_date: null, section: "", url: x.url ?? null,
  }));
  const loader: PassageLoader = { key: ["golden-passage", id], load: (chunk) => evalApi.goldenPassage(id, chunk) };
  return (
    <aside className="detail" aria-label="Answer-key item">
      <div className="d-head"><span className="where">Answer key · {id}</span><span className="sp" />
        <button className="btn sm sq ghost" aria-label="Close panel" onClick={onClose}><Icon name="x" /></button></div>
      <div className="d-body scroll" ref={scroller}>
        {q.isLoading && <div style={{ display: "grid", gap: 12 }}><Skeleton w="45%" h={18} /><Skeleton /><Skeleton w="80%" /></div>}
        {q.isError && <ErrorState title="Couldn't load this item" error={q.error} onRetry={() => q.refetch()} />}
        {d && <>
          <h2>{d.label} <span className="muted" style={{ fontWeight: 500 }}>· {d.ticker}</span></h2>
          <p className="q">{d.question}</p>
          <dl className="ev-kv">
            <dt>Expected</dt><dd>{d.expected.length > 80 ? d.expected : <b>{d.expected}</b>}{d.note && <span className="sub">{d.note}</span>}</dd>
            <dt>Graded</dt><dd>{d.grade}</dd>
            <dt>Check</dt><dd><KeyStatus r={d.review} />{d.review_note && <div className="ev-fixnote">{d.review_note}</div>}</dd>
            {d.quotes.length > 0 && <><dt>Source</dt><dd>{d.quotes.map((x) => (
              <button key={x.n} type="button" className={`ref${x.chunk_id ? "" : " missing"}`} aria-current={x.n === active}
                aria-label={`Show quote ${x.n}${x.chunk_id ? "" : " (not found in the filing text)"}`} onClick={() => setActive(x.n)}>{x.n}</button>))}
              <span className="sub">Check the expected answer against the highlighted text.</span></dd></>}
          </dl>
          {d.editable ? (
            <div className="ev-review">
              {d.review !== "human" && <button className="btn sm" disabled={act.isPending} onClick={() => act.mutate({ action: "checked" })}><Icon name="check" />Mark as checked</button>}
              {d.review !== "needs-fix" && !fixing && <button className="btn sm ghost" onClick={() => { setNote(""); setFixing(true); }}><Icon name="flag" />Needs fixing…</button>}
              {d.review !== "claude-draft" && <button className="btn sm ghost" disabled={act.isPending} onClick={() => act.mutate({ action: "undo" })}><Icon name="undo" />Undo</button>}
            </div>
          ) : <p className="muted small">Taken from the SEC's XBRL data{d.source?.concepts ? ` (${d.source.concepts.join(" + ")}${d.source.end ? `, period ending ${d.source.end}` : ""})` : ""}; no check needed.</p>}
          {fixing && (
            <form className="note-box" onSubmit={(e) => { e.preventDefault(); if (note.trim()) act.mutate({ action: "needs_fix", note }); }}>
              <label className="sr-only" htmlFor="fix-note">What needs fixing</label>
              <textarea id="fix-note" autoFocus value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="What's wrong with the expected answer" />
              <div className="row"><span style={{ flex: 1 }} />
                <button type="button" className="btn sm" onClick={() => setFixing(false)}>Cancel</button>
                <button type="submit" className="btn sm primary" disabled={!note.trim() || act.isPending}>Save</button></div>
            </form>
          )}
          {act.isError && <Notice kind="bad"><p>{(act.error as Error).message}</p></Notice>}
          {d.editable && <p className="muted small" style={{ marginTop: 8 }}>Saved to golden/manual.jsonl (this item's line only). Fixes to the expected answer are made in that file.</p>}
          {citations.length > 0 && <PassageView ticker={d.ticker} source={`golden:${id}`} citations={citations} active={active} onActive={setActive} scrollRoot={scroller} loader={loader} />}
        </>}
      </div>
    </aside>
  );
}
