import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, ApiError, type Memo } from "../lib/api";
import { date } from "../lib/format";
import { Icon } from "../components/Icons";
import { ErrorState, Skeleton } from "../components/States";
import { FindingPanel } from "./Findings";
import { useCompany, useTicker } from "./Company";
import "../styles/findings.css";
import "../styles/memo.css";

export function MemoPage() {
  const t = useTicker();
  const co = useCompany(t).data;
  const [params, setParams] = useSearchParams();
  const q = useQuery({ queryKey: ["memo", t], queryFn: () => api.memo(t), retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 1 });
  const fl = useQuery({ queryKey: ["findings", t], queryFn: () => api.findings(t) });
  const noteN = Number(params.get("note")) || null;
  const m = q.data;
  const note = m?.notes.find((x) => x.n === noteN) ?? null;

  useEffect(() => {  // Export > Print opens this tab with ?print=1
    if (m && params.get("print") === "1") {
      const next = new URLSearchParams(params);
      next.delete("print");
      setParams(next, { replace: true });
      setTimeout(() => window.print(), 300);
    }
  }, [m, params, setParams]);

  const open = (n: number | null) => {
    const next = new URLSearchParams(params);
    if (n) next.set("note", String(n)); else next.delete("note");
    next.delete("p");
    setParams(next, { replace: !!noteN && !!n });
  };
  const group = fl.data?.groups.find((g) => g.items.some((r) => r.qid === note?.qid));

  return (
    <div className={`work memo-work${note ? "" : " solo"}`}>
      <div className="scroll memo-scroll">
        {q.isLoading && <div className="memo-doc" aria-busy="true"><Skeleton w="50%" h={22} /><div style={{ display: "grid", gap: 10, marginTop: 24 }}>{[1, 2, 3, 4, 5, 6].map((i) => <Skeleton key={i} w={`${90 - i * 5}%`} />)}</div></div>}
        {q.isError && (q.error instanceof ApiError && q.error.status === 404
          ? <ErrorState title="No screening memo yet">
              <p>The memo is drafted at the end of a screening, from verified findings only. This company's screening finished without one.</p>
            </ErrorState>
          : <ErrorState title="Couldn't load the screening memo" error={q.error} onRetry={() => q.refetch()} />)}
        {m && <MemoDoc m={m} name={co?.name ?? t} ticker={t} active={noteN} onNote={open} />}
      </div>
      {note && (
        <FindingPanel key={note.qid} ticker={t} qid={note.qid} group={group?.name ?? "Source"} position={`Note ${note.n}`}
          onClose={() => open(null)} />
      )}
    </div>
  );
}

function MemoDoc({ m, name, ticker, active, onNote }: { m: Memo; name: string; ticker: string; active: number | null; onNote: (n: number) => void }) {
  const flagged = m.check?.flagged ?? 0;
  return (
    <article className="memo-doc">
      <div className="memo-tools no-print">
        <span className="muted">{m.notes.length} sources · drafted {date(m.generated?.slice(0, 10))}</span>
        <span className="sp" />
        <a className="btn sm" href={`/api/companies/${ticker}/export/memo.md`}><Icon name="down" />Markdown</a>
        <button className="btn sm" onClick={() => window.print()}><Icon name="print" />Print</button>
      </div>
      <header>
        <p className="kicker">Screening memo</p>
        <h1>{name} <span className="muted">({ticker})</span></h1>
        <p className="byline">From public SEC filings only. Every statement of fact cites a verified finding; the numbers point to the sources listed at the end.</p>
        {flagged > 0 && <p className="flag-note"><Icon name="flag" /> {flagged} {flagged === 1 ? "sentence is" : "sentences are"} marked: the automatic claim check found {flagged === 1 ? "it" : "them"} not fully supported by the cited findings.</p>}
      </header>
      {m.sections.map((s) => (
        <section key={s.heading}>
          <h2>{s.heading}</h2>
          <p>
            {s.sentences.map((x) => (
              <span key={x.n} className={x.flagged ? "flagged" : undefined} title={x.flagged ? `Not fully supported: ${x.reason}` : undefined}>
                {x.text}
                {x.notes.map((n) => (
                  <button key={n} type="button" className="fn" aria-current={n === active} aria-label={`Source ${n}`} onClick={() => onNote(n)}>{n}</button>
                ))}
                {x.flagged && <span className="sr-only"> (flagged: not fully supported)</span>}{" "}
              </span>
            ))}
          </p>
        </section>
      ))}
      {m.open_questions.length > 0 && (
        <section>
          <h2>Open questions</h2>
          <ul>{m.open_questions.map((q) => <li key={q}>{q}</li>)}</ul>
        </section>
      )}
      <section className="sources">
        <h2>Sources</h2>
        <ol>
          {m.notes.map((n) => (
            <li key={n.n} value={n.n}>
              <button type="button" className="src-link no-print-style" onClick={() => onNote(n.n)}>{n.label}</button>
              <span className="print-only"> · “{n.quote}” {n.doc_id.replace(/_/g, " ")}{n.section ? `, ${n.section}` : ""}. {n.url}</span>
            </li>
          ))}
        </ol>
      </section>
    </article>
  );
}
