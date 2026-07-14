import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, FileText, MapPin } from "lucide-react";
import { db } from "@/lib/data/db";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ActionForm } from "@/components/ui/action-form";
import { updateProspectNote } from "@/app/actions";

const INPUT_CLS =
  "w-full rounded-md border border-(--color-input) bg-(--color-background) px-2 py-2 text-sm";

function fmt(d: Date): string {
  return d.toISOString().slice(0, 16).replace("T", " ");
}

export default async function ProspectNoteDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const note = await db.prospectNote.findUnique({ where: { id } });
  if (!note) notFound();

  return (
    <div className="space-y-5">
      <Link
        href={`/prospect/${encodeURIComponent(note.parcelId)}?county=${note.county}`}
        className="inline-flex items-center gap-1 text-sm text-(--color-info) hover:underline"
      >
        <ArrowLeft className="size-4" /> back to prospect
      </Link>

      <Card className="p-6 space-y-2">
        <h1 className="text-2xl font-bold inline-flex items-center gap-2">
          <FileText className="size-5" /> Prospect note
        </h1>
        <Link
          href={`/property/${encodeURIComponent(note.parcelId)}?county=${note.county}`}
          className="text-sm text-(--color-info) hover:underline inline-flex items-center gap-1"
          target="_blank"
          rel="noreferrer"
        >
          <MapPin className="size-3.5" /> Parcel {note.parcelId}
        </Link>
        <div className="text-xs text-(--color-muted-foreground)">
          {note.county} · written {fmt(note.timestamp)}
        </div>
      </Card>

      <Card className="p-5">
        <h2 className="font-semibold mb-3">Edit note</h2>
        <ActionForm action={updateProspectNote}>
          <input type="hidden" name="id" value={note.id} />
          <div className="space-y-3 text-sm">
            <textarea
              name="body"
              rows={6}
              defaultValue={note.body}
              required
              className={INPUT_CLS}
            />
            <Button type="submit">Save</Button>
          </div>
        </ActionForm>
      </Card>
    </div>
  );
}
