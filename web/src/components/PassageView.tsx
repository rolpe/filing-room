import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Block, type Citation, type Mark, type Passage } from "../lib/api";
import { date } from "../lib/format";
import { Icon } from "./Icons";
import { Skeleton } from "./States";

// The filing text behind a set of citations: every quote of the source that sits in this passage is highlighted,
// the active one stronger. Navigation moves between the source's citations; earlier/later text loads neighbours.

function renderText(text: string, marks: Mark[], active: number, firstSeen: Set<number>): ReactNode[] {
  const out: ReactNode[] = [];
  let pos = 0;
  const ms = [...marks].sort((a, b) => a.start - b.start);
  ms.forEach((m, i) => {
    if (m.start < pos) return; // overlapping quotes: keep the first
    if (m.start > pos) out.push(text.slice(pos, m.start));
    const sup = !firstSeen.has(m.cite);
    firstSeen.add(m.cite);
    out.push(
      <mark key={i} className={m.cite === active ? "on" : undefined} data-cite={m.cite}>
        {sup && <sup>{m.cite}</sup>}{text.slice(m.start, m.end)}
      </mark>,
    );
    pos = m.end;
  });
  if (pos < text.length) out.push(text.slice(pos));
  return out;
}

export function Blocks({ blocks, active, dim }: { blocks: Block[]; active: number; dim: boolean }) {
  const seen = new Set<number>();
  return (
    <>
      {blocks.map((b, i) => {
        if (b.type === "p") {
          const ctx = dim && b.marks.length === 0;
          return <p key={i} className={ctx ? "ctx" : undefined}>{renderText(b.text, b.marks, active, seen)}</p>;
        }
        const has = b.rows.some((r) => r.some((c) => c.marks.length));
        return (
          <div key={i} className="tbl"><table className={dim && !has ? "ctx" : undefined}>
            <tbody>
              {b.rows.map((r, j) => (
                <tr key={j}>{r.map((c, k) => <td key={k}>{renderText(c.text, c.marks, active, seen)}</td>)}</tr>
              ))}
            </tbody>
          </table></div>
        );
      })}
    </>
  );
}

function Neighbor({ ticker, chunk, source }: { ticker: string; chunk: string; source: string }) {
  const q = useQuery({ queryKey: ["passage", ticker, chunk, source], queryFn: () => api.passage(ticker, chunk, source) });
  if (q.isLoading) return <div style={{ display: "grid", gap: 8, marginBottom: 14 }}><Skeleton /><Skeleton w="80%" /></div>;
  if (!q.data) return null;
  return <><Blocks blocks={q.data.blocks} active={-1} dim /><hr className="sep" /></>;
}

