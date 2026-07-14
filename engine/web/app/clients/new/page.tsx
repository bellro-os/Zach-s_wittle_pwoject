import Link from "next/link";
import { ArrowLeft, Sparkles } from "lucide-react";
import { allClientsLite } from "@/lib/data/crm";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ClientFormFields } from "@/components/clients/client-form-fields";
import { addClientAndRedirect } from "@/app/actions";
import { FadeIn } from "@/components/ratified-ui";

interface PageProps {
  searchParams: Promise<{
    from?: string;
    county?: string;
    owner?: string;
    addr?: string;
  }>;
}

/** "Convert prospect → client" landing page. Pre-fills the form when the
 * user lands here from a row's expansion panel. Submits and redirects to
 * the new client's detail page. */
export default async function NewClientPage({ searchParams }: PageProps) {
  const sp = await searchParams;
  const allClients = await allClientsLite();

  const prefillFromProspect = Boolean(sp.from);

  return (
    <div className="space-y-5 max-w-2xl">
      <Link
        href="/"
        className="inline-flex items-center gap-1 text-sm text-emerald-300 hover:underline"
      >
        <ArrowLeft className="size-4" /> back to queue
      </Link>

      <FadeIn>
        <Card className="bg-grid-fade relative overflow-hidden p-6">
          <div className="pointer-events-none absolute -top-20 right-1/4 h-56 w-56 rounded-full bg-emerald-500/15 blur-[120px]" />
          <h1 className="relative text-3xl font-semibold tracking-tight text-white flex items-center gap-2">
            {prefillFromProspect && <Sparkles className="size-5 text-emerald-300" />}
            {prefillFromProspect ? "Convert prospect to client" : "New client"}
          </h1>
          {prefillFromProspect && (
            <p className="relative text-sm text-slate-400 mt-1">
              Parcel <span className="font-mono">{sp.from}</span> is being linked
              as this client&apos;s home — that surfaces the seller-score on
              their detail page.
            </p>
          )}

          <form action={addClientAndRedirect} className="relative mt-5 space-y-4">
            <ClientFormFields
              defaults={{
                name: sp.owner ?? "",
                parcelId: sp.from ?? "",
                county: sp.county ?? "",
                source: prefillFromProspect ? "cold" : "",
              }}
              allClients={allClients}
            />
            <div className="flex justify-end gap-2">
              <Link href="/clients">
                <Button type="button" variant="outline">
                  Cancel
                </Button>
              </Link>
              <Button type="submit">Save and open</Button>
            </div>
          </form>
        </Card>
      </FadeIn>
    </div>
  );
}
