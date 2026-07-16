import { CoverageBadge } from "@/components/ui/SourceChip";

export const metadata = { title: "Dark zones — CA Dollar Trace" };

/* The gap registry: why each dark zone exists (legal/structural cause),
   how big it is, and what would fix it. Sources cited inline. Content is
   maintained editorially; magnitude figures are sourced program totals that
   size the GAP, not amounts we can trace. */

const GAPS = [
  {
    id: "fiscal-captcha",
    title: "The state checkbook: readable, but missing its biggest dollars",
    flag: "category_only" as const,
    klass: "(a)+(b) Statutory masking + structural exclusions",
    size: "Vendor files cover ~79% of budgetary expenditures on paper — but for a department like DHCS, under 1% of its budget appears as vendor payments",
    body: [
      "Correction (2026-07-16): we initially reported that Open FI$Cal's downloads were CAPTCHA-gated and unusable by software. That was wrong — user testing showed the files sit on public cloud storage with direct URLs listed in a catalog file, and we now ingest them automatically. We're leaving this note up because a transparency project should show its own corrections. (The discoverability critique stands: there is no documented API, and the former data.ca.gov mirror still lists zero FI$Cal datasets.)",
      "The real gap is what the checkbook excludes by design: state payroll, purchase-card spending, and — decisively — bulk benefit payments. Medi-Cal benefits, the largest single expenditure in the state, never appear as vendor transactions. Our ingest of the FY2025-26 files shows the Department of Health Care Services' checkbook contains roughly $1.4B in vendor payments against a $202.7B enacted budget — the coverage percentages on every agency page are computed from exactly this comparison.",
      "On top of the exclusions, statutorily confidential vendors appear only as 'Confidential' — a third of DHCS's transaction rows. We count and display that share instead of dropping it.",
    ],
    fix: "Publish the excluded flows at aggregate level (benefit payments by program and county), document the bulk-download catalog as a supported API, and restore the data.ca.gov mirror. The confidential-vendor masks are statutory and would need legislative change.",
    cites: [
      { label: "Open FI$Cal download page", url: "https://open.fiscal.ca.gov/download-expenditures.html" },
      { label: "Open FI$Cal dataset notes (exclusions)", url: "https://open.fiscal.ca.gov/datasets.html" },
      { label: "data.ca.gov FI$Cal organization (empty)", url: "https://data.ca.gov/organization/fiscal" },
    ],
  },
  {
    id: "medi-cal",
    title: "Medi-Cal managed care: the largest single dark zone",
    flag: "trail_ends_here" as const,
    klass: "(b) No reporting requirement exists",
    size: "~$189B in Medi-Cal benefits flows through DHCS in 2025-26; ~95% of members are in managed care plans",
    body: [
      "The state's payment to each managed care plan (capitation) is public. What each plan pays hospitals, clinics, and physician groups is not. The largest flow in state government goes dark exactly one hop past the state.",
      "You can see this on our Health & Human Services page: DHCS's Benefits program line is $189.3B of enacted budget — and below the plan level, no public dataset exists.",
    ],
    fix: "A managed-care payment transparency mandate (the AB 2833 model applied to plan-to-provider payments), or DHCS publishing plan encounter/payment aggregates. CalAIM contract reforms promise more subcontractor transparency; payment-level data is not yet public.",
    cites: [
      { label: "DHCS managed care dashboard", url: "https://www.dhcs.ca.gov/services/Pages/MngdCarePerformDashboard.aspx" },
      { label: "CHCF Medi-Cal facts & figures", url: "https://www.chcf.org/publication/medi-cal-facts-figures/" },
    ],
  },
  {
    id: "county-checkbooks",
    title: "Most counties publish no vendor-level checkbook",
    flag: "category_only" as const,
    klass: "(c) Records exist, but are not published",
    size: "58 counties; realignment alone moves ~$6B+/year to county accounts",
    body: [
      "Once state money reaches a county (realignment, social services administration), public visibility drops to annual category totals in the State Controller's ByTheNumbers — self-reported, posted as submitted. A handful of cities (Los Angeles, San Francisco) publish transaction-level checkbooks; most of the 58 counties do not, even though every county runs an accounts-payable system that holds exactly this data.",
    ],
    fix: "County-by-county CPRA requests for AP data in native electronic format (the Sierra Club precedent), and a 'local checkbook standard' bill following the AB 132 model.",
    cites: [
      { label: "SCO ByTheNumbers", url: "https://bythenumbers.sco.ca.gov/" },
      { label: "Checkbook L.A. (the exception)", url: "https://controllerdata.lacity.org/" },
    ],
  },
  {
    id: "k12-vendors",
    title: "School district spending stops at category level",
    flag: "category_only" as const,
    klass: "(b)/(c) No vendor-level reporting requirement; district records unpublished",
    size: "~$121B K-12 all-funds budget across ~1,000 districts",
    body: [
      "SACS financial reporting gives fund/resource/object categories per district — rich for budget shares, blind on who actually gets paid. Charter management organizations route spending through nonprofit 990s with a 12-18 month lag and only top-5 contractor disclosure.",
    ],
    fix: "District-level CPRA requests; longer term, vendor-level reporting in SACS.",
    cites: [
      { label: "CDE SACS data", url: "https://www.cde.ca.gov/ds/fd/fd/" },
      { label: "Ed-Data", url: "https://www.ed-data.org/" },
    ],
  },
  {
    id: "tax-expenditures",
    title: "Invisible spending: tax expenditures are published as PDFs only",
    flag: "category_only" as const,
    klass: "(d) Published, but unusable for systematic analysis",
    size: "Tens of billions per year in credits, deductions, and exclusions — the corporation-tax category alone was ~$5.9B in FY2024-25 (DOF)",
    body: [
      "Spending through the tax code — R&D credits, the film credit, water's-edge elections — is economically equivalent to spending, but appears in no budget line and no checkbook. California does publish reports on it: DOF's annual Tax Expenditure Report and FTB's TER series.",
      "We checked every Tax Expenditure Report dataset on data.ca.gov (2016 through 2020): each one contains exactly one resource, and it is a PDF. The report about invisible spending is itself machine-unreadable — recipient-level detail is additionally confidential under R&TC §19542.",
    ],
    fix: "Publish the TER tables as data (CSV on the open-data portal, like the grants portal does), and expand FTB Form 4197 reporting. Until then: PDF table extraction, verified figure-by-figure, is on our roadmap.",
    cites: [
      { label: "TER datasets on data.ca.gov (PDF-only)", url: "https://data.ca.gov/dataset/tax-expenditure-report" },
      { label: "DOF Tax Expenditure Reports", url: "https://dof.ca.gov/forecasting/economics/tax-expenditure-reports/" },
    ],
  },
  {
    id: "compensation-portal",
    title: "Public payroll data exists — behind a wall that blocks software",
    flag: "category_only" as const,
    klass: "(d) Published, but unusable for systematic analysis",
    size: "Payroll is the single biggest exclusion from every checkbook on this site — roughly half of many agencies' budgets",
    body: [
      "The State Controller publishes Government Compensation in California (publicpay.ca.gov): wages and benefits by position for state departments, counties, cities, and districts. It is exactly the data that would fill the 'payroll excluded' gap in our coverage meters.",
      "The portal's security layer rejects automated retrieval outright (we verified: every request path returns 403 or hangs, including from a normal browser session at times). The data is public; the access is not.",
    ],
    fix: "Mirror the annual raw exports on the state open-data portal, like the Grants Portal does. Until then: a manual download once a year would light this lane up.",
    cites: [
      { label: "publicpay.ca.gov", url: "https://publicpay.ca.gov/" },
    ],
  },
  {
    id: "homelessness-awards",
    title: "Homelessness award lists are published as PDFs",
    flag: "category_only" as const,
    klass: "(d) Published, but unusable for systematic analysis",
    size: "Homekey alone: $3.78B across 261 projects (Rounds 1-3), plus Homekey+ and HHAP",
    body: [
      "HCD publishes who received Homekey money — as PDF lists and a dashboard. The only machine-readable awardee file is the original 2020 round. The State Auditor called homelessness spending 'a bit of a data desert' in 2024; the award lists that DO exist are locked in a format software can't reliably read.",
      "AB 799 requires Cal ICH to publish a public homelessness fiscal dashboard by June 2027 — we're built to ingest it the day it appears.",
    ],
    fix: "Publish award lists as CSV alongside the PDFs (they are clearly generated from spreadsheets). AB 799's 2027 dashboard should ship machine-readable from day one.",
    cites: [
      { label: "Homekey awards dashboard", url: "https://www.hcd.ca.gov/grants-and-funding/homekey/awards-dashboard" },
      { label: "State Auditor report 2023-102.1", url: "https://www.auditor.ca.gov/reports/2023-102.1/index.html" },
    ],
  },
  {
    id: "grants-subrecipients",
    title: "Grants stop at the first awardee",
    flag: "trail_ends_here" as const,
    klass: "(b) No reporting requirement exists",
    size: "Tens of billions in state grants each year",
    body: [
      "AB 132 (2021) forced post-award awardee publication on the Grants Portal — a real win, and our grants page runs on it daily. But the portal explicitly collects no subrecipient information: it records only a flag that subrecipients exist. A nonprofit that re-grants state money is a dead end in the public record.",
    ],
    fix: "Extend AB 132 to subrecipient reporting above a threshold, mirroring federal FSRS subaward rules.",
    cites: [
      { label: "California Grants Portal", url: "https://data.ca.gov/dataset/california-grants-portal" },
    ],
  },
] as const;

