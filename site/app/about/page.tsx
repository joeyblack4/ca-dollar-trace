import { CoverageBadge } from "@/components/ui/SourceChip";
import type { CoverageFlag } from "@/lib/published";
import { fmtAsOf } from "@/lib/published";
import { loadPublished } from "@/lib/published-server";

export const metadata = {
  title: "What this is — CA Dollar Trace",
  description:
    "What CA Dollar Trace is, every government source behind it, how the data is refreshed, and how to read the numbers honestly.",
};

interface CatalogSource {
  source: string;
  name: string;
  publisher: string;
  url: string;
  cadence: string;
  coverage_flag: CoverageFlag;
  caveats: string[];
  layer: string;
  feeds: string;
}
interface Catalog {
  source_count: number;
  layer_order: string[];
  sources: CatalogSource[];
  derived: { source: string; name: string; feeds: string }[];
}

export default async function AboutPage() {
  const pub = await loadPublished<Catalog>("sources_catalog");
  const cat = pub.data;
  const byLayer = (layer: string) => cat.sources.filter((s) => s.layer === layer);

  return (
    <div>
      <h1 className="max-w-3xl text-3xl font-semibold tracking-tight">
        Follow your California tax dollar — honestly.
      </h1>
      <p className="mt-4 max-w-2xl text-fog">
        CA Dollar Trace lets you follow money from the state budget down to the named
        organizations that receive it — and, just as importantly, shows you exactly where the
        public record runs out. It is built entirely from California&apos;s own government data.
        Every figure carries the source it came from, the date it was published, and a one-click
        link to the raw file behind it.
      </p>

      {/* How it works */}
      <section className="mt-10">
        <h2 className="text-xl font-semibold">How it works</h2>
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          <Point title="Official sources only">
            Nothing here is estimated or editorialized. Every number is pulled directly from a
            government system — the enacted budget, the state checkbook, payroll filings, federal
            award databases, and more. They&apos;re listed in full below.
          </Point>
          <Point title="Cited and dated, always">
            Each figure sits above a source chip naming its publisher, its as-of date, and a link
            to the underlying data. If you can&apos;t trace a number to its source, it doesn&apos;t
            belong here.
          </Point>
          <Point title="Refreshed automatically">
            A scheduled job re-pulls the sources on their own cadences — some daily, most monthly
            or annual — and republishes only what actually changed. Nothing is hand-edited between
            pulls.
          </Point>
          <Point title="Gaps are labeled, never zeroed">
            When the trail ends — a masked vendor, a category with no detail, a payment no public
            record follows — we mark it as a dead end. A gap is never quietly shown as a zero.
          </Point>
        </div>
      </section>

      {/* The rule */}
      <section className="mt-10 max-w-2xl">
        <h2 className="text-xl font-semibold">The one rule that matters most</h2>
        <p className="mt-2 text-fog">
          These numbers come from different systems, on different accounting bases, for different
          years. So{" "}
          <strong className="text-ink">you cannot add figures from different sources together</strong>
          . A budget appropriation, an actual payment, a salary, and audited federal spending each
          measure a different thing. The{" "}
          <a href="/methodology/" className="underline underline-offset-2 hover:text-ink">
            methodology page
          </a>{" "}
          spells out what each headline figure is, and why they don&apos;t sum.
        </p>
      </section>

      {/* Sources */}
      <section className="mt-10">
        <h2 className="text-xl font-semibold">
          Where the numbers come from — {cat.source_count} sources
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-fog">
          Every source the site ingests, grouped by where the money sits. Each links to the
          government system it&apos;s drawn from.
        </p>

        <div className="mt-5 space-y-8">
          {cat.layer_order.map((layer) => (
            <div key={layer}>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-poppy">{layer}</h3>
              <div className="mt-2 divide-y divide-rule/60 border-t border-rule/60">
                {byLayer(layer).map((s) => (
                  <div key={s.source} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-3">
                    <a
                      href={s.url}
                      className="font-medium text-ink underline decoration-rule underline-offset-2 hover:text-poppy"
                    >
                      {s.name} ↗
                    </a>
                    <CoverageBadge flag={s.coverage_flag} />
                    <span className="w-full text-sm text-fog">{s.feeds}</span>
                    <span className="w-full text-xs text-fog">
                      <span className="text-ink/70">{s.publisher}</span> · refreshed {s.cadence}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-8">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-poppy">
            Built on top of those sources
          </h3>
          <div className="mt-2 divide-y divide-rule/60 border-t border-rule/60">
            {cat.derived.map((d) => (
              <div key={d.source} className="py-3">
                <span className="font-medium text-ink">{d.name}</span>
                <span className="block text-sm text-fog">{d.feeds}</span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-fog">
            These are computed from the sources above — not pulled from anywhere new. How
            organizations get matched across sources (and when we decline to guess) is described in
            the{" "}
            <a href="/methodology/" className="underline underline-offset-2 hover:text-ink">
              methodology
            </a>
            .
          </p>
        </div>
      </section>

      {/* Where it ends + independence */}
      <section className="mt-10 max-w-2xl space-y-4 text-sm text-fog">
        <div>
          <h2 className="text-lg font-semibold text-ink">Where the trail goes dark</h2>
          <p className="mt-1">
            Some money genuinely can&apos;t be followed further in any public data — Medi-Cal
            plan-to-provider payments, most county and school-district vendors, spending through the
            tax code, records published only as PDFs. Those dead ends are the point, not a
            shortcoming. See the{" "}
            <a href="/gaps/" className="underline underline-offset-2 hover:text-ink">
              dark zones
            </a>
            .
          </p>
        </div>
        <div>
          <h2 className="text-lg font-semibold text-ink">Independent, not government</h2>
          <p className="mt-1">
            This is an independent project. It is not affiliated with, endorsed by, or operated by
            the State of California or any agency named here. It simply re-presents their public
            data with its sources attached, so every figure can be checked against the original.
          </p>
        </div>
        <p className="text-xs">Sources catalog as of {fmtAsOf(pub.as_of)}.</p>
      </section>
    </div>
  );
}

function Point({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-rule p-4">
      <div className="font-medium">{title}</div>
      <p className="mt-1 text-sm text-fog">{children}</p>
    </div>
  );
}
