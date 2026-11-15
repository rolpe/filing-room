import { useEffect, useRef, useState, type ReactNode } from "react";
import { Icon } from "./Icons";

/** A button that opens a small menu; closes on outside click, Escape or choosing an item. */
export function MenuButton({ label, icon, ghost = false, children, ariaLabel }:
  { label?: string; icon: string; ghost?: boolean; ariaLabel?: string; children: (close: () => void) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  return (
    <div className="menu-wrap" ref={wrap}>
      <button className={`btn${ghost ? " ghost" : ""}${label ? "" : " sq"}`} aria-haspopup="menu" aria-expanded={open}
        aria-label={ariaLabel ?? label} onClick={() => setOpen((o) => !o)}>
        <Icon name={icon} />{label}
      </button>
      {open && <div className="menu" role="menu">{children(() => setOpen(false))}</div>}
    </div>
  );
}

export function ConfirmDialog({ title, children, confirm, danger, busy, onConfirm, onClose }:
  { title: string; children: ReactNode; confirm: string; danger?: boolean; busy?: boolean; onConfirm: () => void; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" tabIndex={-1} ref={ref}>
        <header><h2 id="confirm-title">{title}</h2></header>
        <div className="body">{children}</div>
        <footer>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className={`btn ${danger ? "danger" : "primary"}`} disabled={busy} onClick={onConfirm}>{confirm}</button>
        </footer>
      </div>
    </div>
  );
}
