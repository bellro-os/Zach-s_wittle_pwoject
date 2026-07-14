import { listBrands } from "@/lib/brands";
import { FadeIn, Accent } from "@/components/ratified-ui";
import { NewCmaForm } from "./form";

export const dynamic = "force-dynamic";

export default async function NewCmaPage() {
  const brands = await listBrands();
  return (
    <div className="relative mx-auto max-w-3xl">
      {/* Hero / header */}
      <div className="relative">
        <div className="pointer-events-none absolute inset-0 -z-10 bg-grid-fade" />
        <div className="pointer-events-none absolute -top-24 left-1/2 -z-10 h-72 w-72 -translate-x-1/2 rounded-full bg-emerald-500/15 blur-[120px]" />
        <FadeIn className="flex flex-col items-start gap-4 pb-8 pt-2">
          <span className="inline-flex items-center gap-2 rounded-full border border-emerald-500/25 bg-emerald-500/10 px-3.5 py-1 text-xs font-medium uppercase tracking-[0.18em] text-emerald-300">
            New CMA
          </span>
          <h1 className="max-w-2xl text-balance text-4xl font-semibold leading-[1.05] tracking-tight text-white sm:text-5xl">
            Generate a <Accent>branded report</Accent>
          </h1>
          <p className="max-w-xl text-balance text-base leading-relaxed text-slate-400">
            Enter the subject address and the comp engine pulls a similarity-ranked
            set from the latest MLS pull. The PDF renders in ~15 seconds.
          </p>
        </FadeIn>
      </div>
      <NewCmaForm brands={brands} />
    </div>
  );
}
