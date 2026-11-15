import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ApiError } from "../../lib/api";
import { evalApi, runDate, type EvalItem, type EvalRow, type RunKind } from "../../lib/evalApi";
import { periodText } from "../../lib/format";
import { Icon } from "../../components/Icons";
import { PassageView, type PassageLoader } from "../../components/PassageView";
import { ErrorState, Skeleton, SkeletonRows } from "../../components/States";
import { Companies, KeyLine, MetricsList, PassBar, TrustBlock, Verdict } from "./common";
import { StatusBadge } from "../../components/Status";
import "../../styles/findings.css";

type Show = "all" | "failed" | "flipped";

export function EvalRunPage() {
  const { kind = "results", name = "" } = useParams();
  const k = (kind === "spot" ? "spot" : "results") as RunKind;
  const [params, setParams] = useSearchParams();
  const q = useQuery({ queryKey: ["eval-run", k, name], queryFn: () => evalApi.detail(k, name), retry: false });
  const [show, setShow] = useState<Show>("all");
  const [co, setCo] = useState("all");
  const [grade, setGrade] = useState("all");
  const sel = params.get("item");
  const rows = useMemo(() => (q.data?.rows ?? []).filter((r) =>
    (show === "all" || (show === "failed" ? r.correct === false || r.supported === "no" : r.flipped)) &&
    (co === "all" || r.ticker === co) && (grade === "all" || r.grade === grade)), [q.data, show, co, grade]);

  if (q.isLoading) return <div className="page-body"><SkeletonRows rows={8} cols={5} /></div>;
  if (q.isError) {
    const nf = q.error instanceof ApiError && q.error.status === 404;
    return <ErrorState title={nf ? "No such run" : "Couldn't load this run"} error={nf ? undefined : q.error} onRetry={nf ? undefined : () => q.refetch()}>
      <p><Link className="link" to="/evals">All runs</Link></p></ErrorState>;
  }
  const d = q.data!;
  const select = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("item", id); else next.delete("item");
    next.delete("p");
    setParams(next, { replace: !!sel && !!id });
  };
  const failed = d.rows.filter((r) => r.correct === false || r.supported === "no").length;
  const tickers = [...new Set(d.rows.map((r) => r.ticker))];
  const grades = [...new Set(d.rows.map((r) => r.grade))];

  return (
    <div className={`work${sel ? "" : " solo"}`}>
      <div className="scroll page-scroll">
        <div className="ev-page">
          <nav className="crumb" aria-label="Breadcrumb"><Link to="/evals">Runs</Link><Icon name="chev" /><span>{d.label || d.name}</span></nav>
          <div className="title-row" style={{ marginTop: 4 }}>
            <h2 className="ev-title">{d.kind === "spot" ? "Spot check" : "Run"} · {d.label || d.name}</h2>
            <Companies r={d} />
            <span className="sp" />
            <PassBar r={d} />
          </div>
          <p className="meta">{runDate(d.timestamp)} · {d.n_items} items · answers {d.model} (effort {d.effort}, k={d.k}, expand={d.expand}) · judge {d.judge_model ?? "none"}{d.note ? ` · ${d.note}` : ""}</p>
          <TrustBlock s={d} />
          <MetricsList s={d} />
          <KeyLine s={d} />

          <div className="sec-head" style={{ marginTop: 22 }}>
            <h2>What changed</h2>
            {d.prev ? <span className="muted">against <Link className="link" to={`/evals/runs/results/${d.prev.name}`}>{d.prev.label || d.prev.name}</Link>, the previous run on {d.prev.tickers.join(" and ")}</span>
              : <span className="muted">No earlier run on the same companies</span>}
          </div>
          {d.flip_test && <p className="ev-flipline">{d.flip_test.statement}</p>}
          {d.prev && (d.flips.length === 0 ? null : (
            <ul className="ev-flips">
              {d.flips.map((f) => (
                <li key={f.id}><button type="button" className="src-link" onClick={() => select(f.id)}>{f.id.split(":")[0]} · {f.label}</button>
                  <span className={f.after ? "status ok" : "status bad"}>{f.before ? "Correct" : "Wrong"} → {f.after ? "Correct" : "Wrong"}</span></li>
              ))}
            </ul>
          ))}

          <div className="sec-head" style={{ marginTop: 22 }}><h2>Graded items</h2></div>
          <div className="tools" style={{ padding: "0 0 10px" }}>
            <div className="seg" role="group" aria-label="Show">
              {([["all", "All", d.rows.length], ["failed", "Failed", failed], ["flipped", "Changed", d.flips.length]] as [Show, string, number][]).map(([k2, l, n]) => (
                <button key={k2} aria-pressed={show === k2} onClick={() => setShow(k2)}>{l}<i>{n}</i></button>))}
            </div>
            {tickers.length > 1 && <div className="seg" role="group" aria-label="Company">
              {["all", ...tickers].map((t) => <button key={t} aria-pressed={co === t} onClick={() => setCo(t)}>{t === "all" ? "All companies" : t}</button>)}
            </div>}
            <div className="seg" role="group" aria-label="Grade type">
              {["all", ...grades].map((g) => <button key={g} aria-pressed={grade === g} onClick={() => setGrade(g)}>{g === "all" ? "All grades" : g}</button>)}
            </div>
          </div>
          <table className="find ev-items">
            <thead><tr><th>Item</th><th>Grade</th><th>Expected</th><th>App would show</th><th>Result</th></tr></thead>
            <tbody>
              {rows.map((r) => <ItemRow key={r.id} r={r} selected={r.id === sel} onSelect={() => select(r.id)} />)}
              {rows.length === 0 && <tr><td colSpan={5} className="muted">No items match these filters.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      {sel && <ItemPanel key={sel} kind={k} name={name} id={sel} onClose={() => select(null)} />}
    </div>
  );
}

