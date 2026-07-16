"use client";

/* The drill trail: one continuous surface that expands level by level.
   Sankey click seeds the path; every level renders in place below the last,
   and every branch ends in an explicit terminator — never a dead click.

   Levels: area → agency departments → department (funds + programs +
   checkbook row) → checkbook vendors → vendor profile → terminator. */

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { CoverageBadge } from "@/components/ui/SourceChip";
import { PublicSectorChip } from "@/components/agency/VendorsSection";
import { AGENCY_PAGE_FOR_NODE } from "@/lib/agency";
import { fmtFy, fmtUsd, type BudgetWaterfall } from "@/lib/published";
import type {
  AgencyDoc,
  BhcipDoc,
  CompensationDoc,
  CountyFinancesDoc,
  K12Doc,
  MedicalPlansDoc,
  NonprofitsDoc,
  PathSeg,
  ProfilesDoc,
  VendorsDoc,
} from "./types";

/** Departments with a recovered program-level hop past the checkbook */
const DEPT_PLAN_HOP: Record<string, string> = {
  "4260": "Follow the Benefits money into the managed care plans",
};

/** Departments whose money flows to the 58 counties (realignment) */
const isCountyFlowDept = (title: string) => /realignment/i.test(title);

/** The K-12 apportionment department: money flows to ~2,000 school districts */
const isK12Dept = (orgCd: string) => orgCd === "6100";
import type { Published } from "@/lib/published";

/* Vendors whose re-granted awards we've recovered from program reporting */
const RECOVERED_PROGRAMS: Record<string, { program: string; label: string }> = {
  "ADVOCATES FOR HUMAN POTENTIAL": {
    program: "bhcip",
    label: "Re-granted through BHCIP — see the organizations that received it",
  },
};

const FUND_COLORS: Record<string, string> = {
  "General Fund": "#1a1916",
  "Special funds": "#2a78d6",
  "Federal funds": "#7c5cbf",
  "Bond funds": "#1baf7a",
  "Other funds": "#8a8781",
};

/* ---------- tiny client-side fetch cache for published JSON ----------
   Failures are NOT cached (a transient error must not permanently mislabel
   data as missing) and surface as an explicit "error" state, never as the
   same value as "no data". */