export default function GapsPage() {
  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">
        Dark zones: where California&apos;s money goes out of sight
      </h1>
      <p className="mt-3 max-w-2xl text-fog">
        Every gap below is classified by <em>why</em> it exists — statute, missing reporting
        requirement, unpublished records, or unusable formats — because the cause determines the
        fix. Magnitude figures size the gap from official sources; they are not amounts we can
        trace.
      </p>

      <div className="mt-8 space-y-6">
        {GAPS.map((g) => (
          <section key={g.id} id={g.id} className="rounded-lg border border-rule p-5 target:border-poppy">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold">{g.title}</h2>
              <CoverageBadge flag={g.flag} />
            </div>
            <p className="mt-1 font-mono text-xs text-fog">{g.klass}</p>
            <p className="mt-2 text-sm font-medium text-category-only">{g.size}</p>
            {g.body.map((p) => (
              <p key={p.slice(0, 40)} className="mt-2 max-w-3xl text-sm text-fog">
                {p}
              </p>
            ))}
            <p className="mt-3 max-w-3xl text-sm">
              <span className="font-medium">What would fix it:</span>{" "}
              <span className="text-fog">{g.fix}</span>
            </p>
            <p className="mt-2 flex flex-wrap gap-3 text-xs">
              {g.cites.map((c) => (
                <a
                  key={c.url}
                  href={c.url}
                  className="underline decoration-rule underline-offset-2 hover:text-ink"
                >
                  {c.label} ↗
                </a>
              ))}
            </p>
          </section>
        ))}
      </div>
    </div>
  );
}
