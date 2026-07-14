import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { allClientsLite } from "@/lib/data/crm";
import { SearchFormFields } from "@/components/searches/search-form-fields";
import { addSavedSearchAndRedirect } from "@/app/actions";

interface PageProps {
  searchParams: Promise<{ clientId?: string }>;
}

export default async function NewSearchPage({ searchParams }: PageProps) {
  const sp = await searchParams;
  const clients = await allClientsLite();
  return (
    <div className="space-y-5 max-w-3xl">
      <Link
        href="/searches"
        className="inline-flex items-center gap-1 text-sm text-(--color-info) hover:underline"
      >
        <ArrowLeft className="size-4" /> back to searches
      </Link>

      <Card className="p-6">
        <h1 className="text-2xl font-bold">New saved search</h1>
        <p className="text-sm text-(--color-muted-foreground) mt-1">
          Re-runs hourly. New matches get a NEW badge in the detail view.
        </p>
        <form action={addSavedSearchAndRedirect} className="mt-5 space-y-5">
          <SearchFormFields
            defaults={{ clientId: sp.clientId ?? "" }}
            clients={clients}
          />
          <div className="flex justify-end gap-2 pt-3 border-t border-(--color-border)">
            <Link href="/searches">
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </Link>
            <Button type="submit">Save and run</Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
