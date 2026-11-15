import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { estimateUsd, evalApi, type EvalSpec } from "../../lib/evalApi";
import { money } from "../../lib/format";
import { Icon } from "../../components/Icons";
import { ErrorState, Notice, SkeletonRows } from "../../components/States";
import { JobProgress } from "./common";

export function RunEvalPage() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const cfg = useQuery({ queryKey: ["eval-config"], queryFn: evalApi.config });
  const job = useQuery({ queryKey: ["eval-job"], queryFn: evalApi.job,
    refetchInterval: (q) => (q.state.data?.job?.state === "running" ? 1500 : false) });
  const [tickers, setTickers] = useState<string[]>([]);
  const [kind, setKind] = useState<"full" | "spot">("spot");
  const [ids, setIds] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const [watching, setWatching] = useState<string | null>(null);

  useEffect(() => {  // default: every company that can be run
    if (cfg.data && tickers.length === 0) setTickers(cfg.data.companies.filter((c) => c.split === "tune").map((c) => c.ticker));
  }, [cfg.data, tickers.length]);

  const j = job.data?.job ?? null;
  useEffect(() => {  // a run started here that finished: refresh the lists and open the result
    if (j && watching === j.id && j.state === "done" && j.result) {
      qc.invalidateQueries({ queryKey: ["evals"] });
      qc.invalidateQueries({ queryKey: ["usage"] });
      setWatching(null);
      nav(`/evals/runs/${j.result.kind}/${j.result.name}`);
    }
  }, [j, watching, qc, nav]);

  const c = cfg.data;
  const pool = useMemo(() => (c?.items ?? []).filter((i) => tickers.includes(i.ticker)), [c, tickers]);
  const shown = pool.filter((i) => !filter.trim() || `${i.ticker} ${i.label} ${i.grade}`.toLowerCase().includes(filter.trim().toLowerCase()));
  const chosen = ids.filter((id) => pool.some((i) => i.id === id));
  const n = kind === "full" ? pool.length : chosen.length;
  const est = c ? estimateUsd(n, c.per_item_usd) : 0;
  const spend = job.data?.spend ?? c?.spend;
  const over = !!spend && est > spend.remaining_usd;
  const running = j?.state === "running";

  const start = useMutation({
    mutationFn: () => {
      const spec: EvalSpec = { kind, tickers, label: label.trim(), note: note.trim(), ...(kind === "spot" ? { ids: chosen } : {}) };
      return evalApi.start(spec, est);
    },
    onSuccess: (jb) => { setWatching(jb.id); qc.setQueryData(["eval-job"], { job: jb, spend }); qc.invalidateQueries({ queryKey: ["eval-job"] }); },
  });
  const retr = useMutation({ mutationFn: () => evalApi.retrieval(tickers) });

  if (cfg.isLoading) return <div className="page-body"><SkeletonRows rows={6} cols={3} /></div>;
  if (cfg.isError) return <ErrorState title="Couldn't load the run form" error={cfg.error} onRetry={() => cfg.refetch()} />;
  const canStart = !running && n > 0 && tickers.length > 0 && !over && !start.isPending && (kind === "full" || n <= c!.max_spot_items);

  return (
    <div className="scroll page-scroll">
      <div className="ev-page ev-form">
        {j && (j.state === "running" || watching === j.id) && (
          <section className="ev-job">
            {j.state === "running" && <Notice icon="gauge"><JobProgress job={j} /></Notice>}
            {j.state === "failed" && <Notice kind="bad"><p><b>The run stopped.</b> {j.error} Spent {money(j.cost_usd)}.</p></Notice>}
          </section>
        )}
        {j && j.state === "done" && j.result && watching !== j.id && (
          <p className="muted small">Last run: {j.kind === "spot" ? "spot check" : "full run"} {j.label} · {money(j.cost_usd)} · <Link className="link" to={`/evals/runs/${j.result.kind}/${j.result.name}`}>open result</Link></p>
        )}

        <form onSubmit={(e) => { e.preventDefault(); if (canStart) start.mutate(); }}>
          <fieldset>
            <legend>Companies</legend>
            {c!.companies.map((co) => {
              const held = co.split !== "tune";
              return (
                <label key={co.ticker} className={`ev-check${held ? " disabled" : ""}`}>
                  <input type="checkbox" aria-label={`${co.ticker} ${co.name}`} disabled={held || running} checked={!held && tickers.includes(co.ticker)}
                    onChange={(e) => setTickers((t) => e.target.checked ? [...t, co.ticker] : t.filter((x) => x !== co.ticker))} />
                  <span><b>{co.ticker}</b> {co.name} <span className="muted">· {co.items} items</span>
                    {held && <span className="sub">Held out: run once on the frozen system, so it stays out of new runs. Its recorded run is under Runs.</span>}</span>
                </label>
              );
            })}
          </fieldset>

          <fieldset>
            <legend>Scope</legend>
            <label className="ev-check"><input type="radio" name="scope" aria-label="Spot check" checked={kind === "spot"} disabled={running} onChange={() => setKind("spot")} />
              <span><b>Spot check</b> <span className="muted">· chosen items, graded and kept apart from the run history</span></span></label>
            <label className="ev-check"><input type="radio" name="scope" aria-label="Full set" checked={kind === "full"} disabled={running} onChange={() => setKind("full")} />
              <span><b>Full set</b> <span className="muted">· all {pool.length} items; writes a results file and a changelog line, like ./fr eval</span></span></label>
            {kind === "spot" && (
              <div className="ev-picker">
                <div className="tools" style={{ padding: "6px 0" }}>
                  <label className="filter"><Icon name="search" /><input type="search" placeholder="Filter items" aria-label="Filter items" value={filter} onChange={(e) => setFilter(e.target.value)} /></label>
                  <span className="muted small">{chosen.length} of up to {c!.max_spot_items} chosen</span>
                </div>
                <div className="ev-pick-list scroll" role="group" aria-label="Items to spot-check">
                  {shown.map((i) => (
                    <label key={i.id} className="ev-pick">
                      <input type="checkbox" aria-label={`${i.ticker} ${i.label}`} disabled={running || (!chosen.includes(i.id) && chosen.length >= c!.max_spot_items)}
                        checked={chosen.includes(i.id)} onChange={(e) => setIds((x) => e.target.checked ? [...x, i.id] : x.filter((y) => y !== i.id))} />
                      <span className="tick">{i.ticker}</span><span>{i.label}</span><span className="muted">{i.grade}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
          </fieldset>

          <fieldset>
            <legend>Label and note</legend>
            <div className="ev-row">
              <input aria-label="Label" placeholder={kind === "spot" ? "Label (optional)" : "Label, e.g. k12"} value={label} maxLength={40} disabled={running} onChange={(e) => setLabel(e.target.value)} />
              <input aria-label="What changed" placeholder="What changed since the last run" value={note} maxLength={300} disabled={running} onChange={(e) => setNote(e.target.value)} />
            </div>
          </fieldset>

          <div className="ev-cost">
            <div>
              {n === 0 ? <b>Choose the items to check</b>
                : <><b>About {money(est)}</b> <span className="muted">· {n} {n === 1 ? "item" : "items"} × {money(c!.per_item_usd)} per item, averaged from recorded runs</span></>}
              <span className="sub">{spend ? `${money(spend.today_usd)} of ${money(spend.cap_usd)} evaluation budget used today · each run stops at ${money(Math.min(spend.run_limit_usd, spend.remaining_usd))}` : ""}</span>
              <span className="sub">Answers {c!.model} (effort {c!.effort}, k={c!.k}, expand={c!.expand}) · judge {c!.judge_model}</span>
            </div>
            <span className="sp" />
            <button type="submit" className="btn primary" disabled={!canStart}>
              <Icon name="play" />{start.isPending ? "Starting…" : n === 0 ? "Run spot check" : `${kind === "full" ? "Run full eval" : "Run spot check"} · about ${money(est)}`}
            </button>
          </div>
          {over && <Notice kind="warn"><p>This would go over today's evaluation budget. Raise EVAL_MAX_USD_PER_DAY in .env, or choose fewer items.</p></Notice>}
          {running && <p className="muted small">One paid job at a time: a new run can start when this one finishes.</p>}
          {start.isError && <Notice kind="bad"><p>{(start.error as Error).message}</p></Notice>}
        </form>

        <section className="ev-retrieval">
          <div className="sec-head"><h2>Retrieval check</h2><span className="muted">Free, no model calls: is each golden number in the passages the engine would read?</span></div>
          <button className="btn" disabled={retr.isPending || tickers.length === 0} onClick={() => retr.mutate()}>
            <Icon name="search" />{retr.isPending ? "Checking…" : `Run retrieval check on ${tickers.join(" and ") || "…"}`}</button>
          {retr.isError && <Notice kind="bad"><p>{(retr.error as Error).message}</p></Notice>}
          {retr.data && (
            <div className="ev-retr-result">
              <p><b>{retr.data.hits} of {retr.data.total}</b> numeric items found in the retrieved passages · recall {retr.data.recall}% (k={retr.data.k}, expand={retr.data.expand})</p>
              {retr.data.items.filter((i) => !i.ok).length === 0 ? <p className="muted">No misses.</p> : (
                <ul>{retr.data.items.filter((i) => !i.ok).map((i) => <li key={i.id}><span className="status bad"><Icon name="x" />{i.ticker} · {i.label}</span> <span className="muted">top passage {i.top}</span></li>)}</ul>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
