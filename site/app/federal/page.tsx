import { CoverageBadge } from "@/components/ui/SourceChip";
import { SourceChip } from "@/components/ui/SourceChip";
import { loadPublished } from "@/lib/published-server";
import { fmtUsd, type CoverageFlag } from "@/lib/published";

export const metadata = { title: "Federal dollars into California — CA Dollar Trace" };

interface FederalDoc {
  federal_fiscal_year: string;
  recipients: {
    name: string;
    amount_usd: number;
    uei: string | null;
    masked_aggregate: boolean;
    coverage_flag: CoverageFlag;
  }[];
  awarding_agencies: { name: string; amount_usd: number }[];
}

export default async function FederalPage() {
  const pub = await loadPublished<FederalDoc>("federal_ca");
  const d = pub.data;
  const masked = d.recipients.find((r) => r.masked_aggregate);
  const named = d.recipients.filter((r) => !r.masked_aggregate);

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">
        Federal dollars into California — by name
      </h1>
      <p className="mt-2 max-w-2xl text-fog">
        The &quot;Federal funds&quot; slices in the agency fund mixes come from somewhere: these
        are the actual recipients of federal awards performed in California in federal FY
        {d.federal_fiscal_year}. State agencies themselves top the list — this is the money that
        flows <em>through</em> the state budget you see on the waterfall.
      </p>

      {masked && (
        <div className="mt-6 max-w-2xl rounded-lg border border-dark-zone/30 p-4 [background-image:repeating-linear-gradient(45deg,transparent,transparent_6px,rgba(87,83,78,0.05)_6px,rgba(87,83,78,0.05)_12px)]">
          <div className="flex items-center gap-2 text-sm font-medium">
            {fmtUsd(masked.amount_usd)} to individuals <CoverageBadge flag="masked" />
          </div>
          <p className="mt-1 text-sm text-fog">
            The single largest line is payments aggregated across many individual people (direct
            benefits), masked for privacy by the federal government. We show it rather than
            pretending it isn&apos;t there.
          </p>
        </div>
      )}

      <div className="mt-8 grid gap-10 lg:grid-cols-[3fr_2fr]">
        <section>
          <h2 className="text-xl font-semibold">Top named recipients</h2>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[480px] text-sm">
              <thead>
                <tr className="border-b border-rule text-left text-fog">
                  <th className="py-2 pr-4 font-medium">Recipient</th>
                  <th className="py-2 pr-4 font-medium">UEI</th>
                  <th className="py-2 text-right font-medium">FY{d.federal_fiscal_year} obligations</th>
                </tr>
              </thead>
              <tbody>
                {named.slice(0, 40).map((r) => (
                  <tr key={`${r.name}-${r.uei}`} className="border-b border-rule/60">
                    <td className="py-2 pr-4">{r.name}</td>
                    <td className="py-2 pr-4 font-mono text-xs text-fog">{r.uei ?? "—"}</td>
                    <td className="py-2 text-right font-mono text-xs">{fmtUsd(r.amount_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-fog">
            Showing 40 of {named.length} recipients in the published data —{" "}
            <a href="/data/federal_ca.json" className="underline underline-offset-2 hover:text-ink">
              get the full dataset
            </a>
            .
          </p>
        </section>

        <section>
          <h2 className="text-xl font-semibold">Which federal agencies send it</h2>
          <ul className="mt-3 space-y-1.5">
            {d.awarding_agencies.slice(0, 12).map((a) => {
              const max = d.awarding_agencies[0].amount_usd;
              return (
                <li key={a.name} className="text-sm">
                  <div className="flex items-baseline justify-between gap-3">
                    <span>{a.name}</span>
                    <span className="shrink-0 font-mono text-xs">{fmtUsd(a.amount_usd)}</span>
                  </div>
                  <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-rule/40">
                    <div
                      className="h-full rounded-full bg-[#7c5cbf]"
                      style={{ width: `${(a.amount_usd / max) * 100}%` }}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      </div>

      <SourceChip
        source={pub.source}
        asOf={pub.as_of}
        cadence={pub.cadence}
        coverage={pub.coverage_flag}
        caveats={pub.caveats}
        dataHref="/data/federal_ca.json"
      />
    </div>
  );
}
