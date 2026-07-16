import { CoverageBadge } from "@/components/ui/SourceChip";

export const metadata = { title: "Dark zones — CA Dollar Trace" };

/* The gap registry: why each dark zone exists (legal/structural cause),
   how big it is, and what would fix it. Sources cited inline. Content is
   maintained editorially; magnitude figures are sourced program totals that
   size the GAP, not amounts we can trace. */

const GAPS = [
  {
    id: "fiscal-captcha",
    title: "The state checkbook blocks machine access",
    flag: "category_only" as const,
    klass: "(d) Published, but unusable for systematic analysis",
    size: "~79% of state expenditures are in Open FI$Cal — but only one manual download at a time",
    body: [
      "Open FI$Cal publishes vendor-level spending transactions, which should make state payments traceable. In practice, every bulk download on open.fiscal.ca.gov is gated behind a CAPTCHA that requires a human to click through for each file — there is no API, and the former data.ca.gov mirror no longer lists FI$Cal datasets (we checked: the FI$Cal organization on the portal exists but contains zero public datasets).",
      "We verified this directly while building this site: the download pages call a CAPTCHA verification service before releasing each file URL. A transparency portal that cannot be read by software is, for continuous public analysis, category-level only.",
    ],
    fix: "Restore the machine-readable mirror (CKAN) or publish stable direct download URLs. Until then: scheduled manual pulls, and a CPRA request for the underlying database in native format (Sierra Club v. Superior Court (2013) 57 Cal.4th 157 makes electronic records producible in native format at duplication cost).",
    cites: [
      { label: "Open FI$Cal download page", url: "https://open.fiscal.ca.gov/download-expenditures.html" },
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
