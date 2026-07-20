"use client";

/* Shared drill primitives, used by both drill trees (spending: DrillExplorer,
   revenue: RevenueDrill). The affordance grammar lives here: Row is data that
   may drill, RefRow is data that never drills, FollowRow is unmistakably an
   action, Terminator closes a branch — never a dead click. */

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { CoverageBadge } from "@/components/ui/SourceChip";
import { fmtUsd } from "@/lib/published";

/* ---------- tiny client-side fetch cache for published JSON ----------
   Failures are NOT cached (a transient error must not permanently mislabel
   data as missing) and surface as an explicit "error" state, never as the
   same value as "no data". */
const cache = new Map<string, Promise<unknown>>();
export function fetchJson<T>(path: string): Promise<T> {
  if (!cache.has(path)) {
    const p = fetch(path).then((r) => {
      if (!r.ok) throw new Error(`${r.status} ${path}`);
      return r.json();
    });
    p.catch(() => cache.delete(path)); // do not cache rejections
    cache.set(path, p);
  }
  return cache.get(path)! as Promise<T>;
}

export type Fetched<T> = T | null | "loading" | "error";

export function useJson<T>(path: string | null): Fetched<T> {
  const [state, setState] = useState<Fetched<T>>(path ? "loading" : null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!path) return setState(null);
    let live = true;
    setState("loading");
    fetchJson<T>(path)
      .then((d) => live && setState(d))
      .catch(() => live && setState("error"));
    return () => {
      live = false;
    };
  }, [path, retry]);
  // expose retry via a custom event dispatched on window (simple, no context)
  useEffect(() => {
    const h = () => setRetry((n) => n + 1);
    window.addEventListener("drill-retry", h);
    return () => window.removeEventListener("drill-retry", h);
  }, []);
  return state;
}

export function FetchError({ what }: { what: string }) {
  return (
    <p className="text-sm text-fog">
      Couldn&apos;t load {what} — that&apos;s a connection problem on our side, not a gap
      in the public record.{" "}
      <button
        onClick={() => window.dispatchEvent(new Event("drill-retry"))}
        className="underline underline-offset-2 hover:text-ink"
      >
        Retry
      </button>
    </p>
  );
}

/* ---------- shared row primitive: proportional, clickable ---------- */
export function Row({
  label,
  sub,
  usd,
  maxUsd,
  color = "#e87722",
  selected,
  onClick,
  chip,
  valueLabel,
}: {
  label: React.ReactNode;
  sub?: string;
  usd: number;
  maxUsd: number;
  color?: string;
  selected?: boolean;
  onClick?: () => void;
  chip?: React.ReactNode;
  valueLabel?: string;
}) {
  const body = (
    <>
      <div className="flex items-baseline justify-between gap-3">
        <span className={cn("text-sm", selected && "font-semibold")}>
          {label}
          {chip && <span className="ml-2 align-middle">{chip}</span>}
        </span>
        <span className="shrink-0 font-mono text-xs">{valueLabel ?? fmtUsd(usd)}</span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-rule/40">
          <div
            className="h-full rounded-full"
            style={{ width: `${Math.max(0.5, (usd / maxUsd) * 100)}%`, background: color }}
          />
        </div>
        {sub && <span className="shrink-0 text-[11px] text-fog">{sub}</span>}
      </div>
    </>
  );
  if (!onClick)
    return <div className="rounded-md px-3 py-2">{body}</div>;
  return (
    <button
      onClick={onClick}
      className={cn(
        "block w-full rounded-md px-3 py-2 text-left transition-colors hover:bg-poppy/[0.06]",
        selected && "bg-poppy/[0.08] ring-1 ring-poppy/40"
      )}
    >
      {body}
    </button>
  );
}

/* Reference line: a budget category. Deliberately reads as DATA, not a button —
   flat, muted, no hover, thin bar. It does not drill. */
export function RefRow({
  label,
  usd,
  maxUsd,
  sub,
  valueLabel,
}: {
  label: string;
  usd: number;
  maxUsd: number;
  sub?: string;
  valueLabel?: string;
}) {
  return (
    <div className="px-1 py-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm text-ink/90">{label}</span>
        <span className="shrink-0 font-mono text-xs text-fog">{valueLabel ?? fmtUsd(usd)}</span>
      </div>
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-rule/30">
        <div
          className="h-full rounded-full bg-[#2a78d6]/50"
          style={{ width: `${Math.max(0.5, (usd / maxUsd) * 100)}%` }}
        />
      </div>
      {sub && <div className="mt-0.5 text-[11px] text-fog">{sub}</div>}
    </div>
  );
}

/* Action line: a live path deeper. Reads unmistakably as a button — poppy
   border, chevron, hover, "keep following". */
export function FollowRow({
  label,
  hint,
  selected,
  onClick,
}: {
  label: string;
  hint?: string;
  selected?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex w-full items-center justify-between gap-3 rounded-md border px-3 py-2.5 text-left transition-colors",
        selected
          ? "border-poppy bg-poppy/[0.08]"
          : "border-poppy/40 bg-poppy/[0.03] hover:bg-poppy/[0.08]"
      )}
    >
      <span>
        <span className="text-sm font-medium text-ink">{label}</span>
        {hint && <span className="mt-0.5 block text-xs text-fog">{hint}</span>}
      </span>
      <span className="shrink-0 font-mono text-xs text-poppy-deep">keep following →</span>
    </button>
  );
}

export function Terminator({ flag, children }: { flag: "trail_ends_here" | "masked" | "category_only"; children: React.ReactNode }) {
  return (
    <div className="mt-2 rounded-md border border-dark-zone/30 px-3 py-2.5 text-sm text-fog [background-image:repeating-linear-gradient(45deg,transparent,transparent_5px,rgba(87,83,78,0.07)_5px,rgba(87,83,78,0.07)_10px)]">
      <CoverageBadge flag={flag} /> <span className="ml-1">{children}</span>{" "}
      <a href="/gaps/" className="underline decoration-rule underline-offset-2 hover:text-ink">
        details
      </a>
    </div>
  );
}

export function LevelCard({
  step,
  title,
  subtitle,
  chip,
  children,
}: {
  step: number;
  title: string;
  subtitle?: string;
  chip?: React.ReactNode;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, []);
  return (
    <div ref={ref} className="relative pl-6">
      {/* flow connector */}
      <div className="absolute left-2 top-0 h-full w-px bg-rule" aria-hidden />
      <div className="absolute left-[3.5px] top-6 h-2.5 w-2.5 rounded-full border-2 border-poppy bg-paper" aria-hidden />
      <div className="mt-4 rounded-lg border border-rule p-4">
        <div className="flex flex-wrap items-baseline gap-2">
          <h3 className="text-base font-semibold">{title}</h3>
          {chip}
        </div>
        {subtitle && <p className="mt-0.5 text-xs text-fog">{subtitle}</p>}
        <div className="mt-3">{children}</div>
      </div>
    </div>
  );
}
