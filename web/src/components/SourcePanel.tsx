import { useRef } from "react";
import type { Citation } from "../lib/api";
import { Icon } from "./Icons";
import { PassageView } from "./PassageView";

/** The source panel for citations that aren't a finding (Q&A answers): the same passage viewer, in the same frame. */
export function SourcePanel({ ticker, source, title, subtitle, citations, active, onActive, onClose }: {
  ticker: string; source: string; title: string; subtitle?: string; citations: Citation[]; active: number;
  onActive: (n: number) => void; onClose: () => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const missing = citations.filter((c) => !c.verified);
  return (
    <aside className="detail" aria-label="Source">
      <div className="d-head">
        <span className="where">{subtitle}</span>
        <span className="sp" />
        <button className="btn sm sq ghost" aria-label="Close panel" onClick={onClose}><Icon name="x" /></button>
      </div>
      <div className="d-body scroll" ref={scroller}>
        <h2>{title}</h2>
        {missing.length > 0 && (
          <div className="missing-quotes">
            <h3>Cited but not found in the filing</h3>
            {missing.map((c) => <blockquote key={c.n}><b>{c.n} · not found in filing</b>{c.quote}</blockquote>)}
          </div>
        )}
        {citations.length > 0
          ? <PassageView ticker={ticker} source={source} citations={citations} active={active} onActive={onActive} scrollRoot={scroller} />
          : <p className="muted">No passages were cited.</p>}
      </div>
    </aside>
  );
}