const cache = new Map<string, Promise<unknown>>();
function fetchJson<T>(path: string): Promise<T> {
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

type Fetched<T> = T | null | "loading" | "error";

function useJson<T>(path: string | null): Fetched<T> {
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

function FetchError({ what }: { what: string }) {
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
function Row({
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
function RefRow({ label, usd, maxUsd }: { label: string; usd: number; maxUsd: number }) {
  return (
    <div className="px-1 py-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm text-ink/90">{label}</span>
        <span className="shrink-0 font-mono text-xs text-fog">{fmtUsd(usd)}</span>
      </div>
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-rule/30">
        <div
          className="h-full rounded-full bg-[#2a78d6]/50"
          style={{ width: `${Math.max(0.5, (usd / maxUsd) * 100)}%` }}
        />
      </div>
    </div>
  );
}

/* Action line: a live path deeper. Reads unmistakably as a button — poppy
   border, chevron, hover, "keep following". */
function FollowRow({
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

  const recoveredSeg = path.find((s) => s.kind === "recovered") as
    | { kind: "recovered"; program: string }
    | undefined;
  const plansSeg = path.find((s) => s.kind === "plans");
  const countiesSeg = path.find((s) => s.kind === "counties");
  const districtsSeg = path.find((s) => s.kind === "districts");

  const agencyDoc = useJson<AgencyDoc>(agencySeg ? `/data/agencies/${agencySeg.cd}.json` : null);
  const vendorsDoc = useJson<VendorsDoc>(agencySeg ? `/data/vendors/${agencySeg.cd}.json` : null);
  const compDoc = useJson<Published<CompensationDoc>>(deptSeg ? "/data/compensation.json" : null);
  const profilesDoc = useJson<ProfilesDoc>(vendorSeg ? "/data/vendor_profiles.json" : null);
  const bhcipDoc = useJson<Published<BhcipDoc>>(
    recoveredSeg?.program === "bhcip" || (vendorSeg && RECOVERED_PROGRAMS[vendorSeg.name])
      ? "/data/bhcip_awards.json"
      : null
  );
  const plansDoc = useJson<Published<MedicalPlansDoc>>(
    plansSeg ? "/data/medical_plans.json" : null
  );
  const countiesDoc = useJson<Published<CountyFinancesDoc>>(
    countiesSeg ? "/data/county_finances.json" : null
  );
  const k12Doc = useJson<Published<K12Doc>>(districtsSeg ? "/data/k12_finances.json" : null);
  const nonprofitsDoc = useJson<Published<NonprofitsDoc>>(
    vendorSeg ? "/data/nonprofits.json" : null
  );

  if (!area) {
    return (
      <p className="mt-6 text-sm text-fog">
        ↑ Click any spending block in the waterfall to start following the money.
      </p>
    );
  }

  const agency = agencyDoc && agencyDoc !== "loading" && agencyDoc !== "error" ? agencyDoc.data : null;
  const dept =
    deptSeg && agency
      ? (agency.departments.find((d) => d.org_cd === deptSeg.orgCd) ?? null)
      : null;

  /* breadcrumbs are built FROM the path (one crumb per segment, in order) so
     clicking a crumb truncates to that exact segment — display never drifts
     from state, even mid-fetch or with a recovered segment present */
  const crumbs: { label: string; amount?: number; unit?: string; pathIndex: number }[] = [
    { label: "2025-26 budget", pathIndex: -1 },
  ];
  for (let i = 0; i < path.length; i++) {
    const seg = path[i];
    // a mapped area and its agency are one conceptual level: show a single
    // crumb (the agency one) so rewinding never strands the user on nothing
    if (seg.kind === "area" && !(AGENCY_PAGE_FOR_NODE[seg.name] && agencySeg))
      crumbs.push({ label: seg.name, pathIndex: i });
    if (seg.kind === "agency")
      crumbs.push(
        agency
          ? { label: agency.title, amount: agency.total_usd, unit: "all funds", pathIndex: i }
          : { label: "…", pathIndex: i }
      );
    if (seg.kind === "dept")
      crumbs.push(
        dept
          ? { label: dept.title, amount: dept.total_usd, unit: "all funds", pathIndex: i }
          : { label: "…", pathIndex: i }
      );
    if (seg.kind === "checkbook") crumbs.push({ label: "checkbook", pathIndex: i });
    if (seg.kind === "vendor") crumbs.push({ label: seg.name, pathIndex: i });
    if (seg.kind === "recovered") crumbs.push({ label: "re-granted", pathIndex: i });
    if (seg.kind === "plans") crumbs.push({ label: "managed care plans", pathIndex: i });
    if (seg.kind === "counties") crumbs.push({ label: "counties", pathIndex: i });
    if (seg.kind === "districts") crumbs.push({ label: "school districts", pathIndex: i });
  }

  const vendorDept =
    deptSeg && vendorsDoc && vendorsDoc !== "loading" && vendorsDoc !== "error"
      ? (vendorsDoc.data.departments.find((d) => d.org_cd === deptSeg.orgCd) ?? null)
      : null;

  return (
    <div className="mt-8" id="drill">
      <div className="sticky top-0 z-10 -mx-2 flex flex-wrap items-center gap-1 border-b border-rule bg-paper/95 px-2 py-2 text-xs backdrop-blur">
        <span className="font-medium text-fog">Following:</span>
        {crumbs.map((c, i) => (
          <span key={`${c.label}-${i}`} className="flex items-center gap-1">
            {i > 0 && <span className="text-fog">→</span>}
            <button
              onClick={() => setPath(path.slice(0, c.pathIndex + 1))}
              className={cn(
                "rounded px-1.5 py-0.5 hover:bg-poppy/10",
                i === crumbs.length - 1 ? "font-semibold text-ink" : "text-fog"
              )}
            >
              {c.label}
              {c.amount !== undefined && (
                <span className="ml-1 font-mono">
                  {fmtUsd(c.amount)}
                  {c.unit && <span className="text-fog"> {c.unit}</span>}
                </span>
              )}
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
          title={agency ? `${agency.title} — ${fmtUsd(agency.total_usd)} across ${agency.departments.length} departments` : "Departments"}
          subtitle="All funds (state + federal passthrough). Click a department."
        >
          {agencyDoc === "loading" && <p className="text-sm text-fog">Loading departments…</p>}
          {agencyDoc === "error" && <FetchError what="this agency's departments" />}
          {agency &&
            agency.departments.slice(0, 30).map((d) => (
              <Row
                key={d.org_cd}
                label={d.title}
                usd={d.total_usd}
                maxUsd={agency.departments[0]?.total_usd ?? 1}
                sub={`GF ${fmtUsd(d.general_fund_usd)}`}
                selected={deptSeg?.orgCd === d.org_cd}
                onClick={() => setPath([...path.slice(0, path.indexOf(agencySeg) + 1), { kind: "dept", orgCd: d.org_cd }])}
              />
            ))}
          {agency && agency.departments.length > 30 && (
            <p className="mt-2 text-xs text-fog">
              Showing the 30 largest of {agency.departments.length} departments —{" "}
              <a
                href={`/data/agencies/${agencySeg.cd}.json`}
                className="underline underline-offset-2 hover:text-ink"
              >
                all departments in the data
              </a>{" "}
              (the tail includes accounting offsets and small line items).
            </p>
          )}
        </LevelCard>
      )}

      {/* Level 3: department detail */}
      {dept && (
        <LevelCard
          step={3}
          title={`${dept.title} — ${fmtUsd(dept.total_usd)}`}
          subtitle="What the budget assigns this department, and how to follow the money past the budget."
        >
          <div className="text-xs font-semibold uppercase tracking-wide text-fog">
            What the budget buys
          </div>
          {Object.keys(dept.funds_by_class).length > 0 &&
            (() => {
              // bars are drawn from POSITIVE components only; negative fund
              // classes (offsets/credits) are disclosed in text, never used
              // to distort segment widths
              const entries = Object.entries(dept.funds_by_class);
              const positives = entries.filter(([, usd]) => usd > 0);
              const negatives = entries.filter(([, usd]) => usd < 0);
              const posSum = positives.reduce((a, [, usd]) => a + usd, 0);
              return (
                <div className="mb-3">
                  {posSum > 0 && (
                    <div className="flex h-3 overflow-hidden rounded-full">
                      {positives.map(([label, usd]) => (
                        <div
                          key={label}
                          title={`${label}: ${fmtUsd(usd)}`}
                          style={{
                            width: `${(usd / posSum) * 100}%`,
                            background: FUND_COLORS[label] ?? "#8a8781",
                          }}
                        />
                      ))}
                    </div>
                  )}
                  <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-fog">
                    {entries.map(([label, usd]) => (
                      <span key={label} className="flex items-center gap-1">
                        <span className="h-2 w-2 rounded-sm" style={{ background: FUND_COLORS[label] ?? "#8a8781" }} />
                        {label} {fmtUsd(usd)}
                      </span>
                    ))}
                  </div>
                  {negatives.length > 0 && (
                    <p className="mt-1 text-[11px] text-fog">
                      Negative amounts are budget offsets/credits — shown in the legend, excluded
                      from the bar so it can&apos;t misstate the mix.
                    </p>
                  )}
                </div>
              );
            })()}
          <div className="mt-1">
            {dept.programs.slice(0, 10).map((p) => (
              <RefRow
                key={`${p.program_code}-${p.title}`}
                label={p.title}
                usd={p.usd}
                maxUsd={dept.programs[0]?.usd ?? 1}
              />
            ))}
          </div>
          {dept.programs.length > 10 && (
            <p className="mt-1 text-xs text-fog">
              The 10 largest of {dept.programs.length} program lines — all are in the{" "}
              <a
                href={agencySeg ? `/data/agencies/${agencySeg.cd}.json` : "/data/"}
                className="underline underline-offset-2 hover:text-ink"
              >
                published data
              </a>
              .
            </p>
          )}
          {compDoc && compDoc !== "loading" && compDoc !== "error"
            ? (() => {
                const c = compDoc.data.state_by_org_cd[dept.org_cd];
                if (!c) return null;
                return (
                  <div className="mt-3 rounded-md border border-[#7c5cbf]/30 bg-[#7c5cbf]/[0.04] px-3 py-2.5">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-sm font-medium">
                        Its people: {c.positions.toLocaleString()} employees
                      </span>
                      <span className="font-mono text-sm">{fmtUsd(c.wages_usd + c.benefits_usd)}</span>
                    </div>
                    <p className="mt-0.5 text-xs text-fog">
                      {fmtUsd(c.wages_usd)} in wages + {fmtUsd(c.benefits_usd)} in retirement &amp;
                      health benefits ({compDoc.data.year}).
                    </p>
                  </div>
                );
              })()
            : null}
          <p className="mt-2 text-xs text-fog">
            These are the budget&apos;s own categories — the deepest the budget itself goes. To
            follow the money past the budget, use the paths below.
          </p>

          {(() => {
            const actions: React.ReactNode[] = [];
            if (DEPT_PLAN_HOP[dept.org_cd])
              actions.push(
                <FollowRow
                  key="plans"
                  label={DEPT_PLAN_HOP[dept.org_cd]}
                  selected={!!plansSeg}
                  onClick={() =>
                    setPath([
                      ...path.filter(
                        (s) =>
                          s.kind !== "plans" &&
                          s.kind !== "counties" &&
                          s.kind !== "checkbook" &&
                          s.kind !== "vendor" &&
                          s.kind !== "recovered"
                      ),
                      { kind: "plans" },
                    ])
                  }
                />
              );
            if (isCountyFlowDept(dept.title))
              actions.push(
                <FollowRow
                  key="counties"
                  label="Follow it to the counties — where realignment money lands"
                  selected={!!countiesSeg}
                  onClick={() =>
                    setPath([
                      ...path.filter(
                        (s) =>
                          s.kind !== "counties" &&
                          s.kind !== "plans" &&
                          s.kind !== "checkbook" &&
                          s.kind !== "vendor" &&
                          s.kind !== "recovered"
                      ),
                      { kind: "counties" },
                    ])
                  }
                />
              );
            if (isK12Dept(dept.org_cd))
              actions.push(
                <FollowRow
                  key="districts"
                  label="Follow it to the school districts"
                  selected={!!districtsSeg}
                  onClick={() =>
                    setPath([
                      ...path.filter(
                        (s) =>
                          s.kind !== "districts" &&
                          s.kind !== "counties" &&
                          s.kind !== "plans" &&
                          s.kind !== "checkbook" &&
                          s.kind !== "vendor" &&
                          s.kind !== "recovered"
                      ),
                      { kind: "districts" },
                    ])
                  }
                />
              );
            if (vendorDept)
              actions.push(
                <FollowRow
                  key="checkbook"
                  label="Open the checkbook — who actually got paid"
                  hint={`${vendorDept.checkbook_coverage_pct ?? "?"}% of the budget is visible as named vendor payments`}
                  selected={!!checkbookSeg}
                  onClick={() =>
                    setPath([
                      ...path.filter(
                        (s) =>
                          s.kind !== "checkbook" &&
                          s.kind !== "vendor" &&
                          s.kind !== "recovered" &&
                          s.kind !== "plans" &&
                          s.kind !== "counties"
                      ),
                      { kind: "checkbook", orgCd: dept.org_cd },
                    ])
                  }
                />
              );
            return (
              <div className="mt-4 border-t border-rule pt-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-poppy">
                  Follow the money further ↓
                </div>
                <div className="mt-2 space-y-2">
                  {actions.length > 0 ? (
                    actions
                  ) : vendorsDoc === "loading" ? (
                    <p className="text-sm text-fog">Checking what&apos;s traceable…</p>
                  ) : (
                    <Terminator flag="category_only">
                      This department&apos;s spending isn&apos;t traced any deeper in public data —
                      the budget categories above are as far as the record goes here.
                    </Terminator>
                  )}
                </div>
              </div>
            );
          })()}

          {vendorDept && (
            <div className="mt-2">
              {dept.total_usd - vendorDept.vendor_total_usd > 0 ? (
                <Terminator flag="trail_ends_here">
                  The other {fmtUsd(dept.total_usd - vendorDept.vendor_total_usd)} never appears
                  in the checkbook — payroll and bulk benefit payments are excluded by design.
                </Terminator>
              ) : (
                <Terminator flag="category_only">
                  Checkbook payments here exceed this year&apos;s enacted budget by{" "}
                  {fmtUsd(vendorDept.vendor_total_usd - dept.total_usd)} — payments can draw on
                  prior-year appropriations and multi-year bond funds, so the two figures measure
                  different things.
                </Terminator>
              )}
            </div>
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
          {vendorDept.public_sector_usd > 0 && (
            <p className="mb-2 text-xs text-fog">
              {fmtUsd(vendorDept.public_sector_usd)} of this is transfers to other{" "}
              <span className="text-[#1c5cab]">public agencies</span> (heuristic flag) — money
              still inside government, not outside vendors.
            </p>
          )}
          {vendorDept.top_vendors.slice(0, 15).map((v) => (
            <Row
              key={v.name}
              label={v.name}
              usd={v.usd}
              maxUsd={vendorDept.top_vendors[0]?.usd ?? 1}
              color={v.public_sector ? "#2a78d6" : "#1e7f4f"}
              chip={
                v.masked ? (
                  <CoverageBadge flag="masked" />
                ) : v.public_sector ? (
                  <PublicSectorChip />
                ) : undefined
              }
              selected={vendorSeg?.name === v.name}
              onClick={
                v.masked
                  ? undefined
                  : () =>
                      setPath([
                        ...path.filter((s) => s.kind !== "vendor" && s.kind !== "recovered"),
                        { kind: "vendor", name: v.name },
                      ])
              }
            />
          ))}
          <p className="mt-2 text-xs text-fog">
            Showing {Math.min(15, vendorDept.top_vendors.length)} of{" "}
            {vendorDept.vendor_count.toLocaleString()} vendors —{" "}
            <a
              href={agencySeg ? `/data/vendors/${agencySeg.cd}.json` : "/data/"}
              className="underline underline-offset-2 hover:text-ink"
            >
              top 25 in the published data
            </a>
            ; the raw files carry every transaction.
          </p>
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
        <LevelCard step={5} title={vendorSeg.name} subtitle="Everything the checkbook shows for this vendor, FY2020-21 → today (latest year in progress).">
          {profilesDoc === "loading" && <p className="text-sm text-fog">Loading vendor history…</p>}
          {profilesDoc === "error" && <FetchError what="the vendor history" />}
          {profilesDoc && profilesDoc !== "loading" && profilesDoc !== "error" && (() => {
            const p = profilesDoc.data.vendors[vendorSeg.name];
            if (!p)
              return (
                <Terminator flag="category_only">
                  This vendor is outside the 500 largest statewide recipients — every
                  payment is in the raw data download.
                </Terminator>
              );
            const years = Object.entries(p.years).sort();
            const maxY = Math.max(1, ...years.map(([, v]) => v));
            const lastFy = years[years.length - 1]?.[0];
            return (
              <div>
                <p className="text-sm">
                  <span className="font-mono">{fmtUsd(p.total_usd)}</span>{" "}
                  <span className="text-fog">
                    net from the State of California since FY2020-21
                  </span>
                </p>
                {p.years_gross && (
                  <p className="mt-0.5 text-xs text-fog">
                    Net of accounting adjustments — years with material adjustments show
                    &quot;payments recorded&quot; separately below.
                  </p>
                )}
                {(() => {
                  const org =
                    nonprofitsDoc && nonprofitsDoc !== "loading" && nonprofitsDoc !== "error"
                      ? nonprofitsDoc.data.organizations[vendorSeg.name]
                      : null;
                  if (!org) return null;
                  return (
                    <p className="mt-1.5 text-xs">
                      {org.may_operate ? (
                        <span className="text-traceable">
                          ✓ Registered charity in good standing
                        </span>
                      ) : (
                        <span className="font-medium text-[#d03b3b]">
                          ⚠ Listed by the Attorney General as NOT in good standing (
                          {org.registry_status})
                        </span>
                      )}
                      <span className="text-fog"> · {org.ct_number}</span>
                      {org.irs_990?.total_revenue_usd != null && (
                        <span className="text-fog">
                          {" "}
                          · total revenue {fmtUsd(org.irs_990.total_revenue_usd)} (
                          {org.irs_990.latest_filing_year} IRS filing,{" "}
                          <a
                            href={org.irs_990.propublica_url}
                            className="underline underline-offset-2 hover:text-ink"
                          >
                            990 ↗
                          </a>
                          )
                        </span>
                      )}
                    </p>
                  );
                })()}
                <div className="mt-3 flex items-end gap-2">
                  {years.map(([fy, usd]) => (
                    <div key={fy} className="flex flex-col items-center gap-1">
                      <span className="font-mono text-[10px] text-fog">
                        {fmtUsd(usd)}
                        {p.years_gross?.[fy] !== undefined && "*"}
                      </span>
                      <div
                        className={cn(
                          "w-10 rounded-t bg-traceable",
                          fy === lastFy && "opacity-70" // year in progress
                        )}
                        style={{ height: `${Math.max(4, (Math.max(0, usd) / maxY) * 80)}px` }}
                      />
                      <span className="text-[10px] text-fog">{fmtFy(fy)}</span>
                    </div>
                  ))}
                </div>
                <p className="mt-1 text-[10px] text-fog">
                  Latest year is in progress (~60-day accounting lag).
                  {p.years_gross &&
                    " *Net of material adjustments: " +
                      Object.entries(p.years_gross)
                        .sort()
                        .map(([fy, g]) => `${fmtFy(fy)} ${fmtUsd(g)} recorded`)
                        .join(", ") +
                      "."}
                </p>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <div>
                    <div className="text-xs font-medium text-fog">
                      Paid by{p.departments.length > 5 && ` (top 5 of ${p.departments.length})`}
                    </div>
                    {p.departments.slice(0, 5).map((d) => (
                      <Row key={d.org_cd} label={d.title} usd={d.usd} maxUsd={p.departments[0]?.usd ?? 1} color="#2a78d6" />
                    ))}
                  </div>
                  <div>
                    <div className="text-xs font-medium text-fog">
                      Under programs{p.programs.length >= 6 && " (top programs)"}
                    </div>
                    {p.programs.slice(0, 5).map((pr) => (
                      <Row key={pr.program} label={pr.program} usd={pr.usd} maxUsd={p.programs[0]?.usd ?? 1} color="#7c5cbf" />
                    ))}
                  </div>
                </div>
                {RECOVERED_PROGRAMS[vendorSeg.name] ? (
                  <div className="mt-3">
                    <Row
                      label={RECOVERED_PROGRAMS[vendorSeg.name].label}
                      usd={p.total_usd}
                      maxUsd={p.total_usd}
                      color="#1e7f4f"
                      selected={!!recoveredSeg}
                      onClick={() =>
                        setPath([
                          ...path.filter((s) => s.kind !== "recovered"),
                          { kind: "recovered", program: RECOVERED_PROGRAMS[vendorSeg.name].program },
                        ])
                      }
                    />
                    <p className="mt-1 text-xs text-fog">
                      The state&apos;s checkbook stops at the administrator — these names come
                      from the program&apos;s own reporting.
                    </p>
                  </div>
                ) : p.public_sector ? (
                  <Terminator flag="category_only">
                    This payee is itself a public agency — the money stayed inside government.
                    Its own spending shows up in its own budget and checkbook, not here.
                  </Terminator>
                ) : (
                  <Terminator flag="trail_ends_here">
                    What {vendorSeg.name.split(" ")[0]}… does with this money next is not in
                    any public dataset — private organizations publish no checkbook. (Where a
                    program publishes its own award lists — like BHCIP — the trail continues.)
                  </Terminator>
                )}
              </div>
            );
          })()}
        </LevelCard>
      )}

      {/* Level 4-alt: Medi-Cal managed care plans (gated on DHCS being the
          current department — a stale segment must not attach to another dept) */}
      {plansSeg && dept && DEPT_PLAN_HOP[dept.org_cd] && (
        <LevelCard
          step={4}
          title={
            plansDoc && plansDoc !== "loading" && plansDoc !== "error"
              ? `${plansDoc.data.plan_count} managed care plan contracts — ${plansDoc.data.total_enrollees.toLocaleString()} Californians enrolled (${plansDoc.data.latest_month})`
              : "Managed care plans"
          }
          subtitle="Each plan is paid a DHCS-certified rate per member per month. Enrollment is per plan per county; rate ranges span categories of aid."
        >
          {plansDoc === "loading" && <p className="text-sm text-fog">Loading plans…</p>}
          {plansDoc === "error" && <FetchError what="the managed care plan data" />}
          {plansDoc && plansDoc !== "loading" && plansDoc !== "error" && (
            <>
              {plansDoc.data.plans.slice(0, 15).map((p) => (
                <Row
                  key={p.plan_name}
                  label={p.plan_name}
                  sub={
                    p.capitation
                      ? `certified rates ${fmtUsd(p.capitation.pmpm_range[0])}–${fmtUsd(p.capitation.pmpm_range[1])}/member/mo (${p.capitation.rate_year}, ${p.capitation.rate_cells} rate cells)`
                      : "no rate match in the medical capitation files"
                  }
                  usd={p.enrollees ?? 0}
                  maxUsd={plansDoc.data.plans[0]?.enrollees ?? 1}
                  color="#2a78d6"
                  valueLabel={`${(p.enrollees ?? 0).toLocaleString()} enrolled`}
                />
              ))}
              <p className="mt-2 text-xs text-fog">
                Showing 15 of {plansDoc.data.plan_count} plan/county contracts. Rate-to-plan name
                matching covers {plansDoc.data.enrollee_weighted_match_pct}% of enrollees
                (published method + alias list) —{" "}
                <a
                  href="/data/medical_plans.json"
                  className="underline underline-offset-2 hover:text-ink"
                >
                  full data
                </a>
                .
              </p>
              <Terminator flag="trail_ends_here">
                What each plan pays hospitals, clinics, and physicians is not public. Roughly 95%
                of Medi-Cal members are behind this wall — the largest single dark zone in state
                spending.
              </Terminator>
            </>
          )}
        </LevelCard>
      )}

      {/* Level 4-alt: K-12 school districts (gated on the education dept) */}
      {districtsSeg && dept && isK12Dept(dept.org_cd) && (
        <LevelCard
          step={4}
          title={
            k12Doc && k12Doc !== "loading" && k12Doc !== "error"
              ? `${k12Doc.data.lea_count.toLocaleString()} school districts & charters — ${fmtUsd(k12Doc.data.statewide_spend_usd)} in day-to-day spending (FY${k12Doc.data.fiscal_year}, unaudited)`
              : "School districts"
          }
          subtitle="Each district's own report of General Fund operating spending — salaries, benefits, outside services, buildings. Construction funds and pass-throughs are in the full data."
        >
          {k12Doc === "loading" && <p className="text-sm text-fog">Loading districts…</p>}
          {k12Doc === "error" && <FetchError what="the district finance data" />}
          {k12Doc && k12Doc !== "loading" && k12Doc !== "error" && (
            <>
              <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-fog">
                {k12Doc.data.statewide_by_class.map((c) => (
                  <span key={c.object_class}>
                    {c.object_class}: <span className="font-mono">{fmtUsd(c.usd)}</span>
                  </span>
                ))}
              </div>
              {k12Doc.data.districts.slice(0, 15).map((d) => (
                <Row
                  key={d.cds}
                  label={d.district ?? `District ${d.cds}`}
                  sub={`${d.county ?? ""} · biggest cost: ${d.spend_by_class[0]?.object_class ?? "—"}`}
                  usd={d.spend_usd ?? 0}
                  maxUsd={k12Doc.data.districts[0]?.spend_usd ?? 1}
                  color="#b98300"
                />
              ))}
              <p className="mt-2 text-xs text-fog">
                Showing 15 of {k12Doc.data.lea_count.toLocaleString()} districts —{" "}
                <a
                  href="/data/k12_finances.json"
                  className="underline underline-offset-2 hover:text-ink"
                >
                  the largest {k12Doc.data.districts_published} with category detail
                </a>
                ; every district is in the raw download.
              </p>
              <Terminator flag="category_only">
                District reports categorize spending but never name who was paid — no school
                district checkbook exists anywhere in California&apos;s public record. Finding
                out requires asking each district directly.
              </Terminator>
            </>
          )}
        </LevelCard>
      )}

      {/* Level 4-alt: county finances (gated on a realignment-type department) */}
      {countiesSeg && dept && isCountyFlowDept(dept.title) && (
        <LevelCard
          step={4}
          title={
            countiesDoc && countiesDoc !== "loading" && countiesDoc !== "error"
              ? `${countiesDoc.data.county_count} counties — ${fmtUsd(countiesDoc.data.total_latest_usd)} in reported spending (FY${countiesDoc.data.latest_fiscal_year - 1}-${String(countiesDoc.data.latest_fiscal_year).slice(2)})`
              : "County finances"
          }
          subtitle="Once state money reaches a county, this annual self-reported category data is all the public record offers for most of them."
        >
          {countiesDoc === "loading" && <p className="text-sm text-fog">Loading counties…</p>}
          {countiesDoc === "error" && <FetchError what="the county finance data" />}
          {countiesDoc && countiesDoc !== "loading" && countiesDoc !== "error" && (
            <>
              {countiesDoc.data.counties.slice(0, 15).map((c) => (
                <Row
                  key={c.county}
                  label={c.county}
                  sub={`${c.per_capita_usd ? `$${c.per_capita_usd.toLocaleString()}/resident · ` : ""}top: ${c.top_categories[0]?.category ?? "—"}`}
                  usd={c.total_usd ?? 0}
                  maxUsd={countiesDoc.data.counties[0]?.total_usd ?? 1}
                  color="#b98300"
                />
              ))}
              <p className="mt-2 text-xs text-fog">
                Showing 15 of {countiesDoc.data.county_count} counties (San Francisco files as a
                city) —{" "}
                <a
                  href="/data/county_finances.json"
                  className="underline underline-offset-2 hover:text-ink"
                >
                  all counties with category detail
                </a>
                .
              </p>
              <Terminator flag="category_only">
                Self-reported, category-level, posted as submitted. Vendor-level county
                checkbooks mostly don&apos;t exist —{" "}
                <a href="/gaps/#county-checkbooks" className="underline underline-offset-2">
                  the county checkbook gap
                </a>{" "}
                is one of the biggest fixable holes in California transparency.
              </Terminator>
            </>
          )}
        </LevelCard>
      )}

      {/* Level 6: recovered hop — BHCIP re-grants.
          Gated on the CURRENT vendor being the program administrator so a
          stale segment can never attribute BHCIP to the wrong vendor. */}
      {recoveredSeg?.program === "bhcip" &&
        vendorSeg &&
        RECOVERED_PROGRAMS[vendorSeg.name]?.program === "bhcip" &&
        bhcipDoc === "error" && <FetchError what="the BHCIP award data" />}
      {recoveredSeg?.program === "bhcip" &&
        vendorSeg &&
        RECOVERED_PROGRAMS[vendorSeg.name]?.program === "bhcip" &&
        bhcipDoc &&
        bhcipDoc !== "loading" &&
        bhcipDoc !== "error" && (
        <LevelCard
          step={6}
          title={`${bhcipDoc.data.project_count} BHCIP projects at ${bhcipDoc.data.entity_count} organizations`}
          subtitle="Where the re-granted money went — from the program's own reporting; the state's accounting system doesn't show this step."
        >
          <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-fog">
            {bhcipDoc.data.by_round.map((r) => (
              <span key={r.round}>
                {r.round.replace("BHCIP Round", "R").replace("Bond BHCIP R", "Bond R")}:{" "}
                <span className="font-mono">{r.project_count}</span>
              </span>
            ))}
          </div>
          {bhcipDoc.data.entities.slice(0, 20).map((e) => (
            <Row
              key={e.name}
              label={e.name}
              sub={(() => {
                const joined = e.projects.map((p) => p.project).join(" · ");
                return joined.length > 90 ? `${joined.slice(0, 89)}…` : joined;
              })()}
              usd={e.project_count}
              maxUsd={bhcipDoc.data.entities[0]?.project_count ?? 1}
              color="#1e7f4f"
              valueLabel={`${e.project_count} project${e.project_count > 1 ? "s" : ""}`}
            />
          ))}
          <p className="mt-2 text-xs text-fog">
            Showing 20 of {bhcipDoc.data.entity_count} organizations (bars = project count) —{" "}
            <a href="/data/bhcip_awards.json" className="underline underline-offset-2 hover:text-ink">
              full list
            </a>
            .
          </p>
          <Terminator flag="category_only">
            How much each project received is announced only in PDF documents — the names are
            public, but the dollar figures aren&apos;t published as usable data.
          </Terminator>
        </LevelCard>
      )}
    </div>
  );
}
