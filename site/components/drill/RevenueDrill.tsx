"use client";

/* The revenue drill trail: mirrors DrillExplorer, but follows the money
   UPSTREAM — who pays each General Fund revenue source, as far as the law
   allows. Every branch ends at the statutory wall (R&TC §19542 / §7056) with
   an explicit masked terminator — never a dead click.

   Vintage law: the Sankey bar is the DOF enacted estimate for the budget
   year; FTB statistics are for a past tax year. We show both, labeled, and
   never scale one to fit the other. */

import { CoverageBadge, SourceChip, VintageChip } from "@/components/ui/SourceChip";
import { fmtUsd, type BudgetWaterfall, type Published } from "@/lib/published";
import type {
  CorpPublicCompaniesDoc,
  CorpRevenueDoc,
  FederalLensClass,
  FederalLensDoc,
  InsuranceRevenueDoc,
  PathSeg,
  PitRevenueDoc,
  PitZipDoc,
  SalesRevenueDoc,
} from "./types";
import {
  FetchError,
  FollowRow,
  LevelCard,
  RefRow,
  Row,
  Terminator,
  useJson,
} from "./primitives";

const REVENUE_BLUE = "#2a78d6";

/** Which revenue nodes have a data-backed drill (vs curated narrative only) */
const REVENUE_DRILL_FOR_NODE: Record<string, "pit" | "corp" | "sales" | "insurance"> = {
  "Personal Income Tax": "pit",
  "Corporation Tax": "corp",
  "Sales and Use Tax": "sales",
  "Insurance Tax": "insurance",
};

const countySlug = (county: string) =>
  county
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");

const fmtCount = (n: number | null) => (n === null ? "—" : n.toLocaleString("en-US"));

/** "1,888,287 of 8,650,725" -> "22%"; sub-0.5% shows as "<1%" */
const pctOf = (part: number, whole: number) => {
  if (!whole) return "0%";
  const pct = (part / whole) * 100;
  return pct > 0 && pct < 0.5 ? "<1%" : `${Math.round(pct)}%`;
};

/* Segment kinds that belong to a revenue sub-branch; stripped when switching branches */
const BRANCH_KINDS = new Set([
  "rev_brackets",
  "rev_counties",
  "rev_county",
  "rev_zips",
  "rev_high_income",
  "rev_industries",
  "rev_income_classes",
  "rev_companies",
  "rev_biztypes",
  "rev_cities",
  "rev_migration",
]);

/* People-vs-money paired bars: the "who pays" form. Two series on ONE shared
   percent scale — gray = share of filers (context), blue = share of the tax
   (the subject). The mismatch between the two bars IS the story, so each bar
   carries its % directly at the end. */
const FILERS_GRAY = "#8a8781";

/* Federal lens: IRS statistics on the same taxpayers. Purple = federal in the
   site's existing color grammar (fund-class map). These panels are the ONLY
   place federal numbers appear — never inside a California figure. */
const FEDERAL_PURPLE = "#7c5cbf";

function FederalChip() {
  return (
    <span
      className="inline-block rounded-full border px-2 py-0.5 text-xs font-medium"
      style={{
        borderColor: `${FEDERAL_PURPLE}66`,
        background: `${FEDERAL_PURPLE}14`,
        color: FEDERAL_PURPLE,
      }}
    >
      Federal lens — IRS returns
    </span>
  );
}

