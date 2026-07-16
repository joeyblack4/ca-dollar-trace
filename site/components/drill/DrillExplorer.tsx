"use client";

/* The drill trail: one continuous surface that expands level by level.
   Sankey click seeds the path; every level renders in place below the last,
   and every branch ends in an explicit terminator — never a dead click.

   Levels: area → agency departments → department (funds + programs +
   checkbook row) → checkbook vendors → vendor profile → terminator. */

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { CoverageBadge } from "@/components/ui/SourceChip";
import { AGENCY_PAGE_FOR_NODE } from "@/lib/agency";
import { fmtUsd, type BudgetWaterfall } from "@/lib/published";
import type { AgencyDoc, PathSeg, ProfilesDoc, VendorsDoc } from "./types";

const FUND_COLORS: Record<string, string> = {
  "General Fund": "#1a1916",
  "Special funds": "#2a78d6",
  "Federal funds": "#7c5cbf",
  "Bond funds": "#1baf7a",
  "Other funds": "#8a8781",
};

/* ---------- tiny client-side fetch cache for published JSON ---------- */
const cache = new Map<string, Promise<unknown>>();
function fetchJson<T>(path: string): Promise<T> {
  if (!cache.has(path)) {
    cache.set(
      path,
      fetch(path).then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${path}`);
        return r.json();
      })
    );
  }
  return cache.get(path)! as Promise<T>;
}

function useJson<T>(path: string | null): T | null | "loading" {
  const [state, setState] = useState<T | null | "loading">(path ? "loading" : null);
  useEffect(() => {
    if (!path) return setState(null);
    let live = true;
    setState("loading");
    fetchJson<T>(path)
      .then((d) => live && setState(d))
      .catch(() => live && setState(null));
    return () => {
      live = false;
    };
  }, [path]);
  return state;
}

/* ---------- shared row primitive: proportional, clickable ---------- */
function Row({
  label,
  sub,
  usd,
  maxUsd,
  color = "#e87722",
  selected,
  onClick,
  chip,
}: {
  label: React.ReactNode;
  sub?: string;
  usd: number;
  maxUsd: number;
  color?: string;
  selected?: boolean;
  onClick?: () => void;
  chip?: React.ReactNode;
}) {
  const body = (
    <>
      <div className="flex items-baseline justify-between gap-3">
        <span className={cn("text-sm", selected && "font-semibold")}>
          {label}
          {chip && <span className="ml-2 align-middle">{chip}</span>}
        </span>
        <span className="shrink-0 font-mono text-xs">{fmtUsd(usd)}</span>
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

function Terminator({ flag, children }: { flag: "trail_ends_here" | "masked" | "category_only"; children: React.ReactNode }) {
  return (
    <div className="mt-2 rounded-md border border-dark-zone/30 px-3 py-2.5 text-sm text-fog [background-image:repeating-linear-gradient(45deg,transparent,transparent_5px,rgba(87,83,78,0.07)_5px,rgba(87,83,78,0.07)_10px)]">
      <CoverageBadge flag={flag} /> <span className="ml-1">{children}</span>{" "}
      <a href="/gaps/" className="underline decoration-rule underline-offset-2 hover:text-ink">
        details
      </a>
    </div>
  );
}

function LevelCard({
  step,
  title,
  subtitle,
  children,
}: {
  step: number;
  title: string;
  subtitle?: string;
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
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-[11px] text-fog">hop {step}</span>
          <h3 className="text-base font-semibold">{title}</h3>
        </div>
        {subtitle && <p className="mt-0.5 text-xs text-fog">{subtitle}</p>}
        <div className="mt-3">{children}</div>
      </div>
    </div>
  );
}

/* ---------- the explorer ---------- */

export function DrillExplorer({
  waterfall,
  path,
  setPath,
}: {
  waterfall: BudgetWaterfall;
  path: PathSeg[];
  setPath: (p: PathSeg[]) => void;
}) {
  const area = path.find((s) => s.kind === "area") as { kind: "area"; name: string } | undefined;
  const agencySeg = path.find((s) => s.kind === "agency") as { kind: "agency"; cd: string } | undefined;
  const deptSeg = path.find((s) => s.kind === "dept") as { kind: "dept"; orgCd: string } | undefined;
  const checkbookSeg = path.find((s) => s.kind === "checkbook");
  const vendorSeg = path.find((s) => s.kind === "vendor") as { kind: "vendor"; name: string } | undefined;

  const agencyDoc = useJson<AgencyDoc>(agencySeg ? `/data/agencies/${agencySeg.cd}.json` : null);
  const vendorsDoc = useJson<VendorsDoc>(agencySeg ? `/data/vendors/${agencySeg.cd}.json` : null);
  const profilesDoc = useJson<ProfilesDoc>(vendorSeg ? "/data/vendor_profiles.json" : null);

  if (!area) {
    return (
      <p className="mt-6 text-sm text-fog">
        ↑ Click any spending block in the waterfall to start following the money.
      </p>
    );
  }

  const truncate = (i: number) => setPath(path.slice(0, i + 1));

  /* breadcrumb */
  const crumbs: { label: string; amount?: number }[] = [{ label: "General Fund" }];
  crumbs.push({ label: area.name });
  const agency = agencyDoc && agencyDoc !== "loading" ? agencyDoc.data : null;
  const dept = dept0();
  function dept0() {
    if (!deptSeg || !agency) return null;
    return agency.departments.find((d) => d.org_cd === deptSeg.orgCd) ?? null;
  }
  if (agency) crumbs.push({ label: agency.title, amount: agency.total_usd });
  if (dept) crumbs.push({ label: dept.title, amount: dept.total_usd });
  if (checkbookSeg) crumbs.push({ label: "checkbook" });
  if (vendorSeg) crumbs.push({ label: vendorSeg.name });

  const vendorDept =
    deptSeg && vendorsDoc && vendorsDoc !== "loading"
      ? vendorsDoc.data.departments.find((d) => d.org_cd === deptSeg.orgCd) ?? null
      : null;

  return (
    <div className="mt-8" id="drill">
      <div className="sticky top-0 z-10 -mx-2 flex flex-wrap items-center gap-1 border-b border-rule bg-paper/95 px-2 py-2 text-xs backdrop-blur">
        <span className="font-medium text-fog">Following:</span>
        {crumbs.map((c, i) => (
          <span key={`${c.label}-${i}`} className="flex items-center gap-1">
            {i > 0 && <span className="text-fog">→</span>}
            <button
              onClick={() => truncate(Math.min(i - 1, path.length - 1))}
              className={cn(
                "rounded px-1.5 py-0.5 hover:bg-poppy/10",
                i === crumbs.length - 1 ? "font-semibold text-ink" : "text-fog"
              )}
            >
              {c.label}
              {c.amount ? <span className="ml-1 font-mono">{fmtUsd(c.amount)}</span> : null}
            </button>
          </span>
        ))}
      </div>

      {/* Level 1: area -> agency (or agency picker for "Other") */}
      {!AGENCY_PAGE_FOR_NODE[area.name] && !agencySeg && (
        <LevelCard
          step={1}
          title={`"${area.name}" covers the remaining agency groups`}
          subtitle="Pick one to keep following the money (all-funds totals)."
        >
          {waterfall.agencies
            .filter((a) => !Object.values(AGENCY_PAGE_FOR_NODE).includes(a.org_cd))
            .map((a, _, arr) => (
              <Row
                key={a.org_cd}
                label={a.title}
                usd={a.all_funds_usd}
                maxUsd={arr[0].all_funds_usd}
                onClick={() => setPath([area, { kind: "agency", cd: a.org_cd }])}
              />
            ))}
        </LevelCard>
      )}

      {/* Level 2: agency departments */}
      {agencySeg && (
        <LevelCard
          step={2}
          title={agency ? `${agency.title} — ${fmtUsd(agency.total_usd)} across ${agency.departments.length} departments` : "Loading departments…"}
          subtitle="All funds (state + federal passthrough). Click a department."
        >
          {agency &&
            agency.departments.slice(0, 30).map((d) => (
              <Row
                key={d.org_cd}
                label={d.title}
                usd={d.total_usd}
                maxUsd={agency.departments[0].total_usd}
                sub={`GF ${fmtUsd(d.general_fund_usd)}`}
                selected={deptSeg?.orgCd === d.org_cd}
                onClick={() => setPath([...path.slice(0, path.indexOf(agencySeg) + 1), { kind: "dept", orgCd: d.org_cd }])}
              />
            ))}
        </LevelCard>
      )}

      {/* Level 3: department detail */}
      {dept && (
        <LevelCard
          step={3}
          title={`${dept.title} — ${fmtUsd(dept.total_usd)}`}
          subtitle="Where it sits in the budget: fund mix and program lines."
        >
          {Object.keys(dept.funds_by_class).length > 0 && (
            <div className="mb-3">
              <div className="flex h-3 overflow-hidden rounded-full">
                {Object.entries(dept.funds_by_class).map(([label, usd]) => (
                  <div
                    key={label}
                    title={`${label}: ${fmtUsd(usd)}`}
                    style={{
                      width: `${(usd / Object.values(dept.funds_by_class).reduce((a, b) => a + b, 0)) * 100}%`,
                      background: FUND_COLORS[label] ?? "#8a8781",
                    }}
                  />
                ))}
              </div>
              <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-fog">
                {Object.entries(dept.funds_by_class).map(([label, usd]) => (
                  <span key={label} className="flex items-center gap-1">
                    <span className="h-2 w-2 rounded-sm" style={{ background: FUND_COLORS[label] ?? "#8a8781" }} />
                    {label} {fmtUsd(usd)}
                  </span>
                ))}
              </div>
            </div>
          )}
          {dept.programs.slice(0, 10).map((p) => (
            <Row
              key={`${p.program_code}-${p.title}`}
              label={p.title}
              usd={p.usd}
              maxUsd={dept.programs[0]?.usd ?? 1}
              color="#2a78d6"
            />
          ))}

          {vendorDept ? (
            <div className="mt-3">
              <Row
                label="Open the checkbook: who actually got paid"
                sub={`${vendorDept.checkbook_coverage_pct ?? "?"}% of budget visible`}
                usd={vendorDept.vendor_total_usd}
                maxUsd={dept.total_usd}
                color="#1e7f4f"
                selected={!!checkbookSeg}
                onClick={() =>
                  setPath([...path.filter((s) => s.kind !== "checkbook" && s.kind !== "vendor"), { kind: "checkbook", orgCd: dept.org_cd }])
                }
              />
              <Terminator flag="trail_ends_here">
                The other {fmtUsd(dept.total_usd - vendorDept.vendor_total_usd)} never appears in
                the checkbook — payroll and bulk benefit payments are excluded by design.
              </Terminator>
            </div>
          ) : (
            <Terminator flag="category_only">
              No vendor-level checkbook data for this department — budget categories are as deep
              as the public record goes here.
            </Terminator>
          )}
        </LevelCard>
      )}

      {/* Level 4: checkbook vendors */}
      {checkbookSeg && vendorDept && (
        <LevelCard
          step={4}
          title={`The checkbook — ${fmtUsd(vendorDept.vendor_total_usd)} to ${vendorDept.vendor_count.toLocaleString()} vendors (${vendorDept.fiscal_year})`}
          subtitle="Actual payments from the state accounting system. Click a vendor for their full history."
        >
          {vendorDept.top_vendors.slice(0, 15).map((v) => (
            <Row
              key={v.name}
              label={v.name}
              usd={v.usd}
              maxUsd={vendorDept.top_vendors[0].usd}
              color="#1e7f4f"
              chip={v.masked ? <CoverageBadge flag="masked" /> : undefined}
              selected={vendorSeg?.name === v.name}
              onClick={
                v.masked
                  ? undefined
                  : () => setPath([...path.filter((s) => s.kind !== "vendor"), { kind: "vendor", name: v.name }])
              }
            />
          ))}
          {vendorDept.confidential_usd > 0 && (
            <Terminator flag="masked">
              {fmtUsd(vendorDept.confidential_usd)} went to vendors named only
              &quot;Confidential&quot; — statutory masking.
            </Terminator>
          )}
        </LevelCard>
      )}

      {/* Level 5: vendor profile */}
      {vendorSeg && (
        <LevelCard step={5} title={vendorSeg.name} subtitle="Everything the checkbook shows for this vendor, FY2020 → today.">
          {profilesDoc === "loading" && <p className="text-sm text-fog">Loading vendor history…</p>}
          {profilesDoc && profilesDoc !== "loading" && (() => {
            const p = profilesDoc.data.vendors[vendorSeg.name];
            if (!p)
              return (
                <Terminator flag="category_only">
                  This vendor is outside the statewide top 500 we pre-compute — the raw data
                  download has every transaction.
                </Terminator>
              );
            const years = Object.entries(p.years).sort();
            const maxY = Math.max(...years.map(([, v]) => v));
            return (
              <div>
                <p className="text-sm">
                  <span className="font-mono">{fmtUsd(p.total_usd)}</span>{" "}
                  <span className="text-fog">from the State of California since FY2020</span>
                </p>
                <div className="mt-3 flex items-end gap-2">
                  {years.map(([fy, usd]) => (
                    <div key={fy} className="flex flex-col items-center gap-1">
                      <span className="font-mono text-[10px] text-fog">{fmtUsd(usd)}</span>
                      <div
                        className="w-10 rounded-t bg-traceable"
                        style={{ height: `${Math.max(4, (usd / maxY) * 80)}px` }}
                      />
                      <span className="text-[10px] text-fog">FY{fy.slice(2)}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <div>
                    <div className="text-xs font-medium text-fog">Paid by</div>
                    {p.departments.slice(0, 5).map((d) => (
                      <Row key={d.org_cd} label={d.title} usd={d.usd} maxUsd={p.departments[0].usd} color="#2a78d6" />
                    ))}
                  </div>
                  <div>
                    <div className="text-xs font-medium text-fog">Under programs</div>
                    {p.programs.slice(0, 5).map((pr) => (
                      <Row key={pr.program} label={pr.program} usd={pr.usd} maxUsd={p.programs[0].usd} color="#7c5cbf" />
                    ))}
                  </div>
                </div>
                <Terminator flag="trail_ends_here">
                  What {vendorSeg.name.split(" ")[0]}… does with this money next is not in any
                  public dataset — private organizations publish no checkbook. (For grant
                  administrators, the re-granted awards are sometimes published separately —
                  that&apos;s our next connector.)
                </Terminator>
              </div>
            );
          })()}
        </LevelCard>
      )}
    </div>
  );
}
