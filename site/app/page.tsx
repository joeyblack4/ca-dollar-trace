import Link from "next/link";
import { ExplorerShell } from "@/components/drill/ExplorerShell";
import { SourceChip } from "@/components/ui/SourceChip";
import { fmtAsOf, fmtUsd, type BudgetWaterfall } from "@/lib/published";
import { loadPublished } from "@/lib/published-server";

export default async function Home() {
  const pub = await loadPublished<BudgetWaterfall>("budget_waterfall");
  const wf = pub.data;

  return (
    <div>
      <h1 className="max-w-3xl text-4xl font-semibold tracking-tight">
        Follow your California tax dollar —{" "}
        <span className="text-poppy">and see where the trail goes dark.</span>
      </h1>
      <p className="mt-4 max-w-2xl text-fog">
        Below is the {wf.budget_year} enacted General Fund, drawn from the Department of
        Finance&apos;s own published figures. Click any block to trace that money one hop
        further — every step is labeled <em>traceable</em>, <em>category-level only</em>, or{" "}
        <em>trail ends here</em>, because honesty about the gaps is the point.
      </p>

      <div className="mt-8">
        <ExplorerShell waterfall={wf} asOfLabel={`retrieved ${fmtAsOf(pub.as_of)}`} />
      </div>

      <SourceChip
        source={pub.source}
        asOf={pub.as_of}
        cadence={pub.cadence}
        coverage={pub.coverage_flag}
        caveats={pub.caveats}
        dataHref="/data/budget_waterfall.json"
      />

      <section className="mt-14">
        <h2 className="text-xl font-semibold">
          The whole budget: {fmtUsd(wf.state_grand_total_usd)} in state funds
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-fog">
          The General Fund above is the discretionary core. Each agency also spends special
          funds, bond funds, and federal money passing through the state. All-funds totals
          below include that federal passthrough.
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-rule text-left text-fog">
                <th className="py-2 pr-4 font-medium">Agency</th>
                <th className="py-2 pr-4 text-right font-medium">General Fund</th>
                <th className="py-2 pr-4 text-right font-medium">Special funds</th>
                <th className="py-2 pr-4 text-right font-medium">Bond funds</th>
                <th className="py-2 pr-4 text-right font-medium">State funds</th>
                <th className="py-2 pr-4 text-right font-medium">All funds*</th>
                <th className="py-2 text-right font-medium">Positions</th>
              </tr>
            </thead>
            <tbody>
              {wf.agencies.map((a) => (
                <tr key={a.org_cd} className="border-b border-rule/60">
                  <td className="py-2 pr-4">{a.title}</td>
                  <td className="py-2 pr-4 text-right font-mono text-xs">
                    {fmtUsd(a.general_fund_usd)}
                  </td>
                  <td className="py-2 pr-4 text-right font-mono text-xs">
                    {fmtUsd(a.special_fund_usd)}
                  </td>
                  <td className="py-2 pr-4 text-right font-mono text-xs">
                    {fmtUsd(a.bond_fund_usd)}
                  </td>
                  <td className="py-2 pr-4 text-right font-mono text-xs">
                    {fmtUsd(a.state_funds_usd)}
                  </td>
                  <td className="py-2 pr-4 text-right font-mono text-xs">
                    {fmtUsd(a.all_funds_usd)}
                  </td>
                  <td className="py-2 text-right font-mono text-xs">
                    {Math.round(a.positions).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-fog">
          *All funds includes federal funds and reimbursements — money that moves through the
          state budget but isn&apos;t raised by state taxes.
        </p>
      </section>

      <section className="mt-14 grid gap-4 sm:grid-cols-3 text-sm">
        <div className="rounded-lg border border-rule p-4">
          <div className="font-medium">Cited, always</div>
          <p className="mt-1 text-fog">
            Every figure carries its source, publish date, and a one-click link to the raw
            data.
          </p>
        </div>
        <div className="rounded-lg border border-rule p-4">
          <div className="font-medium">Honest about gaps</div>
          <p className="mt-1 text-fog">
            Unknown amounts are labeled unknown — never silently counted as zero.
          </p>
        </div>
        <div className="rounded-lg border border-rule p-4">
          <div className="font-medium">Live sources</div>
          <p className="mt-1 text-fog">
            <Link href="/grants/" className="underline underline-offset-2 hover:text-ink">
              Grant programs
            </Link>{" "}
            refresh daily from the state&apos;s own feeds; more sources are on the way.
          </p>
        </div>
      </section>
    </div>
  );
}
