// Developer tools: the evaluation area. Everything lives under /api/dev/, which 404s when the switch is off.
import { enc, get, post, type Citation, type Passage } from "./api";

export type RunKind = "results" | "spot";

export interface EvalMetrics {
  accuracy: number | null;
  citation_support_rate: number | null;
  unsupported_claim_rate: number | null;
  abstention_precision: number | null;
  abstention_recall: number | null;
  retrieval_recall: number | null;
  false_abstentions: number | null;
  citation_verified_rate: number | null;
  errors: number | null;
}

export interface Rate { k: number; n: number; pct: number | null; ci: [number, number] | null }

export interface Trust {
  verified_wrong: Rate;
  wrong_caught: Rate;
  wrong_by_status: { verified: number; review: number; not_disclosed: number };
  false_not_found: Rate;
  false_not_found_ids: string[];
}

export interface EvalSummary {
  kind: RunKind;
  rates: Record<"accuracy" | "citation_support_rate" | "unsupported_claim_rate" | "abstention_precision" | "abstention_recall" | "retrieval_recall", Rate>;
  trust: Trust;
  key: { checked: Rate; accuracy_checked: Rate; from_sec: number };
  name: string;
  label: string;
  note: string;
  timestamp: string;
  tickers: string[];
  n_items: number;
  holdout: boolean;
  model: string | null;
  effort: string | null;
  k: number | null;
  expand: number;
  judge_model: string | null;
  metrics: EvalMetrics;
  by_grade: Record<string, { n: number; accuracy: number | null }>;
  cost_usd: number;
  wall_seconds: number | null;
  passes: { accuracy: boolean; citation_support_rate: boolean; unsupported_claim_rate: boolean; all: boolean };
}

export interface EvalJob {
  id: string;
  kind: "full" | "spot";
  tickers: string[];
  label: string;
  started: string;
  estimate_usd: number;
  state: "running" | "done" | "failed";
  done: number;
  total: number;
  cost_usd: number;
  error: string | null;
  result: { kind: RunKind; name: string } | null;
}

export interface EvalSpend { today_usd: number; cap_usd: number; remaining_usd: number; run_limit_usd: number }

export interface EvalOverview {
  runs: EvalSummary[];
  spot: EvalSummary[];
  memo_checks: { name: string; ticker: string; note: string; timestamp: string; sentences: number | null; unsupported: number; rate: number | null; cost_usd: number | null }[];
  pass_bar: Record<string, { op: ">=" | "<="; value: number }>;
  job: EvalJob | null;
}

export interface EvalRow {
  id: string;
  ticker: string;
  qid: string;
  label: string;
  grade: string;
  status: string;
  correct: boolean | null;
  supported: string | null;
  answer: string;
  expected: string;
  value_in_context: boolean | null;
  flipped: boolean;
  before: boolean | null;
  app_status: "verified" | "review" | "not_disclosed" | null;
  key: string;
}

export interface EvalDetail extends EvalSummary {
  prev: EvalSummary | null;
  flips: { id: string; before: boolean | null; after: boolean | null; label: string }[];
  flip_test: { better: number; worse: number; p: number; statement: string } | null;
  rows: EvalRow[];
}

export interface GoldenSource {
  method: string;
  quotes: { doc_id: string; quote: string }[];
  concepts: string[] | null;
  end: string | null;
  note: string;
  verified: string | null;
}

export interface EvalItem {
  id: string;
  ticker: string;
  qid: string;
  label: string;
  question: string;
  grade: string;
  expected: string;
  golden: GoldenSource | null;
  status: string;
  answer: string;
  value: string;
  period: string;
  confidence: string | null;
  correct: boolean | null;
  supported: string | null;
  judge_reason: string;
  value_in_context: boolean | null;
  error: string | null;
  citations: Citation[];
}

export type KeyReview = "human" | "claude-draft" | "needs-fix" | "sec-data";

export interface GoldenRow { id: string; qid: string; label: string; grade: string; expected: string; source: GoldenSource | null; review: KeyReview; review_note: string }

export interface GoldenView {
  total: number;
  progress: { manual: number; checked: number; needs_fix: number; from_sec: number };
  companies: { ticker: string; name: string; holdout: boolean; items: GoldenRow[] }[];
}

export interface GoldenItem {
  id: string; ticker: string; qid: string; label: string; question: string; grade: string; expected: string;
  source: GoldenSource | null; note: string; review: KeyReview; review_note: string; editable: boolean;
  quotes: { n: number; doc_id: string; quote: string; chunk_id: string | null; form?: string; period?: string; url?: string }[];
}

export interface EvalConfig {
  companies: { ticker: string; name: string; split: string; items: number }[];
  items: { id: string; ticker: string; qid: string; label: string; grade: string }[];
  per_item_usd: number;
  max_spot_items: number;
  spend: EvalSpend;
  model: string;
  effort: string;
  k: number;
  expand: number;
  judge_model: string;
  job: EvalJob | null;
}

export interface EvalSpec { kind: "full" | "spot"; tickers: string[]; ids?: string[]; label?: string; note?: string }

export interface RetrievalResult {
  k: number;
  expand: number;
  hits: number;
  total: number;
  recall: number | null;
  tickers: string[];
  at: string;
  items: { id: string; ok: boolean; top: string; label: string; ticker: string }[];
}

const B = "/api/dev/evals";
export const evalApi = {
  overview: () => get<EvalOverview>(B),
  config: () => get<EvalConfig>(`${B}/config`),
  golden: () => get<GoldenView>(`${B}/golden`),
  job: () => get<{ job: EvalJob | null; spend: EvalSpend }>(`${B}/job`),
  detail: (kind: RunKind, name: string) => get<EvalDetail>(`${B}/runs/${kind}/${enc(name)}`),
  item: (kind: RunKind, name: string, id: string) => get<EvalItem>(`${B}/runs/${kind}/${enc(name)}/items/${enc(id)}`),
  passage: (kind: RunKind, name: string, id: string, chunk: string) =>
    get<Passage>(`${B}/runs/${kind}/${enc(name)}/passage?item=${enc(id)}&chunk=${enc(chunk)}`),
  goldenItem: (id: string) => get<GoldenItem>(`${B}/golden/${enc(id)}`),
  goldenPassage: (id: string, chunk: string) => get<Passage>(`${B}/golden/${enc(id)}/passage?chunk=${enc(chunk)}`),
  review: (id: string, action: "checked" | "needs_fix" | "undo", note = "") => post<GoldenItem>(`${B}/golden/${enc(id)}/review`, { action, note }),
  start: (spec: EvalSpec, confirm_usd: number) => post<EvalJob>(`${B}/start`, { spec, confirm_usd }),
  retrieval: (tickers: string[]) => post<RetrievalResult>(`${B}/retrieval`, { tickers }),
};

/** Same rule as the server: at least a cent, rounded to cents. */
export function estimateUsd(items: number, perItem: number): number {
  return Math.max(0.01, Math.round(items * perItem * 100) / 100);
}

export function runDate(ts: string): string {
  const m = /^(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})/.exec(ts || "");
  return m ? `${m[1]} ${m[2]}:${m[3]}` : ts;
}

/** "76–96%" for a 95% interval. */
export function ciText(r: Rate | null | undefined): string {
  return r && r.ci ? `${Math.round(r.ci[0])}–${Math.round(r.ci[1])}%` : "";
}
