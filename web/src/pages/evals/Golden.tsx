import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { evalApi } from "../../lib/evalApi";
import { Icon } from "../../components/Icons";
import { ErrorState, SkeletonRows } from "../../components/States";

const CHECK: Record<string, [string, string]> = {
  human: ["ok", "Checked by hand"],
  "claude-draft": ["warn", "Drafted from the quote"],
  "xbrl-auto": ["none", "From SEC XBRL data"],
};

export function GoldenPage() {
  const q = useQuery({ queryKey: ["golden"], queryFn: evalApi.golden });
  const [t, setT] = useState<string | null>(null);
  const [text, setText] = useState("");
  const cos = q.data?.companies ?? [];
  const cur = cos.find((c) => c.ticker === t) ?? cos[0];
  const items = useMemo(() => (cur?.items ?? []).filter((i) =>
    !text.trim() || `${i.label} ${i.expected} ${i.grade} ${i.source?.quotes.map((x) => x.quote).join(" ")}`.toLowerCase().includes(text.trim().toLowerCase())), [cur, text]);
  if (q.isLoading) return <div className="page-body"><SkeletonRows rows={8} cols={4} /></div>;
  if (q.isError) return <ErrorState title="Couldn't load the golden set" error={q.error} onRetry={() => q.refetch()} />;
  return (
    <div className="scroll page-scroll">
      <div className="ev-page">
        <div className="sec-head">
          <h2>Golden set</h2>
          <span className="muted">The answer key: {q.data!.total} items, numbers from SEC XBRL data and text answers drafted from a quoted filing passage</span>
        </div>
        <div className="tools" style={{ padding: "0 0 10px" }}>
          <div className="seg" role="group" aria-label="Company">
            {cos.map((c) => <button key={c.ticker} aria-pressed={cur?.ticker === c.ticker} onClick={() => setT(c.ticker)}>
              {c.ticker}{c.holdout ? " (held out)" : ""}<i>{c.items.length}</i></button>)}
          </div>
          <label className="filter"><Icon name="search" /><input type="search" placeholder="Filter items" aria-label="Filter items" value={text} onChange={(e) => setText(e.target.value)} /></label>
        </div>
        {cur?.holdout && <p className="muted small" style={{ margin: "0 0 10px" }}>Written before the held-out company was run, and not changed since.</p>}
        <div className="tbl-wrap">
          <table className="plain ev-golden">
            <thead><tr><th>Item</th><th>Grade</th><th>Expected</th><th>Source</th><th>Check</th></tr></thead>
            <tbody>
              {items.map((i) => {
                const [cls, label] = CHECK[i.source?.verified ?? ""] ?? ["none", i.source?.verified ?? "–"];
                return (
                  <tr key={i.id}>
                    <td><b>{i.label}</b><span className="sub">{i.qid}</span></td>
                    <td>{i.grade}</td>
                    <td className="ev-wrap">{i.expected}</td>
                    <td className="ev-wrap">
                      {i.source?.quotes.map((x, n) => <blockquote key={n} className="ev-quote">“{x.quote}”<span>{x.doc_id.replace(/_/g, " ")}</span></blockquote>)}
                      {i.source?.method === "xbrl" && <span className="muted">XBRL {i.source.concepts?.join(" + ")}{i.source.end ? `, ${i.source.end}` : ""}</span>}
                      {i.source?.method === "derived" && <span className="muted">Computed from other XBRL items</span>}
                    </td>
                    <td><span className={`status ${cls}`}>{label}</span></td>
                  </tr>
                );
              })}
              {items.length === 0 && <tr><td colSpan={5} className="muted">No items match.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