function ItemRow({ r, selected, onSelect }: { r: EvalRow; selected: boolean; onSelect: () => void }) {
  return (
    <tr aria-selected={selected} onClick={onSelect}>
      <td className="what"><span className="label">{r.label}</span><span className="gist">{r.ticker} · {r.status.replace("_", " ")}{r.flipped ? ` · changed (was ${r.before ? "correct" : "wrong"})` : ""}</span></td>
      <td className="src">{r.grade}</td>
      <td className="src ev-exp" title={r.expected}>{r.expected}{r.key === "human" && <span className="gist">key checked</span>}</td>
      <td className="st">{r.app_status ? <StatusBadge status={r.app_status} /> : <span className="status none">–</span>}</td>
      <td className="st">
        <Verdict correct={r.correct} />
        {r.supported && r.supported !== "yes" && <span className="gist">support: {r.supported}</span>}
      </td>
    </tr>
  );
}

function ItemPanel({ kind, name, id, onClose }: { kind: RunKind; name: string; id: string; onClose: () => void }) {
  const [params, setParams] = useSearchParams();
  const scroller = useRef<HTMLDivElement>(null);
  const q = useQuery({ queryKey: ["eval-item", kind, name, id], queryFn: () => evalApi.item(kind, name, id) });
  const d: EvalItem | undefined = q.data;
  const active = Number(params.get("p")) || (d?.citations.find((c) => c.verified)?.n ?? 1);
  const setActive = (n: number) => { const nx = new URLSearchParams(params); nx.set("p", String(n)); setParams(nx, { replace: true }); };
  const loader: PassageLoader = { key: ["eval-passage", kind, name, id], load: (chunk) => evalApi.passage(kind, name, id, chunk) };
  return (
    <aside className="detail" aria-label="Graded item">
      <div className="d-head">
        <span className="where">{id}</span><span className="sp" />
        <button className="btn sm sq ghost" aria-label="Close panel" onClick={onClose}><Icon name="x" /></button>
      </div>
      <div className="d-body scroll" ref={scroller}>
        {q.isLoading && <div style={{ display: "grid", gap: 12 }}><Skeleton w="45%" h={18} /><Skeleton /><Skeleton w="80%" /></div>}
        {q.isError && <ErrorState title="Couldn't load this item" error={q.error} onRetry={() => q.refetch()} />}
        {d && <>
          <h2>{d.label} <span className="muted" style={{ fontWeight: 500 }}>· {d.ticker}</span></h2>
          <p className="q">{d.question}</p>
          <dl className="ev-kv">
            <dt>Expected</dt>
            <dd>{d.expected.length > 80 ? d.expected : <b>{d.expected || "–"}</b>}
              {d.golden?.quotes.map((g, i) => <blockquote key={i} className="ev-quote">“{g.quote}”<span>{g.doc_id.replace(/_/g, " ")}</span></blockquote>)}
              {d.golden?.method === "xbrl" && <span className="sub">From the SEC's XBRL data: {d.golden.concepts?.join(" + ")}{d.golden.end ? `, period ending ${d.golden.end}` : ""}</span>}
              {d.golden?.note && <span className="sub">{d.golden.note}</span>}
            </dd>
            <dt>Answer</dt>
            <dd>{d.answer || (d.error ? `Error: ${d.error}` : "–")}
              <span className="sub">{[d.status.replace("_", " "), d.value && `value ${d.value}`, d.period && periodText(d.period), d.confidence && `confidence ${d.confidence}`].filter(Boolean).join(" · ")}</span></dd>
            <dt>Verdict</dt>
            <dd><Verdict correct={d.correct} /> <span className="muted">· graded {d.grade}{d.supported ? ` · citation support: ${d.supported}` : ""}</span>
              {d.judge_reason && <span className="sub">Judge: {d.judge_reason}</span>}
              {d.value_in_context !== null && <span className="sub">Golden number {d.value_in_context ? "was" : "was not"} in the passages retrieved.</span>}</dd>
            <dt>Citations</dt>
            <dd>{d.citations.length === 0 ? "None" : d.citations.map((c) => (
              <button key={c.n} type="button" className={`ref${c.verified ? "" : " missing"}`} aria-current={c.n === active}
                aria-label={`Show quote ${c.n}${c.verified ? "" : " (not found in filing)"}`} onClick={() => setActive(c.n)}>{c.n}</button>))}
              {d.citations.some((c) => !c.verified) && <span className="sub">Dashed: quote not found in the filing text.</span>}</dd>
          </dl>
          {d.citations.length > 0 && <PassageView ticker={d.ticker} source={`eval:${id}`} citations={d.citations} active={active}
            onActive={setActive} scrollRoot={scroller} loader={loader} />}
        </>}
      </div>
    </aside>
  );
}
