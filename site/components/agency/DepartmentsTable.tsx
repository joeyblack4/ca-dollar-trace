"use client";

/* Expandable departments table: click a department row to unfold its program
   lines and fund-class split. Integrity flags from the pipeline render as
   visible badges — a mismatch is shown, never hidden. */

import { useState } from "react";
import { cn } from "@/lib/cn";
import { fmtUsd } from "@/lib/published";
import type { DepartmentDetail } from "@/lib/agency";

const FUND_COLORS: Record<string, string> = {
  "General Fund": "#1a1916",
  "Special funds": "#2a78d6",
  "Federal funds": "#7c5cbf",
  "Bond funds": "#1baf7a",
  "Other funds": "#8a8781",
};

export function DepartmentsTable({ departments }: { departments: DepartmentDetail[] }) {
  const [open, setOpen] = useState<string | null>(departments[0]?.org_cd ?? null);

  return (
    <div className="mt-4">
      <div className="hidden border-b border-rule pb-2 text-left text-sm text-fog sm:grid sm:grid-cols-[1fr_120px_120px_90px]">
        <span className="font-medium">Department</span>
        <span className="text-right font-medium">Total</span>
        <span className="text-right font-medium">General Fund</span>
        <span className="text-right font-medium">Detail</span>
      </div>
      {departments.map((d) => {
        const isOpen = open === d.org_cd;
        const flagged = d.integrity.matches_department_total === false;
        return (
          <div key={d.org_cd} className="border-b border-rule/60">
            <button
              onClick={() => setOpen(isOpen ? null : d.org_cd)}
              className="grid w-full grid-cols-[1fr_100px] items-center gap-y-1 py-2.5 text-left text-sm hover:bg-rule/20 sm:grid-cols-[1fr_120px_120px_90px]"
            >
              <span>
                {d.title}
                {flagged && (
                  <span className="ml-2 rounded-full border border-category-only/40 bg-category-only/10 px-2 py-0.5 text-xs text-category-only">
                    lines ≠ total
                  </span>
                )}
                {d.integrity.no_program_detail_published && (
                  <span className="ml-2 rounded-full border border-dark-zone/30 bg-dark-zone/10 px-2 py-0.5 text-xs text-dark-zone">
                    no program detail published
                  </span>
                )}
              </span>
              <span className="text-right font-mono text-xs">{fmtUsd(d.total_usd)}</span>
              <span className="hidden text-right font-mono text-xs sm:block">
                {fmtUsd(d.general_fund_usd)}
              </span>
              <span className="hidden text-right text-xs text-fog sm:block">
                {isOpen ? "▾ close" : "▸ open"}
              </span>
            </button>

            {isOpen && (
              <div className="pb-4 pl-2 sm:pl-4">
                {Object.keys(d.funds_by_class).length > 0 && (
                  <div className="max-w-2xl">
                    <div className="flex h-3 overflow-hidden rounded-full">
                      {Object.entries(d.funds_by_class).map(([label, usd]) => (
                        <div
                          key={label}
                          title={`${label}: ${fmtUsd(usd)}`}
                          style={{
                            width: `${(usd / Math.max(1, Object.values(d.funds_by_class).reduce((a, b) => a + b, 0))) * 100}%`,
                            background: FUND_COLORS[label] ?? "#8a8781",
                          }}
                        />
                      ))}
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-fog">
                      {Object.entries(d.funds_by_class).map(([label, usd]) => (
                        <span key={label} className="flex items-center gap-1.5">
                          <span
                            className="inline-block h-2.5 w-2.5 rounded-sm"
                            style={{ background: FUND_COLORS[label] ?? "#8a8781" }}
                          />
                          {label} {fmtUsd(usd)}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {d.programs.length > 0 && (
                  <table className="mt-3 w-full max-w-2xl text-sm">
                    <thead>
                      <tr className="text-left text-xs text-fog">
                        <th className="py-1 pr-4 font-medium">Program</th>
                        <th className="py-1 pr-4 text-right font-medium">Enacted</th>
                        <th className="py-1 text-right font-medium">Share</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.programs.map((p) => (
                        <tr key={`${p.program_code}-${p.title}`} className="border-t border-rule/40">
                          <td className="py-1.5 pr-4">
                            <span className="font-mono text-xs text-fog">{p.program_code}</span>{" "}
                            {p.title}
                          </td>
                          <td className="py-1.5 pr-4 text-right font-mono text-xs">
                            {fmtUsd(p.usd)}
                          </td>
                          <td
                            className={cn(
                              "py-1.5 text-right font-mono text-xs",
                              d.total_usd === 0 && "text-fog"
                            )}
                          >
                            {d.total_usd > 0 ? `${((p.usd / d.total_usd) * 100).toFixed(1)}%` : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
