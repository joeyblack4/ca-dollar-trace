/* End-to-end visitor flows against the built static export.
   These encode the product's core promises: the drill goes as deep as the
   data allows, dead ends are labeled, and nothing renders as garbage. */

import { expect, test } from "@playwright/test";

test("home renders the waterfall with provenance and no console errors", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

  await page.goto("/");
  await expect(page.locator("svg[role='img']")).toBeVisible();
  await expect(page.getByText("Personal Income Tax")).toBeVisible();
  await expect(page.getByText(/as of \d{4}-\d{2}-\d{2}/).first()).toBeVisible();
  await expect(page.getByText("Get the data").first()).toBeVisible();
  expect(errors.filter((e) => !e.includes("favicon"))).toEqual([]);
});

test("six-hop drill: HHS -> DHCS -> checkbook -> AHP -> BHCIP, then vendor switch clears hop 6", async ({
  page,
}) => {
  await page.goto("/");

  // hop 1: click the HHS spending block in the Sankey
  await page
    .locator("g:has(> rect[fill='#e87722'])")
    .filter({ hasText: "Health and Human Services" })
    .first()
    .click();
  await expect(page.getByRole("button", { name: /State Department of Health Care Services/ })).toBeVisible();

  // hop 3: DHCS
  await page.getByRole("button", { name: /State Department of Health Care Services/ }).click();
  await expect(page.getByText(/0\.7% of the budget is visible/)).toBeVisible();
  await expect(page.getByText(/never appears\s+in the checkbook/)).toBeVisible();

  // payroll nested in the department level (the biggest checkbook exclusion)
  await expect(page.getByText(/Its people: [\d,]+ employees/)).toBeVisible();
  await expect(page.getByText(/in retirement & health benefits/)).toBeVisible();

  // hop 4: checkbook
  await page.getByRole("button", { name: /Open the checkbook/ }).click();
  await expect(page.getByRole("button", { name: /ADVOCATES FOR HUMAN POTENTIAL/ })).toBeVisible();
  await expect(page.getByText(/named only\s+"Confidential"/)).toBeVisible();

  // hop 5: AHP profile with recovered-hop row
  await page.getByRole("button", { name: /ADVOCATES FOR HUMAN POTENTIAL/ }).click();
  await expect(page.getByText(/net from the State of California since FY2020-21/)).toBeVisible();

  // hop 6: recovered BHCIP level
  await page.getByRole("button", { name: /Re-granted through BHCIP/ }).click();
  await expect(page.getByText(/\d+ BHCIP projects at \d+ organizations/)).toBeVisible();

  // REGRESSION (QA C4): switching vendors must remove the recovered level
  await page.getByRole("button", { name: /PRIME THERAPEUTICS/ }).click();
  await expect(page.getByText(/BHCIP projects at/)).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /PRIME THERAPEUTICS/ })).toBeVisible();
});

test("Medi-Cal hospitals hop: plans -> what hospitals report receiving", async ({ page }) => {
  await page.goto("/");
  await page
    .locator("g:has(> rect[fill='#e87722'])")
    .filter({ hasText: "Health and Human Services" })
    .first()
    .click();
  await page.getByRole("button", { name: /State Department of Health Care Services/ }).click();
  await page.getByRole("button", { name: /Follow the Benefits money/ }).click();
  await page.getByRole("button", { name: /What the hospitals say Medi-Cal paid them/ }).click();
  // the receiving end renders with real audited totals
  await expect(
    page.getByRole("heading", { name: /hospitals reported .* in Medi-Cal revenue/ })
  ).toBeVisible();
  // and the remaining darkness stays labeled
  await expect(page.getByText(/remains confidential between plan and hospital/)).toBeVisible();
});

test("Medi-Cal plans hop: DHCS -> named plans with rates -> dark-zone terminator", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .locator("g:has(> rect[fill='#e87722'])")
    .filter({ hasText: "Health and Human Services" })
    .first()
    .click();
  await page.getByRole("button", { name: /State Department of Health Care Services/ }).click();
  await page.getByRole("button", { name: /Follow the Benefits money into the managed care plans/ }).click();

  await expect(page.getByText(/managed care plan contracts — [\d,]+ Californians enrolled/)).toBeVisible();
  await expect(page.getByText(/L\.A\. Care Health Plan/).first()).toBeVisible();
  await expect(page.getByText(/certified rates .*\/member\/mo/).first()).toBeVisible();
  await expect(page.getByText(/matching covers [\d.]+% of enrollees/)).toBeVisible();
  await expect(page.getByText(/Plan-by-plan payments to providers are not public/)).toBeVisible();

  // switching to the checkbook must clear the plans level (sibling exclusivity)
  await page.getByRole("button", { name: /Open the checkbook/ }).click();
  await expect(page.getByText(/managed care plan contracts/)).toHaveCount(0);
});

test("breadcrumb rewind truncates the trail", async ({ page }) => {
  await page.goto("/");
  await page
    .locator("g:has(> rect[fill='#e87722'])")
    .filter({ hasText: "K-12 Education" })
    .first()
    .click();
  const deptButton = page.getByRole("button", { name: /Department of Education/ }).first();
  await deptButton.click();
  await expect(page.getByText(/WHAT THE BUDGET BUYS/i)).toBeVisible();
  // rewind to the agency crumb (area+agency merge into one crumb)
  await page.locator("#drill").getByRole("button", { name: /K thru 12 Education/ }).click();
  await expect(page.getByText(/WHAT THE BUDGET BUYS/i)).toHaveCount(0);
  await expect(page.getByText(/Click a department/)).toBeVisible();
});

