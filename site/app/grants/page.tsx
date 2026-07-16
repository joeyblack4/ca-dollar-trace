import { SourceChip } from "@/components/ui/SourceChip";
import { fmtUsd, type GrantsSummary } from "@/lib/published";
import { loadPublished } from "@/lib/published-server";

export const metadata = { title: "State Grants — CA Dollar Trace" };

export default async function GrantsPage() {
  const pub = await loadPublished<GrantsSummary>("grants_summary");
  const active = pub.data.totals_by_status.find((t) => t.status === "active");
  const topCategories = pub.data.open_by_category.slice(0, 12);

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">California state grants</h1>
      <p className="mt-2 max-w-2xl text-fog">
        Grant opportunities published by state agencies on the California Grants Portal.
        This is the first hop of the grant dollar: state agency → grant program. Awardee and
        subrecipient tracing land in later phases.
      </p>

      <div className="mt-8 grid gap-4 sm:grid-cols-3">
        <div className="rounded-lg border border-rule p-5">
          <div className="text-sm text-fog">Open grant programs</div>
          <div className="mt-1 text-3xl font-semibold">{active?.grant_count ?? "—"}</div>
        </div>
        <div className="rounded-lg border border-rule p-5">
          <div className="text-sm text-fog">Est. funds available (where reported)</div>
          <div className="mt-1 text-3xl font-semibold">
            {fmtUsd(active?.est_avail_funds_known_usd ?? null)}
          </div>
        </div>
        <div className="rounded-lg border border-category-only/40 bg-category-only/5 p-5">
          <div className="text-sm text-fog">Programs with unreported amounts</div>
          <div className="mt-1 text-3xl font-semibold text-category-only">
            {active?.funds_unknown_count ?? "—"}
          </div>
          <div className="mt-1 text-xs text-fog">Counted as unknown, not as $0.</div>
        </div>
      </div>

      <h2 className="mt-12 text-xl font-semibold">Open funding by category</h2>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr className="border-b border-rule text-left text-fog">
              <th className="py-2 pr-4 font-medium">Category</th>
              <th className="py-2 pr-4 text-right font-medium">Programs</th>
              <th className="py-2 pr-4 text-right font-medium">Est. available</th>
              <th className="py-2 text-right font-medium">Amount unknown</th>
            </tr>
          </thead>
          <tbody>
            {topCategories.map((row) => (
              <tr key={row.category} className="border-b border-rule/60">
                <td className="py-2 pr-4">{row.category}</td>
                <td className="py-2 pr-4 text-right font-mono text-xs">{row.grant_count}</td>
                <td className="py-2 pr-4 text-right font-mono text-xs">
                  {fmtUsd(row.est_avail_funds_known_usd)}
                </td>
                <td className="py-2 text-right font-mono text-xs">
                  {row.funds_unknown_count > 0 ? row.funds_unknown_count : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <SourceChip
        source={pub.source}
        asOf={pub.as_of}
        cadence={pub.cadence}
        coverage={pub.coverage_flag}
        caveats={pub.caveats}
        dataHref="/data/grants_summary.json"
      />
    </div>
  );
}
