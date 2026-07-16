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
  // ALL masked aggregates (privacy-masked individuals, PII redactions) —
  // every one is shown; none may silently vanish
  const masked = d.recipients.filter((r) => r.masked_aggregate);
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

      {masked.length > 0 && (
        <div className="mt-6 max-w-2xl rounded-lg border border-dark-zone/30 p-4 [background-image:repeating-linear-gradient(45deg,transparent,transparent_6px,rgba(87,83,78,0.05)_6px,rgba(87,83,78,0.05)_12px)]">
          <div className="flex items-center gap-2 text-sm font-medium">
            {fmtUsd(masked.reduce((s, m) => s + m.amount_usd, 0))} masked{" "}
            <CoverageBadge flag="masked" />
          </div>
          <ul className="mt-1 space-y-1 text-sm text-fog">
            {masked.map((m) => (
              <li key={m.name}>
                <span className="font-mono text-xs">{fmtUsd(m.amount_usd)}</span> — {m.name}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-sm text-fog">
            Payments aggregated across many individual people (direct benefits) or redacted for
            privacy by the federal government. We show every masked line rather than pretending
            it isn&apos;t there.
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
          <p className="mt-1 text-xs text-fog">
            Top 12 of {d.awarding_agencies.length} in the published data.
          </p>
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

      <section className="mt-14">
        <h2 className="text-xl font-semibold">Hand-offs: who passes federal money to whom</h2>
        <p className="mt-2 max-w-2xl text-sm text-fog">
          When a state agency receives federal money and hands it onward — to a county, a school
          district, a nonprofit — that hand-off is reported here. These are the largest reported
          ones; reporting below $30,000 isn&apos;t required and compliance is incomplete.
        </p>
        <SubawardsSection />
      </section>

      <section className="mt-14">
        <h2 className="text-xl font-semibold">
          Audited: every California organization spending $1M+ in federal money
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-fog">
          Federal law requires an independent single audit of any organization spending over the
          threshold in federal awards — including money that arrived through the state. This is
          the deepest systematic view of federal dollars inside California.
        </p>
        <FacSection />
      </section>
    </div>
  );
}

async function SubawardsSection() {
  const sub = await loadPublished<{
    federal_fiscal_year: string;
    largest_edges: { prime: string; sub: string; usd: number; kind: string; federal_agency: string }[];
    by_prime_recipient: { prime: string; total_usd: number; sub_count: number }[];
  }>("federal_subawards");
  const d = sub.data;
  return (
    <>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr className="border-b border-rule text-left text-fog">
              <th className="py-2 pr-4 font-medium">From</th>
              <th className="py-2 pr-4 font-medium">To</th>
              <th className="py-2 pr-4 text-right font-medium">Amount</th>
              <th className="py-2 font-medium">Federal source</th>
            </tr>
          </thead>
          <tbody>
            {d.largest_edges.slice(0, 12).map((e, i) => (
              <tr key={i} className="border-b border-rule/60">
                <td className="py-2 pr-4">{e.prime}</td>
                <td className="py-2 pr-4">{e.sub}</td>
                <td className="py-2 pr-4 text-right font-mono text-xs">{fmtUsd(e.usd)}</td>
                <td className="py-2 text-xs text-fog">{e.federal_agency}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-xs text-fog">
        Largest 12 of the {d.largest_edges.length}+ biggest reported hand-offs (FY
        {d.federal_fiscal_year}) —{" "}
        <a href="/data/federal_subawards.json" className="underline underline-offset-2 hover:text-ink">
          full data
        </a>
        .
      </p>
      <SourceChip
        source={sub.source}
        asOf={sub.as_of}
        cadence={sub.cadence}
        coverage={sub.coverage_flag}
        caveats={sub.caveats}
        dataHref="/data/federal_subawards.json"
      />
    </>
  );
}

async function FacSection() {
  const fac = await loadPublished<{
    audit_year: number;
    in_progress_note: string | null;
    entity_count: number;
    total_federal_expended_usd: number;
    by_entity_type: { entity_type: string; count: number; usd: number }[];
    top_auditees: {
      name: string;
      entity_type: string | null;
      federal_expended_usd: number;
      report_id: string;
    }[];
  }>("federal_audits");
  const d = fac.data;
  return (
    <>
      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <div className="rounded-lg border border-rule p-4">
          <div className="text-sm text-fog">Audit year {d.audit_year}</div>
          <div className="mt-1 text-2xl font-semibold">{fmtUsd(d.total_federal_expended_usd)}</div>
          <div className="text-xs text-fog">{d.entity_count.toLocaleString()} audited organizations</div>
        </div>
        {d.by_entity_type.slice(0, 2).map((t) => (
          <div key={t.entity_type} className="rounded-lg border border-rule p-4">
            <div className="text-sm capitalize text-fog">{t.entity_type} entities</div>
            <div className="mt-1 text-2xl font-semibold">{fmtUsd(t.usd)}</div>
            <div className="text-xs text-fog">{t.count.toLocaleString()} organizations</div>
          </div>
        ))}
      </div>
      {d.in_progress_note && <p className="mt-2 text-xs text-fog">{d.in_progress_note}.</p>}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[520px] text-sm">
          <thead>
            <tr className="border-b border-rule text-left text-fog">
              <th className="py-2 pr-4 font-medium">Organization</th>
              <th className="py-2 pr-4 font-medium">Type</th>
              <th className="py-2 pr-4 text-right font-medium">Federal spending (audited)</th>
              <th className="py-2 font-medium">Audit</th>
            </tr>
          </thead>
          <tbody>
            {d.top_auditees.slice(0, 15).map((a) => (
              <tr key={a.report_id} className="border-b border-rule/60">
                <td className="py-2 pr-4">{a.name}</td>
                <td className="py-2 pr-4 text-xs text-fog">{a.entity_type}</td>
                <td className="py-2 pr-4 text-right font-mono text-xs">
                  {fmtUsd(a.federal_expended_usd)}
                </td>
                <td className="py-2 text-xs">
                  <a
                    href={`https://app.fac.gov/dissemination/summary/${a.report_id}`}
                    className="underline decoration-rule underline-offset-2 hover:text-ink"
                  >
                    view ↗
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-xs text-fog">
        Showing 15 of {d.entity_count.toLocaleString()} —{" "}
        <a href="/data/federal_audits.json" className="underline underline-offset-2 hover:text-ink">
          top 60 in the data
        </a>
        .
      </p>
      <SourceChip
        source={fac.source}
        asOf={fac.as_of}
        cadence={fac.cadence}
        coverage={fac.coverage_flag}
        caveats={fac.caveats}
        dataHref="/data/federal_audits.json"
      />
    </>
  );
}
