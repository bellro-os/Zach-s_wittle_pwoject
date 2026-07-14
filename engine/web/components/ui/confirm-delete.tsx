"use client";

import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Trash2 } from "lucide-react";
import {
  AlertDialog,
  AlertDialogTrigger,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogAction,
  AlertDialogCancel,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import type { ActionResult } from "@/app/actions";

interface Props {
  /** Server action invoked when the user confirms. Receives a FormData
   * containing only the keys passed via `fields`. */
  action: (fd: FormData) => Promise<ActionResult>;
  /** Hidden form data sent to the action. */
  fields: Record<string, string>;
  /** Heading shown on the dialog. */
  title?: string;
  /** Optional supporting copy under the title. */
  description?: string;
  /** Confirm button label. */
  confirmLabel?: string;
  /** Trigger button content (defaults to a trash icon + "Delete"). */
  triggerLabel?: React.ReactNode;
  /** Variant of the trigger button. */
  triggerVariant?: "outline" | "destructive" | "ghost" | "default";
  triggerSize?: "default" | "sm" | "icon";
  /** Optional success/redirect callback. */
  onSuccess?: () => void;
}

/** Reusable destructive confirmation. */
export function ConfirmDelete({
  action,
  fields,
  title = "Delete this item?",
  description = "This action can be undone from the undo bar within 30 seconds.",
  confirmLabel = "Delete",
  triggerLabel,
  triggerVariant = "outline",
  triggerSize = "sm",
  onSuccess,
}: Props) {
  const [open, setOpen] = useState(false);
  const [isPending, startTransition] = useTransition();

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>
        <Button variant={triggerVariant} size={triggerSize}>
          {triggerLabel ?? (
            <>
              <Trash2 className="size-3.5" />
              Delete
            </>
          )}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={isPending}
            onClick={(e) => {
              e.preventDefault();
              startTransition(async () => {
                const fd = new FormData();
                for (const [k, v] of Object.entries(fields)) fd.set(k, v);
                const result = await action(fd);
                if (result.success) {
                  toast.success(result.message ?? "Deleted");
                  setOpen(false);
                  onSuccess?.();
                } else {
                  toast.error(result.error ?? "Could not delete");
                }
              });
            }}
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
