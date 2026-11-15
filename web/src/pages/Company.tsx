import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, NavLink, Outlet, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, type CompanyHeader, type Figure } from "../lib/api";
import { count, date, money, pct, pctChange, shortDate, usd } from "../lib/format";
import { pushRecent } from "../lib/recent";
import { Icon } from "../components/Icons";
import { ConfirmDialog, MenuButton } from "../components/Menu";
import { ErrorState, Notice, Skeleton } from "../components/States";
import { useAddCompany } from "../components/AddCompany";
import "../styles/company.css";

export function useTicker(): string {
  return (useParams().ticker ?? "").toUpperCase();
}

export function useCompany(t: string) {
  return useQuery({
    queryKey: ["company", t], queryFn: () => api.company(t), retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 2,
    refetchInterval: (q) => (q.state.data?.state === "processing" ? 2000 : false),
  });
}

function fig(f: Figure) {
  const v = f.kind === "usd" ? usd(f.value) : f.kind === "pct" ? pct(f.value) : count(f.value);
  const sub = f.sub === null || f.sub === undefined ? "" : f.sub_kind === "pct_change" ? pctChange(f.sub) : pct(f.sub);
  const val = f.qid ? <Link className="fig-link" to={`findings?f=${f.qid}`} title="Open the finding">{v}</Link> : v;
  return <><dt>{f.label}</dt><dd>{val}{sub && <small>{sub}</small>}</dd></>;
}

export function CompanyPage() {
  const t = useTicker();
  const q = useCompany(t);
  const qc = useQueryClient();
  useEffect(() => { if (q.data) pushRecent(t); }, [q.data, t]);
  useEffect(() => {  // a screening that just finished: refresh everything that depends on it
    if (q.data?.state === "ready") qc.invalidateQueries({ queryKey: ["findings", t] });
  }, [q.data?.state, qc, t]);
  useEffect(() => { document.title = q.data ? `${q.data.name} · filing-room` : "filing-room"; }, [q.data]);

  if (q.isLoading) return <HeaderSkeleton />;
  if (q.isError) {
    const nf = q.error instanceof ApiError && q.error.status === 404;
    return <ErrorState title={nf ? `${t} isn't in your coverage` : "Couldn't load this company"} error={nf ? undefined : q.error}
      onRetry={nf ? undefined : () => q.refetch()}>{nf && <p><Link className="link" to="/">Back to coverage</Link></p>}</ErrorState>;
  }
  const c = q.data!;
  return (
    <>
      <Header c={c} />
      {c.state === "ready" ? (
        <>
          <nav className="tabs" aria-label="Company sections">
            <NavLink to="overview">Overview</NavLink>
            <NavLink to="findings">Findings <i>{c.counts.total}</i></NavLink>
            <NavLink to="memo">Screening memo</NavLink>
            <NavLink to="qa">Q&amp;A{c.questions > 0 && <i>{c.questions}</i>}</NavLink>
            <NavLink to="filings">Filings <i>{c.filings}</i></NavLink>
          </nav>
          <Outlet />
        </>
      ) : <NotReady c={c} />}
    </>
  );
}

function Header({ c }: { c: CompanyHeader }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const rm = useMutation({
    mutationFn: () => api.remove(c.ticker),
    onSuccess: (data) => { qc.setQueryData(["coverage"], data); qc.removeQueries({ queryKey: ["company", c.ticker] }); nav("/"); },
  });
  const tenk = c.latest_10k;
  const meta = [
    c.fy_end && `Fiscal year ends ${c.fy_end}`,
    c.filings > 0 && `${c.filings} filings${tenk ? ` through the ${tenk.period} 10-K, filed ${date(tenk.date)}` : ""}`,
    c.updated && `Updated ${shortDate(c.updated)}`,
  ].filter(Boolean).join(" · ");
  return (
    <header className="co-head">
      <nav className="crumb" aria-label="Breadcrumb"><Link to="/">Coverage</Link><Icon name="chev" /><span>{c.ticker}</span></nav>
      <div className="title-row">
        <h1>{c.name}</h1>
        <span className="tick">{c.ticker}</span>
        <span className="sp" />
        <div className="acts">
          {c.state === "ready" && (
            <MenuButton label="Export" icon="down">
              {(close) => <>
                <a role="menuitem" href={`/api/companies/${c.ticker}/export/findings.csv`} onClick={close}>Findings (CSV, with sources)</a>
                {c.has_memo && <a role="menuitem" href={`/api/companies/${c.ticker}/export/memo.md`} onClick={close}>Screening memo (Markdown)</a>}
                {c.has_memo && <button role="menuitem" onClick={() => { close(); nav("memo?print=1"); }}>Print screening memo…</button>}
              </>}
            </MenuButton>
          )}
          {c.state === "ready" && <button className="btn primary" onClick={() => nav("qa")}><Icon name="ask" />Ask a question</button>}
          <MenuButton icon="more" ghost ariaLabel="More actions">
            {(close) => <button role="menuitem" className="danger" onClick={() => { close(); setConfirm(true); }}><Icon name="trash" />Remove from coverage…</button>}
          </MenuButton>
        </div>
      </div>
      {meta && <p className="meta">{meta}</p>}
      {c.figures.length > 0 && (
        <dl className="figures">
          {c.figures.map((f) => <div key={f.key}>{fig(f)}</div>)}
        </dl>
      )}
      {c.figures.length === 0 && <div style={{ height: 14 }} />}
      {confirm && (
        <ConfirmDialog title={`Remove ${c.ticker} from coverage?`} confirm="Remove" danger busy={rm.isPending}
          onConfirm={() => rm.mutate()} onClose={() => setConfirm(false)}>
          <p>This deletes its findings, notes, screening memo and questions from this app. Downloaded filings stay cached, so adding it again costs only the screening.</p>
          {rm.isError && <Notice kind="bad"><p>{(rm.error as Error).message}</p></Notice>}
        </ConfirmDialog>
      )}
    </header>
  );
}

function NotReady({ c }: { c: CompanyHeader }) {
  const add = useAddCompany();
  const j = c.job;
  return (
    <div className="co-state" style={{ borderTop: "1px solid var(--line)" }}>
      {c.state === "processing" && j && (
        <Notice icon="usage">
          <p><b>Screening in progress.</b> Findings, memo and Q&amp;A open when it finishes.</p>
          <span className="sp" />
          <span className="prog wide"><span className="track"><i style={{ transform: `scaleX(${Math.max(0.03, j.fraction)})` }} /></span>{j.label}</span>
        </Notice>
      )}
      {c.state === "failed" && (
        <Notice kind="bad">
          <p><b>Screening stopped.</b> {j?.error ?? "It didn't finish."}{j?.cost_usd ? ` Spent so far: ${money(j.cost_usd)}.` : ""}</p>
          <span className="sp" />
          <button className="btn sm" onClick={() => add(c.ticker)}><Icon name="play" />Resume…</button>
        </Notice>
      )}
    </div>
  );
}

function HeaderSkeleton() {
  return (
    <div className="co-head" aria-busy="true">
      <Skeleton w={120} h={10} />
      <Skeleton w={280} h={20} style={{ marginTop: 10 }} />
      <Skeleton w={420} h={10} style={{ marginTop: 10 }} />
      <div style={{ display: "flex", gap: 28, margin: "18px 0 14px" }}>
        {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} w={90} h={26} />)}
      </div>
    </div>
  );
}
