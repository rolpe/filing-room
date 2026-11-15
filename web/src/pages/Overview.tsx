import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type FindingRow } from "../lib/api";
import { date, findingValue, pct, usd } from "../lib/format";
import { Icon } from "../components/Icons";
import { StatusBadge } from "../components/Status";
import { ErrorState, SkeletonRows } from "../components/States";
import { useTicker } from "./Company";
import "../styles/pages.css";

// The findings a deal team reads first, in this order, when they are disclosed.
const KEY = ["gov_activist", "gov_holders", "gov_structure", "debt_instruments", "cap_buyback_auth", "ma_recent",
  "rev_nrr", "rev_concentration", "restructuring", "lit_material", "risk_key"];

export function OverviewPage() {
  const t = useTicker();
  const fin = useQuery({ queryKey: ["financials", t], queryFn: () => api.financials(t) });
  const fl = useQuery({ queryKey: ["findings", t], queryFn: () => api.findings(t) });
  const all = (fl.data?.groups ?? []).flatMap((g) => g.items);
  const review = all.filter((r) => r.status === "review");
  const key = KEY.map((q) => all.find((r) => r.qid === q)).filter((r): r is FindingRow => !!r && r.status !== "not_disclosed" && !review.includes(r));

  return (
    <div className="scroll page-scroll">
      <div className="overview">
        <section aria-labelledby="fin-h">
          <div className="sec-head">
            <h2 id="fin-h">Financials</h2>
            <span className="muted">From SEC XBRL data, as reported in each year's 10-K · $ in millions</span>
          </div>
          {fin.isLoading && <SkeletonRows rows={8} cols={6} />}
          {fin.isError && <ErrorState title="Couldn't load financials" error={fin.error} onRetry={() => fin.refetch()} />}
          {fin.data && fin.data.years.length === 0 && <p className="muted">The SEC's structured data has no annual figures for this company.</p>}
          {fin.data && fin.data.years.length > 0 && (
            <div className="tbl-wrap">
              <table className="fin">
                <thead>
                  <tr>
                    <th scope="col"><span className="sr-only">Line item</span></th>
                    {fin.data.years.map((y) => (
                      <th scope="col" key={y.end} className="num">
                        {y.url ? <a className="link" href={y.url} target="_blank" rel="noreferrer noopener" title={`10-K for the year ended ${date(y.end)} on sec.gov`}>{y.fy}</a> : y.fy}
                        <span className="sub">{date(y.end)}</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {fin.data.rows.map((r) => (
                    <tr key={r.key} className={r.kind === "pct" ? "ratio" : undefined}>
                      <th scope="row">{r.label}</th>
                      {r.values.map((v, i) => <td key={i} className="num">{v === null ? "–" : r.kind === "usd" ? usd(v).replace("M", "") : pct(v)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {fin.data && fin.data.years.length > 0 && <p className="foot-note">Free cash flow is operating cash flow less capital expenditures (including capitalized software where reported). Year headers link to that year's 10-K.</p>}
        </section>

        <section aria-labelledby="key-h">
          <div className="sec-head"><h2 id="key-h">To review</h2>{review.length > 0 && <span className="muted">{review.length}</span>}</div>
          {fl.isLoading && <SkeletonRows rows={2} cols={3} />}
          {fl.isError && <ErrorState title="Couldn't load findings" error={fl.error} onRetry={() => fl.refetch()} />}
          {fl.data && review.length === 0 && <p className="muted"><Icon name="check" className="icon inline ok" /> Nothing to review: every answered finding is backed by quotes found in the filings.</p>}
          {review.length > 0 && <KeyList rows={review} />}
          <div className="sec-head" style={{ marginTop: 28 }}><h2>Key findings</h2></div>
          {fl.data && <KeyList rows={key} />}
          <p className="foot-note"><Link className="link" to="../findings">All {all.length} findings</Link></p>
        </section>
      </div>
    </div>
  );
}

function KeyList({ rows }: { rows: FindingRow[] }) {
  return (
    <ul className="keylist">
      {rows.map((r) => (
        <li key={r.qid}>
          <Link to={`../findings?f=${r.qid}`}>
            <span className="kl-main"><b>{r.label}</b><span>{r.gist}</span></span>
            <span className="kl-val">{r.value !== null ? findingValue(r.value, r.unit) : r.value_label}</span>
            <StatusBadge status={r.status} text={r.status === "verified" && r.reviewed_at ? "Reviewed" : undefined} />
          </Link>
        </li>
      ))}
    </ul>
  );
}
