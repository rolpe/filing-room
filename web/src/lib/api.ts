// Typed client for the local API (filingroom/server.py). GETs are plain; POSTs carry the X-Filing-Room header.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function handle<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!res.ok) {
    const msg = (body as { error?: string } | null)?.error || `Request failed (${res.status})`;
    throw new ApiError(res.status, msg);
  }
  return body as T;
}

export async function get<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { headers: { Accept: "application/json" } });
  } catch {
    throw new ApiError(0, "Can't reach the filing-room server. Is ./fr ui still running?");
  }
  return handle<T>(res);
}

export async function post<T>(path: string, body: unknown = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Filing-Room": "1" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Can't reach the filing-room server. Is ./fr ui still running?");
  }
  return handle<T>(res);
}

export const enc = encodeURIComponent;

// ---------------------------------------------------------------- types

export type Status = "verified" | "review" | "not_disclosed";
export type CompanyState = "ready" | "processing" | "failed";

export interface Job {
  state: "running" | "failed" | "done";
  stage: string;
  done: number;
  total: number;
  error: string | null;
  started: string;
  cost_usd: number;
  label: string;
  fraction: number;
}

export interface FilingRef {
  form: string;
  period: string;
  date: string;
  url: string;
}

export interface CoverageRow {
  ticker: string;
  name: string;
  state: CompanyState;
  job: Job | null;
  fy: string | null;
  fy_end: string;
  revenue: number | null;
  growth: number | null;
  gross_margin: number | null;
  op_margin: number | null;
  fcf_margin: number | null;
  latest_filing: FilingRef | null;
  updated: string | null;
  findings: { total: number; verified: number; review: number; not_disclosed: number; answered: number } | null;
}

export interface Coverage {
  companies: CoverageRow[];
  counts: { all: number; ready: number; processing: number; failed: number; review: number };
  busy: string | null;
}

export interface SecResult {
  ticker: string;
  name: string;
  cik: number;
  in_coverage: boolean;
}

export interface Estimate {
  usd: number;
  minutes: string;
  answers_done: number;
  answers_total: number;
}

export interface Preview {
  ticker: string;
  name: string;
  cik: number;
  sic: string;
  fy_end: string;
  filings: Record<string, number>;
  eligible: boolean;
  reason: string;
  in_coverage: boolean;
  state: CompanyState | null;
  estimate: Estimate;
  cap: { today_usd: number; cap_usd: number; remaining_usd: number };
  busy: string | null;
}

export interface Figure {
  key: string;
  label: string;
  value: number;
  kind: "usd" | "pct" | "count";
  sub?: number | null;
  sub_kind?: "pct" | "pct_change";
  qid?: string;
}

export interface Counts {
  total: number;
  verified: number;
  review: number;
  not_disclosed: number;
}

export interface CompanyHeader {
  ticker: string;
  name: string;
  cik: number;
  sic: string;
  fy_end: string;
  fy: string | null;
  filings: number;
  latest_filing: FilingRef | null;
  latest_10k: FilingRef | null;
  updated: string | null;
  state: CompanyState;
  job: Job | null;
  figures: Figure[];
  counts: Counts;
  has_memo: boolean;
  questions: number;
}

export interface FindingRow {
  qid: string;
  label: string;
  group: string;
  order: number;
  answer_type: string;
  status: Status;
  reasons: string[];
  reviewed_at: string | null;
  flagged: boolean;
  gist: string;
  value: number | null;
  unit: string | null;
  value_label: string;
  source: string;
  has_note: boolean;
}

export interface FindingsList {
  groups: { name: string; items: FindingRow[] }[];
  counts: Counts;
}

export interface Citation {
  n: number;
  chunk_id: string | null;
  quote: string;
  verified: boolean;
  doc_id: string | null;
  form: string | null;
  period: string | null;
  filing_date: string | null;
  section: string;
  url: string | null;
  in_set?: boolean;
}

export interface Point {
  text: string;
  cites: number[];
}

export interface FindingDetail extends FindingRow {
  question: string;
  answer: string;
  presented: boolean;
  points: Point[];
  citations: Citation[];
  facts: {
    quotes_found: string | null;
    period: string;
    period_full: string;
    confidence: string | null;
    sec_check: { match: boolean; expected: number | null; period: string | null; concepts: string[] | null } | null;
  };
  note: { text: string; at: string | null } | null;
  flagged_at: string | null;
}

export interface Mark {
  start: number;
  end: number;
  cite: number;
}