test("search jumps straight to a vendor's profile with its dossier", async ({ page }) => {
  await page.goto("/");
  // type a name and pick the top match
  await page.locator("#vendor-search").fill("kaiser");
  const option = page.getByRole("option", { name: /KAISER FOUNDATION HOSPITALS/ });
  await expect(option).toBeVisible();
  await expect(option).toContainText("traced across California"); // dossier flag
  await option.click();
  // lands on the vendor profile, deep in the trail — not the top of the drill
  await expect(page.getByRole("heading", { name: /KAISER FOUNDATION HOSPITALS/ })).toBeVisible();
  await expect(page.getByText(/net from the State of California/)).toBeVisible();
  // the full breadcrumb resolved (no stranded "…" crumbs)
  const trail = page.locator("#drill .sticky");
  await expect(trail).toContainText("checkbook");
  await expect(trail).not.toContainText("…");
  // the cross-source dossier is present and does NOT overclaim the link
  await expect(page.getByText("This organization across California")).toBeVisible();
  // named leadership pay from the org's own IRS filing
  await expect(page.getByText(/Who runs it — from its own IRS filing \(\d{4}\)/)).toBeVisible();
  await expect(page.getByRole("cell", { name: "Gregory Adams" })).toBeVisible();
  await expect(page.getByText(/releases filings on a one-to-two-year delay/)).toBeVisible();
});

test("search offers no dead ends for an unpaid name", async ({ page }) => {
  await page.goto("/");
  await page.locator("#vendor-search").fill("zzzznotarealvendor");
  await expect(page.getByText(/No state-checkbook payments/)).toBeVisible();
  await expect(page.getByRole("option")).toHaveCount(0);
});

test("K-12 salary drill: districts expand into job-title pay bands, gaps stay honest", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .locator("g:has(> rect[fill='#e87722'])")
    .filter({ hasText: "K-12 Education" })
    .first()
    .click();
  await page.getByRole("button", { name: /Department of Education/ }).first().click();
  await page.getByRole("button", { name: /Follow it to the school districts/ }).click();

  // statewide pay strip renders from real payroll data
  await expect(page.getByText(/What K-12 jobs pay — [\d,]+ positions/)).toBeVisible();

  // LAUSD: expands into title bands, with the labeled prior-year fallback
  await page.getByRole("button", { name: /Los Angeles Unified/ }).click();
  await expect(page.getByText(/Its people: 97,232 positions/)).toBeVisible();
  await expect(page.getByText(/didn't report 2024 payroll .* showing 2023/)).toBeVisible();
  await expect(page.getByRole("cell", { name: "Teacher", exact: true })).toBeVisible();
  await expect(page.getByText(/removes names before publishing/)).toBeVisible();

  // San Diego: a true non-filer shows the honest absence, never a zero
  await page.getByRole("button", { name: /San Diego Unified/ }).click();
  await expect(page.getByText(/No payroll on record/)).toBeVisible();
  await expect(page.getByText(/absent from the public record, not zero/)).toBeVisible();
});

test("about page lists every source with a working outbound link", async ({ page }) => {
  await page.goto("/about/");
  await expect(page.getByRole("heading", { name: /Where the numbers come from — \d+ sources/ })).toBeVisible();
  // the layer groups and a few known sources are present
  await expect(page.getByText("The state budget").first()).toBeVisible();
  await expect(page.getByRole("link", { name: /Open FI\$Cal/ })).toHaveAttribute("href", /fiscal/i);
  await expect(page.getByRole("link", { name: /Federal Audit Clearinghouse/ })).toBeVisible();
  // honest framing is present, not buried
  await expect(page.getByText(/cannot add figures from different sources together/)).toBeVisible();
  await expect(page.getByText(/Independent, not government/)).toBeVisible();
});

test("no raw negative garbage anywhere on key pages", async ({ page }) => {
  for (const path of ["/", "/grants/", "/federal/", "/gaps/", "/receipt/", "/explore/"]) {
    await page.goto(path);
    const body = await page.locator("body").innerText();
    expect(body, `${path} renders unformatted negative dollars`).not.toMatch(/\$-\d{4,}/);
    expect(body, `${path} renders NaN/Infinity`).not.toMatch(/NaN|Infinity/);
  }
});

test("federal page shows every masked aggregate", async ({ page }) => {
  await page.goto("/federal/");
  await expect(page.getByText("MULTIPLE RECIPIENTS").first()).toBeVisible();
  await expect(page.getByText(/REDACTED/i).first()).toBeVisible();
  await expect(page.getByText(/Showing 40 of/)).toBeVisible();
});

test("grants page disclosures", async ({ page }) => {
  await page.goto("/grants/");
  await expect(page.getByText(/Top 12 of \d+ categories/)).toBeVisible();
  await expect(page.getByText(/flagged “has\s+subrecipients” — identities not collected/).first()).toBeVisible();
});

test("receipt scales with input", async ({ page }) => {
  await page.goto("/receipt/");
  await page.getByLabel(/California income tax you paid/).fill("10000");
  await expect(page.getByText(/Your \$10K split/)).toBeVisible();
  await expect(page.getByText(/not a\s+tax calculation/i)).toBeVisible();
});

test("published data endpoints serve JSON", async ({ request }) => {
  for (const f of [
    "budget_waterfall.json",
    "grants_summary.json",
    "grants_awards.json",
    "federal_ca.json",
    "bhcip_awards.json",
    "vendor_profiles.json",
    "agencies/4000.json",
    "vendors/4000.json",
  ]) {
    const res = await request.get(`/data/${f}`);
    expect(res.ok(), f).toBeTruthy();
    const doc = await res.json();
    expect(doc.source?.name, f).toBeTruthy();
    expect(doc.as_of, f).toBeTruthy();
  }
});