/** The age/household mini-table shown for a set of federal AGI classes. */
function FederalAgePanel({
  classes,
  heading,
  footnote,
}: {
  classes: FederalLensClass[];
  heading: string;
  footnote?: string;
}) {
  const maxPct = Math.max(...classes.map((c) => c.elderly_pct), 1);
  return (
    <div
      className="mt-3 rounded-md border px-3 py-2.5"
      style={{ borderColor: `${FEDERAL_PURPLE}55`, background: `${FEDERAL_PURPLE}08` }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-xs font-medium text-ink/90">{heading}</p>
        <FederalChip />
      </div>
      <p className="mt-0.5 text-[11px] text-fog">
        California tax data carries no age or filing-status detail — federal returns for the same
        taxpayers do. Income classes below are the IRS&apos;s own; they are not the California
        bands above and are never merged with them.
      </p>
      <div className="mt-2">
        {classes.map((c) => {
          const married = c.joint;
          const singleish = c.single + c.head_of_household + c.other_status;
          return (
            <div key={c.label} className="flex items-center gap-2 py-1">
              <span className="w-40 shrink-0 truncate text-xs text-ink/90">{c.label}</span>
              <div
                className="h-1 flex-1 overflow-hidden rounded-full"
                style={{ background: `${FEDERAL_PURPLE}22` }}
                title={`${c.elderly_pct}% of returns have a primary filer 60+`}
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${(c.elderly_pct / maxPct) * 100}%`,
                    background: FEDERAL_PURPLE,
                  }}
                />
              </div>
              <span className="w-16 shrink-0 text-right font-mono text-[11px] text-ink/80">
                {c.elderly_pct}% 60+
              </span>
              <span className="hidden w-44 shrink-0 text-right text-[11px] text-fog sm:block">
                {Math.round((married / c.returns) * 100)}% joint ·{" "}
                {Math.round((singleish / c.returns) * 100)}% single/HoH
              </span>
            </div>
          );
        })}
      </div>
      {footnote && <p className="mt-1.5 text-[11px] text-fog">{footnote}</p>}
    </div>
  );
}

function PairedShareLegend({ moneyLabel }: { moneyLabel: string }) {
  return (
    <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fog">
      <span className="flex items-center gap-1.5">
        <span
          className="inline-block h-2 w-2 rounded-sm"
          style={{ background: FILERS_GRAY }}
          aria-hidden
        />
        share of filers
      </span>
      <span className="flex items-center gap-1.5">
        <span
          className="inline-block h-2 w-2 rounded-sm"
          style={{ background: REVENUE_BLUE }}
          aria-hidden
        />
        {moneyLabel}
      </span>
    </div>
  );
}

function PairedShareRow({
  label,
  sub,
  peoplePct,
  moneyPct,
  maxPct,
}: {
  label: string;
  sub: string;
  peoplePct: number;
  moneyPct: number;
  maxPct: number;
}) {
  const bar = (pct: number, color: string, series: string) => (
    <div className="flex items-center gap-2" title={`${series}: ${pct}%`}>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-rule/30">
        <div
          className="h-full rounded-full"
          style={{ width: `${Math.max(0.4, (pct / maxPct) * 100)}%`, background: color }}
        />
      </div>
      <span className="w-14 shrink-0 text-right font-mono text-[11px] text-ink/80">
        {pct < 0.1 ? "<0.1" : pct.toFixed(pct < 10 ? 1 : 0)}%
      </span>
    </div>
  );
  return (
    <div className="px-1 py-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium text-ink/90">{label}</span>
        <span className="shrink-0 text-[11px] text-fog">{sub}</span>
      </div>
      <div className="mt-1 space-y-0.5">
        {bar(peoplePct, FILERS_GRAY, "share of filers")}
        {bar(moneyPct, REVENUE_BLUE, "share of tax")}
      </div>
    </div>
  );
}

export function RevenueDrill({
  waterfall,
  path,
  setPath,
}: {
  waterfall: BudgetWaterfall;
  path: PathSeg[];
  setPath: (p: PathSeg[]) => void;
}) {
  const root = path[0] as { kind: "revenue"; name: string };
  const drillKind = REVENUE_DRILL_FOR_NODE[root.name];
  const rev = waterfall.general_fund.revenue.find((r) => r.name === root.name);
  const origin = waterfall.origin_visibility?.find((o) => o.node === root.name);

  if (drillKind === undefined && process.env.NODE_ENV !== "production") {
    // a DOF rename would silently orphan the drill mapping — make it loud in dev
    if (rev && !origin) console.warn(`RevenueDrill: no origin narrative for node "${root.name}"`);
  }

  const bracketsSeg = path.find((s) => s.kind === "rev_brackets");
  const countiesSeg = path.find((s) => s.kind === "rev_counties");
  const countySeg = path.find((s) => s.kind === "rev_county") as
    | { kind: "rev_county"; county: string }
    | undefined;
  const zipsSeg = path.find((s) => s.kind === "rev_zips") as
    | { kind: "rev_zips"; county: string }
    | undefined;
  const highIncomeSeg = path.find((s) => s.kind === "rev_high_income");
  const industriesSeg = path.find((s) => s.kind === "rev_industries");
  const incomeClassesSeg = path.find((s) => s.kind === "rev_income_classes");
  const companiesSeg = path.find((s) => s.kind === "rev_companies");
  const biztypesSeg = path.find((s) => s.kind === "rev_biztypes");
  const citiesSeg = path.find((s) => s.kind === "rev_cities");
  const migrationSeg = path.find((s) => s.kind === "rev_migration");

  const pitDoc = useJson<Published<PitRevenueDoc>>(
    drillKind === "pit" ? "/data/revenue/pit.json" : null
  );
  const zipDoc = useJson<Published<PitZipDoc>>(
    zipsSeg ? `/data/revenue/pit_zip/${countySlug(zipsSeg.county)}.json` : null
  );
  const corpDoc = useJson<Published<CorpRevenueDoc>>(
    drillKind === "corp" ? "/data/revenue/corp.json" : null
  );
  const companiesDoc = useJson<Published<CorpPublicCompaniesDoc>>(
    companiesSeg ? "/data/revenue/corp_public_companies.json" : null
  );
  const salesDoc = useJson<Published<SalesRevenueDoc>>(
    drillKind === "sales" ? "/data/revenue/sales.json" : null
  );
  const insDoc = useJson<Published<InsuranceRevenueDoc>>(
    drillKind === "insurance" ? "/data/revenue/insurance.json" : null
  );
  const fedDoc = useJson<Published<FederalLensDoc>>(
    drillKind === "pit" && (bracketsSeg || countySeg || migrationSeg)
      ? "/data/revenue/pit_federal_lens.json"
      : null
  );

  const pitPub = pitDoc && pitDoc !== "loading" && pitDoc !== "error" ? pitDoc : null;
  const pit = pitPub ? pitPub.data : null;
  const corpPub = corpDoc && corpDoc !== "loading" && corpDoc !== "error" ? corpDoc : null;
  const corp = corpPub ? corpPub.data : null;
  const companiesPub =
    companiesDoc && companiesDoc !== "loading" && companiesDoc !== "error" ? companiesDoc : null;
  const salesPub = salesDoc && salesDoc !== "loading" && salesDoc !== "error" ? salesDoc : null;
  const sales = salesPub ? salesPub.data : null;
  const insPub = insDoc && insDoc !== "loading" && insDoc !== "error" ? insDoc : null;
  const ins = insPub ? insPub.data : null;
  const fedPub = fedDoc && fedDoc !== "loading" && fedDoc !== "error" ? fedDoc : null;
  const fed = fedPub ? fedPub.data : null;

  /* breadcrumbs derive from the path, exactly like the spending drill */
  const crumbs: { label: string; amount?: number; pathIndex: number }[] = [
    { label: `${waterfall.budget_year} budget`, pathIndex: -1 },
  ];
  for (let i = 0; i < path.length; i++) {
    const seg = path[i];
    if (seg.kind === "revenue")
      crumbs.push({ label: seg.name, amount: rev?.usd, pathIndex: i });
    if (seg.kind === "rev_brackets") crumbs.push({ label: "income bands", pathIndex: i });
    if (seg.kind === "rev_counties") crumbs.push({ label: "counties", pathIndex: i });
    if (seg.kind === "rev_county") crumbs.push({ label: seg.county, pathIndex: i });
    if (seg.kind === "rev_zips") crumbs.push({ label: "ZIP codes", pathIndex: i });
    if (seg.kind === "rev_high_income") crumbs.push({ label: "top of the distribution", pathIndex: i });
    if (seg.kind === "rev_industries") crumbs.push({ label: "industries", pathIndex: i });
    if (seg.kind === "rev_income_classes") crumbs.push({ label: "income classes", pathIndex: i });
    if (seg.kind === "rev_companies") crumbs.push({ label: "public companies", pathIndex: i });
    if (seg.kind === "rev_biztypes") crumbs.push({ label: "business types", pathIndex: i });
    if (seg.kind === "rev_cities") crumbs.push({ label: "cities & counties", pathIndex: i });
    if (seg.kind === "rev_migration") crumbs.push({ label: "moving in & out", pathIndex: i });
  }

  /* switch to a top-level branch: drop any other branch segs */
  const toBranch = (seg: PathSeg) =>
    setPath([...path.filter((s) => !BRANCH_KINDS.has(s.kind)), seg]);

  const vintage = pit ? <VintageChip label={`Tax year ${pit.tax_year} data`} /> : null;
  let step = 1;

  return (
    <div className="mt-8" id="drill">
      <div className="sticky top-0 z-10 -mx-2 flex flex-wrap items-center gap-1 border-b border-rule bg-paper/95 px-2 py-2 text-xs backdrop-blur">
        <span className="font-medium text-fog">Following:</span>
        {crumbs.map((c, i) => (
          <span key={`${c.label}-${i}`} className="flex items-center gap-1">
            {i > 0 && <span className="text-fog">←</span>}
            <button
              onClick={() => setPath(path.slice(0, c.pathIndex + 1))}
              className={
                "rounded px-1.5 py-0.5 hover:bg-poppy/10 " +
                (i === crumbs.length - 1 ? "font-semibold text-ink" : "text-fog")
              }
            >
              {c.label}
              {c.amount !== undefined && <span className="ml-1 font-mono">{fmtUsd(c.amount)}</span>}
            </button>
          </span>
        ))}
      </div>

      {/* Level 1: the revenue source itself */}
      <LevelCard
        step={step++}
        title={`${root.name} — ${rev ? fmtUsd(rev.usd) : "?"} estimated for ${waterfall.budget_year}`}
        subtitle="Where this money originates, followed as far as the public record goes."
      >
        {drillKind === "pit" && (
          <>
            {pitDoc === "error" && <FetchError what="the income tax statistics" />}
            {pitDoc === "loading" && <p className="text-sm text-fog">Loading…</p>}
            {pit && (
              <>
                <div className="mb-3 rounded-md border border-amber-600/30 bg-amber-500/[0.06] px-3 py-2.5 text-sm text-fog">
                  <p>
                    <span className="font-medium text-ink">
                      Two numbers, two years — deliberately not reconciled.
                    </span>{" "}
                    {pit.budget_reference.note}
                  </p>
                  <p className="mt-1.5 font-mono text-xs">
                    {waterfall.budget_year} estimate {fmtUsd(pit.budget_reference.waterfall_usd)} ·
                    tax year {pit.tax_year} reported liability{" "}
                    {fmtUsd(pit.budget_reference.stats_total_usd)} from{" "}
                    {pit.statewide.returns.toLocaleString("en-US")} returns
                  </p>
                </div>
                <div className="space-y-2">
                  <FollowRow
                    label="Who pays it — by income band"
                    hint={`${pit.brackets.length} bands: how many filers in each, and each band's share of the whole pool`}
                    selected={!!bracketsSeg}
                    onClick={() => toBranch({ kind: "rev_brackets" })}
                  />
                  <FollowRow
                    label="Where it's paid from — all 58 counties"
                    hint="County totals, each openable down to its income mix and ZIP codes"
                    selected={!!countiesSeg}
                    onClick={() => toBranch({ kind: "rev_counties" })}
                  />
                  <FollowRow
                    label="The top of the distribution"
                    hint="Returns over $1 million — a few thousand filers carry a third of the tax"
                    selected={!!highIncomeSeg}
                    onClick={() => toBranch({ kind: "rev_high_income" })}
                  />
                  <FollowRow
                    label="Who's moving in and out — the tax base (federal lens)"
                    hint="IRS migration data: filers arriving and leaving, by income and age"
                    selected={!!migrationSeg}
                    onClick={() => toBranch({ kind: "rev_migration" })}
                  />
                </div>
                {pitPub && (
                  <SourceChip
                    source={pitPub.source}
                    asOf={pitPub.as_of}
                    cadence={pitPub.cadence}
                    coverage={pitPub.coverage_flag}
                    caveats={pitPub.caveats}
                    dataHref={pitPub.source.url}
                  />
                )}
              </>
            )}
          </>
        )}

        {drillKind === "corp" && (
          <>
            {corpDoc === "error" && <FetchError what="the corporation tax statistics" />}
            {corpDoc === "loading" && <p className="text-sm text-fog">Loading…</p>}
            {corp && (
              <>
                <div className="mb-3 rounded-md border border-amber-600/30 bg-amber-500/[0.06] px-3 py-2.5 text-sm text-fog">
                  <p>
                    <span className="font-medium text-ink">
                      Two numbers, two years — deliberately not reconciled.
                    </span>{" "}
                    {corp.budget_reference.note}
                  </p>
                  <p className="mt-1.5 font-mono text-xs">
                    {waterfall.budget_year} estimate {fmtUsd(corp.budget_reference.waterfall_usd)} ·
                    tax year {corp.tax_year} reported liability{" "}
                    {fmtUsd(corp.budget_reference.stats_total_usd)} from{" "}
                    {corp.statewide.returns_with_liability.toLocaleString("en-US")} returns with
                    liability
                  </p>
                </div>
                <div className="space-y-2">
                  <FollowRow
                    label="Which industries pay it"
                    hint={`${corp.industries.length} industry groups, with the C-corp vs S-corp split`}
                    selected={!!industriesSeg}
                    onClick={() => toBranch({ kind: "rev_industries" })}
                  />
                  <FollowRow
                    label="By size of company income"
                    hint="From net-loss filers paying the minimum tax to the $10M+ class that carries most of it"
                    selected={!!incomeClassesSeg}
                    onClick={() => toBranch({ kind: "rev_income_classes" })}
                  />
                  <FollowRow
                    label="Named public companies — what they report paying in state taxes"
                    hint="SEC filings: self-reported state+local tax expense, all states combined"
                    selected={!!companiesSeg}
                    onClick={() => toBranch({ kind: "rev_companies" })}
                  />
                </div>
                {corpPub && (
                  <SourceChip
                    source={corpPub.source}
                    asOf={corpPub.as_of}
                    cadence={corpPub.cadence}
                    coverage={corpPub.coverage_flag}
                    caveats={corpPub.caveats}
                    dataHref={corpPub.source.url}
                  />
                )}
              </>
            )}
          </>
        )}

        {drillKind === "sales" && (
          <>
            {salesDoc === "error" && <FetchError what="the sales tax statistics" />}
            {salesDoc === "loading" && <p className="text-sm text-fog">Loading…</p>}
            {sales && (
              <>
                <div className="mb-3 rounded-md border border-amber-600/30 bg-amber-500/[0.06] px-3 py-2.5 text-sm text-fog">
                  <p>
                    <span className="font-medium text-ink">
                      Taxable sales are the base, not the tax.
                    </span>{" "}
                    {sales.base_note}
                  </p>
                  <p className="mt-1.5 font-mono text-xs">
                    {waterfall.budget_year} GF estimate{" "}
                    {fmtUsd(sales.budget_reference.waterfall_usd)} · GF actually received{" "}
                    {fmtUsd(sales.budget_reference.stats_total_usd)} in FY
                    {sales.fund_split_fiscal_year} · sales data current to {sales.latest_quarter}
                  </p>
                </div>
                <div className="mb-3">
                  <p className="mb-1 text-xs font-medium text-fog">
                    Where each sales-tax dollar goes (FY{sales.fund_split_fiscal_year}, CDTFA
                    Summary of Revenues):
                  </p>
                  {sales.fund_split.map((f) => (
                    <RefRow
                      key={f.fund}
                      label={f.fund}
                      usd={f.revenue_usd}
                      maxUsd={sales.fund_split[0].revenue_usd}
                    />
                  ))}
                </div>
                <div className="space-y-2">
                  <FollowRow
                    label="What kinds of businesses collect it"
                    hint={`${sales.business_types.length} business types, trailing four quarters through ${sales.latest_quarter}`}
                    selected={!!biztypesSeg}
                    onClick={() => toBranch({ kind: "rev_biztypes" })}
                  />
                  <FollowRow
                    label="Where the sales happen — counties & cities"
                    hint="All 58 counties and every city CDTFA publishes, with suppressed cells disclosed"
                    selected={!!citiesSeg}
                    onClick={() => toBranch({ kind: "rev_cities" })}
                  />
                </div>
                {salesPub && (
                  <SourceChip
                    source={salesPub.source}
                    asOf={salesPub.as_of}
                    cadence={salesPub.cadence}
                    coverage={salesPub.coverage_flag}
                    caveats={salesPub.caveats}
                    dataHref={salesPub.source.url}
                  />
                )}
              </>
            )}
          </>
        )}

        {drillKind === "insurance" && (
          <>
            {insDoc === "error" && <FetchError what="the insurance tax assessments" />}
            {insDoc === "loading" && <p className="text-sm text-fog">Loading…</p>}
            {ins && (
              <>
                <div className="mb-3 rounded-md border border-amber-600/30 bg-amber-500/[0.06] px-3 py-2.5 text-sm text-fog">
                  <p>
                    <span className="font-medium text-ink">
                      A 2.35% tax on gross premiums written in California.
                    </span>{" "}
                    {ins.budget_reference.note}
                  </p>
                </div>
                <p className="mb-1 text-xs font-medium text-fog">
                  Assessed by insurer type ({ins.assessment_year} assessments on {ins.business_year}{" "}
                  premiums):
                </p>
                {ins.types.map((t) => (
                  <RefRow
                    key={t.type}
                    label={t.type}
                    usd={t.assessed_usd}
                    maxUsd={ins.types[0].assessed_usd}
                    sub={`${t.share_pct}% of assessments${t.businesses ? ` · ${t.businesses.toLocaleString("en-US")} insurers` : ""}`}
                  />
                ))}
                <RefRow
                  label="Net adjustments (refunds, deficiency assessments)"
                  usd={Math.abs(ins.net_adjustments_usd)}
                  maxUsd={ins.types[0].assessed_usd}
                  valueLabel={fmtUsd(ins.net_adjustments_usd)}
                />
                <Terminator flag="masked">
                  Which insurers? Tax paid by a named insurer is not public. The Department of
                  Insurance publishes premium volumes by company — but not tax — so insurer type
                  is where the public record stops.
                </Terminator>
                {insPub && (
                  <SourceChip
                    source={insPub.source}
                    asOf={insPub.as_of}
                    cadence={insPub.cadence}
                    coverage={insPub.coverage_flag}
                    caveats={insPub.caveats}
                    dataHref={insPub.source.url}
                  />
                )}
              </>
            )}
          </>
        )}

        {drillKind === undefined && (
          <>
            {origin ? (
              <ol className="space-y-3">
                {origin.hops.map((hop, i) => (
                  <li key={hop.label} className="rounded-md border border-rule p-3 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs text-fog">{i + 1}</span>
                      <span className="font-medium">{hop.label}</span>
                      <CoverageBadge flag={hop.flag} />
                    </div>
                    <p className="mt-1 text-fog">{hop.note}</p>
                    <a
                      href={hop.cite}
                      className="mt-1 inline-block text-xs underline decoration-rule underline-offset-2 hover:text-ink"
                    >
                      source ↗
                    </a>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-fog">No origin narrative published for this source yet.</p>
            )}
            {(() => {
              const last = origin?.hops[origin.hops.length - 1]?.flag;
              const flag = last === "masked" || last === "trail_ends_here" ? last : "category_only";
              return (
                <Terminator flag={flag}>
                  A payer-level drill for this source isn&apos;t built yet — what you see above is
                  the shape of the public record.
                </Terminator>
              );
            })()}
          </>
        )}
      </LevelCard>

      {/* ---- PIT branch: income bands ---- */}
      {drillKind === "pit" && bracketsSeg && pit && (
        <LevelCard
          step={step++}
          title="Who pays, by income band"
          subtitle={`Every California return for tax year ${pit.tax_year}, in seven income bands. Each band gets two bars on the same scale: how many of the filers it holds, and how much of the ${fmtUsd(pit.statewide.tax_liability_usd)} it paid.`}
          chip={vintage}
        >
          {(() => {
            const bandMax = Math.max(
              ...pit.display_bands.flatMap((b) => [b.share_of_returns_pct, b.share_of_tax_pct])
            );
            const bottom = pit.display_bands[0];
            const top = pit.display_bands[pit.display_bands.length - 1];
            const megaCum = pit.brackets.find((b) => b.floor_usd === 1_000_000);
            return (
              <>
                <div className="mb-4 grid gap-2 sm:grid-cols-3">
                  <div className="rounded-md border border-rule px-3 py-2 text-sm">
                    <span className="font-mono text-lg">{bottom.share_of_tax_pct.toFixed(1)}%</span>{" "}
                    <span className="text-fog">
                      of the tax came from the half of filers earning under $50,000
                    </span>
                  </div>
                  {megaCum && (
                    <div className="rounded-md border border-rule px-3 py-2 text-sm">
                      <span className="font-mono text-lg">
                        {megaCum.cum_share_of_tax_pct.toFixed(1)}%
                      </span>{" "}
                      <span className="text-fog">came from returns over $1 million</span>
                    </div>
                  )}
                  <div className="rounded-md border border-rule px-3 py-2 text-sm">
                    <span className="font-mono text-lg">{top.share_of_tax_pct.toFixed(1)}%</span>{" "}
                    <span className="text-fog">
                      came from just {fmtCount(top.returns)} returns over $10 million
                    </span>
                  </div>
                </div>
                <PairedShareLegend moneyLabel="share of the tax paid" />
                {pit.display_bands.map((b) => (
                  <details key={b.label} className="group">
                    <summary className="cursor-pointer list-none rounded-md transition-colors hover:bg-rule/20 [&::-webkit-details-marker]:hidden">
                      <PairedShareRow
                        label={b.label}
                        sub={`${fmtCount(b.returns)} returns · avg ${fmtUsd(b.avg_tax_usd)} each`}
                        peoplePct={b.share_of_returns_pct}
                        moneyPct={b.share_of_tax_pct}
                        maxPct={bandMax}
                      />
                      <div className="-mt-1 px-1 pb-1 text-[11px] text-fog">
                        <span className="group-open:hidden">
                          ▸ how they earned it, who they are
                        </span>
                        <span className="hidden group-open:inline">▾ close</span>
                      </div>
                    </summary>
                    <div className="mb-2 ml-1 rounded-md border border-rule/70 px-3 py-2.5">
                      <p className="text-xs font-medium text-fog">
                        How this band earned its {fmtUsd(b.itemized_income_usd)}:
                      </p>
                      <div className="mt-1.5">
                        {b.composition
                          .filter((c) => c.usd !== 0)
                          .map((c) => (
                            <div key={c.source} className="flex items-center gap-2 py-0.5">
                              <span className="w-52 shrink-0 truncate text-xs text-ink/90">
                                {c.source}
                              </span>
                              <div className="h-1 flex-1 overflow-hidden rounded-full bg-rule/30">
                                <div
                                  className="h-full rounded-full"
                                  style={{
                                    width: `${Math.max(0, (Math.max(0, c.share_of_income_pct) / Math.max(1, b.composition[0].share_of_income_pct)) * 100)}%`,
                                    background: REVENUE_BLUE,
                                  }}
                                />
                              </div>
                              <span className="w-28 shrink-0 text-right font-mono text-[11px] text-fog">
                                {fmtUsd(c.usd)} · {c.share_of_income_pct}%
                              </span>
                            </div>
                          ))}
                      </div>
                      <p className="mt-2 text-xs font-medium text-fog">Who they are:</p>
                      <p className="mt-0.5 text-xs text-fog">
                        {[
                          `${pctOf(b.overlays.seniors, b.returns)} claimed the 65+/blind exemption`,
                          b.overlays.renters_credit > 0
                            ? `${pctOf(b.overlays.renters_credit, b.returns)} claimed renter's credit`
                            : "no renter's-credit claims (income limits)",
                          `${pctOf(b.overlays.dependents_credit, b.returns)} claimed dependent credits`,
                          `${pctOf(b.overlays.self_employed, b.returns)} had self-employment income`,
                          b.overlays.mental_health_tax > 0
                            ? `${fmtCount(b.overlays.mental_health_tax)} paid the 1% mental-health surtax on income over $1M (${fmtUsd(b.overlays.mental_health_tax_usd)})`
                            : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                      <p className="mt-1.5 text-[11px] text-fog">
                        Sources netted of reported losses; they sum to{" "}
                        {fmtUsd(b.itemized_income_usd)} vs FTB&apos;s own total-income line of{" "}
                        {fmtUsd(b.total_income_usd)} for this band.
                      </p>
                    </div>
                  </details>
                ))}
              </>
            );
          })()}
          {fed && (
            <FederalAgePanel
              classes={fed.statewide_by_class}
              heading="Age & household, by the IRS's income classes"
              footnote={`Correspondence: IRS counts ${fmtCount(fed.statewide_totals.irs_returns)} CA filers vs FTB's ${fmtCount(fed.statewide_totals.ftb_returns)} — ratio ${fed.statewide_totals.ratio}. ${fed.statewide_totals.note}`}
            />
          )}
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-fog hover:text-ink">
              All {pit.brackets.length} fine-grained bands from FTB&apos;s table
            </summary>
            <div className="mt-2">
              {pit.brackets.map((b) => (
                <RefRow
                  key={b.label}
                  label={b.label}
                  usd={b.tax_liability_usd}
                  maxUsd={Math.max(...pit.brackets.map((x) => x.tax_liability_usd))}
                  sub={`${fmtCount(b.returns)} returns · avg ${fmtUsd(b.avg_tax_usd)} · ${b.share_of_tax_pct}% of the tax`}
                />
              ))}
            </div>
          </details>
          <Terminator flag="masked">
            Who exactly? Individual returns are sealed by law — disclosing them is a misdemeanor
            (R&TC §19542). Income band × county is the finest public cut, so the trail down to a
            person ends here.
          </Terminator>
        </LevelCard>
      )}

      {/* ---- PIT branch: counties ---- */}
      {drillKind === "pit" && countiesSeg && pit && (
        <LevelCard
          step={step++}
          title="Where it's paid from — all 58 counties"
          subtitle={pit.county_measure_note}
          chip={<VintageChip label={`Tax year ${pit.county_tax_year} data`} />}
        >
          {pit.counties.map((c) => (
            <Row
              key={c.county}
              label={c.county}
              usd={c.tax_assessed_usd}
              maxUsd={pit.counties[0].tax_assessed_usd}
              color={REVENUE_BLUE}
              sub={`${fmtCount(c.returns)} returns · ${fmtUsd(c.per_return_tax_usd)} per return`}
              selected={countySeg?.county === c.county}
              onClick={() =>
                setPath([
                  ...path.filter((s) => s.kind !== "rev_county" && s.kind !== "rev_zips"),
                  { kind: "rev_county", county: c.county },
                ])
              }
            />
          ))}
          <div className="mt-3 border-t border-rule pt-2">
            <p className="mb-1 text-xs text-fog">
              Returns FTB can&apos;t place in a county — real money, listed rather than dropped:
            </p>
            {pit.non_geographic.map((g) => (
              <RefRow
                key={g.label}
                label={g.label}
                usd={g.tax_assessed_usd}
                maxUsd={pit.counties[0].tax_assessed_usd}
                sub={`${fmtCount(g.returns)} returns`}
              />
            ))}
            <p className="mt-1 text-xs text-fog">
              Cross-check: counties sum to {fmtUsd(pit.county_cross_check.counties_sum_usd)} vs
              FTB&apos;s own state total {fmtUsd(pit.county_cross_check.state_totals_usd)};
              suppressed small cells leave a residual of{" "}
              {fmtUsd(pit.county_cross_check.suppression_residual_usd)}.
            </p>
          </div>
        </LevelCard>
      )}

      {/* ---- PIT branch: one county ---- */}
      {drillKind === "pit" &&
        countySeg &&
        pit &&
        (() => {
          const county = pit.counties.find((c) => c.county === countySeg.county);
          if (!county) return null;
          return (
            <LevelCard
              step={step++}
              title={`${county.county} County — ${fmtUsd(county.tax_assessed_usd)} assessed`}
              subtitle={`${fmtCount(county.returns)} returns, by income band.`}
              chip={<VintageChip label={`Tax year ${pit.county_tax_year} data`} />}
            >
              {(() => {
                const shares = county.brackets.map((b) => ({
                  ...b,
                  peoplePct:
                    b.returns !== null && county.returns
                      ? (b.returns / county.returns) * 100
                      : null,
                  moneyPct:
                    b.tax_assessed_usd !== null && county.tax_assessed_usd
                      ? (b.tax_assessed_usd / county.tax_assessed_usd) * 100
                      : null,
                }));
                const cMax = Math.max(
                  ...shares.flatMap((b) => [b.peoplePct ?? 0, b.moneyPct ?? 0]),
                  1
                );
                return (
                  <>
                    <PairedShareLegend moneyLabel="share of the tax assessed" />
                    {shares.map((b) =>
                      b.peoplePct === null || b.moneyPct === null ? (
                        <div key={b.label} className="px-1 py-2">
                          <div className="flex items-baseline justify-between gap-3">
                            <span className="text-sm font-medium text-ink/90">{b.label}</span>
                            <span className="shrink-0 text-[11px] text-fog">
                              suppressed at the source — not zero
                            </span>
                          </div>
                        </div>
                      ) : (
                        <PairedShareRow
                          key={b.label}
                          label={b.label}
                          sub={`${fmtCount(b.returns)} returns · ${fmtUsd(b.tax_assessed_usd ?? 0)}`}
                          peoplePct={Math.round(b.peoplePct * 100) / 100}
                          moneyPct={Math.round(b.moneyPct * 100) / 100}
                          maxPct={cMax}
                        />
                      )
                    )}
                  </>
                );
              })()}
              {county.suppressed_cells > 0 && (
                <p className="mt-1 text-xs text-fog">
                  {county.suppressed_cells} band{county.suppressed_cells > 1 ? "s" : ""} suppressed
                  by FTB to protect small groups of filers.
                </p>
              )}
              {(() => {
                const fc = fed?.counties.find((c) => c.county === county.county);
                if (!fc) return null;
                return (
                  <FederalAgePanel
                    classes={fc.classes}
                    heading={`Age & household in ${county.county} County`}
                    footnote={`Correspondence: IRS counts ${fmtCount(fc.correspondence.irs_returns)} filers here vs FTB's ${fmtCount(fc.correspondence.ftb_returns)} — ratio ${fc.correspondence.ratio ?? "n/a"}.`}
                  />
                );
              })()}
              <div className="mt-3">
                <FollowRow
                  label={`ZIP codes in ${county.county}`}
                  hint={`Per-ZIP totals from a fresher table (tax year ${pit.zip_tax_year})`}
                  selected={zipsSeg?.county === county.county}
                  onClick={() =>
                    setPath([
                      ...path.filter((s) => s.kind !== "rev_zips"),
                      { kind: "rev_zips", county: county.county },
                    ])
                  }
                />
              </div>
              <Terminator flag="masked">
                Individual returns in {county.county} County are sealed by law (R&TC §19542).
              </Terminator>
            </LevelCard>
          );
        })()}

      {/* ---- PIT branch: ZIPs in a county ---- */}
      {drillKind === "pit" && zipsSeg && pit && (
        <LevelCard
          step={step++}
          title={`ZIP codes in ${zipsSeg.county}`}
          subtitle="Per-ZIP returns, income, and tax liability — the finest geography FTB publishes."
          chip={<VintageChip label={`Tax year ${pit.zip_tax_year} data`} />}
        >
          {zipDoc === "error" && <FetchError what="the ZIP-code table" />}
          {zipDoc === "loading" && <p className="text-sm text-fog">Loading…</p>}
          {zipDoc && zipDoc !== "loading" && zipDoc !== "error" && (
            <>
              <div className="max-h-96 overflow-y-auto pr-1">
                {zipDoc.data.zips.map((z) => (
                  <RefRow
                    key={z.zip}
                    label={`${z.zip} · ${z.city}`}
                    usd={z.tax_liability_usd}
                    maxUsd={zipDoc.data.zips[0].tax_liability_usd}
                    sub={`${fmtCount(z.returns)} returns${z.agi_usd !== null && z.returns ? ` · avg income ${fmtUsd(Math.round(z.agi_usd / z.returns))}` : ""}`}
                  />
                ))}
              </div>
              <p className="mt-1 text-xs text-fog">
                All {zipDoc.data.zips.length} published ZIPs shown ·{" "}
                {fmtUsd(zipDoc.data.total_tax_liability_usd)} total. {pit.zip_coverage.note}
              </p>
              <Terminator flag="masked">
                Below the ZIP level the law takes over: individual returns are confidential
                (R&TC §19542).
              </Terminator>
            </>
          )}
        </LevelCard>
      )}

      {/* ---- PIT branch: high income ---- */}
      {drillKind === "pit" && highIncomeSeg && pit && (
        <LevelCard
          step={step++}
          title="The top of the distribution"
          subtitle="Returns with adjusted gross income over $1 million, in FTB's own tiers."
          chip={vintage}
        >
          {(() => {
            const totalShare = pit.high_income.reduce((s, t) => s + t.share_of_tax_pct, 0);
            const totalReturns = pit.high_income.reduce((s, t) => s + t.returns, 0);
            return (
              <div className="mb-3 rounded-md border border-rule px-3 py-2 text-sm">
                <span className="font-mono text-lg">{totalShare.toFixed(1)}%</span>{" "}
                <span className="text-fog">
                  of all PIT came from {fmtCount(totalReturns)} returns over $1 million —{" "}
                  {((totalReturns / pit.statewide.returns) * 100).toFixed(2)}% of all filers. This
                  concentration is why state revenue swings with capital gains.
                </span>
              </div>
            );
          })()}
          {pit.high_income.map((t) => (
            <RefRow
              key={t.label}
              label={t.label}
              usd={t.tax_liability_usd}
              maxUsd={Math.max(...pit.high_income.map((x) => x.tax_liability_usd))}
              sub={`${fmtCount(t.returns)} returns · ${t.share_of_tax_pct}% of all PIT`}
            />
          ))}
          <Terminator flag="masked">
            Which people? Sealed by law (R&TC §19542) — FTB publishes counts and totals per tier,
            never names.
          </Terminator>
        </LevelCard>
      )}

      {/* ---- PIT branch: migration (federal lens) ---- */}
      {drillKind === "pit" && migrationSeg && (
        <LevelCard
          step={step++}
          title="Who's moving in and out — the tax base"
          subtitle="IRS migration data: filers whose returns moved into or out of California between consecutive filing years. Federal returns — a demographic lens, not California tax dollars."
          chip={<FederalChip />}
        >
          {fedDoc === "error" && <FetchError what="the IRS migration data" />}
          {fedDoc === "loading" && <p className="text-sm text-fog">Loading…</p>}
          {fed && (
            <>
              <div className="mb-4 grid gap-2 sm:grid-cols-2">
                <div className="rounded-md border border-rule px-3 py-2 text-sm">
                  <span className="font-mono text-lg">
                    {fed.migration.net_returns.toLocaleString("en-US")}
                  </span>{" "}
                  <span className="text-fog">
                    net filers in {fed.migration.years}:{" "}
                    {fmtCount(fed.migration.inflow_returns)} arrived,{" "}
                    {fmtCount(fed.migration.outflow_returns)} left
                  </span>
                </div>
                <div className="rounded-md border border-rule px-3 py-2 text-sm">
                  <span className="font-mono text-lg">{fmtUsd(fed.migration.net_agi_usd)}</span>{" "}
                  <span className="text-fog">
                    net income moved with them — {fmtUsd(fed.migration.inflow_agi_usd)} arrived
                    vs {fmtUsd(fed.migration.outflow_agi_usd)} left
                  </span>
                </div>
              </div>
              <p className="mb-1 text-xs font-medium text-fog">
                The trend — net filers per year:
              </p>
              {(() => {
                const maxAbs = Math.max(
                  ...fed.migration.trend.map((t) => Math.abs(t.net_returns)),
                  1
                );
                const worst = fed.migration.trend.reduce((a, b) =>
                  Math.abs(b.net_returns) > Math.abs(a.net_returns) ? b : a
                );
                return (
                  <>
                    {fed.migration.trend.map((t) => (
                      <div key={t.years} className="flex items-center gap-2 py-1">
                        <span className="w-24 shrink-0 font-mono text-xs text-ink/90">
                          {t.years}
                        </span>
                        <div
                          className="h-1 flex-1 overflow-hidden rounded-full"
                          style={{ background: `${FEDERAL_PURPLE}22` }}
                          title={`in ${t.inflow_returns.toLocaleString()} · out ${t.outflow_returns.toLocaleString()}`}
                        >
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${(Math.abs(t.net_returns) / maxAbs) * 100}%`,
                              background: FEDERAL_PURPLE,
                            }}
                          />
                        </div>
                        <span className="w-20 shrink-0 text-right font-mono text-[11px] text-ink/80">
                          {t.net_returns > 0 ? "+" : ""}
                          {t.net_returns.toLocaleString("en-US")}
                        </span>
                        <span className="hidden w-24 shrink-0 text-right font-mono text-[11px] text-fog sm:block">
                          {fmtUsd(t.net_agi_usd)} AGI
                        </span>
                      </div>
                    ))}
                    <p className="mb-3 mt-1 text-[11px] text-fog">
                      {fed.migration.trend_note} Worst year in this window: {worst.years} (
                      {worst.net_returns.toLocaleString("en-US")} net filers).
                    </p>
                  </>
                );
              })()}
              <p className="mb-1 text-xs font-medium text-fog">
                By income (IRS classes), {fed.migration.years}:
              </p>
              {(() => {
                const maxNet = Math.max(
                  ...fed.migration.by_income.map((r) => Math.abs(r.net_returns)),
                  ...fed.migration.by_age.map((r) => Math.abs(r.net_returns)),
                  1
                );
                const row = (r: (typeof fed.migration.by_income)[number]) => (
                  <div key={r.label} className="flex items-center gap-2 py-1">
                    <span className="w-40 shrink-0 truncate text-xs text-ink/90">{r.label}</span>
                    <div
                      className="h-1 flex-1 overflow-hidden rounded-full"
                      style={{ background: `${FEDERAL_PURPLE}22` }}
                      title={`in ${r.inflow_returns.toLocaleString()} · out ${r.outflow_returns.toLocaleString()}`}
                    >
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${(Math.abs(r.net_returns) / maxNet) * 100}%`,
                          background: FEDERAL_PURPLE,
                        }}
                      />
                    </div>
                    <span className="w-20 shrink-0 text-right font-mono text-[11px] text-ink/80">
                      {r.net_returns > 0 ? "+" : ""}
                      {r.net_returns.toLocaleString("en-US")}
                    </span>
                    <span className="hidden w-40 shrink-0 text-right text-[11px] text-fog sm:block">
                      in {fmtUsd(r.inflow_agi_usd)} · out {fmtUsd(r.outflow_agi_usd)}
                    </span>
                  </div>
                );
                return (
                  <>
                    {fed.migration.by_income.map(row)}
                    <p className="mb-1 mt-3 text-xs font-medium text-fog">
                      By age of the primary filer:
                    </p>
                    {fed.migration.by_age.map(row)}
                  </>
                );
              })()}
              <Terminator flag="category_only">
                Where exactly they went (or came from) is published state-to-state and
                county-to-county, but without the age × income detail — and the movers
                themselves are as sealed as every other taxpayer.
              </Terminator>
              {fedPub && (
                <SourceChip
                  source={fedPub.source}
                  asOf={fedPub.as_of}
                  cadence={fedPub.cadence}
                  coverage={fedPub.coverage_flag}
                  caveats={fedPub.caveats}
                  dataHref={fedPub.source.url}
                />
              )}
            </>
          )}
        </LevelCard>
      )}

      {/* ---- Corp branch: industries ---- */}
      {drillKind === "corp" && industriesSeg && corp && (
        <LevelCard
          step={step++}
          title="Which industries pay it"
          subtitle={`Tax liability by industry group, tax year ${corp.tax_year}. Statewide only — no geographic breakdown of corporate tax exists.`}
          chip={<VintageChip label={`Tax year ${corp.tax_year} data`} />}
        >
          {corp.industries.map((i) => (
            <RefRow
              key={i.industry}
              label={i.industry}
              usd={i.tax_liability_usd}
              maxUsd={corp.industries[0].tax_liability_usd}
              sub={`${i.share_of_tax_pct}% of corp tax · ${fmtCount(i.returns)} returns${
                i.c_corp_tax_usd !== null && i.s_corp_tax_usd !== null
                  ? ` · C-corps ${fmtUsd(i.c_corp_tax_usd)} / S-corps ${fmtUsd(i.s_corp_tax_usd)}`
                  : ""
              }`}
            />
          ))}
          <p className="mt-1 text-xs text-fog">
            Industry groups sum to {fmtUsd(corp.industry_reconciliation.leaf_sum_usd)} vs
            FTB&apos;s own all-industry total {fmtUsd(corp.industry_reconciliation.file_total_usd)}.
          </p>
          <Terminator flag="masked">
            Which companies? Corporate returns are confidential (R&TC §19542) — no public dataset
            names a corporate taxpayer or breaks the tax down geographically. For what public
            companies say themselves, follow the SEC branch above.
          </Terminator>
        </LevelCard>
      )}

      {/* ---- Corp branch: income classes ---- */}
      {drillKind === "corp" && incomeClassesSeg && corp && (
        <LevelCard
          step={step++}
          title="By size of company income"
          subtitle={corp.income_class_measure_note}
          chip={<VintageChip label={`Tax year ${corp.income_class_tax_year} data`} />}
        >
          {(() => {
            const groupMax = Math.max(
              ...corp.display_classes.flatMap((c) => [c.share_of_returns_pct, c.share_of_tax_pct])
            );
            const top = corp.display_classes[corp.display_classes.length - 1];
            const bottom = corp.display_classes[0];
            return (
              <>
                <div className="mb-4 grid gap-2 sm:grid-cols-2">
                  <div className="rounded-md border border-rule px-3 py-2 text-sm">
                    <span className="font-mono text-lg">{top.share_of_tax_pct.toFixed(1)}%</span>{" "}
                    <span className="text-fog">
                      of the tax was assessed on just {fmtCount(top.returns)} companies with
                      California net income over $10 million — {top.share_of_returns_pct}% of
                      filers
                    </span>
                  </div>
                  <div className="rounded-md border border-rule px-3 py-2 text-sm">
                    <span className="font-mono text-lg">
                      {bottom.share_of_returns_pct.toFixed(0)}%
                    </span>{" "}
                    <span className="text-fog">
                      of corporate filers reported a loss or no income — most still owe the
                      minimum tax
                    </span>
                  </div>
                </div>
                <PairedShareLegend moneyLabel="share of the tax assessed" />
                {corp.display_classes.map((c) => (
                  <PairedShareRow
                    key={c.label}
                    label={c.label}
                    sub={`${fmtCount(c.returns)} returns`}
                    peoplePct={c.share_of_returns_pct}
                    moneyPct={c.share_of_tax_pct}
                    maxPct={groupMax}
                  />
                ))}
              </>
            );
          })()}
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-fog hover:text-ink">
              All {corp.income_classes.length} fine-grained classes from FTB&apos;s table
            </summary>
            <div className="mt-2">
              {corp.income_classes.map((c) => (
                <RefRow
                  key={c.label}
                  label={c.label}
                  usd={c.tax_assessed_usd}
                  maxUsd={Math.max(...corp.income_classes.map((x) => x.tax_assessed_usd))}
                  sub={`${fmtCount(c.returns)} returns · ${c.share_of_tax_pct}% of the ${fmtUsd(corp.income_class_total_usd)} assessed`}
                />
              ))}
            </div>
          </details>
          <Terminator flag="masked">
            Which companies? Sealed by law (R&TC §19542) — class counts and totals are the finest
            public cut.
          </Terminator>
        </LevelCard>
      )}

      {/* ---- Corp branch: named public companies (SEC) ---- */}
      {drillKind === "corp" && companiesSeg && (
        <LevelCard
          step={step++}
          title="Named public companies — what they report paying in state taxes"
          subtitle="From each company's own 10-K. This is SEC data, not FTB data."
          chip={
            companiesPub ? (
              <VintageChip label={`Calendar year ${companiesPub.data.calendar_year}`} />
            ) : null
          }
        >
          {companiesDoc === "error" && <FetchError what="the SEC company filings" />}
          {companiesDoc === "loading" && <p className="text-sm text-fog">Loading…</p>}
          {companiesPub && (
            <>
              <div className="mb-3 rounded-md border border-amber-600/30 bg-amber-500/[0.06] px-3 py-2.5 text-sm text-fog">
                <span className="font-medium text-ink">Read this correctly:</span>{" "}
                {companiesPub.data.measure_note}
              </div>
              <div className="max-h-96 overflow-y-auto pr-1">
                {companiesPub.data.companies.map((co) => (
                  <RefRow
                    key={co.cik}
                    label={`${co.company}${co.ticker ? ` (${co.ticker})` : ""}${co.ca_hq ? " · CA-HQ" : ""}`}
                    usd={co.state_local_tax_expense_usd}
                    maxUsd={companiesPub.data.companies[0].state_local_tax_expense_usd}
                    sub={`HQ ${co.hq_state ?? "?"} · all-states expense${
                      co.total_income_tax_expense_usd !== null
                        ? ` · total income tax ${fmtUsd(co.total_income_tax_expense_usd)}`
                        : ""
                    }`}
                  />
                ))}
              </div>
              <p className="mt-1 text-xs text-fog">
                Top {companiesPub.data.universe.shown} of{" "}
                {companiesPub.data.universe.companies_reporting.toLocaleString("en-US")} companies
                reporting this line;{" "}
                {companiesPub.data.universe.excluded_implausible} filings excluded as XBRL tagging
                errors ({companiesPub.data.universe.screen_rule}).
              </p>
              <Terminator flag="masked">
                Each company&apos;s California share is confidential by law (R&TC §19542) — the
                state cannot publish it, and companies don&apos;t break it out. All-states
                self-reported expense is where the truthful trail ends.
              </Terminator>
            </>
          )}
        </LevelCard>
      )}

      {/* ---- Sales branch: business types ---- */}
      {drillKind === "sales" && biztypesSeg && sales && (
        <LevelCard
          step={step++}
          title="What kinds of businesses collect it"
          subtitle={`Taxable sales by business type, trailing four quarters (${sales.trailing_quarters[0]} → ${sales.latest_quarter}). Taxable sales — not tax collected.`}
          chip={<VintageChip label={`Through ${sales.latest_quarter}`} />}
        >
          {sales.business_types.map((t) => (
            <RefRow
              key={t.label}
              label={t.label}
              usd={t.taxable_sales_usd}
              maxUsd={sales.business_types[0].taxable_sales_usd}
              valueLabel={`${fmtUsd(t.taxable_sales_usd)} sales`}
              sub={`${t.share_pct}% of all taxable sales${t.permits ? ` · ${t.permits.toLocaleString("en-US")} active permits` : ""}`}
            />
          ))}
          <p className="mt-1 text-xs text-fog">
            Types sum to {fmtUsd(sales.business_type_reconciliation.partition_sum_usd)} vs
            CDTFA&apos;s own statewide total{" "}
            {fmtUsd(sales.business_type_reconciliation.total_all_outlets_usd)}.
          </p>
          <Terminator flag="masked">
            Which sellers? Individual seller-permit records are confidential (R&TC §7056) — and
            business type × city is not published, so the two views below can&apos;t be crossed.
          </Terminator>
        </LevelCard>
      )}

      {/* ---- Sales branch: counties & cities ---- */}
      {drillKind === "sales" && citiesSeg && sales && (
        <LevelCard
          step={step++}
          title="Where the sales happen"
          subtitle={`County totals, then every published city, trailing four quarters through ${sales.latest_quarter}. Taxable sales — not tax collected.`}
          chip={<VintageChip label={`Through ${sales.latest_quarter}`} />}
        >
          <p className="mb-1 text-xs font-medium text-fog">All 58 counties:</p>
          <div className="max-h-96 overflow-y-auto pr-1">
            {sales.counties.map((c) => (
              <RefRow
                key={c.county}
                label={c.county}
                usd={c.taxable_sales_usd}
                maxUsd={sales.counties[0].taxable_sales_usd}
                valueLabel={`${fmtUsd(c.taxable_sales_usd)} sales`}
              />
            ))}
          </div>
          <p className="mt-1 text-xs text-fog">
            Counties sum to {fmtUsd(sales.county_reconciliation.counties_sum_usd)} vs the
            statewide {fmtUsd(sales.county_reconciliation.statewide_total_usd)} — the gap is
            sales CDTFA can&apos;t place in a county.
          </p>
          <p className="mb-1 mt-3 text-xs font-medium text-fog">
            Every published city ({sales.cities.length}; {sales.suppressed_city_count} with
            suppressed quarters):
          </p>
          <div className="max-h-96 overflow-y-auto pr-1">
            {sales.cities.map((c) => (
              <RefRow
                key={`${c.city}-${c.county}`}
                label={`${c.city} · ${c.county}`}
                usd={c.taxable_sales_usd ?? 0}
                maxUsd={sales.cities[0].taxable_sales_usd ?? 1}
                valueLabel={
                  c.taxable_sales_usd === null
                    ? "suppressed"
                    : `${fmtUsd(c.taxable_sales_usd)} sales${c.suppressed ? "*" : ""}`
                }
              />
            ))}
          </div>
          {sales.suppressed_city_count > 0 && (
            <p className="mt-1 text-xs text-fog">
              * partial: some quarters suppressed at the source (R&TC §7056), never estimated.
            </p>
          )}
          <Terminator flag="masked">
            Below the city level the law takes over: individual seller-permit data is
            confidential (R&TC §7056).
          </Terminator>
        </LevelCard>
      )}
    </div>
  );
}
