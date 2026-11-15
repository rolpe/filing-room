import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, type CoverageRow } from "../lib/api";
import { ago, date, pct, shortDate, usd } from "../lib/format";
import { CompanySearch, type SearchHandle } from "../components/CompanySearch";
import { useAddCompany } from "../components/AddCompany";
import { Icon } from "../components/Icons";
import { ErrorState, SkeletonRows } from "../components/States";
import "../styles/coverage.css";

type Filter = "all" | "ready" | "processing" | "review" | "failed";

export function CoveragePage() {
  const search = useRef<SearchHandle>(null);
  const q = useQuery({
    queryKey: ["coverage"], queryFn: api.coverage,
    refetchInterval: (query) => (query.state.data?.counts.processing ? 2000 : false),
  });
  const [filter, setFilter] = useState<Filter>("all");
  const data = q.data;
  const empty = data && data.companies.length === 0;

  return (
    <>
      {!empty && (
        <div className="bar">
          <CompanySearch ref={search} shortcut />
          <span className="sp" />
          <button className="btn primary" onClick={() => search.current?.focus()}><Icon name="plus" />Add company</button>
        </div>
      )}
      {q.isLoading && <div className="page-body"><div className="page-head" style={{ padding: "22px 0 14px" }}><h1>Coverage</h1></div><SkeletonRows rows={4} cols={8} /></div>}
      {q.isError && <ErrorState title="Couldn't load coverage" error={q.error} onRetry={() => q.refetch()} />}
      {empty && <FirstRun />}
      {data && !empty && <CoverageTable rows={data.companies} counts={data.counts} filter={filter} setFilter={setFilter} />}
    </>
  );
}

function FirstRun() {
  return (
    <div className="scroll" style={{ flex: 1 }}>
      <div className="first">
        <h1>Screen a public company from its SEC filings</h1>
        <p>Find a US-listed company to add it to your coverage.</p>
        <CompanySearch large shortcut autoFocus />
        <div className="hint">Search by name or ticker. Any company that files 10-Ks with the SEC works.</div>
        <dl>
          <dt>What you get</dt>
          <dd>39 findings on ownership, capital structure, revenue, profitability, people and risk, each tied to a quote checked against the filing; five years of financials from SEC data; a screening memo; and a place to ask follow-up questions.</dd>
          <dt>Sources</dt>
          <dd>The last two 10-Ks, last four 10-Qs, latest proxy statement and latest earnings release, from SEC EDGAR. Nothing else.</dd>
          <dt>Cost and time</dt>
          <dd>About $1.25 in model usage and a few minutes per company. You confirm the cost before anything runs; spending is capped per day.</dd>
        </dl>
      </div>
    </div>
  );
}

function CoverageTable({ rows, counts, filter, setFilter }:
  { rows: CoverageRow[]; counts: Record<string, number>; filter: Filter; setFilter: (f: Filter) => void }) {
  const nav = useNavigate();
  const shown = rows.filter((r) =>
    filter === "all" ? true : filter === "review" ? !!r.findings?.review : r.state === filter);
  const segs: [Filter, string][] = [["all", "All"], ["ready", "Ready"], ["processing", "In progress"], ["review", "To review"]];
  if (counts.failed) segs.push(["failed", "Stopped"]);
  return (
    <>
      <div className="page-head">
        <h1>Coverage</h1>
        <span className="count">{rows.length} {rows.length === 1 ? "company" : "companies"}</span>
        <span className="sp" />
        <div className="seg" role="group" aria-label="Filter companies">
          {segs.map(([k, label]) => (
            <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}>{label}<i>{counts[k]}</i></button>
          ))}
        </div>
      </div>
      <div className="page-body scroll">
        <table className="cov">
          <thead>
            <tr>
              <th>Company</th>
              <th className="c1">Fiscal year</th>
              <th className="num">Revenue</th>
              <th className="num">Growth</th>
              <th className="num c2">Gross margin</th>
              <th className="num c3">Op. margin</th>
              <th className="num c2">FCF margin</th>
              <th className="c1">Latest filing</th>
              <th>Findings</th>
              <th>Review</th>
              <th className="c3">Updated</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => <Row key={r.ticker} r={r} open={() => nav(`/c/${r.ticker}`)} />)}
            {shown.length === 0 && <tr><td colSpan={11} className="muted" style={{ cursor: "default" }}>No companies match this filter.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Row({ r, open }: { r: CoverageRow; open: () => void }) {
  const add = useAddCompany();
  const qc = useQueryClient();
  const rm = useMutation({
    mutationFn: () => api.remove(r.ticker),
    onSuccess: (data) => qc.setQueryData(["coverage"], data),
  });
  const wait = r.state !== "ready" ? " wait" : "";
  const fin = (v: string) => (r.revenue === null ? "–" : v);
  return (
    <tr className={r.state === "processing" ? "pending" : r.state === "failed" ? "failed" : ""} onClick={open}>
      <td><a className="name" href={`/c/${r.ticker}`} onClick={(e) => { e.preventDefault(); }}><b>{r.ticker}</b><span>{r.name}</span></a></td>
      <td className={`c1${r.fy ? "" : wait}`}>{r.fy ?? "–"}{r.fy && <span className="sub">ended {r.fy_end}</span>}</td>
      <td className={`num${wait}`}>{fin(usd(r.revenue))}</td>
      <td className={`num${wait}`}>{fin(pct(r.growth))}</td>
      <td className={`num c2${wait}`}>{fin(pct(r.gross_margin))}</td>
      <td className={`num c3${wait}`}>{fin(pct(r.op_margin))}</td>
      <td className={`num c2${wait}`}>{fin(pct(r.fcf_margin))}</td>
      <td className={`c1${r.latest_filing ? "" : wait}`}>{r.latest_filing ? <>{r.latest_filing.form}<span className="sub">{date(r.latest_filing.date)}</span></> : "–"}</td>
      {r.state === "processing" && r.job && (
        <td colSpan={2}>
          <span className="prog" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(r.job.fraction * 100)} aria-label={`${r.ticker} screening progress`}>
            <span className="track"><i style={{ transform: `scaleX(${Math.max(0.03, r.job.fraction)})` }} /></span>{r.job.label}
          </span>
        </td>
      )}
      {r.state === "failed" && (
        <td colSpan={2} onClick={(e) => e.stopPropagation()} style={{ cursor: "default" }}>
          <div className="row-acts">
            <span className="stopped" title={r.job?.error ?? ""}>Stopped{r.job?.error ? `: ${r.job.error}` : ""}</span>
            <button className="btn sm" onClick={() => add(r.ticker)}><Icon name="play" />Resume…</button>
            <button className="btn sm ghost" disabled={rm.isPending} onClick={() => rm.mutate()}>Remove</button>
          </div>
        </td>
      )}
      {r.state === "ready" && r.findings && <>
        <td>{r.findings.answered} of {r.findings.total}<span className="sub">{r.findings.not_disclosed} not disclosed</span></td>
        <td>{r.findings.review
          ? <span className="status warn"><Icon name="flag" />{r.findings.review} to review</span>
          : <span className="status ok"><Icon name="check" />All verified</span>}</td>
      </>}
      <td className="c3 muted">{r.state === "processing" && r.job ? `Started ${ago(r.job.started)}` : shortDate(r.updated)}</td>
    </tr>
  );
}
