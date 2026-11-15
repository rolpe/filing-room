import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, type Preview } from "../lib/api";
import { money } from "../lib/format";
import { Icon } from "./Icons";
import { Notice, Skeleton } from "./States";

// One dialog for adding a company and for resuming one whose screening stopped. Paid: shows the estimate and the
// day's budget, and starts only on an explicit click. While another company is being screened it offers nothing.

const Ctx = createContext<(ticker: string) => void>(() => {});
export const useAddCompany = () => useContext(Ctx);

export function AddCompanyProvider({ children }: { children: ReactNode }) {
  const [ticker, setTicker] = useState<string | null>(null);
  const open = useCallback((t: string) => setTicker(t.toUpperCase()), []);
  return (
    <Ctx.Provider value={open}>
      {children}
      {ticker && <AddDialog ticker={ticker} onClose={() => setTicker(null)} />}
    </Ctx.Provider>
  );
}

const FORMS: [string, string, string][] = [
  ["10-K", "annual report", "annual reports"],
  ["10-Q", "quarterly report", "quarterly reports"],
  ["DEF 14A", "proxy statement", "proxy statements"],
  ["8-K", "earnings release", "earnings releases"],
];

const READ: Record<string, number> = { "10-K": 2, "10-Q": 4, "DEF 14A": 1, "8-K": 1 }; // what a screening reads

function filingsText(f: Record<string, number>) {
  return FORMS.filter(([k]) => f[k]).map(([k, one, many]) => {
    const n = Math.min(f[k], READ[k]);
    return `${n} ${n === 1 ? one : many}`;
  }).join(", ");
}

function AddDialog({ ticker, onClose }: { ticker: string; onClose: () => void }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const ref = useRef<HTMLDivElement>(null);
  const q = useQuery({ queryKey: ["preview", ticker], queryFn: () => api.preview(ticker), staleTime: 0, retry: false });
  const p = q.data;
  const resume = !!p && p.in_coverage && p.state === "failed";
  const go = useMutation({
    mutationFn: (pv: Preview) => (resume ? api.retry(pv.ticker, pv.estimate.usd) : api.start(pv.ticker, pv.estimate.usd)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["coverage"] });
      qc.invalidateQueries({ queryKey: ["company", ticker] });
      onClose();
      if (!resume) nav("/");
    },
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  let footer: ReactNode = <button className="btn" onClick={onClose}>Cancel</button>;
  let body: ReactNode;
  if (q.isLoading) {
    body = <div style={{ display: "grid", gap: 10, padding: "8px 0 14px" }}><Skeleton w="60%" /><Skeleton w="80%" /><Skeleton w="40%" /></div>;
  } else if (q.isError || !p) {
    body = <Notice kind="bad"><p>{(q.error as Error)?.message || "Couldn't look this company up on EDGAR."}</p></Notice>;
    footer = <><button className="btn" onClick={onClose}>Close</button><button className="btn" onClick={() => q.refetch()}>Try again</button></>;
  } else {
    const overCap = p.estimate.usd > p.cap.remaining_usd;
    const ready = p.in_coverage && p.state !== "failed";
    body = (
      <>
        <dl className="kv">
          <dt>Company</dt><dd>{p.name} <span className="muted">· {p.ticker} · CIK {p.cik}</span></dd>
          {p.sic && <><dt>Industry</dt><dd>{p.sic}</dd></>}
          {p.fy_end && <><dt>Fiscal year ends</dt><dd>{p.fy_end}</dd></>}
          <dt>Filings to read</dt><dd>{filingsText(p.filings) || "None found"}</dd>
          {p.eligible && !ready && <>
            <dt>{resume ? "To finish" : "Estimated cost"}</dt>
            <dd><b>About {money(p.estimate.usd)}</b> in model usage · {p.estimate.minutes} minutes
              {resume && p.estimate.answers_done > 0 && <div className="muted">{p.estimate.answers_done} of {p.estimate.answers_total} answers are kept from the first attempt</div>}
            </dd>
            <dt>Today</dt><dd>{money(p.cap.today_usd)} of {money(p.cap.cap_usd)} daily screening budget used</dd>
          </>}
        </dl>
        {!p.eligible && <Notice kind="warn"><p>{p.reason}</p></Notice>}
        {ready && <Notice icon="check"><p>{p.ticker} is already in coverage.</p></Notice>}
        {p.eligible && !ready && p.busy && <Notice><p>{p.busy} is being screened now. One company at a time: come back when it finishes.</p></Notice>}
        {p.eligible && !ready && !p.busy && overCap && <Notice kind="warn"><p>This would go over today's screening budget. Raise RUN_MAX_USD_PER_DAY in .env, or try tomorrow.</p></Notice>}
        {!resume && p.eligible && !ready && !p.busy && !overCap &&
          <p>Reads the latest 10-Ks, 10-Qs, proxy and earnings release from EDGAR, answers 39 screening questions with quotes checked against the filings, and drafts a screening memo.</p>}
        {go.isError && <Notice kind="bad"><p>{(go.error as Error).message}</p></Notice>}
      </>
    );
    if (ready) {
      footer = <><button className="btn" onClick={onClose}>Close</button>
        <button className="btn primary" onClick={() => { onClose(); nav(`/c/${p.ticker}`); }}>Open {p.ticker}</button></>;
    } else if (p.eligible && !p.busy && !overCap) {
      footer = <>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={go.isPending} onClick={() => go.mutate(p)}>
          <Icon name={resume ? "play" : "plus"} />
          {go.isPending ? "Starting…" : `${resume ? "Resume" : "Screen"} ${p.ticker} · about ${money(p.estimate.usd)}`}
        </button>
      </>;
    } else {
      footer = <button className="btn" onClick={onClose}>Close</button>;
    }
  }

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="add-title" tabIndex={-1} ref={ref}>
        <header>
          <h2 id="add-title">{resume ? `Resume screening ${ticker}` : `Add ${p?.name ?? ticker}`}</h2>
          <button className="btn ghost sm sq" aria-label="Close" onClick={onClose}><Icon name="x" /></button>
        </header>
        <div className="body">{body}</div>
        <footer>{footer}</footer>
      </div>
    </div>
  );
}
