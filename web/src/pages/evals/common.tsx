import type { EvalJob, EvalMetrics, EvalSummary } from "../../lib/evalApi";
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

export function MetricsList({ m, byGrade, cost, seconds }: {
  m: EvalMetrics; byGrade: Record<string, { n: number; accuracy: number | null }>; cost: number; seconds: number | null;
}) {
  return (
    <dl className="ev-metrics">
      <div><dt>Accuracy</dt><dd>{pctv(m.accuracy)}</dd>
        <dd className="sub">{Object.entries(byGrade).filter(([, v]) => v.n).map(([g, v]) => `${g} ${pctv(v.accuracy)} (${v.n})`).join(" · ")}</dd></div>
      <div><dt>Citation support</dt><dd>{pctv(m.citation_support_rate)}</dd><dd className="sub">judge: verified quotes back the answer</dd></div>
      <div><dt>Unsupported claims</dt><dd>{pctv(m.unsupported_claim_rate)}</dd><dd className="sub">answers with no supporting quote</dd></div>
      <div><dt>Abstention P / R</dt><dd>{pctv(m.abstention_precision)} / {pctv(m.abstention_recall)}</dd>
        <dd className="sub">{m.false_abstentions ?? 0} said "not found" wrongly</dd></div>
      <div><dt>Retrieval recall</dt><dd>{pctv(m.retrieval_recall)}</dd><dd className="sub">golden number in the passages read</dd></div>
      <div><dt>Cost</dt><dd>{money(cost)}</dd><dd className="sub">{seconds ? `${Math.round(seconds)} s` : ""}</dd></div>
    </dl>
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
