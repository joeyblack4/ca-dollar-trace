import { SourceChip } from "@/components/ui/SourceChip";
import { loadPublished } from "@/lib/published-server";
import { fmtUsd } from "@/lib/published";

export const metadata = { title: "Counties, cities & districts — CA Dollar Trace" };

interface LocalDoc {
  county_count: number;
  entities_published: number;
  entities_not_shown: number;
  entities_not_shown_total_usd: number;
  latest_fiscal_year: number;
  total_latest_usd: number;
  counties: {
    county: string;
    fiscal_year: number;
    total_usd: number | null;
    per_capita_usd: number | null;
    top_categories: { category: string; usd: number }[];
  }[];
}

interface CheckbooksDoc {
  los_angeles: {
    fiscal_year: string;
    total_usd: number;
    transaction_count: number;
    top_vendors: { name: string; usd: number }[];
  };
  san_francisco: {
    total_usd: number;
    contract_count: number;
    top_vendors: { name: string; usd: number }[];
  };
}

function EntityTable({
  rows,
  label,
  payroll,
}: {
  rows: LocalDoc["counties"];
  label: string;
  payroll?: Record<string, { wages_usd: number; benefits_usd: number }>;
}) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full min-w-[620px] text-sm">
        <thead>
          <tr className="border-b border-rule text-left text-fog">
            <th className="py-2 pr-4 font-medium">{label}</th>
            <th className="py-2 pr-4 text-right font-medium">Reported spending</th>
            {payroll && <th className="py-2 pr-4 text-right font-medium">of which payroll</th>}
            <th className="py-2 pr-4 text-right font-medium">Per resident</th>
            <th className="py-2 font-medium">Biggest area</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const p = payroll?.[c.county.toUpperCase()];
            return (
              <tr key={c.county} className="border-b border-rule/60">
                <td className="py-2 pr-4">{c.county}</td>
                <td className="py-2 pr-4 text-right font-mono text-xs">{fmtUsd(c.total_usd)}</td>
                {payroll && (
                  <td className="py-2 pr-4 text-right font-mono text-xs">
                    {p ? fmtUsd(p.wages_usd + p.benefits_usd) : "—"}
                  </td>
                )}
                <td className="py-2 pr-4 text-right font-mono text-xs">
                  {c.per_capita_usd ? `$${c.per_capita_usd.toLocaleString()}` : "—"}
                </td>
                <td className="py-2 text-xs text-fog">{c.top_categories[0]?.category ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface CompDoc {
  year: number;
  statewide_wages_usd: number;
  statewide_benefits_usd: number;
  levels: Record<
    string,
    {
      positions: number;
      wages_usd: number;
      benefits_usd: number;
      top_employers: { employer: string; positions: number; wages_usd: number; benefits_usd: number }[];
    }
  >;
  by_employer: Record<string, { wages_usd: number; benefits_usd: number; positions: number }>;
}

interface PensionDoc {
  fiscal_year: string;
  agency_count: number;
  total_liabilities_usd: number;
  total_assets_usd: number;
  total_unfunded_usd: number;
  by_kind: Record<string, number>;
  agencies: Record<
    string,
    {
      name: string;
      kind: string;
      liabilities_usd: number;
      assets_usd: number;
      unfunded_usd: number;
      funded_pct: number | null;
    }
  >;
}

export default async function LocalPage() {
  const counties = await loadPublished<LocalDoc>("county_finances");
  const cities = await loadPublished<LocalDoc>("city_finances");
  const districts = await loadPublished<LocalDoc>("district_finances");
  const books = await loadPublished<CheckbooksDoc>("city_checkbooks");
  const comp = await loadPublished<CompDoc>("compensation");
  const pensions = await loadPublished<PensionDoc>("pension_positions");
  const topUnfunded = Object.values(pensions.data.agencies)
    .sort((a, b) => b.unfunded_usd - a.unfunded_usd)
    .slice(0, 12);

  const sections = [
    {
      title: `${counties.data.county_count} counties — ${fmtUsd(counties.data.total_latest_usd)}`,
      sub: "Where realignment and social-services money lands. San Francisco files as a city.",
      doc: counties,
      label: "County",
      rows: counties.data.counties.slice(0, 12),
      showing: `Showing 12 of ${counties.data.county_count}`,
    },
    {
      title: `${cities.data.county_count} cities — ${fmtUsd(cities.data.total_latest_usd)}`,
      sub: `Detail for the ${cities.data.entities_published} largest; the other ${cities.data.entities_not_shown} cities (${fmtUsd(cities.data.entities_not_shown_total_usd)}) are in the raw data.`,
      doc: cities,
      label: "City",
      rows: cities.data.counties.slice(0, 12),
      showing: `Showing 12 of ${cities.data.county_count}`,
    },
    {
      title: `${districts.data.county_count.toLocaleString()} special districts — ${fmtUsd(districts.data.total_latest_usd)}`,
      sub: "Water, transit, hospital, and insurance-pool districts — the layer of government residents know least.",
      doc: districts,
      label: "District",
      rows: districts.data.counties.slice(0, 12),
      showing: `Showing 12 of ${districts.data.county_count.toLocaleString()}`,
    },
  ];

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">
        Beyond the state: counties, cities & special districts
      </h1>
      <p className="mt-2 max-w-2xl text-fog">
        Every local government files an annual financial report with the State Controller —
        self-reported, category-level, posted as submitted. For most of them, this is the whole
        public record of their spending.
      </p>

      <section className="mt-8 rounded-lg border border-rule p-5">
        <h2 className="text-xl font-semibold">
          The part the checkbooks leave out: payroll
        </h2>
        <p className="mt-1 max-w-2xl text-sm text-fog">
          Vendor checkbooks never include salaries — yet payroll is often half of what a
          government spends. Reported to the State Controller for {comp.data.year}: state, county,
          and city employees together.
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          {(["state", "county", "city"] as const).map((lv) => {
            const x = comp.data.levels[lv];
            if (!x) return null;
            return (
              <div key={lv} className="rounded-lg border border-rule p-4">
                <div className="text-sm capitalize text-fog">{lv} payroll</div>
                <div className="mt-1 text-2xl font-semibold">
                  {fmtUsd(x.wages_usd + x.benefits_usd)}
                </div>
                <div className="text-xs text-fog">
                  {fmtUsd(x.wages_usd)} wages + {fmtUsd(x.benefits_usd)} benefits ·{" "}
                  {x.positions.toLocaleString()} positions
                </div>
              </div>
            );
          })}
        </div>
        <SourceChip
          source={comp.source}
          asOf={comp.as_of}
          cadence={comp.cadence}
          coverage={comp.coverage_flag}
          caveats={comp.caveats}
          dataHref="/data/compensation.json"
        />
      </section>

      <section className="mt-8 rounded-lg border border-rule p-5">
        <h2 className="text-xl font-semibold">Tomorrow&apos;s spending: pension debt</h2>
        <p className="mt-1 max-w-2xl text-sm text-fog">
          {pensions.data.agency_count} local governments in CalPERS with their own plans have
          promised {fmtUsd(pensions.data.total_liabilities_usd)} in pensions and set aside{" "}
          {fmtUsd(pensions.data.total_assets_usd)} — an unfunded gap of{" "}
          <strong className="text-ink">{fmtUsd(pensions.data.total_unfunded_usd)}</strong> (FY
          {pensions.data.fiscal_year} valuations) that future budgets must pay down.
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b border-rule text-left text-fog">
                <th className="py-2 pr-4 font-medium">Government</th>
                <th className="py-2 pr-4 text-right font-medium">Unfunded</th>
                <th className="py-2 text-right font-medium">Funded</th>
              </tr>
            </thead>
            <tbody>
              {topUnfunded.map((a) => (
                <tr key={`${a.kind}-${a.name}`} className="border-b border-rule/60">
                  <td className="py-2 pr-4">
                    {a.name} <span className="text-xs text-fog">({a.kind})</span>
                  </td>
                  <td className="py-2 pr-4 text-right font-mono text-xs">
                    {fmtUsd(a.unfunded_usd)}
                  </td>
                  <td className="py-2 text-right font-mono text-xs">
                    {a.funded_pct != null ? `${a.funded_pct}%` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 max-w-2xl text-xs text-fog">
          CalPERS only: Los Angeles (city and county), San Francisco, and about 20 county
          systems run their own retirement funds and aren&apos;t in this data — their absence
          here is a data boundary, not a clean bill of health.
        </p>
        <SourceChip
          source={pensions.source}
          asOf={pensions.as_of}
          cadence={pensions.cadence}
          coverage={pensions.coverage_flag}
          caveats={pensions.caveats}
          dataHref="/data/pension_positions.json"
        />
      </section>

      {sections.map((s) => (
        <section key={s.title} className="mt-10">
          <h2 className="text-xl font-semibold">{s.title}</h2>
          <p className="mt-1 max-w-2xl text-sm text-fog">{s.sub}</p>
          <EntityTable
            rows={s.rows}
            label={s.label}
            payroll={
              s.label === "County" || s.label === "City" ? comp.data.by_employer : undefined
            }
          />
          <p className="mt-1 text-xs text-fog">{s.showing} by spending.</p>
          <SourceChip
            source={s.doc.source}
            asOf={s.doc.as_of}
            cadence={s.doc.cadence}
            coverage={s.doc.coverage_flag}
            caveats={s.doc.caveats}
            dataHref={`/data/${s.title.includes("counties") ? "county" : s.title.includes("cities") ? "city" : "district"}_finances.json`}
          />
        </section>
      ))}

      <section className="mt-12 rounded-lg border border-traceable/30 bg-traceable/[0.04] p-5">
        <h2 className="text-xl font-semibold">
          The two that show their checkbooks
        </h2>
        <p className="mt-1 max-w-2xl text-sm text-fog">
          Los Angeles and San Francisco publish actual vendor-level payment data — proof that
          every county and city could. Nobody else does.
        </p>
        <div className="mt-4 grid gap-6 sm:grid-cols-2">
          <div>
            <h3 className="font-medium">
              Los Angeles — {fmtUsd(books.data.los_angeles.total_usd)} (FY
              {books.data.los_angeles.fiscal_year})
            </h3>
            <p className="text-xs text-fog">
              {books.data.los_angeles.transaction_count.toLocaleString()} payment transactions
            </p>
            <ul className="mt-2 space-y-1 text-sm">
              {books.data.los_angeles.top_vendors.slice(0, 6).map((v) => (
                <li key={v.name} className="flex justify-between gap-3">
                  <span className="truncate">{v.name}</span>
                  <span className="shrink-0 font-mono text-xs">{fmtUsd(v.usd)}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="font-medium">
              San Francisco — {fmtUsd(books.data.san_francisco.total_usd)} on contracts to date
            </h3>
            <p className="text-xs text-fog">
              {books.data.san_francisco.contract_count.toLocaleString()} contracts (a different
              measure than LA&apos;s — not comparable)
            </p>
            <ul className="mt-2 space-y-1 text-sm">
              {books.data.san_francisco.top_vendors.slice(0, 6).map((v) => (
                <li key={v.name} className="flex justify-between gap-3">
                  <span className="truncate">{v.name}</span>
                  <span className="shrink-0 font-mono text-xs">{fmtUsd(v.usd)}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <SourceChip
          source={books.source}
          asOf={books.as_of}
          cadence={books.cadence}
          coverage={books.coverage_flag}
          caveats={books.caveats}
          dataHref="/data/city_checkbooks.json"
        />
      </section>
    </div>
  );
}