export type Block =
  | { type: "p"; text: string; marks: Mark[] }
  | { type: "table"; rows: { text: string; marks: Mark[] }[][] };

export interface Passage {
  chunk_id: string;
  doc_id: string;
  form: string;
  form_label: string;
  period: string;
  filing_date: string;
  heading: string;
  subheading: string;
  url: string;
  blocks: Block[];
  found: number[];
  quotes_here: number[];
  prev_chunk: string | null;
  next_chunk: string | null;
  /** The cited passage isn't in the current filings (a refresh replaced its filing). */
  missing?: boolean;
}

export interface Financials {
  years: { fy: string; end: string; url: string | null }[];
  rows: { key: string; label: string; kind: "usd" | "pct"; values: (number | null)[] }[];
}

export interface MemoSentence { n: number; text: string; kind: "fact" | "judgment"; notes: number[]; flagged: boolean; reason: string }
export interface MemoNote { n: number; qid: string; label: string; quote: string; doc_id: string; section: string; url: string }
export interface Memo {
  title: string;
  generated: string | null;
  model: string | null;
  sections: { heading: string; sentences: MemoSentence[] }[];
  open_questions: string[];
  notes: MemoNote[];
  check: { sentences: number; flagged: number } | null;
}

export interface Question {
  id: string;
  asked_at: string;
  question: string;
  status: "answered" | "not_found" | "unsupported" | "error";
  answer: string;
  value: string;
  unit: string;
  period: string;
  confidence: string;
  error: string | null;
  citations: Citation[];
  cost_usd: number;
  model: string;
}

export interface Thread {
  questions: Question[];
  spend: { today_usd: number; cap_usd: number; estimate_usd: number };
}

export interface Filing {
  doc_id: string;
  form: string;
  form_label: string;
  period: string;
  report_date: string;
  filing_date: string;
  url: string;
}

export interface Usage {
  days: { date: string; questions_usd: number; screening_usd: number }[];
  total_usd: number;
  caps: {
    questions: { today_usd: number; cap_usd: number; estimate_usd: number };
    screening: { today_usd: number; cap_usd: number; per_run_limit_usd: number };
  };
  by_company: { ticker: string; name: string; screening_usd: number; questions: number; questions_usd: number }[];
}

export const api = {
  coverage: () => get<Coverage>("/api/coverage"),
  search: (q: string) => get<SecResult[]>(`/api/sec/search?q=${enc(q)}`),
  preview: (t: string) => get<Preview>(`/api/sec/preview/${enc(t)}`),
  start: (ticker: string, confirm_usd: number) => post<CoverageRow>("/api/companies", { ticker, confirm_usd }),
  retry: (t: string, confirm_usd: number) => post<CoverageRow>(`/api/companies/${enc(t)}/retry`, { confirm_usd }),
  remove: (t: string) => post<Coverage>(`/api/companies/${enc(t)}/remove`),
  company: (t: string) => get<CompanyHeader>(`/api/companies/${enc(t)}`),
  findings: (t: string) => get<FindingsList>(`/api/companies/${enc(t)}/findings`),
  finding: (t: string, qid: string) => get<FindingDetail>(`/api/companies/${enc(t)}/findings/${enc(qid)}`),
  passage: (t: string, chunk: string, source: string) =>
    get<Passage>(`/api/companies/${enc(t)}/passage?chunk=${enc(chunk)}&source=${enc(source)}`),
  note: (t: string, qid: string, text: string) =>
    post<FindingDetail>(`/api/companies/${enc(t)}/findings/${enc(qid)}/note`, { text }),
  flag: (t: string, qid: string, flagged: boolean) =>
    post<FindingDetail>(`/api/companies/${enc(t)}/findings/${enc(qid)}/flag`, { flagged }),
  financials: (t: string) => get<Financials>(`/api/companies/${enc(t)}/financials`),
  memo: (t: string) => get<Memo>(`/api/companies/${enc(t)}/memo`),
  questions: (t: string) => get<Thread>(`/api/companies/${enc(t)}/questions`),
  ask: (t: string, question: string, max_usd: number) => post<Thread>(`/api/companies/${enc(t)}/questions`, { question, max_usd }),
  filings: (t: string) => get<Filing[]>(`/api/companies/${enc(t)}/filings`),
  usage: () => get<Usage>("/api/usage"),
  review: (t: string, qid: string, reviewed: boolean) =>
    post<FindingDetail>(`/api/companies/${enc(t)}/findings/${enc(qid)}/review`, { reviewed }),
};
