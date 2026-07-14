"use client";

import { useTransition } from "react";
import { toast } from "sonner";
import { X } from "lucide-react";
import { acknowledgeReminder } from "@/app/actions";

interface Props {
  clientId: string;
  kind: "anniversary" | "birthday";
}

/** Inline dismiss button for the anniversary / birthday reminder cards.
 * Records that the agent has acknowledged this year's instance so it
 * stops showing in stats banners and detail-page cards until next year. */
export function DismissReminder({ clientId, kind }: Props) {
  const [isPending, startTransition] = useTransition();
  return (
    <button
      type="button"
      disabled={isPending}
      onClick={() => {
        startTransition(async () => {
          const fd = new FormData();
          fd.set("id", clientId);
          fd.set("kind", kind);
          const result = await acknowledgeReminder(fd);
          if (result.success) toast.success(`Dismissed for the year`);
          else toast.error(result.error ?? "Could not dismiss");
        });
      }}
      className="text-(--color-muted-foreground) hover:text-(--color-foreground) text-xs inline-flex items-center gap-1"
      title="Dismiss until next year"
    >
      <X className="size-3" /> dismiss
    </button>
  );
}
