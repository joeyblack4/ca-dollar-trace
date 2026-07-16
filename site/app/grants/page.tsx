import { SourceChip } from "@/components/ui/SourceChip";
import { fmtUsd, type GrantsSummary } from "@/lib/published";
import { loadPublished } from "@/lib/published-server";

export const metadata = { title: "State Grants — CA Dollar Trace" };

interface AwardsDoc {
  by_fiscal_year: {
    fiscal_year: string;
    award_count: number;
    awarded_known_usd: number | null;
    amount_unknown_count: number;
    with_subrecipients_usd: number | null;
    with_subrecipients_count: number;
  }[];
  top_recipients: {
    recipient_name: string;
    recipient_type: string;
    award_count: number;
    awarded_usd: number | null;
    any_subrecipients: boolean;
  }[];
}

export default async function GrantsPage() {
  const pub = await loadPublished<GrantsSummary>("grants_summary");
  const awards = await loadPublished<AwardsDoc>("grants_awards");
  const active = pub.data.totals_by_status.find((t) => t.status === "active");
  // sort by known funds — the file is not guaranteed sorted
  const allCategories = [...pub.data.open_by_category].sort(
    (a, b) => (b.est_avail_funds_known_usd ?? 0) - (a.est_avail_funds_known_usd ?? 0)
  );
  const topCategories = allCategories.slice(0, 12);

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
      <p className="mt-1 text-xs text-fog">
        Top 12 of {allCategories.length} categories by known available funds —{" "}
        <a href="/data/grants_summary.json" className="underline underline-offset-2 hover:text-ink">
          full data
        </a>
        .
      </p>
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

      <section className="mt-14">
        <h2 className="text-xl font-semibold">Actual awards: who received grant money</h2>
        <p className="mt-2 max-w-2xl text-sm text-fog">
          Post-award data (AB 132, grants closing July 2022 onward). The last column is the
          honest one: dollars where the recipient told the state subrecipients exist — but the
          portal never collects who they are. That money has a known, unnamed next hop.
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          {awards.data.by_fiscal_year.map((fy) => (
            <div key={fy.fiscal_year} className="rounded-lg border border-rule p-4">
              <div className="text-sm text-fog">FY {fy.fiscal_year}</div>
              <div className="mt-1 text-2xl font-semibold">
                {fmtUsd(fy.awarded_known_usd)}
              </div>
              <div className="text-xs text-fog">
                {fy.award_count.toLocaleString()} awards
                {fy.amount_unknown_count > 0 && ` · ${fy.amount_unknown_count} amounts unknown`}
              </div>
              <div className="mt-2 border-t border-rule pt-2 text-xs">
                <span className="font-medium text-category-only">
                  {fmtUsd(fy.with_subrecipients_usd)}
                </span>{" "}
                <span className="text-fog">
                  ({fy.with_subrecipients_count.toLocaleString()} awards) flagged “has
                  subrecipients” — identities not collected
                </span>
              </div>
            </div>
          ))}
        </div>

        <h3 className="mt-8 text-lg font-semibold">Top grant recipients (3 fiscal years)</h3>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b border-rule text-left text-fog">
                <th className="py-2 pr-4 font-medium">Recipient</th>
                <th className="py-2 pr-4 font-medium">Type</th>
                <th className="py-2 pr-4 text-right font-medium">Awards</th>
                <th className="py-2 pr-4 text-right font-medium">Total</th>
                <th className="py-2 text-right font-medium">Subrecipients?</th>
              </tr>
            </thead>
            <tbody>
              {awards.data.top_recipients.slice(0, 20).map((r) => (
                <tr key={r.recipient_name} className="border-b border-rule/60">
                  <td className="py-2 pr-4">{r.recipient_name}</td>
                  <td className="py-2 pr-4 text-xs text-fog">{r.recipient_type}</td>
                  <td className="py-2 pr-4 text-right font-mono text-xs">{r.award_count}</td>
                  <td className="py-2 pr-4 text-right font-mono text-xs">
                    {fmtUsd(r.awarded_usd)}
                  </td>
                  <td className="py-2 text-right text-xs">
                    {r.any_subrecipients ? (
                      <span className="text-category-only">yes — unnamed</span>
                    ) : (
                      <span className="text-fog">no</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <SourceChip
          source={awards.source}
          asOf={awards.as_of}
          cadence={awards.cadence}
          coverage={awards.coverage_flag}
          caveats={awards.caveats}
          dataHref="/data/grants_awards.json"
        />
      </section>
    </div>
  );
}
