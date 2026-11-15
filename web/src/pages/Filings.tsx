import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { date } from "../lib/format";
import { Icon } from "../components/Icons";
import { ErrorState, SkeletonRows } from "../components/States";
import { useTicker } from "./Company";
import "../styles/pages.css";

export function FilingsPage() {
  const t = useTicker();
  const q = useQuery({ queryKey: ["filings", t], queryFn: () => api.filings(t) });
  return (
    <div className="scroll page-scroll">
      <div className="narrow">
        <div className="sec-head"><h2>Filings read</h2><span className="muted">From SEC EDGAR</span></div>
        {q.isLoading && <SkeletonRows rows={8} cols={5} />}
        {q.isError && <ErrorState title="Couldn't load filings" error={q.error} onRetry={() => q.refetch()} />}
        {q.data && q.data.length === 0 && <p className="muted">No filings are cached for this company.</p>}
        {q.data && q.data.length > 0 && (
          <table className="plain">
            <thead><tr><th>Form</th><th>Document</th><th>Period</th><th>Period end</th><th>Filed</th><th><span className="sr-only">Link</span></th></tr></thead>
            <tbody>
              {q.data.map((f) => (
                <tr key={f.doc_id}>
                  <td><b>{f.form}</b></td>
                  <td>{f.form_label.replace(/ \(.*\)$/, "")}</td>
                  <td>{f.period}</td>
                  <td>{f.form === "DEF 14A" ? <span className="muted">Meeting {date(f.report_date)}</span> : date(f.report_date)}</td>
                  <td>{date(f.filing_date)}</td>
                  <td className="num"><a className="btn sm" href={f.url} target="_blank" rel="noreferrer noopener"><Icon name="ext" />sec.gov</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
