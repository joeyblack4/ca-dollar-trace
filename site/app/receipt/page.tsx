import { ReceiptCalculator } from "@/components/receipt/ReceiptCalculator";
import { SourceChip } from "@/components/ui/SourceChip";
import { loadPublished } from "@/lib/published-server";
import type { BudgetWaterfall } from "@/lib/published";

export const metadata = { title: "Your receipt — CA Dollar Trace" };

export default async function ReceiptPage() {
  const pub = await loadPublished<BudgetWaterfall>("budget_waterfall");

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">Your California tax receipt</h1>
      <p className="mt-2 max-w-2xl text-fog">
        Enter the state income tax you actually paid and see where a dollar like yours goes,
        using the enacted {pub.data.budget_year} General Fund proportions. We don&apos;t estimate
        your taxes — you bring the number, we bring the split.
      </p>

      <ReceiptCalculator data={pub.data} />

      <SourceChip
        source={pub.source}
        asOf={pub.as_of}
        cadence={pub.cadence}
        coverage={pub.coverage_flag}
        caveats={pub.caveats}
        dataHref="/data/budget_waterfall.json"
      />
    </div>
  );
}
