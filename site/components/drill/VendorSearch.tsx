"use client";

/* Search the state checkbook by name and jump straight to that organization's
   money trail. Selecting a result seeds the exact drill path a click would —
   area → agency → department → checkbook → vendor — so the visitor lands on the
   profile (and its cross-source dossier) already open. Every result is
   followable; we only publish vendors whose path resolves. */

import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { fmtUsd } from "@/lib/published";
import type { PathSeg, SearchIndexDoc } from "./types";

type Entry = SearchIndexDoc["vendors"][number];

const MAX_RESULTS = 8;

function pathFor(e: Entry): PathSeg[] {
  return [
    { kind: "area", name: e.area },
    { kind: "agency", cd: e.agency_cd },
    { kind: "dept", orgCd: e.dept_org_cd },
    { kind: "checkbook", orgCd: e.dept_org_cd },
    { kind: "vendor", name: e.name },
  ];
}

export function VendorSearch({ onJump }: { onJump: (p: PathSeg[]) => void }) {
  const [vendors, setVendors] = useState<Entry[] | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    fetch("/data/search_index.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: { data: SearchIndexDoc }) => live && setVendors(d.data.vendors))
      .catch(() => live && setVendors([])); // a failed index just disables search
    return () => {
      live = false;
    };
  }, []);

  // close on outside click
  useEffect(() => {
    const onDoc = (ev: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q.length < 2 || !vendors) return [];
    const starts: Entry[] = [];
    const contains: Entry[] = [];
    for (const v of vendors) {
      const n = v.name.toLowerCase();
      if (n.startsWith(q)) starts.push(v);
      else if (n.includes(q)) contains.push(v);
      if (starts.length >= MAX_RESULTS) break;
    }
    // `vendors` is pre-sorted by spend, so each bucket stays spend-ranked
    return [...starts, ...contains].slice(0, MAX_RESULTS);
  }, [query, vendors]);

  useEffect(() => setActive(0), [query]);

  const choose = (e: Entry) => {
    onJump(pathFor(e));
    setOpen(false);
    setQuery("");
    // let the drill mount, then bring it into view
    requestAnimationFrame(() =>
      document.getElementById("drill")?.scrollIntoView({ behavior: "smooth", block: "start" })
    );
  };

  const onKeyDown = (ev: React.KeyboardEvent) => {
    if (!results.length) return;
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      setActive((a) => Math.min(a + 1, results.length - 1));
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      choose(results[active]);
    } else if (ev.key === "Escape") {
      setOpen(false);
    }
  };

  // search is a progressive enhancement — render nothing until the index loads
  if (vendors !== null && vendors.length === 0) return null;

  return (
    <div ref={boxRef} className="relative">
      <label htmlFor="vendor-search" className="sr-only">
        Search for an organization the state pays
      </label>
      <div className="flex items-center gap-2 rounded-lg border border-rule bg-paper px-3 py-2 focus-within:border-poppy">
        <span aria-hidden className="text-fog">
          ⌕
        </span>
        <input
          id="vendor-search"
          type="text"
          role="combobox"
          aria-expanded={open && results.length > 0}
          aria-controls="vendor-search-results"
          autoComplete="off"
          placeholder="Search an organization the state pays — e.g. Kaiser, Deloitte, a local nonprofit"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          className="w-full bg-transparent text-sm outline-none placeholder:text-fog"
        />
      </div>

      {open && query.trim().length >= 2 && (
        <div
          id="vendor-search-results"
          role="listbox"
          className="absolute z-20 mt-1 w-full overflow-hidden rounded-lg border border-rule bg-paper shadow-lg"
        >
          {results.length === 0 ? (
            <p className="px-3 py-3 text-sm text-fog">
              No state-checkbook payments to an organization matching “{query.trim()}”. Organizations
              paid only through federal or nonprofit channels are in those sections.
            </p>
          ) : (
            results.map((e, i) => (
              <button
                key={`${e.name}-${e.agency_cd}-${e.dept_org_cd}`}
                role="option"
                aria-selected={i === active}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(e)}
                className={cn(
                  "flex w-full items-center justify-between gap-3 border-b border-rule/60 px-3 py-2 text-left last:border-b-0",
                  i === active ? "bg-poppy/10" : "hover:bg-poppy/5"
                )}
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm text-ink">{e.name}</span>
                  {e.dossier && (
                    <span className="text-[11px] text-fog">traced across California ↗</span>
                  )}
                </span>
                <span className="shrink-0 font-mono text-xs text-fog">{fmtUsd(e.total_usd)}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
