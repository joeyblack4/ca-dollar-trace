"use client";

/* The taxpayer receipt: enter the CA income tax you actually paid (Form 540,
   "total tax") and see it split in the same proportions as General Fund
   spending. Flat effective-proportion apportionment — the HMRC/federal-receipt
   method — with its limitation disclosed. No tax is calculated or estimated. */

import { useState } from "react";
import { fmtUsd, type BudgetWaterfall } from "@/lib/published";

export function ReceiptCalculator({ data }: { data: BudgetWaterfall }) {
  const [tax, setTax] = useState<number>(5000);
  const gf = data.general_fund;

  const rows = gf.expenditure.map((e) => ({
    name: e.name,
    share: e.usd / gf.expenditure_total_usd,
    yours: (tax * e.usd) / gf.expenditure_total_usd,
  }));

  return (
    <div className="mt-6 max-w-2xl">
      <label className="block text-sm font-medium" htmlFor="tax">
        California income tax you paid (Form 540, total tax)
      </label>
      <div className="mt-1.5 flex items-center gap-3">
        <span className="text-lg text-fog">$</span>
        <input
          id="tax"
          type="number"
          min={0}
          step={100}
          value={Number.isFinite(tax) ? tax : ""}
          onChange={(e) => setTax(Math.max(0, Number(e.target.value)))}
          className="w-40 rounded-md border border-rule bg-white px-3 py-2 font-mono text-lg focus:border-poppy focus:outline-none"
        />
        <input
          type="range"
          min={0}
          max={50000}
          step={100}
          value={Math.min(tax, 50000)}
          onChange={(e) => setTax(Number(e.target.value))}
          className="flex-1 accent-poppy"
          aria-label="Tax amount slider"
        />
      </div>

      <div className="mt-6 rounded-lg border border-rule">
        <div className="border-b border-rule px-4 py-3">
          <span className="text-sm text-fog">Your {fmtUsd(tax)} split like the General Fund:</span>
        </div>
        <ul>
          {rows.map((r) => (
            <li key={r.name} className="flex items-center gap-3 border-b border-rule/50 px-4 py-2.5 last:border-0">
              <div className="w-44 shrink-0 text-sm sm:w-56">{r.name}</div>
              <div className="h-3 flex-1 overflow-hidden rounded-full bg-rule/40">
                <div
                  className="h-full rounded-full bg-poppy"
                  style={{ width: `${r.share * 100}%` }}
                />
              </div>
              <div className="w-20 shrink-0 text-right font-mono text-sm">
                {r.yours.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 })}
              </div>
              <div className="w-12 shrink-0 text-right font-mono text-xs text-fog">
                {(r.share * 100).toFixed(0)}¢/$
              </div>
            </li>
          ))}
        </ul>
      </div>

      <p className="mt-4 text-xs text-fog">
        Method: your amount × each area&apos;s share of {fmtUsd(gf.expenditure_total_usd)} in
        enacted General Fund spending. This is the same flat-proportion method as the UK HMRC tax
        summary and the 2011 federal taxpayer receipt: percentages are identical for everyone;
        only the dollars scale. It does not model earmarks tied to specific revenue streams
        (Prop 98 minimums, Prop 63 mental-health surcharge), special funds, or federal funds —
        and your sales, property, and payroll taxes are not included. For information only; not a
        tax calculation.
      </p>
    </div>
  );
}
