import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, type Question, type Status } from "../lib/api";
import { ago, money, periodText } from "../lib/format";
import { Icon } from "../components/Icons";
import { SourcePanel } from "../components/SourcePanel";
import { StatusBadge } from "../components/Status";
import { ErrorState, Notice, Skeleton } from "../components/States";
import { useTicker } from "./Company";
import "../styles/findings.css";
import "../styles/pages.css";

/** Same rules as findings: verified only when answered, every quote found in the filing and confidence not low. */
function statusOf(q: Question): [Status, string] {
  if (q.status === "not_found") return ["not_disclosed", ""];
  if (q.status === "error") return ["review", "Couldn't be answered"];
  const ok = q.citations.filter((c) => c.verified).length;
  if (ok === 0) return ["review", "No quote found in the filing"];
  if (ok < q.citations.length) return ["review", `${q.citations.length - ok} of ${q.citations.length} quotes not found in the filing`];
  if (q.confidence === "low") return ["review", "Low confidence"];
  return ["verified", ""];
}

export function QAPage() {
  const t = useTicker();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [draft, setDraft] = useState("");
  const [last, setLast] = useState<{ id: string; cost: number } | null>(null);
  const th = useQuery({ queryKey: ["questions", t], queryFn: () => api.questions(t) });
  const sel = params.get("q");
  const active = Number(params.get("p")) || 1;
  const ask = useMutation({
    mutationFn: (text: string) => api.ask(t, text, th.data?.spend.estimate_usd ?? 0.05),
    onSuccess: (data) => {
      qc.setQueryData(["questions", t], data);
      qc.invalidateQueries({ queryKey: ["company", t] });
      qc.invalidateQueries({ queryKey: ["usage"] });
      const q = data.questions[data.questions.length - 1];
      if (q) setLast({ id: q.id, cost: q.cost_usd });
      setDraft("");
    },
  });
  const open = (id: string | null, n = 1) => {
    const next = new URLSearchParams(params);
    if (id) { next.set("q", id); next.set("p", String(n)); } else { next.delete("q"); next.delete("p"); }
    setParams(next, { replace: true });
  };

  const s = th.data?.spend;
  const over = !!s && s.today_usd + s.estimate_usd > s.cap_usd;
  const qs = [...(th.data?.questions ?? [])].reverse();
  const selected = qs.find((x) => x.id === sel) ?? null;

  return (
    <div className={`work${selected ? "" : " solo"}`}>
      <div className="scroll page-scroll">
        <div className="qa">
          <form className="ask" onSubmit={(e) => { e.preventDefault(); if (draft.trim() && !over) ask.mutate(draft.trim()); }}>
            <label htmlFor="ask-text" className="sec-head" style={{ margin: 0 }}><h2>Ask about {t}'s filings</h2></label>
            <textarea id="ask-text" value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={500} rows={3}
              placeholder="For example: What are the change-of-control terms in the convertible notes?"
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); (e.currentTarget.form as HTMLFormElement).requestSubmit(); } }} />
            <div className="ask-row">
              <span className="muted small">
                {s ? <>Up to {money(s.estimate_usd)} per question · {money(s.today_usd)} of {money(s.cap_usd)} used today</> : <Skeleton w={220} />}
              </span>
              <span className="sp" />
              <button type="submit" className="btn primary" disabled={!draft.trim() || ask.isPending || over || !s}>
                <Icon name="ask" />{ask.isPending ? "Reading the filings…" : `Ask · up to ${money(s?.estimate_usd ?? 0.05)}`}
              </button>
            </div>
            {over && <Notice kind="warn"><p>Today's question budget is used. Raise UI_MAX_USD_PER_DAY in .env to ask more today.</p></Notice>}
            {ask.isError && <Notice kind="bad"><p>{(ask.error as Error).message}</p></Notice>}
            <p className="muted small" style={{ margin: "8px 0 0" }}>Answers come only from this company's filings, with quotes checked against the text. Questions about the future or about data the filings don't hold come back as not disclosed.</p>
          </form>

          {ask.isPending && (
            <div className="qa-item pending" aria-busy="true"><p className="qq">{ask.variables}</p><Skeleton w="85%" /><Skeleton w="60%" style={{ marginTop: 8 }} /></div>
          )}
          {th.isLoading && <div style={{ display: "grid", gap: 10, marginTop: 20 }}><Skeleton w="60%" /><Skeleton /></div>}
          {th.isError && <ErrorState title="Couldn't load questions" error={th.error} onRetry={() => th.refetch()} />}
          {th.data && qs.length === 0 && !ask.isPending && <p className="muted" style={{ marginTop: 24 }}>No questions yet. Asked questions and their cited answers are kept here.</p>}
          {qs.map((q) => {
            const [st, why] = statusOf(q);
            return (
              <article key={q.id} className={`qa-item${q.id === sel ? " on" : ""}`}>
                <p className="qq">{q.question}</p>
                <p className="qa-answer">{q.answer || (q.error ? "This question couldn't be answered." : "")}
                  {q.citations.map((c) => (
                    <button key={c.n} type="button" className={`ref${c.verified ? "" : " missing"}`} aria-current={q.id === sel && c.n === active}
                      aria-label={`Show quote ${c.n}`} onClick={() => open(q.id, c.n)}>{c.n}</button>
                  ))}
                </p>
                <div className="qa-meta">
                  <StatusBadge status={st} text={why ? `To review: ${why.toLowerCase()}` : undefined} />
                  {q.period && <span className="muted">{periodText(q.period)}</span>}
                  <span className="muted">{ago(q.asked_at)}</span>
                  <span className="muted">Cost {money(q.cost_usd)}{last?.id === q.id ? " (just now)" : ""}</span>
                </div>
              </article>
            );
          })}
        </div>
      </div>
      {selected && (
        <SourcePanel ticker={t} source={`question:${selected.id}`} title={selected.question} subtitle="Question · sources"
          citations={selected.citations} active={active} onActive={(n) => open(selected.id, n)} onClose={() => open(null)} />
      )}
    </div>
  );
}
