import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { evalApi, runDate, type EvalSummary } from "../../lib/evalApi";
import { money } from "../../lib/format";
import { ErrorState, Notice, SkeletonRows } from "../../components/States";
import { Companies, JobProgress, PassBar, pctv } from "./common";

export function EvalRunsPage() {
  const q = useQuery({ queryKey: ["evals"], queryFn: evalApi.overview,
    refetchInterval: (qq) => (qq.state.data?.job?.state === "running" ? 2000 : false) });
  if (q.isLoading) return <div className="page-body"><SkeletonRows rows={6} cols={8} /></div>;
  if (q.isError) return <ErrorState title="Couldn't load evaluation runs" error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data!;
  const bar = d.pass_bar;
  return (
    <div className="scroll page-scroll">
      <div className="ev-page">
        {d.job?.state === "running" && (
          <Notice icon="gauge"><JobProgress job={d.job} /><span className="sp" /><Link className="btn sm" to="/evals/run">View</Link></Notice>
        )}
        <section>
          <div className="sec-head">
            <h2>Accuracy across runs</h2>
            <span className="muted">Pass bar set before building: accuracy ≥ {bar.accuracy.value}% · citation support ≥ {bar.citation_support_rate.value}% · unsupported claims ≤ {bar.unsupported_claim_rate.value}%</span>
          </div>
          <Trend runs={[...d.runs].reverse()} bar={bar.accuracy.value} />
        </section>

        <section>
          <div className="sec-head"><h2>Full runs</h2><span className="muted">{d.runs.length} · newest first</span></div>
          {d.runs.length === 0 ? <p className="muted">No recorded runs in results/.</p> : <RunTable runs={d.runs} />}
        </section>

        {d.spot.length > 0 && (
          <section>
            <div className="sec-head"><h2>Spot checks</h2><span className="muted">A few items graded on demand; not part of the trend or the changelog</span></div>
            <RunTable runs={d.spot} />
          </section>
        )}

        {d.memo_checks.length > 0 && (
          <section>
            <div className="sec-head"><h2>Memo claim checks</h2><span className="muted">A judge reads each memo sentence against only the answers it cites</span></div>
            <div className="tbl-wrap">
              <table className="plain">
                <thead><tr><th>Date</th><th>Company</th><th>Change</th><th className="num">Sentences</th><th className="num">Unsupported</th><th className="num">Rate</th><th className="num">Cost</th></tr></thead>
                <tbody>
                  {d.memo_checks.map((m) => (
                    <tr key={m.name}><td>{runDate(m.timestamp)}</td><td><span className="tick">{m.ticker}</span></td>
                      <td className="ev-note">{m.note || "–"}</td><td className="num">{m.sentences ?? "–"}</td><td className="num">{m.unsupported}</td>
                      <td className="num">{pctv(m.rate)}</td><td className="num">{m.cost_usd === null ? "–" : money(m.cost_usd)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function RunTable({ runs }: { runs: EvalSummary[] }) {
  const nav = useNavigate();
  return (
    <div className="tbl-wrap">
      <table className="plain ev-runs">
        <thead>
          <tr>
            <th>Run</th><th>Companies</th><th className="num">Items</th><th className="num">Accuracy</th>
            <th className="num">Cite support</th><th className="num">Unsupported</th><th className="num">Abstain P / R</th>
            <th className="num">Retrieval</th><th className="num">Cost</th><th>Pass bar</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.name} className={r.holdout ? "holdout" : undefined} onClick={() => nav(`/evals/runs/${r.kind}/${r.name}`)}>
              <td className="ev-run">
                <Link to={`/evals/runs/${r.kind}/${r.name}`} onClick={(e) => e.stopPropagation()}><b>{r.label || r.name}</b></Link>
                <span className="sub">{runDate(r.timestamp)}{r.note ? ` · ${r.note}` : ""}</span>
              </td>
              <td><Companies r={r} /></td>
              <td className="num">{r.n_items}</td>
              <td className="num"><b>{pctv(r.metrics.accuracy)}</b></td>
              <td className="num">{pctv(r.metrics.citation_support_rate)}</td>
              <td className="num">{pctv(r.metrics.unsupported_claim_rate)}</td>
              <td className="num">{pctv(r.metrics.abstention_precision)} / {pctv(r.metrics.abstention_recall)}</td>
              <td className="num">{pctv(r.metrics.retrieval_recall)}</td>
              <td className="num">{money(r.cost_usd)}</td>
              <td><PassBar r={r} compact /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Accuracy per full run, oldest to newest, with the pass bar as a dashed line. Plain inline SVG. */
function Trend({ runs, bar }: { runs: EvalSummary[]; bar: number }) {
  const pts = runs.filter((r) => r.metrics.accuracy !== null);
  if (pts.length < 2) return <p className="muted">The trend appears once there are two recorded runs.</p>;
  const W = 760, H = 190, L = 56, R = 56, T = 18, B = 48;
  const lo = Math.min(80, ...pts.map((r) => r.metrics.accuracy!)) - 2;
  const hi = 100;
  const x = (i: number) => L + (i * (W - L - R)) / (pts.length - 1);
  const y = (v: number) => T + ((hi - v) * (H - T - B)) / (hi - lo);
  const ticks = [lo + 2, 85, 90, 95, 100].filter((v, i, a) => a.indexOf(v) === i && v >= lo && v <= hi);
  const path = pts.map((r, i) => `${i ? "L" : "M"}${x(i)},${y(r.metrics.accuracy!)}`).join(" ");
  return (
    <figure className="ev-trend">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Accuracy by run: ${pts.map((r) => `${r.label} ${r.metrics.accuracy}%`).join(", ")}`}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className={v === bar ? "bar" : "grid"} />
            <text x={L - 8} y={y(v) + 4} className="axis" textAnchor="end">{Math.round(v)}%</text>
          </g>
        ))}
        <text x={W - R} y={y(bar) - 6} className="axis" textAnchor="end">pass bar {bar}%</text>
        <path d={path} className="line" />
        {pts.map((r, i) => (
          <g key={r.name}>
            <circle cx={x(i)} cy={y(r.metrics.accuracy!)} r={r.holdout ? 5.5 : 4} className={r.holdout ? "pt holdout" : "pt"}>
              <title>{`${r.label}: ${r.metrics.accuracy}% on ${r.n_items} items (${r.tickers.join(", ")})`}</title>
            </circle>
            <text x={x(i)} y={y(r.metrics.accuracy!) - 10} className="val" textAnchor="middle">{r.metrics.accuracy}%</text>
            <text x={x(i)} y={H - B + 18} className="axis" textAnchor="middle">{r.label}</text>
            <text x={x(i)} y={H - B + 32} className="axis faint" textAnchor="middle">{r.holdout ? `held out · ${r.n_items}` : `${r.tickers.join("+")} · ${r.n_items}`}</text>
          </g>
        ))}
      </svg>
    </figure>
  );
}
