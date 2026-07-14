"use client";

import Link from "next/link";
import { useTransition } from "react";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ActionForm } from "@/components/ui/action-form";
import { addProspectNote, deleteProspectNote } from "@/app/actions";

interface Note {
  id: string;
  timestamp: Date;
  body: string;
}

interface Props {
  parcelId: string;
  county: string;
  notes: Note[];
}

export function ProspectNotes({ parcelId, county, notes }: Props) {
  return (
    <Card className="p-5 gap-3">
      <h2 className="font-semibold text-white inline-flex items-center gap-2">
        <Plus className="size-4 text-emerald-300" /> Prospect notes
        <span className="text-slate-500 font-normal text-sm">
          ({notes.length})
        </span>
      </h2>
      <p className="text-xs text-slate-500 -mt-1">
        Scribble anything about this parcel without converting the owner to a client.
      </p>

      <ActionForm
        action={addProspectNote}
        resetOnSuccess
        className="flex gap-2 items-start"
      >
        <input type="hidden" name="parcelId" value={parcelId} />
        <input type="hidden" name="county" value={county} />
        <input
          name="body"
          required
          placeholder="e.g. 'new roof in 2023; owner mentioned wanting to retire'"
          className="flex-1 h-9 rounded-md border border-(--color-input) bg-(--color-background) px-3 text-sm"
        />
        <Button type="submit" size="sm">
          <Plus className="size-3.5" /> Add
        </Button>
      </ActionForm>

      {notes.length === 0 ? (
        <p className="text-sm text-slate-500 italic">
          No notes yet.
        </p>
      ) : (
        <ul className="divide-y divide-white/8">
          {notes.map((n) => (
            <NoteRow key={n.id} note={n} parcelId={parcelId} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function NoteRow({ note, parcelId }: { note: Note; parcelId: string }) {
  const [isPending, startTransition] = useTransition();
  return (
    <li className="py-2 flex items-start justify-between gap-3 text-sm">
      <div className="flex-1 min-w-0">
        <p className="whitespace-pre-wrap text-slate-300">{note.body}</p>
        <Link
          href={`/prospect-notes/${note.id}`}
          className="text-[10px] text-slate-500 tabular-nums hover:text-emerald-300 hover:underline"
        >
          {note.timestamp.toISOString().replace("T", " ").slice(0, 16)} · edit ›
        </Link>
      </div>
      <button
        type="button"
        disabled={isPending}
        onClick={() => {
          startTransition(async () => {
            const fd = new FormData();
            fd.set("id", note.id);
            fd.set("parcelId", parcelId);
            const result = await deleteProspectNote(fd);
            if (result.success) toast.success("Note deleted");
            else toast.error(result.error ?? "Could not delete");
          });
        }}
        className="text-slate-500 hover:text-rose-300 text-xs"
      >
        <Trash2 className="size-3.5" />
      </button>
    </li>
  );
}
