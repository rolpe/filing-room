import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, type FindingDetail, type FindingRow, type Status } from "../lib/api";
import { date, findingValue, periodText, usd } from "../lib/format";
import { typing, useMedia, useToast } from "../lib/hooks";
import { Icon } from "../components/Icons";
import { PassageView } from "../components/PassageView";
import { StatusBadge } from "../components/Status";
import { ErrorState, Skeleton, SkeletonRows } from "../components/States";
import { useTicker } from "./Company";
import "../styles/findings.css";

type Filter = "all" | Status;

export function FindingsPage() {
  const t = useTicker();
  const [params, setParams] = useSearchParams();
  const selected = params.get("f");
  const wide = useMedia("(min-width: 1021px)");
  const list = useQuery({ queryKey: ["findings", t], queryFn: () => api.findings(t) });
  const [filter, setFilter] = useState<Filter>("all");
  const [text, setText] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  const rows = useMemo(() => {
    const needle = text.trim().toLowerCase();
    return (list.data?.groups ?? []).map((g) => ({
      ...g,
      items: g.items.filter((r) => (filter === "all" || r.status === filter) &&
        (!needle || `${r.label} ${r.gist} ${r.value_label} ${r.source} ${g.name}`.toLowerCase().includes(needle))),
    })).filter((g) => g.items.length);
  }, [list.data, filter, text]);
  const flat = useMemo(() => rows.flatMap((g) => g.items), [rows]);

  const select = (qid: string | null, replace = false) => {
    const next = new URLSearchParams(params);
    if (qid) next.set("f", qid); else next.delete("f");
    next.delete("p");
    setParams(next, { replace });
  };

  // Wide windows always show a finding; narrow ones open the drawer only on request.
  useEffect(() => {
    if (wide && !selected && flat.length) select(flat[0].qid, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wide, selected, flat.length]);

  const pos = flat.findIndex((r) => r.qid === selected);
  const move = (d: number) => {
    const i = pos < 0 ? 0 : Math.min(Math.max(pos + d, 0), flat.length - 1);
    if (flat[i]) select(flat[i].qid, true);
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (typing(e) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); move(-1); }
      else if (e.key === "Escape" && !wide && selected) select(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  useEffect(() => {  // keep the selected row visible
    listRef.current?.querySelector('tr[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  if (list.isLoading) return <div className="work solo"><div className="list" style={{ padding: "0 var(--gutter)" }}><SkeletonRows rows={10} cols={4} /></div></div>;
  if (list.isError) return <ErrorState title="Couldn't load findings" error={list.error} onRetry={() => list.refetch()} />;
  const counts = list.data!.counts;
  const segs: [Filter, string, number][] = [["all", "All", counts.total], ["verified", "Verified", counts.verified],
    ["review", "To review", counts.review], ["not_disclosed", "Not disclosed", counts.not_disclosed]];
  const group = rows.find((g) => g.items.some((r) => r.qid === selected));

  return (
    <div className={`work${selected ? "" : " solo"}`}>
      <section className="list" aria-label="Findings">
        <div className="tools">
          <label className="filter"><Icon name="search" />
            <input type="search" placeholder="Filter findings" aria-label="Filter findings" value={text} onChange={(e) => setText(e.target.value)} />
          </label>
          <div className="seg" role="group" aria-label="Status">
            {segs.map(([k, label, n]) => <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}>{label}<i>{n}</i></button>)}
          </div>
        </div>
        <div className="scroll" style={{ flex: 1, minHeight: 0 }} ref={listRef}>
          {flat.length === 0 ? <p className="empty">No findings match{text ? ` “${text}”` : " this filter"}.</p> : (
            <table className="find">
              <thead><tr><th>Finding</th><th className="num">Value</th><th className="src">Source</th><th>Status</th></tr></thead>
              <tbody>
                {rows.map((g) => [
                  <tr className="group" key={g.name}><td colSpan={4}>{g.name}<i>{g.items.length}</i></td></tr>,
                  ...g.items.map((r) => <Row key={r.qid} r={r} selected={r.qid === selected} onSelect={() => select(r.qid)} />),
                ])}
              </tbody>
            </table>
          )}
        </div>
      </section>
      {selected && (
        <FindingPanel key={selected} ticker={t} qid={selected} group={group?.name ?? ""}
          position={group ? `${group.items.findIndex((r) => r.qid === selected) + 1} of ${group.items.length}` : ""}
          onPrev={pos > 0 ? () => move(-1) : undefined} onNext={pos >= 0 && pos < flat.length - 1 ? () => move(1) : undefined}
          onClose={() => select(null)} />
      )}
    </div>
  );
}

function Row({ r, selected, onSelect }: { r: FindingRow; selected: boolean; onSelect: () => void }) {
  return (
    <tr aria-selected={selected} onClick={onSelect} tabIndex={-1}>
      <td className="what">
        <span className="label">{r.label}{r.has_note && <Icon name="note" />}</span>
        <span className="gist" title={r.gist}>{r.gist}</span>
      </td>
      <td className="num val">{r.value !== null ? findingValue(r.value, r.unit) : r.value_label}</td>
      <td className="src">{r.source}</td>
      <td className="st"><StatusBadge status={r.status} text={r.status === "verified" && r.reviewed_at ? "Reviewed" : undefined} /></td>
    </tr>
  );
}

// ---------------------------------------------------------------- detail panel

function Refs({ cites, active, onPick, missing }: { cites: number[]; active: number; onPick: (n: number) => void; missing: Set<number> }) {
  return <>{cites.map((n) => (
    <button key={n} type="button" className={`ref${missing.has(n) ? " missing" : ""}`} aria-current={n === active}
      aria-label={`Show quote ${n}${missing.has(n) ? " (not found in filing)" : ""}`} onClick={() => onPick(n)}>{n}</button>
  ))}</>;
}

function FindingPanel({ ticker, qid, group, position, onPrev, onNext, onClose }: {
  ticker: string; qid: string; group: string; position: string;
  onPrev?: () => void; onNext?: () => void; onClose: () => void;
}) {
  const [params, setParams] = useSearchParams();
  const q = useQuery({ queryKey: ["finding", ticker, qid], queryFn: () => api.finding(ticker, qid) });
  const scroller = useRef<HTMLDivElement>(null);
  const d = q.data;
  const active = Number(params.get("p")) || (d?.citations.find((c) => c.verified)?.n ?? d?.citations[0]?.n ?? 1);
  const setActive = (n: number) => {
    const next = new URLSearchParams(params);
    next.set("p", String(n));
    setParams(next, { replace: true });
  };

  return (
    <aside className="detail" aria-label="Finding detail">
      <div className="d-head">
        <span className="where">{group}{position && ` · ${position}`}</span>
        <span className="sp" />
        <button className="btn sm sq ghost" aria-label="Previous finding" disabled={!onPrev} onClick={onPrev}><Icon name="up" /></button>
        <button className="btn sm sq ghost" aria-label="Next finding" disabled={!onNext} onClick={onNext}><Icon name="dn" /></button>
        <button className="btn sm sq ghost" aria-label="Close panel" onClick={onClose}><Icon name="x" /></button>
      </div>
      <div className="d-body scroll" ref={scroller}>
        {q.isLoading && <div style={{ display: "grid", gap: 12 }}><Skeleton w="45%" h={18} /><Skeleton /><Skeleton w="90%" /><Skeleton w="70%" /></div>}
        {q.isError && <ErrorState title="Couldn't load this finding" error={q.error} onRetry={() => q.refetch()} />}
        {d && <Detail d={d} ticker={ticker} active={active} setActive={setActive} scroller={scroller} />}
      </div>
    </aside>
  );
}

function Detail({ d, ticker, active, setActive, scroller }: {
  d: FindingDetail; ticker: string; active: number; setActive: (n: number) => void; scroller: React.RefObject<HTMLDivElement | null>;
}) {
  const qc = useQueryClient();
  const [toast, setToast] = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(d.note?.text ?? "");
  const missing = new Set(d.citations.filter((c) => !c.verified).map((c) => c.n));
  const verifiedNs = d.citations.filter((c) => c.verified).map((c) => c.n);
  const onSaved = (nd: FindingDetail) => {
    qc.setQueryData(["finding", ticker, d.qid], nd);
    qc.invalidateQueries({ queryKey: ["findings", ticker] });
    qc.invalidateQueries({ queryKey: ["company", ticker] });
    qc.invalidateQueries({ queryKey: ["coverage"] });
  };
  const note = useMutation({ mutationFn: (text: string) => api.note(ticker, d.qid, text), onSuccess: (nd) => { onSaved(nd); setEditing(false); } });
  const flag = useMutation({ mutationFn: (v: boolean) => api.flag(ticker, d.qid, v), onSuccess: onSaved });
  const review = useMutation({ mutationFn: (v: boolean) => api.review(ticker, d.qid, v), onSuccess: onSaved });
  const err = (note.error || flag.error || review.error) as Error | null;

  const [lead, ...rest] = d.points;
  const copy = async () => {
    const c = d.citations.find((x) => x.n === active && x.verified) ?? d.citations.find((x) => x.verified);
    const summary = d.points.map((p) => p.text).join(" ") || d.answer;
    const src = c ? `\nSource: ${ticker} ${c.form ?? ""} ${c.period ?? ""}, ${c.section}${c.filing_date ? ` (filed ${date(c.filing_date)})` : ""}.\n“${c.quote}”\n${c.url ?? ""}` : "";
    try {
      await navigator.clipboard.writeText(`${d.label} (${ticker}): ${summary}${src}`);
      setToast("Copied with citation");
    } catch {
      setToast("Couldn't copy: clipboard not available");
    }
  };

  const sec = d.facts.sec_check;
  return (
    <>
      <h2>{d.label}</h2>
      <p className="q">{d.question}</p>
      {d.status === "not_disclosed" ? (
        <Clamp key={d.qid}><p className="lead">{d.answer || "The filings reviewed don't disclose this."}</p></Clamp>
      ) : (
        <>
          {lead && (d.presented
            ? <p className="lead">{lead.text}<Refs cites={lead.cites} active={active} onPick={setActive} missing={missing} /></p>
            : <Clamp key={d.qid}><p className="lead">{lead.text}<Refs cites={lead.cites} active={active} onPick={setActive} missing={missing} /></p></Clamp>)}
          {rest.length > 0 && (
            <ul className="terms">
              {rest.map((p, i) => <li key={i}>{p.text}<Refs cites={p.cites} active={active} onPick={setActive} missing={missing} /></li>)}
            </ul>
          )}
        </>
      )}

      <dl className="facts">
        <div><dt>Status</dt><dd>
          {d.status === "verified" && d.reviewed_at
            ? <StatusBadge status="verified" text={`Reviewed ${date(d.reviewed_at)}`} />
            : d.status === "not_disclosed" ? <StatusBadge status="not_disclosed" text="Not disclosed in the filings" />
            : d.facts.quotes_found
              ? <StatusBadge status={d.status} text={`${d.facts.quotes_found} quotes found in filing`} />
              : <StatusBadge status={d.status} />}
        </dd></div>
        {d.facts.period && <div><dt>Period</dt><dd title={periodText(d.facts.period_full)}>{periodText(d.facts.period)}</dd></div>}
        {d.facts.confidence && d.status !== "not_disclosed" && <div><dt>Confidence</dt><dd style={{ textTransform: "capitalize" }}>{d.facts.confidence}</dd></div>}
        {sec && <div><dt>SEC data</dt><dd>{sec.match
          ? <span className="status ok"><Icon name="check" />Matches XBRL{sec.period ? `, ${sec.period}` : ""}</span>
          : <span className="status warn"><Icon name="flag" />XBRL reports {sec.expected !== null ? (d.unit === "USD" ? usd(sec.expected) : sec.expected) : "a different value"}</span>}</dd></div>}
      </dl>

      {d.reasons.length > 0 && (
        <div className={`reasons${d.status === "verified" ? " cleared" : ""}`}>
          <b>{d.status === "verified" ? "Checked by you despite:" : "Why it needs review:"}</b>
          <ul>{d.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      )}

      <div className="acts">
        {d.status !== "not_disclosed" && verifiedNs.length > 0 &&
          <button className="btn sm ghost" onClick={copy}><Icon name="copy" />Copy with citation</button>}
        {!editing && <button className="btn sm ghost" onClick={() => { setDraft(d.note?.text ?? ""); setEditing(true); }}>
          <Icon name="note" />{d.note ? "Edit note" : "Add note"}</button>}
        {d.status === "review" && !d.flagged &&
          <button className="btn sm ghost" disabled={review.isPending} onClick={() => review.mutate(true)}><Icon name="check" />Mark as reviewed</button>}
        {d.reviewed_at && <button className="btn sm ghost" disabled={review.isPending} onClick={() => review.mutate(false)}><Icon name="undo" />Undo review</button>}
        <button className="btn sm ghost" aria-pressed={d.flagged} disabled={flag.isPending} onClick={() => flag.mutate(!d.flagged)}>
          <Icon name="flag" />{d.flagged ? "Remove flag" : "Flag for review"}</button>
      </div>
      {err && <p className="status bad" role="alert" style={{ marginTop: 6 }}>{err.message}</p>}

      {(editing || d.note) && (
        <div className="note-box">
          {editing ? (
            <form onSubmit={(e) => { e.preventDefault(); note.mutate(draft); }}>
              <label className="sr-only" htmlFor="note-text">Note</label>
              <textarea id="note-text" autoFocus value={draft} maxLength={4000} onChange={(e) => setDraft(e.target.value)}
                placeholder="What you checked, what's open, who to ask" />
              <div className="row">
                {d.note && <button type="button" className="btn sm ghost" onClick={() => note.mutate("")}>Delete note</button>}
                <span style={{ flex: 1 }} />
                <button type="button" className="btn sm" onClick={() => setEditing(false)}>Cancel</button>
                <button type="submit" className="btn sm primary" disabled={note.isPending}>Save note</button>
              </div>
            </form>
          ) : d.note && <><p>{d.note.text}</p>{d.note.at && <small>Note · {date(d.note.at)}</small>}</>}
        </div>
      )}

      {missing.size > 0 && (
        <div className="missing-quotes">
          <h3>Cited but not found in the filing</h3>
          {d.citations.filter((c) => !c.verified).map((c) => (
            <blockquote key={c.n}><b>{c.n} · not found in filing</b>{c.quote}</blockquote>
          ))}
        </div>
      )}

      {d.citations.length > 0 && (
        <PassageView ticker={ticker} source={`finding:${d.qid}`} citations={d.citations} active={active} onActive={setActive} scrollRoot={scroller} />
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </>
  );
}

/** Long answer prose (no presentation pass) is clamped to about six lines so the filing passage stays in view. */
function Clamp({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [over, setOver] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => setOver(el.scrollHeight > el.clientHeight + 2);
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return (
    <>
      <div ref={ref} className={open ? "clamp open" : "clamp"}>{children}</div>
      {(over || open) && <button type="button" className="btn ghost sm more-btn" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Icon name={open ? "up" : "dn"} />{open ? "Show less" : "Show more"}</button>}
    </>
  );
}
