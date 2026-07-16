import Link from "next/link";
import { SourceChip } from "@/components/ui/SourceChip";
import { loadPublished } from "@/lib/published-server";
import { fmtUsd, type BudgetWaterfall } from "@/lib/published";

export const metadata = { title: "Explore agencies — CA Dollar Trace" };

export default async function ExplorePage() {
  const pub = await loadPublished<BudgetWaterfall>("budget_waterfall");
  const agencies = pub.data.agencies;

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">All twelve agency groups</h1>
      <p className="mt-2 max-w-2xl text-fog">
        {fmtUsd(pub.data.state_grand_total_usd)} in state funds for {pub.data.budget_year}; the
        all-funds figures below add federal money administered through the state. Open any agency
        to drill into departments, programs, and fund mixes.
      </p>

      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {agencies.map((a) => (
          <Link
            key={a.org_cd}
            href={`/agency/${a.org_cd}/`}
            className="rounded-lg border border-rule p-4 transition-colors hover:border-poppy/60 hover:bg-poppy/[0.03]"
          >
            <div className="text-sm font-medium">{a.title}</div>
            <div className="mt-2 flex items-baseline justify-between">
              <span className="font-mono text-lg">{fmtUsd(a.all_funds_usd)}</span>
              <span className="text-xs text-fog">all funds</span>
            </div>
            <div className="mt-1 flex items-baseline justify-between text-xs text-fog">
              <span className="font-mono">{fmtUsd(a.general_fund_usd)}</span>
              <span>General Fund</span>
            </div>
          </Link>
        ))}
      </div>

      <SourceChip
        source={pub.source}
        asOf={pub.as_of}
        cadence={pub.cadence}
        coverage={pub.coverage_flag}
        caveats={pub.caveats}
        dataHref="/data/budget_waterfall.json"
      />
    </div>
  );
}
