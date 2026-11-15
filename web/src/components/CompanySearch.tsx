import { forwardRef, useEffect, useId, useImperativeHandle, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, type SecResult } from "../lib/api";
import { useDebounced } from "../lib/hooks";
import { Icon } from "./Icons";
import { useAddCompany } from "./AddCompany";

// Find-or-add: companies already in coverage open; any other SEC registrant opens the add dialog.

export interface SearchHandle { focus: () => void }

export const CompanySearch = forwardRef<SearchHandle, { large?: boolean; shortcut?: boolean; autoFocus?: boolean }>(
  function CompanySearch({ large = false, shortcut = false, autoFocus = false }, handle) {
    const [q, setQ] = useState("");
    const [open, setOpen] = useState(false);
    const [active, setActive] = useState(0);
    const input = useRef<HTMLInputElement>(null);
    const nav = useNavigate();
    const add = useAddCompany();
    const listId = useId();
    const dq = useDebounced(q.trim(), 150);
    useImperativeHandle(handle, () => ({ focus: () => input.current?.focus() }));

    const res = useQuery({ queryKey: ["sec-search", dq], queryFn: () => api.search(dq), enabled: dq.length > 0, staleTime: 60_000 });
    const items: SecResult[] = useMemo(() => {
      const r = res.data ?? [];
      return [...r.filter((x) => x.in_coverage), ...r.filter((x) => !x.in_coverage)];
    }, [res.data]);

    useEffect(() => setActive(0), [dq]);
    useEffect(() => {
      if (!shortcut) return;
      const onKey = (e: KeyboardEvent) => {
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
          e.preventDefault();
          input.current?.focus();
          input.current?.select();
        }
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }, [shortcut]);

    const pick = (r: SecResult) => {
      setOpen(false);
      setQ("");
      input.current?.blur();
      if (r.in_coverage) nav(`/c/${r.ticker}`);
      else add(r.ticker);
    };

    const onKeyDown = (e: React.KeyboardEvent) => {
      if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, items.length - 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
      else if (e.key === "Enter" && items[active]) { e.preventDefault(); pick(items[active]); }
      else if (e.key === "Escape") { setOpen(false); input.current?.blur(); }
    };

    const show = open && dq.length > 0;
    const indexed = items.map((r, i) => ({ r, i }));
    const groups = [
      { key: "cov", title: "In coverage", items: indexed.filter((x) => x.r.in_coverage) },
      { key: "sec", title: "Add from SEC EDGAR", items: indexed.filter((x) => !x.r.in_coverage) },
    ];
    return (
      <div className={`search${large ? " lg" : ""}`}>
        <Icon name="search" />
        <input ref={input} type="search" value={q} autoFocus={autoFocus}
          placeholder="Find a company by name or ticker" aria-label="Find a company"
          role="combobox" aria-expanded={show} aria-controls={listId} aria-autocomplete="list"
          aria-activedescendant={show && items[active] ? `${listId}-${active}` : undefined}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 120)} onKeyDown={onKeyDown} />
        {shortcut && <kbd>⌘K</kbd>}
        {show && (
          <div className="results scroll" id={listId} role="listbox" aria-label="Companies">
            {res.isError && <div className="none" role="presentation">Search is unavailable: {(res.error as Error).message}</div>}
            {!res.isError && res.isFetching && items.length === 0 && <div className="none" role="presentation">Searching SEC registrants…</div>}
            {!res.isError && !res.isFetching && items.length === 0 && <div className="none" role="presentation">No SEC-registered company matches “{dq}”.</div>}
            {groups.map((g) => g.items.length > 0 && (
              <div key={g.key} role="group" aria-labelledby={`${listId}-${g.key}`}>
                <h3 id={`${listId}-${g.key}`} role="presentation">{g.title}</h3>
                {g.items.map(({ r, i }) => (
                  <div key={r.ticker} role="option" id={`${listId}-${i}`} aria-selected={i === active}
                    aria-label={`${r.ticker}, ${r.name}, ${r.in_coverage ? "open" : "add"}`}
                    onMouseDown={(e) => { e.preventDefault(); pick(r); }} onMouseEnter={() => setActive(i)}>
                    <b>{r.ticker}</b><span>{r.name}</span><small>{r.in_coverage ? "Open" : "Add…"}</small>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  });
