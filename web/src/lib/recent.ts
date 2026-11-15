// Recently opened companies, per browser. A convenience only: always filtered against the coverage list.
const KEY = "filing-room:recent";

export function readRecent(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function pushRecent(ticker: string) {
  try {
    const next = [ticker, ...readRecent().filter((t) => t !== ticker)].slice(0, 6);
    localStorage.setItem(KEY, JSON.stringify(next));
    window.dispatchEvent(new Event("filing-room:recent"));
  } catch {
    /* storage unavailable: recents just don't persist */
  }
}
