import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { date, money } from "../lib/format";
import { ErrorState, SkeletonRows } from "../components/States";
import "../styles/pages.css";

function Meter({ label, used, cap, note }: { label: string; used: number; cap: number; note: string }) {
  const f = cap > 0 ? Math.min(1, used / cap) : 0;
  return (
    <div className="meter">
      <dt>{label}</dt>
      <dd><b>{money(used)}</b> <span className="muted">of {money(cap)} today</span></dd>
      <dd><span className="prog wide" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(f * 100)} aria-label={`${label} used today`}>
        <span className="track"><i style={{ transform: `scaleX(${f})` }} /></span></span></dd>
      <dd className="muted small">{note}</dd>
    </div>
  );
}

export function UsagePage() {
  const q = useQuery({ queryKey: ["usage"], queryFn: api.usage });
  const u = q.data;
  return (
    <>
      <div className="page-head"><h1>Usage</h1>{u && <span className="count">{money(u.total_usd)} in model usage to date</span>}</div>
      <div className="page-body scroll">
        {q.isLoading && <SkeletonRows rows={5} cols={3} />}
        {q.isError && <ErrorState title="Couldn't load usage" error={q.error} onRetry={() => q.refetch()} />}
        {u && (
          <div className="narrow" style={{ padding: 0 }}>
            <dl className="meters">
              <Meter label="Screenings" used={u.caps.screening.today_usd} cap={u.caps.screening.cap_usd}
                note={`Each screening stops at ${money(u.caps.screening.per_run_limit_usd)}. Change the daily cap with RUN_MAX_USD_PER_DAY in .env.`} />
              <Meter label="Questions" used={u.caps.questions.today_usd} cap={u.caps.questions.cap_usd}
                note={`Up to ${money(u.caps.questions.estimate_usd)} per question. Change the daily cap with UI_MAX_USD_PER_DAY in .env.`} />
            </dl>

            <div className="sec-head"><h2>By day</h2></div>
            {u.days.length === 0 ? <p className="muted">Nothing spent yet.</p> : (
              <table className="plain">
                <thead><tr><th>Date</th><th className="num">Screenings</th><th className="num">Questions</th><th className="num">Total</th></tr></thead>
                <tbody>
                  {u.days.map((d) => (
                    <tr key={d.date}><td>{date(d.date)}</td><td className="num">{money(d.screening_usd)}</td>
                      <td className="num">{money(d.questions_usd)}</td><td className="num"><b>{money(d.screening_usd + d.questions_usd)}</b></td></tr>
                  ))}
                </tbody>
              </table>
            )}

            <div className="sec-head" style={{ marginTop: 28 }}><h2>By company</h2><span className="muted">Companies in coverage</span></div>
            {u.by_company.length === 0 ? <p className="muted">No companies in coverage.</p> : (
              <table className="plain">
                <thead><tr><th>Company</th><th className="num">Screening</th><th className="num">Questions</th><th className="num">Question cost</th></tr></thead>
                <tbody>
                  {u.by_company.map((c) => (
                    <tr key={c.ticker}><td><Link className="link" to={`/c/${c.ticker}`}><b>{c.ticker}</b></Link> <span className="muted">{c.name}</span></td>
                      <td className="num">{money(c.screening_usd)}</td><td className="num">{c.questions}</td><td className="num">{money(c.questions_usd)}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="foot-note">Daily totals come from the app's spend ledgers. Removing a company from coverage doesn't change them.</p>
          </div>
        )}
      </div>
    </>
  );
}
