import type { ReactNode } from "react";
import { Icon } from "./Icons";

export function Skeleton({ w = "100%", h = 12, style }: { w?: number | string; h?: number; style?: React.CSSProperties }) {
  return <span className="sk" style={{ width: w, height: h, ...style }} />;
}

export function SkeletonRows({ rows = 6, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading" style={{ display: "grid", gap: 18, padding: "16px 0" }}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} style={{ display: "grid", gridTemplateColumns: `2fr repeat(${cols - 1}, 1fr)`, gap: 24 }}>
          {Array.from({ length: cols }, (_, j) => <Skeleton key={j} w={j === 0 ? "70%" : "60%"} />)}
        </div>
      ))}
    </div>
  );
}

export function ErrorState({ title = "Something went wrong", error, onRetry, children }:
  { title?: string; error?: unknown; onRetry?: () => void; children?: ReactNode }) {
  const msg = error instanceof Error ? error.message : error ? String(error) : "";
  return (
    <div className="state" role="alert">
      <h2>{title}</h2>
      {msg && <p>{msg}</p>}
      {children}
      {onRetry && <button className="btn" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Notice({ kind = "", icon = "alert", children }: { kind?: "" | "warn" | "bad"; icon?: string; children: ReactNode }) {
  return (
    <div className={`notice ${kind}`} role={kind === "bad" ? "alert" : undefined}>
      <Icon name={icon} />
      {children}
    </div>
  );
}
