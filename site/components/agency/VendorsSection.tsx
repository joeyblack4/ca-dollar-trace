/* The checkbook layer: named vendors per department (Open FI$Cal), with the
   coverage percentage — how much of the department's enacted budget actually
   appears as vendor payments — computed, not asserted. Confidential-vendor
   dollars are shown as their own labeled quantity. */

import { CoverageBadge } from "@/components/ui/SourceChip";
import { fmtUsd } from "@/lib/published";

export interface VendorDept {
  org_cd: string;
  title: string;
  fiscal_year: string;
  transactions: number;
  vendor_count: number;
  vendor_total_usd: number;
  confidential_usd: number;
  public_sector_usd: number;
  enacted_budget_usd: number | null;
  checkbook_coverage_pct: number | null;
  top_vendors: { name: string; usd: number; masked: boolean; public_sector: boolean }[];
}

export function PublicSectorChip() {
  return (
    <span className="rounded-full border border-[#2a78d6]/40 bg-[#2a78d6]/10 px-2 py-0.5 text-xs text-[#1c5cab]">
      public agency
    </span>
  );
}

export function VendorsSection({ departments }: { departments: VendorDept[] }) {
  const fy = departments[0]?.fiscal_year;
  return (
    <section className="mt-10">
      <h2 className="text-xl font-semibold">
        The checkbook: who actually got paid ({fy})
      </h2>
      <p className="mt-1 max-w-2xl text-sm text-fog">
        Actual vendor payments from the state&apos;s accounting system (modified accrual, ~60-day
        lag; year in progress). The coverage bar is the honest part: payroll and bulk benefit
        payments never appear here, so for some departments most of the budget is simply not in
        the checkbook.
      </p>

      <div className="mt-4 space-y-3">
        {departments.map((d) => {
          const pct = d.checkbook_coverage_pct;
          return (
            <details key={d.org_cd} className="rounded-lg border border-rule">
              <summary className="cursor-pointer list-none p-4 [&::-webkit-details-marker]:hidden">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-sm font-medium">{d.title}</span>
                  <span className="font-mono text-sm">{fmtUsd(d.vendor_total_usd)} to {d.vendor_count.toLocaleString()} vendors</span>
                </div>
                {pct !== null && (
                  <div className="mt-2 max-w-xl">
                    <div className="flex h-2.5 overflow-hidden rounded-full bg-dark-zone/15 [background-image:repeating-linear-gradient(45deg,transparent,transparent_4px,rgba(87,83,78,0.15)_4px,rgba(87,83,78,0.15)_8px)]">
                      <div
                        className="h-full rounded-l-full bg-traceable"
                        style={{ width: `${Math.min(100, pct)}%` }}
                      />
                    </div>
                    <div className="mt-1 text-xs text-fog">
                      {pct}% of the {fmtUsd(d.enacted_budget_usd)} enacted budget appears as
                      vendor payments{" "}
                      {d.confidential_usd > 0 && (
                        <>
                          · {fmtUsd(d.confidential_usd)} of it paid to{" "}
                          <span className="text-dark-zone">&quot;Confidential&quot;</span> vendors
                        </>
                      )}
                    </div>
                  </div>
                )}
              </summary>
              <div className="border-t border-rule/60 p-4">
                <table className="w-full max-w-2xl text-sm">
                  <thead>
                    <tr className="text-left text-xs text-fog">
                      <th className="py-1 pr-4 font-medium">Top vendors</th>
                      <th className="py-1 text-right font-medium">Paid ({fy} to date)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.top_vendors.slice(0, 10).map((v) => (
                      <tr key={v.name} className="border-t border-rule/40">
                        <td className="py-1.5 pr-4">
                          {v.name}
                          {v.masked && (
                            <span className="ml-2 align-middle">
                              <CoverageBadge flag="masked" />
                            </span>
                          )}
                          {v.public_sector && (
                            <span className="ml-2 align-middle">
                              <PublicSectorChip />
                            </span>
                          )}
                        </td>
                        <td className="py-1.5 text-right font-mono text-xs">{fmtUsd(v.usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}