export function PassageView({ ticker, source, citations, active, onActive, scrollRoot }: {
  ticker: string; source: string; citations: Citation[]; active: number; onActive: (n: number) => void;
  scrollRoot?: React.RefObject<HTMLElement | null>;
}) {
  const c = citations.find((x) => x.n === active) ?? citations[0];
  const idx = c ? citations.indexOf(c) : -1;
  const chunk = c?.chunk_id ?? null;
  const q = useQuery({
    queryKey: ["passage", ticker, chunk, source], queryFn: () => api.passage(ticker, chunk!, source),
    enabled: !!chunk, retry: false,
  });
  const [before, setBefore] = useState<string[]>([]);
  const [after, setAfter] = useState<string[]>([]);
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => { setBefore([]); setAfter([]); }, [chunk]);
  const lastActive = useRef(active);
  useEffect(() => {  // bring the active quote into view when the reader moves to another one (not on first open)
    if (!q.data || !body.current || q.data.chunk_id !== chunk || lastActive.current === active) return;
    lastActive.current = active;
    const el = body.current.querySelector(`mark[data-cite="${c?.n}"]`) as HTMLElement | null;
    const root = scrollRoot?.current;
    if (el && root) {
      const r = el.getBoundingClientRect();
      const rr = root.getBoundingClientRect();
      if (r.top < rr.top + 40 || r.bottom > rr.bottom - 20) root.scrollTo({ top: root.scrollTop + r.top - rr.top - rr.height / 3, behavior: "smooth" });
    }
  }, [q.data, active, chunk, c?.n, scrollRoot]);

  if (!c) return null;
  const p: Passage | undefined = q.data;
  return (
    <div className="doc">
      <div className="doc-head">
        <div className="t">
          <b>{p?.form_label ?? (c.form ? `${c.form} ${c.period ?? ""}` : "Filing")}</b>
          <span>{[p?.filing_date && `Filed ${date(p.filing_date)}`, p?.heading || c.section].filter(Boolean).join(" · ")}</span>
        </div>
        <span className="sp" />
        {citations.length > 1 && <span className="pos">Passage {idx + 1} of {citations.length}</span>}
        {citations.length > 1 && <>
          <button className="btn sm sq ghost" aria-label="Previous passage" disabled={idx <= 0} onClick={() => onActive(citations[idx - 1].n)}><Icon name="up" /></button>
          <button className="btn sm sq ghost" aria-label="Next passage" disabled={idx >= citations.length - 1} onClick={() => onActive(citations[idx + 1].n)}><Icon name="dn" /></button>
        </>}
        {(p?.url || c.url) && <a className="btn sm" href={p?.url || c.url || "#"} target="_blank" rel="noreferrer noopener"><Icon name="ext" />sec.gov</a>}
      </div>
      <div className="filing" ref={body}>
        {!c.verified && (
          <div className="notice warn miss">
            <Icon name="alert" />
            <p>Quote {c.n} was not found in the filing text. The answer cited it from this passage{chunk ? "" : ", which could not be identified"}:
              <br /><span style={{ fontFamily: "var(--serif)" }}>“{c.quote}”</span></p>
          </div>
        )}
        {chunk && q.isLoading && <div style={{ display: "grid", gap: 10 }}><Skeleton w="40%" /><Skeleton /><Skeleton /><Skeleton w="70%" /></div>}
        {chunk && q.isError && <p className="miss">This passage could not be loaded. {(q.error as Error).message}</p>}
        {p && <>
          {p.prev_chunk && before.length < MAX_EXTRA && (
            <div className="more"><button className="btn sm ghost" onClick={() => setBefore((b) => [prevOf(p, b), ...b].filter(Boolean) as string[])}>
              <Icon name="up" />Earlier text</button></div>
          )}
          {before.map((id) => <Neighbor key={id} ticker={ticker} chunk={id} source={source} />)}
          {p.subheading && !startsWith(p, p.subheading) && <h3>{p.subheading}</h3>}
          <Blocks blocks={p.blocks} active={c.n} dim={p.found.length > 0} />
          {after.map((id) => <Neighbor key={id} ticker={ticker} chunk={id} source={source} />)}
          {p.next_chunk && after.length < MAX_EXTRA && (
            <div className="more"><button className="btn sm ghost" onClick={() => setAfter((a) => [...a, nextOf(p, a)].filter(Boolean) as string[])}>
              <Icon name="dn" />Later text</button></div>
          )}
        </>}
      </div>
    </div>
  );
}

function startsWith(p: Passage, heading: string) {
  const b = p.blocks[0];
  return !!b && b.type === "p" && b.text.trim().toLowerCase() === heading.trim().toLowerCase();
}

const MAX_EXTRA = 3; // neighbouring passages to load either side; beyond that, open the filing on sec.gov

// Chunk ids end in a three-digit sequence within their section ("...#item8#041").
function step(id: string, d: number): string | null {
  const m = /^(.*#)(\d{3})$/.exec(id);
  if (!m) return null;
  const n = Number(m[2]) + d;
  return n < 0 ? null : `${m[1]}${String(n).padStart(3, "0")}`;
}
function prevOf(p: Passage, before: string[]) {
  return before.length ? step(before[0], -1) : p.prev_chunk;
}
function nextOf(p: Passage, after: string[]) {
  return after.length ? step(after[after.length - 1], 1) : p.next_chunk;
}
