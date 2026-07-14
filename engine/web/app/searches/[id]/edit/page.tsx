import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { allClientsLite } from "@/lib/data/crm";
import { getSavedSearch } from "@/lib/data/saved-searches";
import { SearchFormFields } from "@/components/searches/search-form-fields";
import { updateSavedSearchAction } from "@/app/actions";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function EditSavedSearchPage({ params }: PageProps) {
  const { id } = await params;
  const data = await getSavedSearch(id);
  if (!data) notFound();
  const clients = await allClientsLite();

  async function submit(formData: FormData) {
    "use server";
    formData.set("id", id);
    const r = await updateSavedSearchAction(formData);
    if (!r.success) throw new Error(r.error);
    const { redirect } = await import("next/navigation");
    redirect(`/searches/${id}`);
  }

  return (
    <div className="space-y-5 max-w-3xl">
      <Link
        href={`/searches/${id}`}
        className="inline-flex items-center gap-1 text-sm text-(--color-info) hover:underline"
      >
        <ArrowLeft className="size-4" /> back to search
      </Link>

      <Card className="p-6">
        <h1 className="text-2xl font-bold">Edit saved search</h1>
        <form action={submit} className="mt-5 space-y-5">
          <SearchFormFields
            defaults={{
              name: data.summary.name,
              description: data.summary.description ?? "",
              clientId: data.summary.clientId ?? "",
              criteria: data.summary.criteria,
            }}
            centerLabel={data.summary.centerLabel}
            clients={clients}
          />
          <div className="flex justify-end gap-2 pt-3 border-t border-(--color-border)">
            <Link href={`/searches/${id}`}>
              <Button type="button" variant="outline">
                Cancel
              </Button>
            </Link>
            <Button type="submit">Save changes</Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
