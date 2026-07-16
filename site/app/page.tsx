import Link from "next/link";

export default function Home() {
  return (
    <div className="max-w-2xl">
      <h1 className="text-4xl font-semibold tracking-tight">
        Follow your California tax dollar —{" "}
        <span className="text-poppy">and see where the trail goes dark.</span>
      </h1>
      <p className="mt-6 text-lg text-fog">
        California publishes a lot about how it spends money — and hides more than you&apos;d
        think, not always on purpose. This project traces every dollar as far as the public
        record allows, cites every number to its government source, and flags the exact spot
        where visibility ends instead of pretending it doesn&apos;t.
      </p>
      <div className="mt-8 flex gap-4">
        <Link
          href="/grants/"
          className="rounded-md bg-poppy px-4 py-2 text-sm font-medium text-white hover:bg-poppy-deep"
        >
          Explore state grants →
        </Link>
      </div>
      <div className="mt-12 grid gap-4 sm:grid-cols-3 text-sm">
        <div className="rounded-lg border border-rule p-4">
          <div className="font-medium">Cited, always</div>
          <p className="mt-1 text-fog">
            Every figure carries its source, publish date, and a one-click link to the raw data.
          </p>
        </div>
        <div className="rounded-lg border border-rule p-4">
          <div className="font-medium">Honest about gaps</div>
          <p className="mt-1 text-fog">
            Unknown amounts are labeled unknown — never silently counted as zero.
          </p>
        </div>
        <div className="rounded-lg border border-rule p-4">
          <div className="font-medium">Built in the open</div>
          <p className="mt-1 text-fog">
            Open pipeline, open data layers, published methodology per source.
          </p>
        </div>
      </div>
    </div>
  );
}
