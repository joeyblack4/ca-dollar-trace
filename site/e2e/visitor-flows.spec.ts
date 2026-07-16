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
  await expect(page.getByText(/0\.7% of budget visible/)).toBeVisible();
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
  await expect(page.getByText(/What each plan pays hospitals/)).toBeVisible();

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
  await expect(page.getByText(/fund mix and program lines/)).toBeVisible();
  // rewind to the agency crumb (area+agency merge into one crumb)
  await page.locator("#drill").getByRole("button", { name: /K thru 12 Education/ }).click();
  await expect(page.getByText(/fund mix and program lines/)).toHaveCount(0);
  await expect(page.getByText(/Click a department/)).toBeVisible();
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
