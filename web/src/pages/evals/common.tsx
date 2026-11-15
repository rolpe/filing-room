import { ciText, type EvalJob, type EvalSummary, type Rate } from "../../lib/evalApi";
import { money } from "../../lib/format";
import { Icon } from "../../components/Icons";

export function pctv(v: number | null | undefined): string {
  return v === null || v === undefined ? "–" : `${v.toFixed(1)}%`;
}

export function Companies({ r }: { r: Pick<EvalSummary, "tickers" | "holdout"> }) {
  return (
    <span className="ev-cos">
      {r.tickers.map((t) => <span key={t} className="tick">{t}</span>)}
      {r.holdout && <span className="ev-holdout" title="Held out: not looked at until the system was frozen, then run once">Held out</span>}
    </span>
  );
}

export function PassBar({ r, compact = false }: { r: EvalSummary; compact?: boolean }) {
  if (r.passes.all) return <span className="status ok"><Icon name="check" />{compact ? "Meets" : "Meets the pass bar"}</span>;
  const miss = [
    !r.passes.accuracy && "accuracy",
    !r.passes.citation_support_rate && "citation support",
    !r.passes.unsupported_claim_rate && "unsupported claims",
  ].filter(Boolean).join(", ");
  return <span className="status warn" title={`Below the bar on ${miss}`}><Icon name="flag" />Misses: {miss}</span>;
}

/** A rate with its 95% interval underneath. */
export function RateCell({ r, bold = false }: { r: Rate; bold?: boolean }) {
  const v = r.pct === null ? "–" : `${r.pct.toFixed(1)}%`;
  return <>{bold ? <b>{v}</b> : v}{r.ci && <span className="ci">{ciText(r)}</span>}</>;
}

export function MetricsList({ s }: { s: EvalSummary }) {
  const r = s.rates;
  const one = (label: string, rate: Rate, note: string) => (
    <div><dt>{label}</dt><dd>{rate.pct === null ? "–" : `${rate.pct.toFixed(1)}%`}{rate.ci && <span className="ci">{ciText(rate)}</span>}</dd>
      <dd className="sub">{rate.k} of {rate.n} · {note}</dd></div>
  );
  return (
    <dl className="ev-metrics">
      {one("Accuracy", r.accuracy, Object.entries(s.by_grade).filter(([, v]) => v.n).map(([g, v]) => `${g} ${pctv(v.accuracy)}`).join(", "))}
      {one("Citation support", r.citation_support_rate, "verified quotes back the answer")}
      {one("Unsupported claims", r.unsupported_claim_rate, "answers with no supporting quote")}
      {one("Abstention precision", r.abstention_precision, "\"not found\" was right")}
      {one("Abstention recall", r.abstention_recall, "unanswerable items caught")}
      {one("Retrieval recall", r.retrieval_recall, "golden number in the passages read")}
      <div><dt>Cost</dt><dd>{money(s.cost_usd)}</dd><dd className="sub">{s.wall_seconds ? `${Math.round(s.wall_seconds)} s` : ""}</dd></div>
    </dl>
  );
}

/** The headline: how far the app's own Verified / To review / Not disclosed statuses can be trusted. */
export function TrustBlock({ s }: { s: EvalSummary }) {
  const t = s.trust;
  const w = t.wrong_by_status;
  const pct = (r: Rate) => (r.pct === null ? "" : ` (${r.pct.toFixed(1)}%, ${ciText(r)})`);
  return (
    <section className="ev-trust" aria-labelledby="trust-h">
      <h2 id="trust-h">Can the app's statuses be trusted?</h2>
      <ul>
        <li><b>{t.verified_wrong.k} of {t.verified_wrong.n}</b> answers the app would mark Verified were wrong{pct(t.verified_wrong)}.</li>
        <li><b>{t.wrong_caught.k} of {t.wrong_caught.n}</b> wrong answers would be marked To review{pct(t.wrong_caught)}
          {t.wrong_caught.n > 0 && <span className="muted">; of the rest, {w.verified} would show as Verified and {w.not_disclosed} as Not disclosed</span>}.</li>
        <li><b>{t.false_not_found.k} of {t.false_not_found.n}</b> items the filings do answer came back Not disclosed{pct(t.false_not_found)}.</li>
      </ul>
      <p className="muted small">Uses the app's own status rules on each graded answer. The SEC number check counts only where the answer key is the SEC figure; reviews and flags don't apply. Judgment-only items are left out of correctness.</p>
    </section>
  );
}

export function KeyLine({ s }: { s: EvalSummary }) {
  const k = s.key;
  return (
    <p className="muted small ev-keyline">
      Answer key checked by hand for {k.checked.k} of {k.checked.n} graded items{k.from_sec ? `; ${k.from_sec} more come from SEC data` : ""}.
      {k.accuracy_checked.n > 0 && <> On checked items only: accuracy <b>{k.accuracy_checked.pct?.toFixed(1)}%</b> ({k.accuracy_checked.k} of {k.accuracy_checked.n}, {ciText(k.accuracy_checked)}).</>}
    </p>
  );
}

export function JobProgress({ job }: { job: EvalJob }) {
  const f = job.total ? job.done / job.total : 0;
  return (
    <span className="prog wide" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(f * 100)} aria-label="Evaluation progress">
      <span className="track"><i style={{ transform: `scaleX(${Math.max(0.03, f)})` }} /></span>
      {job.kind === "spot" ? "Spot check" : "Full run"}: answered and graded {job.done} of {job.total} · {money(job.cost_usd)} so far
    </span>
  );
}

export function Verdict({ correct }: { correct: boolean | null }) {
  if (correct === null) return <span className="status none"><Icon name="none" />Not graded</span>;
  return correct ? <span className="status ok"><Icon name="check" />Correct</span> : <span className="status bad"><Icon name="x" />Wrong</span>;
}
