"use client";

import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Edit3, X, Check } from "lucide-react";
import { updateTouch } from "@/app/actions";
import { cn } from "@/lib/utils";

interface Props {
  touch: {
    id: string;
    notes: string | null;
  };
}

/** Inline editor for a Touch's notes. Click pencil → input opens →
 * blur or click check → saves → toast confirms. */
export function EditTouchButton({ touch }: Props) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(touch.notes ?? "");
  const [isPending, startTransition] = useTransition();

  function save() {
    const trimmed = value.trim();
    if (trimmed === (touch.notes ?? "").trim()) {
      setEditing(false);
      return;
    }
    startTransition(async () => {
      const fd = new FormData();
      fd.set("id", touch.id);
      fd.set("notes", trimmed);
      const result = await updateTouch(fd);
      if (result.success) {
        toast.success("Touch updated");
        setEditing(false);
      } else {
        toast.error(result.error ?? "Could not update");
      }
    });
  }

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="text-[10px] text-(--color-muted-foreground) hover:text-(--color-foreground) inline-flex items-center gap-1"
        title="Edit notes"
      >
        <Edit3 className="size-3" />
        edit
      </button>
    );
  }

  return (
    <div className="mt-1 flex items-start gap-1 w-full">
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) save();
          if (e.key === "Escape") setEditing(false);
        }}
        autoFocus
        rows={2}
        className={cn(
          "flex-1 rounded-md border border-(--color-input) bg-(--color-background) px-2 py-1 text-sm",
          isPending && "opacity-50",
        )}
        placeholder="Notes (Cmd+Enter to save, Esc to cancel)"
      />
      <button
        type="button"
        onClick={save}
        disabled={isPending}
        className="p-1 rounded-md bg-(--color-primary) text-(--color-primary-foreground) hover:opacity-90"
        title="Save"
      >
        <Check className="size-3.5" />
      </button>
      <button
        type="button"
        onClick={() => setEditing(false)}
        className="p-1 rounded-md border border-(--color-border) hover:bg-(--color-accent)"
        title="Cancel"
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}
