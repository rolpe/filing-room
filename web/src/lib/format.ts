// Number and date formatting. Negatives in parentheses; money in $M with one decimal from $1M up.

const n1 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const n0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

function paren(neg: boolean, s: string) {
  return neg ? `(${s})` : s;
}

export function usd(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  const s = a >= 1e6 ? `$${n1.format(a / 1e6)}M` : `$${n0.format(a)}`;
  return paren(v < 0, s);
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const s = `${Math.abs(v).toFixed(digits)}%`;
  return paren(v < 0, s);
}

export function pctChange(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "";
  return v < 0 ? `(${Math.abs(v).toFixed(1)}%)` : `+${v.toFixed(1)}%`;
}

export function count(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  return paren(v < 0, n0.format(Math.abs(v)));
}

/** A finding's value as the model stated it: integers stay integers ("95%"), decimals keep one place. */
export function findingValue(v: number | null, unit: string | null): string {
  if (v === null) return "";
  if (unit === "USD") return usd(v);
  if (unit === "percent") return Number.isInteger(v) ? paren(v < 0, `${Math.abs(v)}%`) : pct(v);
  return count(v);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parts(iso: string): [number, number, number] | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}

/** "2026-08-20" -> "Aug 20, 2026" */
export function date(iso: string | null | undefined): string {
  const p = parts(iso || "");
  return p ? `${MONTHS[p[1] - 1]} ${p[2]}, ${p[0]}` : "";
}

/** "2026-09-27" -> "Sep 27" this year, else "Sep 27, 2025" */
export function shortDate(iso: string | null | undefined): string {
  const p = parts(iso || "");
  if (!p) return "";
  return p[0] === new Date().getFullYear() ? `${MONTHS[p[1] - 1]} ${p[2]}` : date(iso);
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return shortDate(iso);
}

export function money(v: number): string {
  return `$${v.toFixed(2)}`;
}

export const statusLabel = { verified: "Verified", review: "To review", not_disclosed: "Not disclosed" } as const;
